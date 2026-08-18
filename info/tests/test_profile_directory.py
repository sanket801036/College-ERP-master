"""Self-service contact details, and a way to look somebody up.

Neither existed: the only self-service was the password form, and the only way
to find a student was the search box on the fees page.
"""
from django.test import TestCase
from django.urls import reverse

from info.tests import factories as f


class ProfileTests(TestCase):
    def setUp(self):
        self.dept = f.make_dept()
        self.klass = f.make_class(self.dept)
        self.student = f.make_student(self.klass, name='Asha Rao',
                                      username='pupil')
        self.teacher = f.make_teacher(self.dept, id='t001', username='staff')
        self.url = reverse('profile')

    def _payload(self, **overrides):
        data = {'email': 'asha@example.edu', 'phone': '+91 98765 43210',
                'address': '12 Park Road'}
        data.update(overrides)
        return data

    def test_a_student_sees_their_own_record(self):
        self.client.force_login(self.student.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.student.USN)
        self.assertContains(response, 'Asha Rao')

    def test_a_teacher_sees_their_staff_id_and_department(self):
        self.client.force_login(self.teacher.user)

        response = self.client.get(self.url)

        self.assertContains(response, self.teacher.id)
        self.assertContains(response, self.dept.name)

    def test_contact_details_can_be_updated(self):
        self.client.force_login(self.student.user)

        response = self.client.post(self.url, self._payload())

        self.assertRedirects(response, self.url)
        self.student.refresh_from_db()
        self.student.user.refresh_from_db()
        self.assertEqual(self.student.phone, '+91 98765 43210')
        self.assertEqual(self.student.address, '12 Park Road')
        self.assertEqual(self.student.user.email, 'asha@example.edu')

    def test_the_form_does_not_expose_usn_or_class(self):
        """Changing those is an administrative act with consequences for
        attendance and marks, not a profile edit.

        Asserted as an exclusion rather than an exact field list: the form is
        allowed to grow - it has since gained a photo - but never these.
        """
        self.client.force_login(self.student.user)

        fields = set(self.client.get(self.url).context['form'].fields)

        self.assertFalse(fields & {'USN', 'class_id', 'DOB', 'name', 'sex',
                                   'is_active', 'dept', 'id'})

    def test_a_malformed_phone_number_is_rejected(self):
        self.client.force_login(self.student.user)

        response = self.client.post(self.url, self._payload(phone='call me'))

        self.assertEqual(response.status_code, 200)
        self.student.refresh_from_db()
        self.assertEqual(self.student.phone, '')

    def test_an_email_already_in_use_is_rejected(self):
        """Password resets are addressed by email; two accounts sharing one
        makes that ambiguous."""
        other = f.make_student(self.klass, usn='1CS20CS900', name='Someone',
                               username='other')
        other.user.email = 'taken@example.edu'
        other.user.save(update_fields=['email'])
        self.client.force_login(self.student.user)

        response = self.client.post(self.url,
                                    self._payload(email='taken@example.edu'))

        self.assertEqual(response.status_code, 200)
        self.assertIn('already uses that address',
                      str(response.context['form'].errors['email']))

    def test_keeping_your_own_email_is_not_a_clash(self):
        self.student.user.email = 'asha@example.edu'
        self.student.user.save(update_fields=['email'])
        self.client.force_login(self.student.user)

        response = self.client.post(self.url, self._payload())

        self.assertRedirects(response, self.url)

    def test_an_admin_has_no_profile_record_to_show(self):
        self.client.force_login(f.make_admin())

        response = self.client.get(self.url)

        self.assertRedirects(response, reverse('password_change'))

    def test_anonymous_users_are_sent_to_login(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])


class DirectoryTests(TestCase):
    def setUp(self):
        self.dept = f.make_dept()
        self.klass = f.make_class(self.dept)
        self.teacher = f.make_teacher(self.dept, id='t001', name='Ravi Shankar',
                                      username='staff')
        self.asha = f.make_student(self.klass, usn='1CS20CS001', name='Asha Rao',
                                   username='asha')
        self.bhavna = f.make_student(self.klass, usn='1CS20CS002',
                                     name='Bhavna Singh', username='bhavna')
        self.url = reverse('directory')
        self.client.force_login(self.teacher.user)

    def _names(self, **params):
        page = self.client.get(self.url, params).context['page']
        return [p.name for p in page]

    def test_lists_students_by_default(self):
        self.assertEqual(self._names(), ['Asha Rao', 'Bhavna Singh'])

    def test_search_by_name(self):
        self.assertEqual(self._names(q='bhavna'), ['Bhavna Singh'])

    def test_search_by_usn(self):
        self.assertEqual(self._names(q='CS001'), ['Asha Rao'])

    def test_search_by_class(self):
        self.assertEqual(len(self._names(q=self.klass.pk)), 2)

    def test_switching_to_teachers(self):
        self.assertEqual(self._names(kind='teachers'), ['Ravi Shankar'])

    def test_search_teachers_by_staff_id(self):
        self.assertEqual(self._names(kind='teachers', q='t001'),
                         ['Ravi Shankar'])

    def test_no_match_says_so(self):
        response = self.client.get(self.url, {'q': 'nobody by that name'})

        self.assertContains(response, 'Nobody matches that search')

    def test_the_list_is_paginated(self):
        for i in range(30):
            f.make_student(self.klass, usn='2CS20CS%03d' % i,
                           name='Student %d' % i, username='s%d' % i)

        page = self.client.get(self.url).context['page']

        self.assertEqual(len(page), 25)
        self.assertTrue(page.has_next())

    def test_a_student_cannot_open_the_directory(self):
        """A roster of every classmate's contact details is not something a
        student needs."""
        self.client.force_login(self.asha.user)

        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_an_admin_can(self):
        self.client.force_login(f.make_admin())

        self.assertEqual(self.client.get(self.url).status_code, 200)
