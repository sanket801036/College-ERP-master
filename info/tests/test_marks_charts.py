"""The last two charts: subjects compared, and each subject's internals."""
from django.test import TestCase
from django.urls import reverse

from info.models import MarksClass, StudentCourse
from info.templatetags.charts import sparkline
from info.tests import factories as f
from info.views import _student_marks_rows


class SparklineTagTests(TestCase):
    def _run(self, marks):
        return sparkline([{'label': 'I%d' % i, 'marks': m, 'total': 20}
                          for i, m in enumerate(marks, start=1)], 20)

    def test_a_rising_run_reads_as_up(self):
        context = self._run([8, 14, 18])

        self.assertEqual(context['direction'], 'up')
        self.assertEqual(len(context['points']), 3)

    def test_a_falling_run_reads_as_down(self):
        self.assertEqual(self._run([18, 9])['direction'], 'down')

    def test_an_unchanged_run_reads_as_flat(self):
        self.assertEqual(self._run([12, 12])['direction'], 'flat')

    def test_a_single_internal_is_not_a_trend(self):
        """One point says nothing the row's own number does not."""
        self.assertEqual(self._run([12])['points'], [])

    def test_the_direction_is_also_stated_in_words(self):
        """So it is never carried by the slope alone."""
        context = self._run([8, 18])

        self.assertIn('8 to 18 out of 20', context['summary'])

    def test_the_last_point_is_marked_out(self):
        context = self._run([8, 14, 18])

        self.assertEqual(context['last'], context['points'][-1])


class InternalTrendTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        klass = f.make_class(dept)
        self.course = f.make_course(dept)
        teacher = f.make_teacher(dept, id='t001', username='owner')
        self.assign = f.make_assign(klass, self.course, teacher)
        self.student = f.make_student(klass, username='pupil')

    @property
    def sc(self):
        # Loaded the way the page loads it: publication state comes from
        # MarksClass, and without it every component reads as released.
        return _student_marks_rows(self.student)[0]

    def _publish(self, **marks):
        sc = StudentCourse.objects.get(student=self.student, course=self.course)
        for name, value in marks.items():
            component = name.replace('_', ' ')
            sc.marks_set.filter(name=component).update(marks1=value)
            MarksClass.objects.filter(assign=self.assign, name=component).update(
                status=True, is_published=True)

    def test_returns_the_internals_in_order(self):
        self._publish(**{'Internal test 1': 11, 'Internal test 2': 15,
                         'Internal test 3': 18})

        rows = self.sc.internal_trend()

        self.assertEqual([r['label'] for r in rows], ['I1', 'I2', 'I3'])
        self.assertEqual([r['marks'] for r in rows], [11, 15, 18])

    def test_unpublished_internals_are_left_out(self):
        """An unsat test plotted at zero reads as a collapse in performance
        rather than a test that has not happened."""
        self._publish(**{'Internal test 1': 11, 'Internal test 2': 15})

        self.assertEqual(len(self.sc.internal_trend()), 2)

    def test_events_are_not_part_of_the_trend(self):
        """Internal 3 to Event 1 is not a like-for-like comparison."""
        self._publish(**{'Internal test 1': 11, 'Internal test 2': 15,
                         'Internal test 3': 18, 'Event 1': 20})

        self.assertEqual(len(self.sc.internal_trend()), 3)

    def test_nothing_published_means_no_trend(self):
        self.assertEqual(self.sc.internal_trend(), [])


class MarksPageChartTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        self.teacher = f.make_teacher(dept, id='t001', username='owner')
        self.student = f.make_student(self.klass, username='pupil')
        self.client.force_login(self.student.user)

    def _course(self, code, short, cie_marks):
        course = f.make_course(dept=self.klass.dept, id=code, name='Course ' + code,
                               shortname=short)
        assign = f.make_assign(self.klass, course, self.teacher)
        sc = StudentCourse.objects.get(student=self.student, course=course)
        for name, value in cie_marks.items():
            sc.marks_set.filter(name=name).update(marks1=value)
            MarksClass.objects.filter(assign=assign, name=name).update(
                status=True, is_published=True)
        return course

    def test_subjects_are_ranked_strongest_first(self):
        self._course('CS101', 'DBMS', {'Internal test 1': 20,
                                       'Internal test 2': 20})
        self._course('CS102', 'OS', {'Internal test 1': 8,
                                     'Internal test 2': 6})

        rows = self.client.get(
            reverse('marks_list', args=(self.student.USN,))).context['cie_by_course']

        self.assertEqual([label for label, _ in rows], ['DBMS', 'OS'])
        self.assertGreater(rows[0][1], rows[1][1])

    def test_courses_with_nothing_published_are_left_out(self):
        self._course('CS101', 'DBMS', {'Internal test 1': 15})
        self._course('CS102', 'OS', {})

        rows = self.client.get(
            reverse('marks_list', args=(self.student.USN,))).context['cie_by_course']

        self.assertEqual([label for label, _ in rows], ['DBMS'])

    def test_a_single_subject_is_not_charted(self):
        """A comparison chart of one bar is just the number again."""
        self._course('CS101', 'DBMS', {'Internal test 1': 15})

        response = self.client.get(reverse('marks_list', args=(self.student.USN,)))

        self.assertNotContains(response, 'How your subjects compare')

    def test_the_page_draws_both_charts(self):
        self._course('CS101', 'DBMS', {'Internal test 1': 12,
                                       'Internal test 2': 18})
        self._course('CS102', 'OS', {'Internal test 1': 9,
                                     'Internal test 2': 7})

        response = self.client.get(reverse('marks_list', args=(self.student.USN,)))

        self.assertContains(response, 'How your subjects compare')
        self.assertContains(response, 'erp-sparkline')
