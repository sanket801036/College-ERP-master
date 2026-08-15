"""The dashboards were four links and a notice list. They now show standing.

Nothing here needed new data - classes_to_attend and classes_can_skip have been
model properties all along and were never surfaced anywhere.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from info.models import (Attendance, AttendanceClass, Fee, MarksClass)
from info.tests import factories as f
from info.tests.test_attendance_totals import mark


class StudentDashboardTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        self.course = f.make_course(dept)
        teacher = f.make_teacher(dept, id='t001', username='owner')
        self.assign = f.make_assign(self.klass, self.course, teacher)
        self.student = f.make_student(self.klass, username='pupil')
        self.client.force_login(self.student.user)

    def test_shows_overall_attendance_weighted_by_sessions(self):
        mark(self.assign, self.student, self.course, present_count=8,
             absent_count=2)

        context = self.client.get(reverse('index')).context

        self.assertEqual(context['overall_attendance'], 80.0)

    def test_no_classes_yet_is_not_reported_as_zero_percent(self):
        context = self.client.get(reverse('index')).context

        self.assertIsNone(context['overall_attendance'])

    def test_courses_below_the_threshold_are_flagged_with_a_target(self):
        mark(self.assign, self.student, self.course, present_count=5,
             absent_count=5)

        response = self.client.get(reverse('index'))

        at_risk = response.context['at_risk']
        self.assertEqual(len(at_risk), 1)
        self.assertEqual(at_risk[0].classes_to_attend, 10)
        self.assertContains(response, 'Attendance shortfall')

    def test_courses_with_headroom_show_how_many_can_be_missed(self):
        mark(self.assign, self.student, self.course, present_count=9,
             absent_count=1)

        response = self.client.get(reverse('index'))

        can_skip = response.context['can_skip']
        self.assertEqual(can_skip[0].classes_can_skip, 2)
        self.assertContains(response, 'Room to spare')

    def test_shows_outstanding_fees_and_the_next_due_date(self):
        Fee.objects.create(student=self.student, fee_type='Tuition Fee',
                           amount=Decimal('45000'), due_date=date(2026, 9, 1))
        Fee.objects.create(student=self.student, fee_type='Exam Fee',
                           amount=Decimal('2500'), due_date=date(2026, 8, 1))

        context = self.client.get(reverse('index')).context

        self.assertEqual(context['fees_due'], Decimal('47500'))
        self.assertEqual(context['next_due'].due_date, date(2026, 8, 1))

    def test_counts_overdue_fees(self):
        Fee.objects.create(student=self.student, fee_type='Exam Fee',
                           amount=Decimal('2500'),
                           due_date=timezone.localdate() - timedelta(days=3))

        self.assertEqual(self.client.get(reverse('index')).context['overdue_count'], 1)


class TeacherDashboardTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        self.course = f.make_course(dept)
        self.teacher = f.make_teacher(dept, id='t001', username='owner')
        self.assign = f.make_assign(self.klass, self.course, self.teacher)
        self.student = f.make_student(self.klass, username='pupil')
        self.client.force_login(self.teacher.user)

    def test_lists_sessions_whose_attendance_was_never_submitted(self):
        AttendanceClass.objects.create(assign=self.assign,
                                       date=timezone.localdate() - timedelta(days=1),
                                       status=0)

        response = self.client.get(reverse('index'))

        self.assertEqual(response.context['pending_sessions_count'], 1)
        self.assertContains(response, 'Attendance still to take')

    def test_future_sessions_are_not_pending_yet(self):
        AttendanceClass.objects.create(assign=self.assign,
                                       date=timezone.localdate() + timedelta(days=7),
                                       status=0)

        self.assertEqual(
            self.client.get(reverse('index')).context['pending_sessions_count'], 0)

    def test_submitted_sessions_drop_off_the_list(self):
        AttendanceClass.objects.create(assign=self.assign,
                                       date=timezone.localdate() - timedelta(days=1),
                                       status=1)

        self.assertEqual(
            self.client.get(reverse('index')).context['pending_sessions_count'], 0)

    def test_lists_marks_not_yet_entered(self):
        response = self.client.get(reverse('index'))

        # Six test categories are created per assignment, none entered yet.
        self.assertEqual(len(response.context['pending_marks']), 6)
        self.assertContains(response, 'Marks not entered')

    def test_entered_marks_drop_off_the_list(self):
        MarksClass.objects.filter(assign=self.assign,
                                  name='Internal test 1').update(status=True)

        self.assertEqual(len(self.client.get(reverse('index')).context['pending_marks']), 5)

    def test_lists_students_below_the_threshold(self):
        mark(self.assign, self.student, self.course, present_count=2,
             absent_count=8)

        response = self.client.get(reverse('index'))

        self.assertEqual(response.context['at_risk_count'], 1)
        self.assertEqual(response.context['at_risk'][0].student, self.student)

    def test_counts_classes_and_students(self):
        context = self.client.get(reverse('index')).context

        self.assertEqual(context['class_count'], 1)
        self.assertEqual(context['student_count'], 1)


class AdminDashboardTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        self.course = f.make_course(dept)
        teacher = f.make_teacher(dept, id='t001', username='owner')
        self.assign = f.make_assign(self.klass, self.course, teacher)
        self.student = f.make_student(self.klass, username='pupil')
        self.client.force_login(f.make_admin())

    def test_shows_average_attendance_and_students_at_risk(self):
        mark(self.assign, self.student, self.course, present_count=5,
             absent_count=5)

        context = self.client.get(reverse('index')).context

        self.assertEqual(context['avg_attendance'], 50.0)
        self.assertEqual(context['at_risk_count'], 1)

    def test_shows_outstanding_fees(self):
        Fee.objects.create(student=self.student, fee_type='Tuition Fee',
                           amount=Decimal('45000'),
                           due_date=timezone.localdate() - timedelta(days=1))

        context = self.client.get(reverse('index')).context

        self.assertEqual(context['fees_outstanding'], Decimal('45000'))
        self.assertEqual(context['overdue_count'], 1)

    def test_survives_an_empty_database(self):
        Attendance.objects.all().delete()

        context = self.client.get(reverse('index')).context

        self.assertIsNone(context['avg_attendance'])
        self.assertEqual(context['at_risk_count'], 0)
