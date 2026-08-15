from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from info.models import Student, Teacher
from info.tests import factories as f

User = get_user_model()


class AddStudentTests(TestCase):
    def setUp(self):
        self.dept = f.make_dept()
        self.klass = f.make_class(self.dept)
        self.client.force_login(f.make_admin())

    def _payload(self, **overrides):
        data = {
            'USN': '1CS20CS002',
            'name': 'Asha Rao',
            'class_id': self.klass.pk,
            'sex': 'Female',
            'DOB': '2002-05-14',
            'email': 'asha@example.com',
        }
        data.update(overrides)
        return data

    def test_creates_student_and_shows_credentials_once(self):
        response = self.client.post(reverse('add_student'), self._payload())

        self.assertEqual(response.status_code, 200)
        student = Student.objects.get(USN='1CS20CS002')
        self.assertEqual(student.name, 'Asha Rao')
        self.assertIsNotNone(student.user)

        creds = response.context['credentials']
        self.assertEqual(creds['username'], student.user.username)
        self.assertTrue(student.user.check_password(creds['password']),
                        'the password shown to the admin must be the real one')

    def test_duplicate_usn_is_rejected_instead_of_overwriting(self):
        """The important one.

        USN is the primary key, so saving a Student with an existing USN used to
        UPDATE that row - wiping the original student's name, class and DOB and
        moving their login to the new account, with no error shown.
        """
        existing = f.make_student(self.klass, usn='1CS20CS003', name='Original Name')
        original_user_id = existing.user_id

        response = self.client.post(
            reverse('add_student'),
            self._payload(USN='1CS20CS003', name='Impostor'),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context['form'], 'USN',
                             'A student with this USN already exists.')

        existing.refresh_from_db()
        self.assertEqual(existing.name, 'Original Name')
        self.assertEqual(existing.user_id, original_user_id)
        self.assertEqual(Student.objects.count(), 1)

    def test_failed_submission_does_not_leave_an_orphan_user(self):
        before = User.objects.count()

        self.client.post(reverse('add_student'), self._payload(email='not-an-email'))

        self.assertEqual(User.objects.count(), before)
        self.assertFalse(Student.objects.filter(USN='1CS20CS002').exists())

    def test_username_collision_gets_a_suffix(self):
        f.make_student(self.klass, usn='2CS20CS002', name='Asha Kumar',
                       username='asha_002')

        self.client.post(reverse('add_student'), self._payload())

        student = Student.objects.get(USN='1CS20CS002')
        self.assertEqual(student.user.username, 'asha_002_2')

    def test_email_is_stored_on_the_user(self):
        """Password reset and notifications have nowhere to go without this."""
        self.client.post(reverse('add_student'), self._payload())

        student = Student.objects.get(USN='1CS20CS002')
        self.assertEqual(student.user.email, 'asha@example.com')

    def test_password_is_not_derived_from_personal_details(self):
        self.client.post(reverse('add_student'), self._payload())

        user = Student.objects.get(USN='1CS20CS002').user
        self.assertFalse(user.check_password('asha_2002'),
                         'passwords must not be guessable from name + birth year')

    def test_non_admin_is_turned_away(self):
        self.client.force_login(f.make_student(self.klass, usn='9CS20CS009',
                                               username='someone').user)

        response = self.client.post(reverse('add_student'), self._payload())

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Student.objects.filter(USN='1CS20CS002').exists())


class AddTeacherTests(TestCase):
    def setUp(self):
        self.dept = f.make_dept()
        self.client.force_login(f.make_admin())

    def _payload(self, **overrides):
        data = {
            'id': 'T042',
            'name': 'Ravi Shankar',
            'dept': self.dept.pk,
            'sex': 'Male',
            'DOB': '1979-03-02',
            'email': 'ravi@example.com',
        }
        data.update(overrides)
        return data

    def test_creates_teacher(self):
        response = self.client.post(reverse('add_teacher'), self._payload())

        teacher = Teacher.objects.get(id='t042')
        self.assertEqual(teacher.name, 'Ravi Shankar')
        self.assertTrue(
            teacher.user.check_password(response.context['credentials']['password']))

    def test_duplicate_staff_id_is_rejected_instead_of_overwriting(self):
        existing = f.make_teacher(self.dept, id='t042', name='Original Teacher')

        response = self.client.post(reverse('add_teacher'), self._payload())

        self.assertFormError(response.context['form'], 'id',
                             'A teacher with this ID already exists.')
        existing.refresh_from_db()
        self.assertEqual(existing.name, 'Original Teacher')
        self.assertEqual(Teacher.objects.count(), 1)
