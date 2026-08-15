"""AttendanceTotal: the maths, the duplicate-name crash, and query counts."""
from datetime import date, timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from info.models import Attendance, AttendanceClass, AttendanceTotal
from info.tests import factories as f


def mark(assign, student, course, present_count, absent_count=0):
    """Record `present_count` attended and `absent_count` missed sessions."""
    day = date(2026, 1, 5)
    for i in range(present_count + absent_count):
        session = AttendanceClass.objects.create(assign=assign,
                                                 date=day + timedelta(days=i))
        Attendance.objects.create(course=course, student=student,
                                  attendanceclass=session, date=session.date,
                                  status=i < present_count)


class AttendanceMathTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        self.course = f.make_course(dept)
        self.teacher = f.make_teacher(dept, id='t001', username='owner')
        self.assign = f.make_assign(self.klass, self.course, self.teacher)
        self.student = f.make_student(self.klass, username='pupil')

    def _total(self):
        # Nothing creates these rows on a schedule; the views backfill them.
        total, _ = AttendanceTotal.objects.get_or_create(student=self.student,
                                                         course=self.course)
        return total

    def test_no_classes_held_yet(self):
        total = self._total()

        self.assertFalse(total.has_classes)
        self.assertEqual(total.total_class, 0)
        self.assertEqual(total.attendance, 0)

    def test_percentage_and_counts(self):
        mark(self.assign, self.student, self.course, present_count=8, absent_count=2)
        total = self._total()

        self.assertTrue(total.has_classes)
        self.assertEqual(total.att_class, 8)
        self.assertEqual(total.total_class, 10)
        self.assertEqual(total.attendance, 80.0)

    def test_classes_to_attend_when_below_threshold(self):
        # 5 of 10 attended: needs 10 consecutive classes to reach 75%
        mark(self.assign, self.student, self.course, present_count=5, absent_count=5)

        self.assertEqual(self._total().classes_to_attend, 10)

    def test_classes_to_attend_is_zero_when_already_above(self):
        mark(self.assign, self.student, self.course, present_count=9, absent_count=1)

        self.assertEqual(self._total().classes_to_attend, 0)

    def test_classes_can_skip(self):
        # 9 of 10 attended: 9/0.75 = 12, so 2 more may be missed
        mark(self.assign, self.student, self.course, present_count=9, absent_count=1)

        self.assertEqual(self._total().classes_can_skip, 2)

    def test_classes_can_skip_is_zero_at_the_threshold(self):
        mark(self.assign, self.student, self.course, present_count=6, absent_count=2)

        total = self._total()
        self.assertEqual(total.attendance, 75.0)
        self.assertEqual(total.classes_can_skip, 0)

    def test_duplicate_student_names_do_not_break_the_page(self):
        """The properties looked records up by name, not primary key, so a
        second student with the same name raised MultipleObjectsReturned and
        500'd the attendance page for both of them."""
        f.make_student(self.klass, usn='1CS20CS999', name=self.student.name,
                       username='twin')
        mark(self.assign, self.student, self.course, present_count=3)

        total = self._total()
        self.assertEqual(total.att_class, 3)
        self.assertEqual(total.attendance, 100.0)

        self.client.force_login(self.student.user)
        response = self.client.get(reverse('attendance', args=(self.student.USN,)))
        self.assertEqual(response.status_code, 200)


class AttendanceQueryCountTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        self.teacher = f.make_teacher(dept, id='t001', username='owner')
        self.students = [
            f.make_student(self.klass, usn='1CS20CS00%d' % i,
                           name='Student %d' % i, username='s%d' % i)
            for i in range(1, 6)
        ]
        self.assigns = []
        for n in range(1, 4):
            course = f.make_course(dept, id='CS10%d' % n, name='Course %d' % n,
                                   shortname='C%d' % n)
            self.assigns.append(f.make_assign(self.klass, course, self.teacher))
        for assign in self.assigns:
            mark(assign, self.students[0], assign.course, present_count=4,
                 absent_count=1)

    def test_student_page_query_count_is_flat(self):
        """Cost ~19 queries per course, so 3 courses ran ~60. It is a fixed
        set now regardless of how many courses the student takes."""
        self.client.force_login(self.students[0].user)
        url = reverse('attendance', args=(self.students[0].USN,))

        # Two of these belong to the topbar's unread-notice badge, which every
        # page carries; the point is that none of them scale with course count.
        with self.assertNumQueries(9):
            self.assertEqual(self.client.get(url).status_code, 200)

    def test_teacher_class_page_query_count_is_flat(self):
        """Cost ~19 queries per student, so a 45-student class ran into the
        hundreds. Fixed now however many students are in the class."""
        self.client.force_login(self.teacher.user)
        url = reverse('t_student', args=(self.assigns[0].id,))

        with self.assertNumQueries(12):
            self.assertEqual(self.client.get(url).status_code, 200)

    def test_adding_students_does_not_add_queries(self):
        """The direct statement of the fix: doubling the class size must not
        change the number of queries."""
        self.client.force_login(self.teacher.user)
        url = reverse('t_student', args=(self.assigns[0].id,))

        with CaptureQueriesContext(connection) as small:
            self.client.get(url)

        for i in range(6, 16):
            f.make_student(self.klass, usn='1CS20CS0%02d' % i,
                           name='Student %d' % i, username='s%d' % i)

        with CaptureQueriesContext(connection) as large:
            self.client.get(url)

        self.assertEqual(len(small), len(large))
