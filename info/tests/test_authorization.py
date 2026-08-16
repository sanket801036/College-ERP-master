"""Every teacher view used to carry @login_required and nothing else.

A student account could read whole-class attendance and marks, open the entry
forms, and flip individual attendance records by guessing an integer id. These
tests pin all of that shut.
"""
from datetime import date

from django.test import TestCase
from django.urls import reverse

from info.models import Attendance, AttendanceClass, MarksClass
from info.tests import factories as f


class TeacherViewAccessTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        self.course = f.make_course(dept)
        self.teacher = f.make_teacher(dept, id='t001', username='owner')
        self.assign = f.make_assign(self.klass, self.course, self.teacher)
        self.student = f.make_student(self.klass, username='pupil')

        # a second teacher, with their own class, to test cross-teacher access
        self.other_teacher = f.make_teacher(dept, id='t002', name='Other Teacher',
                                            username='other')
        other_class = f.make_class(dept, id='CS-3B', section='B')
        self.other_assign = f.make_assign(other_class, self.course, self.other_teacher)

        self.session = AttendanceClass.objects.create(assign=self.assign,
                                                      date=date(2026, 1, 6))
        self.marks_class = MarksClass.objects.get(assign=self.assign,
                                                  name='Internal test 1')

    def _teacher_urls(self):
        return [
            reverse('t_student', args=(self.assign.id,)),
            reverse('t_class_date', args=(self.assign.id,)),
            reverse('t_report', args=(self.assign.id,)),
            reverse('t_marks_list', args=(self.assign.id,)),
            reverse('t_student_marks', args=(self.assign.id,)),
            reverse('t_attendance', args=(self.session.id,)),
            reverse('t_marks_entry', args=(self.marks_class.id,)),
            reverse('edit_marks', args=(self.marks_class.id,)),
            reverse('t_clas', args=(self.teacher.id, 1)),
        ]

    def test_student_cannot_reach_any_teacher_view(self):
        self.client.force_login(self.student.user)

        for url in self._teacher_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_owning_teacher_can_reach_their_own_views(self):
        self.client.force_login(self.teacher.user)

        for url in self._teacher_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_teacher_cannot_reach_another_teachers_class(self):
        self.client.force_login(self.other_teacher.user)

        for url in [reverse('t_student', args=(self.assign.id,)),
                    reverse('t_report', args=(self.assign.id,)),
                    reverse('t_marks_list', args=(self.assign.id,)),
                    reverse('t_clas', args=(self.teacher.id, 1))]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_superuser_can_reach_everything(self):
        self.client.force_login(f.make_admin())

        for url in self._teacher_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)


class ChangeAttendanceTests(TestCase):
    """change_att flipped any Attendance row by id, on a GET, for any user."""

    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        self.course = f.make_course(dept)
        self.teacher = f.make_teacher(dept, id='t001', username='owner')
        self.assign = f.make_assign(self.klass, self.course, self.teacher)
        self.student = f.make_student(self.klass, username='pupil')
        session = AttendanceClass.objects.create(assign=self.assign,
                                                 date=date(2026, 1, 6))
        self.record = Attendance.objects.create(
            course=self.course, student=self.student, attendanceclass=session,
            date=session.date, status=False)
        self.url = reverse('change_att', args=(self.record.id,))

    def test_student_cannot_flip_their_own_absence(self):
        self.client.force_login(self.student.user)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 403)
        self.record.refresh_from_db()
        self.assertFalse(self.record.status)

    def test_get_is_rejected(self):
        """A state change on GET bypasses CSRF and is triggerable by an <img>."""
        self.client.force_login(self.teacher.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 405)
        self.record.refresh_from_db()
        self.assertFalse(self.record.status)

    def test_unrelated_teacher_cannot_flip_the_record(self):
        dept = self.course.dept
        stranger = f.make_teacher(dept, id='t002', name='Stranger', username='stranger')
        self.client.force_login(stranger.user)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 403)
        self.record.refresh_from_db()
        self.assertFalse(self.record.status)

    def test_owning_teacher_can_flip_the_record(self):
        self.client.force_login(self.teacher.user)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 302)
        self.record.refresh_from_db()
        self.assertTrue(self.record.status)


class WriteEndpointTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        course = f.make_course(dept)
        self.teacher = f.make_teacher(dept, id='t001', username='owner')
        self.assign = f.make_assign(self.klass, course, self.teacher)
        self.student = f.make_student(self.klass, username='pupil')
        self.session = AttendanceClass.objects.create(assign=self.assign,
                                                      date=date(2026, 1, 6))
        self.marks_class = MarksClass.objects.get(assign=self.assign,
                                                  name='Internal test 1')

    def test_student_cannot_submit_attendance_for_the_class(self):
        self.client.force_login(self.student.user)

        response = self.client.post(reverse('confirm', args=(self.session.id,)),
                                    {self.student.USN: 'present'})

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Attendance.objects.count(), 0)

    def test_student_cannot_submit_marks_for_the_class(self):
        self.client.force_login(self.student.user)

        response = self.client.post(
            reverse('marks_confirm', args=(self.marks_class.id,)),
            {self.student.USN: '18'})

        self.assertEqual(response.status_code, 403)
        self.marks_class.refresh_from_db()
        self.assertFalse(self.marks_class.status)

    def test_student_cannot_cancel_a_class(self):
        self.client.force_login(self.student.user)

        response = self.client.post(reverse('cancel_class', args=(self.session.id,)))

        self.assertEqual(response.status_code, 403)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, 0)
