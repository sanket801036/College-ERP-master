"""Handing out the one-time passwords.

The credentials appear once, in the response that created the accounts - they
are random and not stored readably - so that page has to be printable.
"""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from info.tests import factories as f

HEADER = ['usn', 'name', 'class', 'sex', 'dob', 'email']


class SlipTests(TestCase):
    def setUp(self):
        self.dept = f.make_dept()
        self.klass = f.make_class(self.dept)
        self.client.force_login(f.make_admin())

    def _import(self, rows):
        lines = [','.join(HEADER)] + [','.join(row) for row in rows]
        upload = SimpleUploadedFile('intake.csv', '\n'.join(lines).encode(),
                                    'text/csv')
        return self.client.post(reverse('bulk_import'),
                                {'file': upload, 'kind': 'students'})

    def _row(self, usn, name, email):
        return [usn, name, self.klass.pk, 'Female', '2004-05-14', email]

    def test_a_slip_is_rendered_for_every_imported_person(self):
        """One each, rather than a table - a printed table has to be cut into
        strips and matched back up against the names by hand."""
        response = self._import([
            self._row('1CS22CS001', 'Asha Rao', 'asha@example.edu'),
            self._row('1CS22CS002', 'Bhavna Singh', 'bhavna@example.edu'),
        ])

        body = response.content.decode()
        self.assertEqual(body.count('erp-slip-name'), 2)
        self.assertIn('Asha Rao', body)
        self.assertIn('Bhavna Singh', body)

    def test_the_slip_carries_the_credentials(self):
        response = self._import(
            [self._row('1CS22CS001', 'Asha Rao', 'asha@example.edu')])

        person = response.context['created'][0]
        body = response.content.decode()
        slip = body[body.index('erp-slip-name'):body.index('erp-slip-note')]
        self.assertIn(person['username'], slip)
        self.assertIn(person['password'], slip)

    def test_the_slip_says_the_password_is_temporary(self):
        """The account is created with must_change_password set, so the slip
        should not read as though this is the permanent one."""
        response = self._import(
            [self._row('1CS22CS001', 'Asha Rao', 'asha@example.edu')])

        self.assertContains(response, 'choose your own password')

    def test_the_screen_furniture_is_marked_not_to_print(self):
        response = self._import(
            [self._row('1CS22CS001', 'Asha Rao', 'asha@example.edu')])

        self.assertContains(response, 'erp-no-print')

    def test_a_single_account_gets_a_slip_too(self):
        """Both routes hand out credentials, so both print the same thing."""
        response = self.client.post(reverse('add_student'), {
            'USN': '1CS22CS009', 'name': 'Solo Student',
            'class_id': self.klass.pk, 'sex': 'Male', 'DOB': '2004-01-01',
            'email': 'solo@example.edu'})

        self.assertContains(response, 'erp-slip-name')
        self.assertContains(response, 'Solo Student')

    def test_no_slip_before_anything_has_been_created(self):
        response = self.client.get(reverse('bulk_import'))

        self.assertNotContains(response, 'erp-slip-name')
