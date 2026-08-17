"""Documentation, versioning, and the teacher-facing endpoints.

The API was student-only and read-only, with no way to see what it offered
short of reading the source.
"""
from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse

from info.models import Attendance, AttendanceClass
from info.tests import factories as f


class SchemaTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.student = f.make_student(f.make_class(dept), username='pupil')
        self.client.force_login(self.student.user)

    def test_the_schema_is_served(self):
        response = self.client.get('/api/schema/')

        self.assertEqual(response.status_code, 200)
        self.assertIn('openapi', response.content.decode()[:200].lower())

    def test_swagger_and_redoc_render(self):
        for url in ['/api/docs/', '/api/redoc/']:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_endpoints_answer_on_both_the_versioned_and_plain_paths(self):
        """Versioned before anything consumes it; the old paths stay as aliases
        so nothing that already calls them breaks."""
        for path in ['details', 'attendance', 'marks', 'timetable']:
            with self.subTest(path=path):
                self.assertEqual(
                    self.client.get('/api/v1/%s/' % path).status_code, 200)
                self.assertEqual(
                    self.client.get('/api/%s/' % path).status_code, 200)


class TeacherEndpointTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        self.course = f.make_course(dept)
        self.teacher = f.make_teacher(dept, id='t001', username='owner')
        self.assign = f.make_assign(self.klass, self.course, self.teacher)

        self.present = f.make_student(self.klass, usn='1CS20CS001',
                                      name='Asha Rao', username='asha')
        self.absent = f.make_student(self.klass, usn='1CS20CS002',
                                     name='Bhavna Singh', username='bhavna')

        day = date(2026, 1, 5)
        for i in range(4):
            session = AttendanceClass.objects.create(assign=self.assign,
                                                     date=day + timedelta(days=i))
            Attendance.objects.create(course=self.course, student=self.present,
                                      attendanceclass=session,
                                      date=session.date, status=True)
            Attendance.objects.create(course=self.course, student=self.absent,
                                      attendanceclass=session,
                                      date=session.date, status=i == 0)

        self.other_teacher = f.make_teacher(dept, id='t002', name='Other',
                                            username='other')

    def test_a_teacher_sees_their_own_classes(self):
        self.client.force_login(self.teacher.user)

        rows = self.client.get('/api/v1/classes/').json()['data']

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['course_id'], self.course.id)
        self.assertEqual(rows[0]['student_count'], 2)

    def test_a_teacher_does_not_see_another_teachers_classes(self):
        self.client.force_login(self.other_teacher.user)

        self.assertEqual(self.client.get('/api/v1/classes/').json()['data'], [])

    def test_a_superuser_sees_every_class(self):
        self.client.force_login(f.make_admin())

        self.assertEqual(len(self.client.get('/api/v1/classes/').json()['data']), 1)

    def test_a_student_cannot_reach_the_teacher_endpoints(self):
        self.client.force_login(self.present.user)

        response = self.client.get('/api/v1/classes/')

        self.assertEqual(response.status_code, 404)

    def test_class_students_reports_attendance_standing(self):
        self.client.force_login(self.teacher.user)

        url = '/api/v1/classes/%d/students/' % self.assign.id
        rows = {r['usn']: r for r in self.client.get(url).json()['data']}

        self.assertEqual(rows['1CS20CS001']['percentage'], 100.0)
        self.assertFalse(rows['1CS20CS001']['at_risk'])
        self.assertEqual(rows['1CS20CS002']['attended'], 1)
        self.assertEqual(rows['1CS20CS002']['percentage'], 25.0)
        self.assertTrue(rows['1CS20CS002']['at_risk'])

    def test_a_teacher_cannot_read_another_teachers_class(self):
        self.client.force_login(self.other_teacher.user)

        response = self.client.get(
            '/api/v1/classes/%d/students/' % self.assign.id)

        self.assertEqual(response.status_code, 404)

    def test_a_student_with_no_sessions_is_not_flagged_at_risk(self):
        """0% on a course that has not met is not a warning."""
        newcomer = f.make_student(self.klass, usn='1CS20CS003', name='New',
                                  username='new')
        self.client.force_login(self.teacher.user)

        url = '/api/v1/classes/%d/students/' % self.assign.id
        rows = {r['usn']: r for r in self.client.get(url).json()['data']}

        self.assertEqual(rows[newcomer.USN]['held'], 0)
        self.assertFalse(rows[newcomer.USN]['at_risk'])

    def test_unauthenticated_callers_are_rejected(self):
        self.assertEqual(self.client.get('/api/v1/classes/').status_code, 401)
