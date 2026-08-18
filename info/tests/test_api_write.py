"""Token sign-in, and submitting attendance over the API.

The API had no way to obtain a token and no way to write anything, so it could
only ever be a read-only companion to the web app.
"""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token

from info.models import CLASS_CANCELLED, Attendance, AttendanceClass, AuditLog
from info.tests import factories as f


class TokenTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        self.teacher = f.make_teacher(dept, id='t001', username='staff',
                                      password='pass12345')
        self.student = f.make_student(self.klass, username='pupil',
                                      password='pass12345')
        self.url = '/api/v1/auth/token/'

    def test_valid_credentials_return_a_token(self):
        response = self.client.post(self.url, {'username': 'staff',
                                               'password': 'pass12345'})

        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertEqual(data['token'],
                         Token.objects.get(user=self.teacher.user).key)
        self.assertEqual(data['role'], 'teacher')

    def test_the_role_is_reported(self):
        for username, role in [('pupil', 'student'), ('staff', 'teacher')]:
            with self.subTest(role=role):
                response = self.client.post(self.url, {'username': username,
                                                       'password': 'pass12345'})
                self.assertEqual(response.json()['data']['role'], role)

    def test_a_wrong_password_is_rejected(self):
        response = self.client.post(self.url, {'username': 'staff',
                                               'password': 'nope'})

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Token.objects.exists())

    def test_the_same_token_comes_back_on_a_second_sign_in(self):
        first = self.client.post(self.url, {'username': 'staff',
                                            'password': 'pass12345'})
        second = self.client.post(self.url, {'username': 'staff',
                                             'password': 'pass12345'})

        self.assertEqual(first.json()['data']['token'],
                         second.json()['data']['token'])

    def test_the_token_then_works_on_a_real_endpoint(self):
        token = self.client.post(
            self.url, {'username': 'pupil', 'password': 'pass12345'}
        ).json()['data']['token']

        response = self.client.get('/api/v1/details/',
                                   HTTP_AUTHORIZATION='Token ' + token)

        self.assertEqual(response.status_code, 200)


class SubmitAttendanceTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        self.course = f.make_course(dept)
        self.teacher = f.make_teacher(dept, id='t001', username='owner')
        self.assign = f.make_assign(self.klass, self.course, self.teacher)
        self.asha = f.make_student(self.klass, usn='1CS20CS001', name='Asha',
                                   username='asha')
        self.bhavna = f.make_student(self.klass, usn='1CS20CS002',
                                     name='Bhavna', username='bhavna')
        self.session = AttendanceClass.objects.create(
            assign=self.assign, date=timezone.localdate() - timedelta(days=1))
        self.url = '/api/v1/sessions/%d/attendance/' % self.session.id
        self.client.force_login(self.teacher.user)

    def _submit(self, present, url=None):
        return self.client.post(url or self.url, {'present': present},
                                content_type='application/json')

    def test_marks_the_whole_class(self):
        response = self._submit([self.asha.USN])

        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertTrue(data['first_submission'])
        self.assertEqual(data['present'], 1)
        self.assertEqual(data['total'], 2)

        self.assertTrue(Attendance.objects.get(student=self.asha).status)
        self.assertFalse(Attendance.objects.get(student=self.bhavna).status)

    def test_an_empty_list_marks_everybody_absent(self):
        self._submit([])

        self.assertEqual(Attendance.objects.filter(status=True).count(), 0)
        self.assertEqual(Attendance.objects.count(), 2)

    def test_resubmitting_reports_and_logs_what_changed(self):
        self._submit([self.asha.USN])

        response = self._submit([self.bhavna.USN])

        data = response.json()['data']
        self.assertFalse(data['first_submission'])
        self.assertEqual(data['changed'], 2)
        self.assertEqual(
            AuditLog.objects.filter(action='attendance.changed').count(), 2)

    def test_a_usn_from_another_class_is_rejected(self):
        """Quietly ignoring it would record this whole class absent on the
        caller's behalf."""
        other = f.make_class(self.klass.dept, id='CS-3B', section='B')
        stranger = f.make_student(other, usn='9CS20CS999', name='Stranger',
                                  username='stranger')

        response = self._submit([stranger.USN])

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Attendance.objects.exists())

    def test_a_cancelled_session_cannot_be_marked(self):
        AttendanceClass.objects.filter(pk=self.session.pk).update(
            status=CLASS_CANCELLED)

        response = self._submit([])

        self.assertEqual(response.status_code, 409)
        self.assertFalse(Attendance.objects.exists())

    def test_a_future_session_cannot_be_marked(self):
        future = AttendanceClass.objects.create(
            assign=self.assign, date=timezone.localdate() + timedelta(days=7))

        response = self._submit(
            [], url='/api/v1/sessions/%d/attendance/' % future.id)

        self.assertEqual(response.status_code, 409)

    def test_another_teacher_cannot_mark_this_session(self):
        stranger = f.make_teacher(self.klass.dept, id='t002', name='Stranger',
                                  username='stranger_t')
        self.client.force_login(stranger.user)

        response = self._submit([])

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Attendance.objects.exists())

    def test_a_student_cannot_mark_attendance(self):
        self.client.force_login(self.asha.user)

        response = self._submit([self.asha.USN])

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Attendance.objects.exists())

    def test_an_unauthenticated_caller_is_rejected(self):
        self.client.logout()

        self.assertEqual(self._submit([]).status_code, 401)


class SharedRulesTests(TestCase):
    """The web form and the API go through the same service.

    An API with its own copy of these rules would be a way around the checks
    the form performs.
    """

    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        self.course = f.make_course(dept)
        self.teacher = f.make_teacher(dept, id='t001', username='owner')
        self.assign = f.make_assign(self.klass, self.course, self.teacher)
        self.student = f.make_student(self.klass, usn='1CS20CS001',
                                      username='pupil')
        self.client.force_login(self.teacher.user)

    def _session(self, days_ago=1):
        return AttendanceClass.objects.create(
            assign=self.assign,
            date=timezone.localdate() - timedelta(days=days_ago))

    def test_both_routes_produce_the_same_record(self):
        via_form = self._session(days_ago=1)
        self.client.post(reverse('confirm', args=(via_form.id,)),
                         {self.student.USN: 'present'})

        via_api = self._session(days_ago=2)
        self.client.post('/api/v1/sessions/%d/attendance/' % via_api.id,
                         {'present': [self.student.USN]},
                         content_type='application/json')

        records = Attendance.objects.filter(student=self.student)
        self.assertEqual(records.count(), 2)
        self.assertTrue(all(r.status for r in records))

    def test_both_routes_refuse_a_cancelled_session(self):
        session = self._session()
        AttendanceClass.objects.filter(pk=session.pk).update(
            status=CLASS_CANCELLED)

        form = self.client.post(reverse('confirm', args=(session.id,)),
                                {self.student.USN: 'present'})
        api = self.client.post('/api/v1/sessions/%d/attendance/' % session.id,
                               {'present': []},
                               content_type='application/json')

        self.assertEqual(form.status_code, 302)  # redirected carrying an error
        self.assertEqual(api.status_code, 409)
        self.assertFalse(Attendance.objects.exists())
