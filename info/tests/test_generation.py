"""Asking a model for an answer, and the ways a bad one gets through.

Almost nothing here is about whether the model is any good - that is not
testable and not this layer's job. It is about the answers that are wrong in a
way a template cannot see: one that was cut off at the token ceiling and reads
as finished, one where the retrieval step passed no context and the model
answered from nothing, and the transport failures that look like a rejected
key when they are a missing header.
"""
import json
import urllib.error
from unittest import mock

from django.test import SimpleTestCase, override_settings

from info.generation import (
    MAX_TOKENS,
    USER_AGENT,
    Answer,
    FakeGenerator,
    GenerationError,
    GroqGenerator,
    get_generator,
)


def reply(text='an answer', finish='stop', model='openai/gpt-oss-120b'):
    return {
        'model': model,
        'choices': [{'message': {'content': text}, 'finish_reason': finish}],
        'usage': {'total_tokens': 42},
    }


class FakeGeneratorTests(SimpleTestCase):
    def test_it_echoes_the_user_message(self):
        # So a test can prove the prompt it built actually reached the model.
        # The bug this catches is a retrieval step that passed no context and
        # a chatbot that answered from nothing.
        answer = FakeGenerator().ask('be helpful', 'what is a binary tree')

        self.assertIn('what is a binary tree', answer.text)

    def test_it_records_what_it_was_asked(self):
        generator = FakeGenerator()

        generator.ask('system text', 'user text')

        self.assertEqual(generator.calls[0][0]['content'], 'system text')
        self.assertEqual(generator.calls[0][1]['content'], 'user text')

    def test_a_fixed_reply_can_be_pinned(self):
        self.assertEqual(FakeGenerator(reply='no').ask('s', 'u').text, 'no')

    def test_its_answers_are_never_truncated(self):
        self.assertFalse(FakeGenerator().ask('s', 'u').truncated)


class GroqTests(SimpleTestCase):
    def setUp(self):
        self.generator = GroqGenerator('test-key')

    def test_a_key_is_required(self):
        with self.assertRaises(GenerationError):
            GroqGenerator('')

    def test_it_returns_the_answer_text(self):
        with mock.patch.object(GroqGenerator, '_post', return_value=reply()):
            self.assertEqual(self.generator.ask('s', 'u').text, 'an answer')

    def test_a_truncated_answer_says_so(self):
        # finish_reason 'length' means the ceiling cut it off mid-sentence.
        # Rendered into a page that is indistinguishable from a finished one.
        with mock.patch.object(GroqGenerator, '_post',
                               return_value=reply(finish='length')):
            self.assertTrue(self.generator.ask('s', 'u').truncated)

    def test_a_finished_answer_does_not(self):
        with mock.patch.object(GroqGenerator, '_post', return_value=reply()):
            self.assertFalse(self.generator.ask('s', 'u').truncated)

    def test_the_temperature_stays_low_by_default(self):
        # This model answers from retrieved passages. Creativity is the
        # failure mode, not the feature.
        with mock.patch.object(GroqGenerator, '_post',
                               return_value=reply()) as post:
            self.generator.ask('s', 'u')

        self.assertLessEqual(post.call_args[0][0]['temperature'], 0.2)

    def test_the_ceiling_is_sent_so_one_call_cannot_run_away(self):
        with mock.patch.object(GroqGenerator, '_post',
                               return_value=reply()) as post:
            self.generator.ask('s', 'u')

        self.assertEqual(post.call_args[0][0]['max_tokens'], MAX_TOKENS)

    def test_an_empty_content_is_an_empty_answer_not_a_crash(self):
        with mock.patch.object(GroqGenerator, '_post',
                               return_value=reply(text=None)):
            self.assertEqual(self.generator.ask('s', 'u').text, '')

    def test_an_unexpected_response_shape_is_an_error(self):
        with mock.patch.object(GroqGenerator, '_post', return_value={'oops': 1}):
            with self.assertRaises(GenerationError):
                self.generator.ask('s', 'u')

    def test_sending_nothing_is_refused_before_the_call(self):
        with mock.patch.object(GroqGenerator, '_post') as post:
            with self.assertRaises(GenerationError):
                self.generator.complete([])

        post.assert_not_called()


class TransportTests(SimpleTestCase):
    """The header, and which failures are worth a second try."""

    def setUp(self):
        self.generator = GroqGenerator('test-key')
        # The backoff is real seconds. Every test here drives it to
        # exhaustion, so left alone this class alone would add twelve seconds
        # to a suite of nearly nine hundred tests.
        patcher = mock.patch('info.generation.time.sleep')
        self.sleep = patcher.start()
        self.addCleanup(patcher.stop)

    def test_every_request_carries_a_user_agent(self):
        # Groq sits behind a WAF that rejects urllib's default with a 403
        # reading exactly like a rejected key. This is the guard against
        # losing another hour to that.
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured['headers'] = request.headers
            raise urllib.error.URLError('stop here')

        with mock.patch('urllib.request.urlopen', fake_urlopen):
            with self.assertRaises(GenerationError):
                self.generator.ask('s', 'u')

        # urllib title-cases header names.
        self.assertEqual(captured['headers'].get('User-agent'), USER_AGENT)

    def test_the_key_is_sent_as_a_bearer_token(self):
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured['headers'] = request.headers
            raise urllib.error.URLError('stop here')

        with mock.patch('urllib.request.urlopen', fake_urlopen):
            with self.assertRaises(GenerationError):
                self.generator.ask('s', 'u')

        self.assertEqual(captured['headers'].get('Authorization'),
                         'Bearer test-key')

    def test_a_bad_key_is_not_retried(self):
        # It will say the same thing next time, and retrying a 401 three times
        # only makes the failure slower.
        error = urllib.error.HTTPError('url', 401, 'Unauthorized', {}, None)

        with mock.patch('urllib.request.urlopen', side_effect=error) as opened:
            with self.assertRaises(GenerationError):
                self.generator.ask('s', 'u')

        self.assertEqual(opened.call_count, 1)

    def test_a_rate_limit_is_retried(self):
        error = urllib.error.HTTPError('url', 429, 'Too Many', {}, None)

        with mock.patch('urllib.request.urlopen', side_effect=error) as opened:
            with self.assertRaises(GenerationError):
                self.generator.ask('s', 'u')

        self.assertGreater(opened.call_count, 1)

    def test_a_server_error_is_retried(self):
        error = urllib.error.HTTPError('url', 503, 'Unavailable', {}, None)

        with mock.patch('urllib.request.urlopen', side_effect=error) as opened:
            with self.assertRaises(GenerationError):
                self.generator.ask('s', 'u')

        self.assertGreater(opened.call_count, 1)

    def test_a_retry_that_succeeds_returns_the_answer(self):
        class Body:
            def read(self):
                return json.dumps(reply()).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        error = urllib.error.HTTPError('url', 429, 'Too Many', {}, None)

        with mock.patch('urllib.request.urlopen', side_effect=[error, Body()]):
            answer = self.generator.ask('s', 'u')

        self.assertEqual(answer.text, 'an answer')


class ConfigurationTests(SimpleTestCase):
    @override_settings(GROQ_API_KEY='')
    def test_no_key_falls_back_to_the_fake(self):
        self.assertIsInstance(get_generator(), FakeGenerator)

    @override_settings(GROQ_API_KEY='a-key')
    def test_a_key_selects_groq(self):
        self.assertIsInstance(get_generator(), GroqGenerator)

    @override_settings(GROQ_API_KEY='a-key', GROQ_MODEL='qwen/qwen3.8-27b')
    def test_the_model_is_configurable_without_a_code_change(self):
        self.assertEqual(get_generator().model, 'qwen/qwen3.8-27b')


class AnswerTests(SimpleTestCase):
    def test_it_renders_as_its_text_in_a_template(self):
        self.assertEqual('%s' % Answer('hello'), 'hello')

    def test_it_carries_the_model_that_answered(self):
        # Which model wrote an answer matters when one is swapped and the
        # answers change character.
        self.assertEqual(Answer('x', model='openai/gpt-oss-120b').model,
                         'openai/gpt-oss-120b')
