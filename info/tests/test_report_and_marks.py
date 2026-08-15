from datetime import date, timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from info.models import Attendance, AttendanceClass, StudentCourse
from info.tests import factories as f


class MarksListTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        teacher = f.make_teacher(dept, id='t001', username='owner')
        self.course = f.make_course(dept)
        f.make_assign(self.klass, self.course, teacher)
        self.student = f.make_student(self.klass, username='pupil')
        self.client.force_login(self.student.user)

    def test_marks_are_returned_in_header_order(self):
        sc = StudentCourse.objects.get(student=self.student, course=self.course)
        for name, value in [('Internal test 1', 11), ('Internal test 2', 12),
                            ('Internal test 3', 13), ('Event 1', 14),
                            ('Event 2', 15), ('Semester End Exam', 66)]:
            sc.marks_set.filter(name=name).update(marks1=value)

        self.assertEqual([m.marks1 for m in sc.marks_in_order],
                         [11, 12, 13, 14, 15, 66])

    def test_page_renders_without_a_studentcourse_row(self):
        """The fallback that was meant to cover this passed type='I' to
        marks_set.create(), which raises TypeError - Marks has no such field."""
        StudentCourse.objects.filter(student=self.student).delete()

        response = self.client.get(reverse('marks_list', args=(self.student.USN,)))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            StudentCourse.objects.filter(student=self.student,
                                         course=self.course).exists())


class ReportQueryTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        self.teacher = f.make_teacher(dept, id='t001', username='owner')
        course = f.make_course(dept)
        self.assign = f.make_assign(self.klass, course, self.teacher)
        self.students = [
            f.make_student(self.klass, usn='1CS20CS00%d' % i,
                           name='Student %d' % i, username='s%d' % i)
            for i in range(1, 5)
        ]
        session = AttendanceClass.objects.create(assign=self.assign,
                                                 date=date(2026, 1, 6))
        for s in self.students:
            Attendance.objects.create(course=course, student=s,
                                      attendanceclass=session,
                                      date=session.date, status=True)
        self.client.force_login(self.teacher.user)

    def test_report_renders(self):
        response = self.client.get(reverse('t_report', args=(self.assign.id,)))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['sc_list']), 4)

    def test_report_queries_do_not_grow_with_class_size(self):
        """Each row looked up its own attendance and the template asks for it
        twice, so this ran about five queries per student."""
        url = reverse('t_report', args=(self.assign.id,))

        with CaptureQueriesContext(connection) as small:
            self.client.get(url)

        session = AttendanceClass.objects.create(assign=self.assign,
                                                 date=date(2026, 1, 7))
        for i in range(5, 15):
            student = f.make_student(self.klass, usn='1CS20CS0%02d' % i,
                                     name='Student %d' % i, username='s%d' % i)
            Attendance.objects.create(course=self.assign.course, student=student,
                                      attendanceclass=session,
                                      date=session.date, status=True)

        with CaptureQueriesContext(connection) as large:
            self.client.get(url)

        self.assertEqual(len(small), len(large))

    def test_report_survives_a_missing_studentcourse_row(self):
        StudentCourse.objects.filter(student=self.students[0]).delete()

        response = self.client.get(reverse('t_report', args=(self.assign.id,)))

        self.assertEqual(response.status_code, 200)
