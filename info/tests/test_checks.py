"""The deploy checks, which exist because of a bug that reported nothing.

`manage.py check` runs on every start, including Render's during a deploy,
which is the only moment anybody is watching a log. These warnings are the
difference between a half-configured service failing at deploy time and
failing three weeks later in front of somebody.

The storage check earned its place: the bucket, region and credentials were
set but the endpoint was not, so uploads were signed for Backblaze and
addressed to Amazon. They succeeded. The files landed. Every link pointed at a
host that had never heard of them, and nothing anywhere raised.

The AI checks are the same shape. Two providers are needed and neither does
the other's job, so configuring one and not the other leaves something that
looks like it works.
"""
from django.test import SimpleTestCase, override_settings

from info.checks import (
    W001,
    W002,
    W003,
    W004,
    W005,
    check_ai_layer,
    check_object_storage,
)


def ids(problems):
    return {problem.id for problem in problems}


class ObjectStorageTests(SimpleTestCase):
    @override_settings(USE_S3=False)
    def test_nothing_is_checked_when_storage_is_off(self):
        self.assertEqual(check_object_storage(None), [])

    @override_settings(USE_S3=True, AWS_S3_REGION_NAME='us-east-005',
                       AWS_S3_ENDPOINT_URL=None,
                       AWS_ACCESS_KEY_ID='k', AWS_SECRET_ACCESS_KEY='s')
    def test_a_non_aws_region_without_an_endpoint_is_the_original_bug(self):
        # Signed for Backblaze, addressed to Amazon. Uploads succeed and every
        # link is dead.
        self.assertIn(W001, ids(check_object_storage(None)))

    @override_settings(USE_S3=True, AWS_S3_REGION_NAME='us-east-005',
                       AWS_S3_ENDPOINT_URL='https://s3.us-east-005.backblazeb2.com',
                       AWS_ACCESS_KEY_ID='k', AWS_SECRET_ACCESS_KEY='s')
    def test_the_same_region_with_an_endpoint_is_fine(self):
        self.assertNotIn(W001, ids(check_object_storage(None)))

    @override_settings(USE_S3=True, AWS_S3_REGION_NAME='eu-west-2',
                       AWS_S3_ENDPOINT_URL=None,
                       AWS_ACCESS_KEY_ID='k', AWS_SECRET_ACCESS_KEY='s')
    def test_a_real_aws_region_needs_no_endpoint(self):
        self.assertNotIn(W001, ids(check_object_storage(None)))

    @override_settings(USE_S3=True, AWS_S3_REGION_NAME='eu-west-2',
                       AWS_S3_ENDPOINT_URL=None,
                       AWS_ACCESS_KEY_ID='', AWS_SECRET_ACCESS_KEY='')
    def test_a_bucket_with_no_credentials_is_reported(self):
        self.assertIn(W002, ids(check_object_storage(None)))


class AiLayerTests(SimpleTestCase):
    @override_settings(GROQ_API_KEY='', GEMINI_API_KEY='',
                       AI_DAILY_CALL_CAP=200, AI_USER_DAILY_CALL_CAP=30)
    def test_no_keys_at_all_is_not_a_complaint(self):
        # A checkout with no keys is a normal state, not a broken deployment.
        self.assertEqual(check_ai_layer(None), [])

    @override_settings(GROQ_API_KEY='g', GEMINI_API_KEY='e',
                       AI_DAILY_CALL_CAP=200, AI_USER_DAILY_CALL_CAP=30)
    def test_both_keys_and_real_caps_is_clean(self):
        self.assertEqual(check_ai_layer(None), [])

    @override_settings(GROQ_API_KEY='g', GEMINI_API_KEY='',
                       AI_DAILY_CALL_CAP=200, AI_USER_DAILY_CALL_CAP=30)
    def test_generation_without_embeddings_is_the_dangerous_half(self):
        # The chatbot answers fluently from whichever passages the fake
        # embedder happened to retrieve, and nothing reports that they were
        # the wrong ones. This is the warning worth having.
        self.assertIn(W003, ids(check_ai_layer(None)))

    @override_settings(GROQ_API_KEY='', GEMINI_API_KEY='e',
                       AI_DAILY_CALL_CAP=200, AI_USER_DAILY_CALL_CAP=30)
    def test_embeddings_without_generation_is_reported_too(self):
        self.assertIn(W004, ids(check_ai_layer(None)))

    @override_settings(GROQ_API_KEY='g', GEMINI_API_KEY='e',
                       AI_DAILY_CALL_CAP=0, AI_USER_DAILY_CALL_CAP=30)
    def test_a_zero_cap_alongside_a_live_key_is_worth_saying_out_loud(self):
        # Zero is a legitimate setting - it is the off switch - but a public
        # demo with a live key and a cap somebody meant to set is not.
        self.assertIn(W005, ids(check_ai_layer(None)))

    @override_settings(GROQ_API_KEY='', GEMINI_API_KEY='',
                       AI_DAILY_CALL_CAP=0, AI_USER_DAILY_CALL_CAP=0)
    def test_zero_caps_with_no_keys_is_silent(self):
        # Nothing is configured, so there is nothing to warn about.
        self.assertEqual(check_ai_layer(None), [])
