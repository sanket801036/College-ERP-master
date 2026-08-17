"""The dashboards reported bare totals.

"Average attendance 85%" does not say which classes drag it down, and
"outstanding 107,000" does not say what it is owed against.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from info.models import Fee, FeeTransaction
from info.tests import factories as f
from info.tests.test_attendance_totals import mark


class AdminChartTests(TestCase):
    def setUp(self):
        self.dept = f.make_dept()
        self.klass = f.make_class(self.dept)
        self.course = f.make_course(self.dept)
        self.teacher = f.make_teacher(self.dept, id='t001', username='owner')
        self.assign = f.make_assign(self.klass, self.course, self.teacher)
        self.student = f.make_student(self.klass, username='pupil')
        self.client.force_login(f.make_admin())

    def test_attendance_by_class_is_ordered_weakest_first(self):
        other = f.make_class(self.dept, id='CS-3B', section='B')
        other_assign = f.make_assign(other, self.course,
                                     f.make_teacher(self.dept, id='t002',
                                                    name='Other',
                                                    username='other'))
        strong = f.make_student(other, usn='1CS20CS900', name='Strong',
                                username='strong')
        mark(self.assign, self.student, self.course, present_count=5,
             absent_count=5)
        mark(other_assign, strong, self.course, present_count=9, absent_count=1)

        rows = self.client.get(reverse('index')).context['attendance_by_class']

        self.assertEqual(rows, [(self.klass.pk, 50.0), (other.pk, 90.0)])

    def test_classes_with_no_sessions_are_left_out(self):
        """A class that has not met has no attendance to compare, and plotting
        it at zero would read as the worst performer."""
        rows = self.client.get(reverse('index')).context['attendance_by_class']

        self.assertEqual(rows, [])

    def test_collection_rate_is_the_share_of_billings_paid(self):
        fee = Fee.objects.create(student=self.student, fee_type='Tuition Fee',
                                 amount=Decimal('10000'),
                                 due_date=date(2026, 9, 1))
        FeeTransaction.objects.create(fee=fee, amount=Decimal('2500'))
        fee.recalculate_paid()

        context = self.client.get(reverse('index')).context

        self.assertEqual(context['collection_rate'], 25.0)

    def test_collection_rate_is_none_when_nothing_is_billed(self):
        """Zero of zero is not a collection rate, and 0% would read as a
        failure to collect."""
        self.assertIsNone(self.client.get(reverse('index')).context['collection_rate'])

    def test_outstanding_is_grouped_by_fee_type_largest_first(self):
        Fee.objects.create(student=self.student, fee_type='Tuition Fee',
                           amount=Decimal('45000'), due_date=date(2026, 9, 1))
        Fee.objects.create(student=self.student, fee_type='Exam Fee',
                           amount=Decimal('2500'), due_date=date(2026, 9, 1))

        rows = self.client.get(reverse('index')).context['outstanding_by_type']

        # Reported in thousands - full rupee amounts overrun the value column.
        self.assertEqual(rows, [('Tuition Fee', 45.0), ('Exam Fee', 2.5)])

    def test_settled_fees_drop_out_of_the_outstanding_chart(self):
        fee = Fee.objects.create(student=self.student, fee_type='Exam Fee',
                                 amount=Decimal('2500'),
                                 due_date=date(2026, 9, 1))
        FeeTransaction.objects.create(fee=fee, amount=Decimal('2500'))
        fee.recalculate_paid()

        self.assertEqual(
            self.client.get(reverse('index')).context['outstanding_by_type'], [])

    def test_students_by_department(self):
        rows = self.client.get(reverse('index')).context['students_by_dept']

        self.assertEqual(rows, [(self.dept.name, 1)])

    def test_the_page_renders_the_charts(self):
        mark(self.assign, self.student, self.course, present_count=5,
             absent_count=5)
        Fee.objects.create(student=self.student, fee_type='Exam Fee',
                           amount=Decimal('2500'), due_date=date(2026, 9, 1))

        response = self.client.get(reverse('index'))

        self.assertContains(response, 'Attendance by class')
        self.assertContains(response, 'Fee collection')
        self.assertContains(response, 'Students by department')
        self.assertContains(response, '<svg')

    def test_an_empty_database_says_so_instead_of_drawing_nothing(self):
        response = self.client.get(reverse('index'))

        self.assertContains(response, 'No attendance recorded yet')
        self.assertContains(response, 'No fees raised yet')


class TeacherChartTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        self.teacher = f.make_teacher(dept, id='t001', username='owner')
        self.dbms = f.make_course(dept, id='CS501', name='Databases',
                                  shortname='DBMS')
        self.os_course = f.make_course(dept, id='CS502', name='Operating Systems',
                                       shortname='OS')
        self.a1 = f.make_assign(self.klass, self.dbms, self.teacher)
        self.a2 = f.make_assign(self.klass, self.os_course, self.teacher)
        self.student = f.make_student(self.klass, username='pupil')
        self.client.force_login(self.teacher.user)

    def test_each_register_is_compared_separately(self):
        """The same class under two courses is two attendance registers, so it
        appears twice rather than being averaged into one bar."""
        mark(self.a1, self.student, self.dbms, present_count=9, absent_count=1)
        mark(self.a2, self.student, self.os_course, present_count=5,
             absent_count=5)

        rows = self.client.get(reverse('index')).context['attendance_by_class']

        self.assertEqual(rows, [('%s OS' % self.klass.pk, 50.0),
                                ('%s DBMS' % self.klass.pk, 90.0)])

    def test_a_teacher_sees_only_their_own_classes(self):
        stranger = f.make_teacher(self.klass.dept, id='t002', name='Stranger',
                                  username='stranger')
        other_class = f.make_class(self.klass.dept, id='CS-3B', section='B')
        other_assign = f.make_assign(other_class, self.dbms, stranger)
        other_student = f.make_student(other_class, usn='1CS20CS900',
                                       name='Theirs', username='theirs')
        mark(other_assign, other_student, self.dbms, present_count=1,
             absent_count=9)

        rows = self.client.get(reverse('index')).context['attendance_by_class']

        self.assertEqual(rows, [])

    def test_no_chart_before_any_class_has_met(self):
        response = self.client.get(reverse('index'))

        self.assertEqual(response.context['attendance_by_class'], [])
        self.assertNotContains(response, 'How your classes compare')
