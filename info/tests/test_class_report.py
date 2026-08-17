from datetime import date

from django.test import TestCase
from django.urls import reverse

from info.models import Attendance, AttendanceClass, Marks, MarksClass, StudentCourse
from info.tests import factories as f


class ClassReportTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        self.course = f.make_course(dept)
        self.teacher = f.make_teacher(dept, id='t001', username='owner')
        self.assign = f.make_assign(self.klass, self.course, self.teacher)

    def add_student(self, usn, name, attended, held, cie_marks,
                    submitted=True):
        """A student with a given attendance record and a given CIE."""
        student = f.make_student(self.klass, usn=usn, name=name,
                                 username=usn.lower())
        for index in range(held):
            session = AttendanceClass.objects.create(
                assign=self.assign, date=date(2026, 8, 1 + index), status=1)
            Attendance.objects.create(
                student=student, course=self.course, attendanceclass=session,
                date=session.date, status=index < attended)

        sc = StudentCourse.objects.get(student=student, course=self.course)
        # Two components of 20, halved, so cie_marks*2 total gives cie_marks.
        for name_ in ('Internal test 1', 'Internal test 2'):
            Marks.objects.update_or_create(
                studentcourse=sc, name=name_, defaults={'marks1': cie_marks})
            MarksClass.objects.update_or_create(
                assign=self.assign, name=name_, defaults={'status': submitted})
        return student

    def url(self, **params):
        base = reverse('t_report', args=(self.assign.id,))
        if not params:
            return base
        return base + '?' + '&'.join('%s=%s' % kv for kv in params.items())

    def get(self, **params):
        self.client.force_login(self.teacher.user)
        return self.client.get(self.url(**params))

    def test_summary_counts_the_class(self):
        self.add_student('1CS001', 'Anita', attended=9, held=10, cie_marks=18)
        self.add_student('1CS002', 'Bhaskar', attended=5, held=10, cie_marks=4)

        response = self.get()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['headcount'], 2)

    def test_at_risk_needs_both_low_attendance_and_low_marks(self):
        """Either alone is common and often recoverable; the combination is
        the signal a teacher can act on."""
        self.add_student('1CS001', 'Low attendance only', attended=5, held=10,
                         cie_marks=20)
        self.add_student('1CS002', 'Low marks only', attended=10, held=10,
                         cie_marks=2)
        self.add_student('1CS003', 'Both', attended=5, held=10, cie_marks=2)

        response = self.get()

        self.assertEqual(response.context['at_risk_count'], 1)
        at_risk = [sc for sc in response.context['sc_list'] if sc.is_at_risk]
        self.assertEqual(at_risk[0].student.name, 'Both')

    def test_the_risk_filter_narrows_the_table(self):
        self.add_student('1CS001', 'Fine', attended=10, held=10, cie_marks=20)
        self.add_student('1CS002', 'Struggling', attended=2, held=10, cie_marks=1)

        response = self.get(risk='1')

        self.assertEqual(len(response.context['sc_list']), 1)
        self.assertContains(response, 'Struggling')
        self.assertNotContains(response, '>Fine<')

    def test_sorting_by_cie_brings_the_lowest_up_first(self):
        """The point of sorting a class report is to surface the students in
        trouble, so the numeric sorts run lowest-first."""
        self.add_student('1CS001', 'High', attended=10, held=10, cie_marks=20)
        self.add_student('1CS002', 'Low', attended=10, held=10, cie_marks=2)

        response = self.get(sort='cie')

        names = [sc.student.name for sc in response.context['sc_list']]
        self.assertEqual(names, ['Low', 'High'])

    def test_an_unknown_sort_falls_back_rather_than_erroring(self):
        self.add_student('1CS001', 'Anita', attended=10, held=10, cie_marks=10)

        response = self.get(sort='; drop table')

        self.assertEqual(response.status_code, 200)

    def test_a_zero_in_a_submitted_batch_counts_towards_the_average(self):
        """MarksClass is per-assign, so "submitted" is class-wide: once the
        teacher submits a batch, a student with no mark genuinely scored zero
        and belongs in the average."""
        self.add_student('1CS001', 'Marked', attended=10, held=10, cie_marks=20)
        f.make_student(self.klass, usn='1CS002', name='Unmarked',
                       username='1cs002')

        response = self.get()

        self.assertEqual(response.context['avg_cie'], 10.0)

    def test_a_class_with_nothing_marked_reports_no_average(self):
        f.make_student(self.klass, usn='1CS002', name='Unmarked',
                       username='1cs002')

        response = self.get()

        self.assertIsNone(response.context['avg_cie'])

    def test_an_incomplete_cie_is_not_called_on_track(self):
        """A green tick on a student sitting at 10/50 halfway through the
        semester is reassurance nobody has earned yet."""
        self.add_student('1CS001', 'Middling', attended=10, held=10,
                         cie_marks=10)

        response = self.get()

        self.assertContains(response, 'In progress')
        self.assertNotContains(response, 'On track')

    def test_at_risk_still_fires_on_an_incomplete_cie(self):
        """Unlike the standing, this one is an early warning - waiting for
        every component before flagging it would defeat the point."""
        self.add_student('1CS001', 'Struggling', attended=2, held=10,
                         cie_marks=1)

        response = self.get()

        self.assertEqual(response.context['at_risk_count'], 1)

    def test_standing_is_a_word_not_only_a_colour(self):
        self.add_student('1CS001', 'Struggling', attended=2, held=10, cie_marks=1)

        response = self.get()

        self.assertContains(response, 'At risk')

    def test_query_count_does_not_grow_with_class_size(self):
        self.add_student('1CS001', 'Anita', attended=9, held=10, cie_marks=18)
        self.client.force_login(self.teacher.user)

        with self.assertNumQueries(17):
            self.assertEqual(self.client.get(self.url()).status_code, 200)

        for n in range(2, 8):
            self.add_student('1CS00%d' % n, 'Student %d' % n, attended=6,
                             held=10, cie_marks=10)

        with self.assertNumQueries(17):
            self.assertEqual(self.client.get(self.url()).status_code, 200)

    def test_a_student_cannot_open_the_report(self):
        student = self.add_student('1CS001', 'Anita', attended=9, held=10,
                                   cie_marks=18)
        self.client.force_login(student.user)

        response = self.client.get(self.url())

        self.assertNotEqual(response.status_code, 200)


    def test_export_returns_a_spreadsheet(self):
        self.add_student('1CS001', 'Anita', attended=9, held=10, cie_marks=18)
        self.client.force_login(self.teacher.user)

        response = self.client.get(
            reverse('t_report_export', args=(self.assign.id,)))

        self.assertEqual(response.status_code, 200)
        self.assertIn('spreadsheetml', response['Content-Type'])
        self.assertIn('attachment', response['Content-Disposition'])

    def test_export_is_closed_to_students(self):
        student = self.add_student('1CS001', 'Anita', attended=9, held=10,
                                   cie_marks=18)
        self.client.force_login(student.user)

        response = self.client.get(
            reverse('t_report_export', args=(self.assign.id,)))

        self.assertNotEqual(response.status_code, 200)
