"""Turning text into the vectors a similarity search compares.

Two things about this module are load-bearing and easy to get wrong.

**The dimension is part of the schema.** A stored vector is only comparable to
vectors from the same model. Swapping the embedding model - or even a provider
silently changing one - makes every row already in the database meaningless,
and the symptom is not an error but a retriever that returns confident
nonsense. So the dimension is declared here, checked on every response, and a
mismatch is refused loudly rather than stored.

**Embedding is the one part of the pipeline that costs money and can fail.**
Generation is called once per question; embedding is called once per chunk of
every document ever ingested. The retry and batching rules therefore live here
rather than at the call sites, and a failure leaves nothing half-written - the
caller either gets every vector it asked for or an exception.

Nothing here knows about Django models. It takes strings and returns lists of
floats, which is what lets the whole pipeline be tested against `FakeEmbedder`
without a key, a network, or a bill.
"""
import hashlib
import json
import logging
import math
import struct
import time
import urllib.error
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)

# Pinned, not read from a response: see the module docstring - a provider that
# quietly returned a different width one day would corrupt the store rather
# than fail.
#
# `text-embedding-004` was the obvious choice and no longer exists; asking for
# it returns a 404 that reads like a broken endpoint. `gemini-embedding-001`
# replaces it.
GEMINI_MODEL = 'gemini-embedding-001'

# The model's default is 3072, and 768 is asked for explicitly. That is not a
# storage economy, it is an index limit: pgvector will *store* up to 16,000
# dimensions but its HNSW and IVFFlat indexes both cap at 2,000. A 3072-wide
# column is therefore unindexable, and every similarity query degrades to a
# sequential scan over every chunk in the college - which works fine on a
# seeded demo and falls over on a real corpus, silently, later.
GEMINI_DIMENSIONS = 768

GEMINI_ENDPOINT = ('https://generativelanguage.googleapis.com/v1beta/'
                   'models/%s:batchEmbedContents')

# Gemini accepts 100 per batch. Under it by a margin, because a batch that is
# rejected for size costs the whole batch.
BATCH_SIZE = 64

# Total attempts per batch, including the first. Rate limits on a free tier are
# common and transient; a permanent failure is better surfaced after three
# tries than after twenty.
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 2

TIMEOUT_SECONDS = 60

# Sent on every request. Not decoration: some providers sit behind a WAF that
# rejects the default urllib agent outright, which reads as an auth failure
# and sends you looking at the key instead of the header.
USER_AGENT = 'college-erp/1.0'


class EmbeddingError(Exception):
    """The provider could not be reached, or answered with the wrong shape."""


class Embedder:
    """What the pipeline depends on. Providers implement `embed`."""

    dimensions = 0
    name = 'none'

    def embed(self, texts):
        """A list of vectors, one per text, in the order given."""
        raise NotImplementedError

    def embed_one(self, text):
        return self.embed([text])[0]

    def _check(self, vectors, expected):
        if len(vectors) != expected:
            raise EmbeddingError(
                '%s returned %d vectors for %d texts'
                % (self.name, len(vectors), expected))
        for vector in vectors:
            if len(vector) != self.dimensions:
                raise EmbeddingError(
                    '%s returned a %d-dimension vector, expected %d - the '
                    'stored vectors are not comparable to these'
                    % (self.name, len(vector), self.dimensions))
        return vectors


class FakeEmbedder(Embedder):
    """Deterministic vectors from a hash. For tests and for a demo with no key.

    Not a stub that returns zeros: the vectors are unit-length and stable per
    string, so similar-looking code paths can be exercised end to end and two
    identical chunks really do come back identical. It has no idea what words
    mean, so it is useless for judging retrieval *quality* - only for proving
    the plumbing carries the right vector to the right row.
    """

    name = 'fake'

    def __init__(self, dimensions=GEMINI_DIMENSIONS):
        self.dimensions = dimensions

    def embed(self, texts):
        return self._check([self._vector(t) for t in texts], len(texts))

    def _vector(self, text):
        # Enough hash output to fill the requested dimensions, four bytes per
        # float, expanded by rehashing rather than repeating so the components
        # are not visibly periodic.
        needed = self.dimensions * 4
        blob, counter = b'', 0
        seed = text.encode('utf-8')
        while len(blob) < needed:
            blob += hashlib.sha256(seed + str(counter).encode()).digest()
            counter += 1

        raw = struct.unpack('<%dI' % self.dimensions, blob[:needed])
        # Centre on zero so vectors can point in any direction; a hash is
        # otherwise entirely positive and every pair looks similar.
        values = [(n / 0xFFFFFFFF) - 0.5 for n in raw]
        norm = math.sqrt(sum(v * v for v in values)) or 1.0
        return [v / norm for v in values]


class GeminiEmbedder(Embedder):
    """text-embedding-004 over the REST API.

    Chosen because neither Groq nor xAI serves embeddings and Gemini's free
    tier covers a college's worth of course material several times over. The
    call is plain urllib rather than the Google SDK: one endpoint, one request
    shape, and the SDK would be a dependency carrying an auth stack this
    project does not otherwise use.
    """

    name = 'gemini'
    dimensions = GEMINI_DIMENSIONS

    def __init__(self, api_key, model=GEMINI_MODEL):
        if not api_key:
            raise EmbeddingError('GEMINI_API_KEY is not set')
        self.api_key = api_key
        self.model = model

    def embed(self, texts):
        texts = list(texts)
        if not texts:
            return []

        vectors = []
        for start in range(0, len(texts), BATCH_SIZE):
            vectors.extend(self._batch(texts[start:start + BATCH_SIZE]))
        return self._check(vectors, len(texts))

    def _batch(self, batch):
        payload = {'requests': [
            {'model': 'models/%s' % self.model,
             'content': {'parts': [{'text': text}]},
             # Asked for explicitly rather than taking the model's 3072
             # default - see GEMINI_DIMENSIONS for why the width is an index
             # decision, not a storage one.
             'outputDimensionality': self.dimensions,
             # RETRIEVAL_DOCUMENT tells the model this text is being stored to
             # be searched, not used as the search. Gemini embeds the two
             # asymmetrically, and using the wrong one costs real accuracy.
             'taskType': 'RETRIEVAL_DOCUMENT'}
            for text in batch]}

        data = self._post(payload)
        try:
            return [item['values'] for item in data['embeddings']]
        except (KeyError, TypeError) as exc:
            raise EmbeddingError('unexpected response shape: %s' % exc) from exc

    def _post(self, payload):
        url = '%s?key=%s' % (GEMINI_ENDPOINT % self.model, self.api_key)
        body = json.dumps(payload).encode('utf-8')
        request = urllib.request.Request(url, data=body, headers={
            'Content-Type': 'application/json',
            'User-Agent': USER_AGENT,
        })

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                with urllib.request.urlopen(request,
                                            timeout=TIMEOUT_SECONDS) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                # 429 is the free tier's rate limit and 5xx is theirs, not
                # ours; both are worth another try. A 400 or 403 will say the
                # same thing next time, so it is raised immediately.
                retryable = exc.code == 429 or exc.code >= 500
                if not retryable or attempt == MAX_ATTEMPTS:
                    raise EmbeddingError(
                        'gemini returned %s: %s'
                        % (exc.code, _read(exc))) from exc
            except urllib.error.URLError as exc:
                if attempt == MAX_ATTEMPTS:
                    raise EmbeddingError('gemini unreachable: %s' % exc) from exc

            wait = BACKOFF_SECONDS * (2 ** (attempt - 1))
            logger.warning('embedding attempt %d failed, retrying in %ds',
                           attempt, wait)
            time.sleep(wait)

        raise EmbeddingError('gemini did not answer')  # unreachable


def _read(exc):
    try:
        return exc.read().decode('utf-8', 'replace')[:200]
    except Exception:
        return ''


def get_embedder():
    """The configured provider, or the fake when nothing is configured.

    Falling back rather than failing is deliberate, and matches how storage
    and email already behave here: a checkout with no keys still runs, and the
    features that need one degrade instead of taking the app down with them.
    `info/checks.py` is where a half-configured deployment gets complained
    about, not at import time.
    """
    key = getattr(settings, 'GEMINI_API_KEY', '')
    if not key:
        return FakeEmbedder()
    return GeminiEmbedder(key)


def cosine(a, b):
    """Similarity of two vectors, for the tests and for a store without pgvector.

    pgvector does this in the database for real queries; this exists so the
    retrieval logic can be asserted without the extension installed.
    """
    if len(a) != len(b):
        raise ValueError('vectors of different lengths are not comparable')
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0
