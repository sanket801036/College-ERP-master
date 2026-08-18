"""Profile photos.

MEDIA_ROOT was '' and MEDIA_URL '/', so an upload had nowhere to go and would
have been served from the site root. Nothing could be uploaded at all.
"""
import io
import shutil
import tempfile

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from info.tests import factories as f

MEDIA = tempfile.mkdtemp()


def an_image(size=(800, 600), mode='RGB', fmt='JPEG', name='photo.jpg'):
    image = Image.new(mode, size, (120, 60, 200))
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    buffer.seek(0)
    content_type = 'image/png' if fmt == 'PNG' else 'image/jpeg'
    return SimpleUploadedFile(name, buffer.read(), content_type)


@override_settings(MEDIA_ROOT=MEDIA)
class PhotoUploadTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        self.student = f.make_student(self.klass, name='Asha Rao',
                                      username='asha')
        self.client.force_login(self.student.user)
        self.url = reverse('profile')

    def _post(self, **extra):
        data = {'email': 'asha@example.edu', 'phone': '', 'address': ''}
        data.update(extra)
        return self.client.post(self.url, data)

    def test_a_photo_can_be_uploaded(self):
        response = self._post(photo=an_image())

        self.assertRedirects(response, self.url)
        self.student.refresh_from_db()
        self.assertTrue(self.student.photo)

    def test_it_is_cropped_square_and_resized(self):
        """A phone photograph is several megabytes and thousands of pixels
        wide, and it would be served at that size on every roster row."""
        self._post(photo=an_image(size=(2000, 1200)))

        self.student.refresh_from_db()
        with Image.open(self.student.photo) as stored:
            self.assertEqual(stored.size,
                             (settings.PROFILE_PHOTO_SIZE,
                              settings.PROFILE_PHOTO_SIZE))

    def test_it_is_stored_as_jpeg_even_when_a_png_is_uploaded(self):
        self._post(photo=an_image(fmt='PNG', name='photo.png'))

        self.student.refresh_from_db()
        with Image.open(self.student.photo) as stored:
            self.assertEqual(stored.format, 'JPEG')

    def test_transparency_is_flattened_rather_than_erroring(self):
        """JPEG has no alpha channel, so an RGBA upload has to be composited
        onto something first."""
        response = self._post(photo=an_image(mode='RGBA', fmt='PNG',
                                             name='photo.png'))

        self.assertRedirects(response, self.url)
        self.student.refresh_from_db()
        self.assertTrue(self.student.photo)

    def test_the_file_is_named_after_the_person(self):
        """So a file in a bucket can be traced back without the database."""
        self._post(photo=an_image())

        self.student.refresh_from_db()
        self.assertIn(self.student.USN, self.student.photo.name)

    def test_an_oversized_upload_is_rejected(self):
        big = SimpleUploadedFile('big.jpg', b'x' * (6 * 1024 * 1024),
                                 'image/jpeg')

        response = self._post(photo=big)

        self.assertEqual(response.status_code, 200)
        self.student.refresh_from_db()
        self.assertFalse(self.student.photo)

    def test_a_file_that_is_not_an_image_is_rejected(self):
        response = self._post(photo=SimpleUploadedFile('notes.txt', b'hello',
                                                       'text/plain'))

        self.assertEqual(response.status_code, 200)
        self.student.refresh_from_db()
        self.assertFalse(self.student.photo)

    def test_uploading_a_second_photo_replaces_the_first(self):
        self._post(photo=an_image())
        self.student.refresh_from_db()
        first = self.student.photo.name

        self._post(photo=an_image(size=(500, 500)))

        self.student.refresh_from_db()
        self.assertTrue(self.student.photo)
        self.assertFalse(self.student.photo.storage.exists(first))

    def test_a_photo_can_be_removed(self):
        self._post(photo=an_image())

        self._post(remove_photo='on')

        self.student.refresh_from_db()
        self.assertFalse(self.student.photo)

    def test_saving_other_details_leaves_the_photo_alone(self):
        self._post(photo=an_image())
        self.student.refresh_from_db()
        existing = self.student.photo.name

        self._post(phone='+91 90000 00000')

        self.student.refresh_from_db()
        self.assertEqual(self.student.photo.name, existing)


@override_settings(MEDIA_ROOT=MEDIA)
class PhotoDisplayTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        self.teacher = f.make_teacher(dept, id='t001', username='staff')
        self.student = f.make_student(self.klass, name='Asha Rao',
                                      username='asha')

    def test_the_directory_falls_back_to_an_initial(self):
        """Most people will not upload one, and a broken image icon on every
        row is worse than a letter."""
        self.client.force_login(self.teacher.user)

        response = self.client.get(reverse('directory'))

        self.assertContains(response, 'erp-photo-empty')

    def test_the_directory_shows_the_photo_once_there_is_one(self):
        self.client.force_login(self.student.user)
        self.client.post(reverse('profile'),
                         {'email': 'asha@example.edu', 'phone': '',
                          'address': '', 'photo': an_image()})
        self.client.force_login(self.teacher.user)

        response = self.client.get(reverse('directory'))

        self.student.refresh_from_db()
        self.assertContains(response, self.student.photo.url)
