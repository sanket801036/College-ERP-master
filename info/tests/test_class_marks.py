from django.template import Context, Template
from django.test import TestCase
from django.urls import reverse

from info.models import Attendance, AttendanceClass, Marks, MarksClass, StudentCourse
from info.templatetags.charts import bar_chart
from info.tests import factories as f
from info.views import _cie_bands, _median


class MedianTests(TestCase):
    def test_odd_length_takes_the_middle(self):
        self.assertEqual(_median([1, 5, 9]), 5)

    def test_even_length_averages_the_pair(self):
        self.assertEqual(_median([1, 4, 6, 9]), 5.0)

    def test_empty_is_none_not_zero(self):
        self.assertIsNone(_median([]))


class DistributionTests(TestCase):
    def test_marks_fall_into_their_bands(self):
        bands = dict(_cie_bands([0, 5, 12, 25, 33, 50, 50]))

        self.assertEqual(bands['0-10'], 2)
        self.assertEqual(bands['11-20'], 1)
        self.assertEqual(bands['21-30'], 1)
        self.assertEqual(bands['31-40'], 1)
        self.assertEqual(bands['41-50'], 2)

    def test_the_bands_cover_every_mark(self):
        cies = [0, 1, 10, 11, 20, 21, 30, 31, 40, 41, 50]

        self.assertEqual(sum(c for _, c in _cie_bands(cies)), len(cies))

    def test_no_marks_means_no_chart(self):
        self.assertEqual(_cie_bands([]), [])


class BarChartTests(TestCase):
    def test_the_longest_bar_fills_the_plot(self):
        context = bar_chart([('a', 5), ('b', 10)])

        self.assertAlmostEqual(context['bars'][1]['value_x'] - 8,
                               context['plot_right'], places=1)

    def test_all_zero_values_do_not_divide_by_zero(self):
        """A chart of nothing is honestly empty, not a crash."""
        context = bar_chart([('a', 0), ('b', 0)])

        self.assertEqual(len(context['bars']), 2)
        self.assertEqual(context['bars'][0]['path'], '')

    def test_an_explicit_maximum_sets_the_scale(self):
        context = bar_chart([('a', 5)], max_value=10)

        midpoint = (context['plot_left'] + context['plot_right']) / 2
        self.assertAlmostEqual(context['bars'][0]['value_x'] - 8, midpoint,
                               places=1)

    def test_no_rows_renders_nothing(self):
        html = Template(
            '{% load charts %}{% bar_chart rows %}'
        ).render(Context({'rows': []}))

        self.assertNotIn('<svg', html)

    def test_highlight_recedes_the_others(self):
        """Emphasis: one bar in the accent, the rest grey - the honest form
        when the story is about a single entry."""
        context = bar_chart([('a', 5), ('b', 9)], highlight='b')

        self.assertTrue(context['bars'][0]['muted'])
        self.assertFalse(context['bars'][1]['muted'])

    def test_a_stub_bar_is_not_drawn_as_a_lozenge(self):
        """The 4px corner radius has to collapse on a very short bar or the
        rounding is wider than the bar itself."""
        context = bar_chart([('tiny', 1), ('big', 1000)])

        self.assertTrue(context['bars'][0]['path'],
                        'a tiny bar still draws something')


class ClassMarksPageTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        self.course = f.make_course(dept)
        self.teacher = f.make_teacher(dept, id='t001', username='owner')
        self.assign = f.make_assign(self.klass, self.course, self.teacher)
        self.client.force_login(self.teacher.user)

    def add(self, usn, name, cie_marks, attended=10, held=10):
        student = f.make_student(self.klass, usn=usn, name=name,
                                 username=usn.lower())
        sc = StudentCourse.objects.get(student=student, course=self.course)
        # Two components of 20 each, halved, so cie_marks each gives that CIE.
        for component in ('Internal test 1', 'Internal test 2'):
            Marks.objects.update_or_create(
                studentcourse=sc, name=component,
                defaults={'marks1': cie_marks})
            MarksClass.objects.update_or_create(
                assign=self.assign, name=component, defaults={'status': True})
        for index in range(held):
            session = AttendanceClass.objects.create(
                assign=self.assign, date='2026-08-%02d' % (index + 1), status=1)
            Attendance.objects.create(
                student=student, course=self.course, attendanceclass=session,
                date=session.date, status=index < attended)
        return student

    def url(self):
        return reverse('t_student_marks', args=(self.assign.id,))

    def test_an_unknown_class_is_a_404_not_a_500(self):
        response = self.client.get(reverse('t_student_marks', args=(99999,)))

        self.assertEqual(response.status_code, 404)

    def test_the_page_reports_the_class_statistics(self):
        self.add('1CS001', 'Anita', 18)
        self.add('1CS002', 'Bharat', 10)
        self.add('1CS003', 'Chetan', 2)

        response = self.client.get(self.url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['average_cie'], 10.0)
        self.assertEqual(response.context['median_cie'], 10)
        self.assertEqual(response.context['lowest_cie'], 2)
        self.assertEqual(response.context['highest_cie'], 18)

    def test_the_distribution_is_offered_to_the_chart(self):
        self.add('1CS001', 'Anita', 18)
        self.add('1CS002', 'Bharat', 17)

        response = self.client.get(self.url())

        self.assertEqual(dict(response.context['distribution'])['11-20'], 2)
        self.assertContains(response, 'erp-chart-bar')

    def test_nothing_marked_means_no_statistics_and_no_chart(self):
        f.make_student(self.klass, usn='1CS001', name='Anita',
                       username='1cs001')

        response = self.client.get(self.url())

        self.assertIsNone(response.context['average_cie'])
        self.assertEqual(response.context['distribution'], [])
        self.assertNotContains(response, 'erp-chart-bar')

    def test_at_risk_needs_both_low_marks_and_low_attendance(self):
        self.add('1CS001', 'Low marks only', 2, attended=10, held=10)
        self.add('1CS002', 'Both', 2, attended=3, held=10)

        response = self.client.get(self.url())

        names = [sc.student.name for sc in response.context['at_risk']]
        self.assertEqual(names, ['Both'])

    def test_marks_are_looked_up_by_name_not_by_position(self):
        """Marks has no Meta.ordering, so iterating the queryset into fixed
        headings could put a value under the wrong test."""
        student = self.add('1CS001', 'Anita', 15)
        sc = StudentCourse.objects.get(student=student, course=self.course)
        # Rewrite the first component last, which is what moves a row's
        # position in an unordered result.
        Marks.objects.filter(studentcourse=sc,
                             name='Internal test 1').update(marks1=7)

        response = self.client.get(self.url())

        row = response.context['sc_list'][0]
        by_name = {m.name: m.marks1 for m in row.marks_in_order if m}
        self.assertEqual(by_name['Internal test 1'], 7)
        self.assertEqual(by_name['Internal test 2'], 15)

    def test_counts_are_whole_numbers_not_floats(self):
        """"3.0 students" is a float leaking into prose."""
        self.add('1CS001', 'Anita', 18)

        response = self.client.get(self.url())

        self.assertContains(response, '1 students')
        self.assertNotContains(response, '1.0 students')

    def test_eligibility_is_not_reported_as_zero_while_undecided(self):
        """Two of five components in, so nobody has an eligibility answer -
        and "0" reads as "nobody qualifies"."""
        self.add('1CS001', 'Anita', 20)

        response = self.client.get(self.url())

        self.assertEqual(response.context['decided'], [])
        self.assertContains(response, 'Not settled')

    def test_query_count_does_not_grow_with_class_size(self):
        self.add('1CS001', 'Anita', 18)

        with self.assertNumQueries(14):
            self.assertEqual(self.client.get(self.url()).status_code, 200)

        for n in range(2, 9):
            self.add('1CS00%d' % n, 'Student %d' % n, 10 + n)

        with self.assertNumQueries(14):
            self.assertEqual(self.client.get(self.url()).status_code, 200)

    def test_a_student_cannot_open_it(self):
        student = self.add('1CS001', 'Anita', 18)
        self.client.force_login(student.user)

        response = self.client.get(self.url())

        self.assertNotEqual(response.status_code, 200)
