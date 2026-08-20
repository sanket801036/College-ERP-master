"""Which storage the deployment actually picked.

The failure this guards against is quiet: one missing environment variable and
the app keeps working perfectly, writing uploads to a disk that Render throws
away on the next deploy. Nobody notices until somebody looks for a medical
certificate that was there last week.

The settings module is re-imported under a patched environment rather than
tested through `django.conf.settings`, because the choice is made once at
import time and cannot be observed any other way.
"""
import importlib
from unittest import mock

from django.test import SimpleTestCase

BASE_ENV = {
    'SECRET_KEY': 'test-key-not-used-anywhere',
    'DEBUG': 'False',
}


def settings_with(**env):
    """Import the settings module under this environment and hand it back."""
    import CollegeERP.settings as module

    with mock.patch.dict('os.environ', {**BASE_ENV, **env}, clear=False):
        return importlib.reload(module)


class StorageBackendTests(SimpleTestCase):
    def tearDown(self):
        # Leave the module as the rest of the suite expects to find it.
        settings_with()

    def test_without_a_bucket_uploads_stay_on_the_local_disk(self):
        module = settings_with(AWS_STORAGE_BUCKET_NAME='')

        self.assertFalse(module.USE_S3)
        self.assertEqual(module.STORAGES['default']['BACKEND'],
                         'django.core.files.storage.FileSystemStorage')

    def test_a_bucket_switches_the_backend_to_s3(self):
        module = settings_with(AWS_STORAGE_BUCKET_NAME='college-erp-media')

        self.assertTrue(module.USE_S3)
        self.assertEqual(module.STORAGES['default']['BACKEND'],
                         'storages.backends.s3.S3Storage')

    def test_a_custom_endpoint_is_passed_through(self):
        # What makes this any S3-compatible provider - B2 here - rather than
        # AWS specifically.
        module = settings_with(
            AWS_STORAGE_BUCKET_NAME='college-erp-media',
            AWS_S3_REGION_NAME='us-west-004',
            AWS_S3_ENDPOINT_URL='https://s3.us-west-004.backblazeb2.com')

        self.assertEqual(module.AWS_S3_ENDPOINT_URL,
                         'https://s3.us-west-004.backblazeb2.com')
        self.assertEqual(module.AWS_S3_REGION_NAME, 'us-west-004')

    def test_no_endpoint_means_none_rather_than_an_empty_string(self):
        # boto3 reads an empty endpoint as an endpoint and fails to resolve it;
        # None is what tells it to work the region out for itself.
        module = settings_with(AWS_STORAGE_BUCKET_NAME='college-erp-media')

        self.assertIsNone(module.AWS_S3_ENDPOINT_URL)

    def test_uploads_are_never_world_readable(self):
        module = settings_with(AWS_STORAGE_BUCKET_NAME='college-erp-media')

        # These are photographs of people and medical certificates. The ACL is
        # None because B2 has none to set; the signing is what grants access.
        self.assertIsNone(module.AWS_DEFAULT_ACL)
        self.assertTrue(module.AWS_QUERYSTRING_AUTH)
        self.assertLessEqual(module.AWS_QUERYSTRING_EXPIRE, 3600)


class DatabaseConnectionTests(SimpleTestCase):
    def tearDown(self):
        settings_with()

    def test_connections_are_not_held_past_a_serverless_idle_timeout(self):
        # Neon closes idle connections after five minutes. Holding one for
        # longer hands the next request a dead socket.
        module = settings_with(
            DATABASE_URL='postgres://user:pass@host.neon.tech/db')

        self.assertLessEqual(module.DATABASES['default']['CONN_MAX_AGE'], 300)
        self.assertTrue(module.DATABASES['default']['CONN_HEALTH_CHECKS'])
