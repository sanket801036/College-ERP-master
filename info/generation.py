"""Asking a model to write something, and the rules around doing that safely.

The counterpart to `embeddings.py`: that module turns text into vectors so a
search can find a passage, this one hands the found passages to a model and
asks for an answer. Neither knows about Django models, which is what lets the
whole pipeline be tested without a key or a network.

Three things here are not incidental.

**Temperature is low and stays low.** This model is not being asked to write;
it is being asked to answer *from the passages it was given*. Creativity is the
failure mode - an invented fee deadline delivered fluently is worse than no
chatbot at all - so the default sits near zero and the prompt tells it to
refuse rather than reach.

**A truncated answer is reported, not returned quietly.** Hitting the token
ceiling mid-sentence looks exactly like a finished answer to a template.

**The User-Agent is required.** Groq sits behind a WAF that rejects urllib's
default outright, with a 403 that reads exactly like a rejected key. That cost
an hour and a wrong conclusion about a key being dead; it is a header, and it
is in the one place every request goes through.
"""
import json
import logging
import time
import urllib.error
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)

GROQ_ENDPOINT = 'https://api.groq.com/openai/v1/chat/completions'

# Grounded answering, not writing. Near-zero rather than exactly zero: some
# providers treat 0 as "unset" and quietly substitute their own default.
TEMPERATURE = 0.1

# Long enough for an answer with a citation, short enough that a runaway
# response cannot burn a free tier in one call.
MAX_TOKENS = 1024

MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 2
TIMEOUT_SECONDS = 60

# See the module docstring. Without this, Groq answers 403 with a Cloudflare
# body and no mention of the header.
USER_AGENT = 'college-erp/1.0'


class GenerationError(Exception):
    """The provider could not be reached, or answered with the wrong shape."""


class Answer:
    """What came back, and whether it is whole.

    A string would lose `truncated`, and a truncated answer rendered into a
    page is indistinguishable from a complete one.
    """

    def __init__(self, text, *, truncated=False, model='', tokens=0):
        self.text = text
        self.truncated = truncated
        self.model = model
        self.tokens = tokens

    def __str__(self):
        return self.text

    def __repr__(self):
        return '<Answer %r truncated=%s>' % (self.text[:40], self.truncated)


class Generator:
    """What the chatbot and the question generator depend on."""

    name = 'none'

    def complete(self, messages, *, max_tokens=MAX_TOKENS,
                 temperature=TEMPERATURE):
        """`messages` is the OpenAI shape: [{'role': ..., 'content': ...}]."""
        raise NotImplementedError

    def ask(self, system, user, **kwargs):
        return self.complete([{'role': 'system', 'content': system},
                              {'role': 'user', 'content': user}], **kwargs)


class FakeGenerator(Generator):
    """Answers without a network, for tests and for a checkout with no key.

    It echoes the last user message rather than returning a fixed string, so a
    test can assert that the prompt it built actually reached the model - the
    bug this catches is a retrieval step that silently passed no context.
    """

    name = 'fake'

    def __init__(self, reply=None):
        self.reply = reply
        self.calls = []

    def complete(self, messages, *, max_tokens=MAX_TOKENS,
                 temperature=TEMPERATURE):
        self.calls.append(messages)
        if self.reply is not None:
            return Answer(self.reply, model='fake')

        last = next((m['content'] for m in reversed(messages)
                     if m.get('role') == 'user'), '')
        return Answer('[fake answer to] %s' % last[:200], model='fake')


class GroqGenerator(Generator):
    """Chat completions over Groq's OpenAI-compatible endpoint.

    Plain urllib rather than the openai package: one endpoint, one request
    shape, and a dependency whose surface is far larger than the two fields
    this uses would be carried into every deploy for no gain.
    """

    name = 'groq'

    def __init__(self, api_key, model=None):
        if not api_key:
            raise GenerationError('GROQ_API_KEY is not set')
        self.api_key = api_key
        self.model = model or getattr(settings, 'GROQ_MODEL',
                                      'openai/gpt-oss-120b')

    def complete(self, messages, *, max_tokens=MAX_TOKENS,
                 temperature=TEMPERATURE):
        if not messages:
            raise GenerationError('no messages to send')

        data = self._post({
            'model': self.model,
            'messages': list(messages),
            'temperature': temperature,
            'max_tokens': max_tokens,
        })

        try:
            choice = data['choices'][0]
            text = choice['message']['content'] or ''
        except (KeyError, IndexError, TypeError) as exc:
            raise GenerationError('unexpected response shape: %s' % exc) from exc

        usage = data.get('usage') or {}
        return Answer(
            text.strip(),
            # 'length' means the ceiling cut it off, not that it finished.
            truncated=choice.get('finish_reason') == 'length',
            model=data.get('model', self.model),
            tokens=usage.get('total_tokens', 0),
        )

    def _post(self, payload):
        body = json.dumps(payload).encode('utf-8')
        request = urllib.request.Request(GROQ_ENDPOINT, data=body, headers={
            'Authorization': 'Bearer %s' % self.api_key,
            'Content-Type': 'application/json',
            'User-Agent': USER_AGENT,
        })

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                with urllib.request.urlopen(request,
                                            timeout=TIMEOUT_SECONDS) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                # 429 is the free tier's rate limit and 5xx is theirs; both are
                # worth another try. A 400 or 401 says the same thing next
                # time, so it is raised straight away.
                if not (exc.code == 429 or exc.code >= 500) or attempt == MAX_ATTEMPTS:
                    raise GenerationError(
                        'groq returned %s: %s' % (exc.code, _read(exc))) from exc
            except urllib.error.URLError as exc:
                if attempt == MAX_ATTEMPTS:
                    raise GenerationError('groq unreachable: %s' % exc) from exc

            wait = BACKOFF_SECONDS * (2 ** (attempt - 1))
            logger.warning('generation attempt %d failed, retrying in %ds',
                           attempt, wait)
            time.sleep(wait)

        raise GenerationError('groq did not answer')  # unreachable


def _read(exc):
    try:
        return exc.read().decode('utf-8', 'replace')[:200]
    except Exception:
        return ''


def get_generator():
    """The configured provider, or the fake when nothing is configured.

    Same rule as storage, email and embeddings: a checkout with no keys still
    runs, and `info/checks.py` is where a half-configured deployment is
    complained about.
    """
    key = getattr(settings, 'GROQ_API_KEY', '')
    if not key:
        return FakeGenerator()
    return GroqGenerator(key)
