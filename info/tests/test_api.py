"""The four read-only student endpoints.

As shipped these returned 400 "User not authenticated" to every caller: each
view re-derived the user from a Token row on top of DRF's own authentication,
and nothing in the application ever issued a token.
"""
from datetime import date, timedelta

from django.test import TestCase
from rest_framework.authtoken.models import Token

from info.models import AssignTime, Attendance, AttendanceClass, StudentCourse
from info.tests import factories as f


class StudentApiTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        self.course = f.make_course(dept)
        self.teacher = f.make_teacher(dept, id='t001', username='owner')
        self.assign = f.make_assign(self.klass, self.course, self.teacher)
        self.student = f.make_student(self.klass, name='Asha Rao',
                                      username='pupil')
        AssignTime.objects.create(assign=self.assign, day='Monday',
                                  period='7:30 - 8:30')

        day = date(2026, 1, 5)
        for i in range(4):
            session = AttendanceClass.objects.create(assign=self.assign,
                                                     date=day + timedelta(days=i))
            Attendance.objects.create(course=self.course, student=self.student,
                                      attendanceclass=session,
                                      date=session.date, status=i < 3)

    def test_session_authentication_is_accepted(self):
        """The headline bug: a signed-in student was rejected outright."""
        self.client.force_login(self.student.user)

        for url in ['/api/details/', '/api/attendance/', '/api/marks/',
                    '/api/timetable/']:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_token_authentication_still_works(self):
        token = Token.objects.create(user=self.student.user)

        response = self.client.get('/api/details/',
                                   HTTP_AUTHORIZATION='Token %s' % token.key)

        self.assertEqual(response.status_code, 200)

    def test_unauthenticated_gets_401(self):
        self.assertEqual(self.client.get('/api/details/').status_code, 401)

    def test_details_returns_the_profile_without_date_of_birth(self):
        self.client.force_login(self.student.user)

        data = self.client.get('/api/details/').json()['data']

        self.assertEqual(data['name'], 'Asha Rao')
        self.assertEqual(data['USN'], self.student.USN)
        self.assertNotIn('DOB', data)

    def test_attendance_returns_actual_attendance(self):
        """The serializer used fields='__all__' on a model whose useful values
        are all properties, so the endpoint returned identifiers and nothing
        else."""
        self.client.force_login(self.student.user)

        rows = self.client.get('/api/attendance/').json()['data']

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['attended'], 3)
        self.assertEqual(row['held'], 4)
        self.assertEqual(row['percentage'], 75.0)
        self.assertIn('classes_to_attend', row)

    def test_marks_include_cie(self):
        sc = StudentCourse.objects.get(student=self.student, course=self.course)
        sc.marks_set.filter(name='Internal test 1').update(marks1=18)
        self.client.force_login(self.student.user)

        rows = self.client.get('/api/marks/').json()['data']

        self.assertEqual(rows[0]['cie'], 9)
        self.assertEqual(rows[0]['marks']['Internal test 1'], 18)

    def test_timetable_uses_a_data_key(self):
        """It returned its payload under "user_marks", copied from the marks
        view."""
        self.client.force_login(self.student.user)

        body = self.client.get('/api/timetable/').json()

        self.assertIn('data', body)
        self.assertNotIn('user_marks', body)
        self.assertEqual(body['data'][0]['day'], 'Monday')
        self.assertEqual(body['data'][0]['teacher'], self.teacher.name)

    def test_attendance_endpoint_does_not_write(self):
        """It created missing AttendanceTotal rows inside the GET handler."""
        from info.models import AttendanceTotal
        AttendanceTotal.objects.all().delete()
        self.client.force_login(self.student.user)

        self.client.get('/api/attendance/')

        self.assertEqual(AttendanceTotal.objects.count(), 0)

    def test_a_teacher_gets_404_not_a_500(self):
        """Teachers have no student record; the old code turned every failure
        into a 400 carrying the raw exception text."""
        self.client.force_login(self.teacher.user)

        self.assertEqual(self.client.get('/api/details/').status_code, 404)

    def test_a_student_only_ever_sees_their_own_records(self):
        other = f.make_student(self.klass, usn='1CS20CS999', name='Someone Else',
                               username='other')
        self.client.force_login(self.student.user)

        data = self.client.get('/api/details/').json()['data']

        self.assertEqual(data['USN'], self.student.USN)
        self.assertNotEqual(data['USN'], other.USN)
