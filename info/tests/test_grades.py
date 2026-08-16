from django.test import TestCase
from django.urls import reverse

from info.models import (CIE_MAX, Marks, MarksClass, SEE_ELIGIBILITY_CIE,
                         SEE_NAME, StudentCourse, grade_for, required_see_for,
                         sgpa_for)
from info.tests import factories as f


class GradeBandTests(TestCase):
    """VTU's 10-point scale, on a final out of 100."""

    def test_each_band_boundary(self):
        cases = [(100, 'O', 10), (90, 'O', 10), (89.9, 'A+', 9), (80, 'A+', 9),
                 (79, 'A', 8), (70, 'A', 8), (69, 'B+', 7), (60, 'B+', 7),
                 (59, 'B', 6), (55, 'B', 6), (54, 'C', 5), (50, 'C', 5),
                 (49, 'P', 4), (40, 'P', 4), (39.9, 'F', 0), (0, 'F', 0)]

        for final, letter, points in cases:
            with self.subTest(final=final):
                self.assertEqual(grade_for(final), (letter, points))


class RequiredSeeTests(TestCase):
    """final = CIE + SEE/2, solved backwards for the SEE."""

    def test_a_mid_cie_needs_a_reachable_paper(self):
        # 38 banked, 70 needed for an A: (70 - 38) * 2 = 64.
        self.assertEqual(required_see_for(38, 70), 64)

    def test_a_band_already_secured_on_the_cie_alone_needs_nothing(self):
        self.assertEqual(required_see_for(45, 40), 0)

    def test_an_unreachable_band_is_none_not_a_number_over_100(self):
        """A CIE of 10 cannot reach 90 even with a perfect paper - saying
        "you need 160/100" would be worse than saying it is gone."""
        self.assertIsNone(required_see_for(10, 90))

    def test_exactly_a_perfect_paper_is_still_reachable(self):
        self.assertEqual(required_see_for(20, 70), 100)

    def test_rounds_up_so_the_band_is_actually_cleared(self):
        # (55 - 30.5) * 2 = 49.0 exactly; a fractional CIE must not round down
        # into a mark that misses the band.
        self.assertEqual(required_see_for(30.1, 55), 50)


class SgpaTests(TestCase):
    class FakeCourse:
        def __init__(self, credits):
            self.credits = credits

    class FakeCourseRow:
        def __init__(self, points, credits):
            self._points = points
            self.course = SgpaTests.FakeCourse(credits)

        @property
        def grade(self):
            return ('X', self._points) if self._points is not None else None

    def test_weights_by_credits_not_by_course_count(self):
        """The whole reason Course.credits exists: a 1-credit lab must not
        pull as hard as a 4-credit core paper."""
        rows = [self.FakeCourseRow(10, 4), self.FakeCourseRow(4, 1)]

        # (10*4 + 4*1) / 5 = 8.8, where a plain mean would give 7.0.
        self.assertEqual(sgpa_for(rows), 8.8)

    def test_ungraded_courses_are_left_out(self):
        rows = [self.FakeCourseRow(8, 4), self.FakeCourseRow(None, 4)]

        self.assertEqual(sgpa_for(rows), 8.0)

    def test_no_results_at_all_gives_none_rather_than_zero(self):
        rows = [self.FakeCourseRow(None, 4)]

        self.assertIsNone(sgpa_for(rows))


class StudentCourseGradeTests(TestCase):
    def setUp(self):
        self.dept = f.make_dept()
        self.klass = f.make_class(self.dept)
        self.student = f.make_student(self.klass, username='pupil')
        self.course = f.make_course(self.dept)
        self.teacher = f.make_teacher(self.dept, id='t001', username='owner')
        self.assign = f.make_assign(self.klass, self.course, self.teacher)
        self.sc = StudentCourse.objects.get(student=self.student,
                                            course=self.course)

    def score(self, name, marks, submitted=True):
        Marks.objects.update_or_create(
            studentcourse=self.sc, name=name, defaults={'marks1': marks})
        MarksClass.objects.update_or_create(
            assign=self.assign, name=name, defaults={'status': submitted})

    def reload(self):
        sc = StudentCourse.objects.get(pk=self.sc.pk)
        StudentCourse.attach_submitted([sc], self.klass.pk)
        return sc

    def test_cie_is_half_the_five_components(self):
        for name in ('Internal test 1', 'Internal test 2', 'Internal test 3'):
            self.score(name, 20)
        self.score('Event 1', 20)
        self.score('Event 2', 20)

        self.assertEqual(self.reload().get_cie(), CIE_MAX)

    def test_an_unsubmitted_component_reads_as_pending_not_zero(self):
        """marks1 defaults to 0, so without consulting MarksClass.status a test
        nobody has sat is indistinguishable from one scored zero."""
        self.score('Internal test 1', 0, submitted=False)

        rows = self.reload().component_rows()

        self.assertTrue(rows[0]['pending'])

    def test_a_genuine_zero_is_not_pending(self):
        self.score('Internal test 1', 0, submitted=True)

        rows = self.reload().component_rows()

        self.assertFalse(rows[0]['pending'])
        self.assertEqual(rows[0]['marks'], 0)

    def test_see_is_none_until_the_batch_is_submitted(self):
        self.score(SEE_NAME, 72, submitted=False)

        self.assertIsNone(self.reload().get_see())

    def test_final_is_cie_plus_half_the_see(self):
        self.score('Internal test 1', 20)
        self.score('Internal test 2', 20)
        self.score(SEE_NAME, 80)

        sc = self.reload()

        self.assertEqual(sc.get_cie(), 20)
        self.assertEqual(sc.final_marks, 60)
        self.assertEqual(sc.grade, ('B+', 7))

    def test_no_grade_while_the_see_is_pending(self):
        self.score('Internal test 1', 18)

        self.assertIsNone(self.reload().grade)

    def score_all(self, marks):
        for name in ('Internal test 1', 'Internal test 2', 'Internal test 3',
                     'Event 1', 'Event 2'):
            self.score(name, marks)

    def test_see_eligibility_follows_the_cie_cut_off(self):
        self.score_all(10)  # CIE 25

        sc = self.reload()

        self.assertGreaterEqual(sc.get_cie(), SEE_ELIGIBILITY_CIE)
        self.assertIs(sc.is_see_eligible, True)

    def test_a_low_cie_is_flagged_ineligible(self):
        self.score_all(2)  # CIE 5

        self.assertIs(self.reload().is_see_eligible, False)

    def test_eligibility_is_undecided_while_components_are_outstanding(self):
        """The bug this guards: a course whose tests have not been sat sits at
        CIE 0, and flagging it "not eligible" reads as a course already failed
        rather than one that has not started."""
        self.score('Internal test 1', 18)

        sc = self.reload()

        self.assertFalse(sc.cie_is_final)
        self.assertIsNone(sc.is_see_eligible)

    def test_a_course_with_nothing_marked_has_no_marks(self):
        self.assertFalse(self.reload().has_marks)

    def test_a_course_marked_zero_still_counts_as_marked(self):
        self.score('Internal test 1', 0, submitted=True)

        self.assertTrue(self.reload().has_marks)

    def test_reachable_grades_drop_the_unreachable_ones(self):
        self.score('Internal test 1', 10)  # CIE 5

        letters = [t['letter'] for t in self.reload().reachable_grades]

        self.assertIn('P', letters)
        self.assertNotIn('O', letters, 'a CIE of 5 cannot reach 90')

    def test_reachable_grades_are_empty_once_the_result_is_in(self):
        self.score('Internal test 1', 20)
        self.score(SEE_NAME, 80)

        self.assertEqual(self.reload().reachable_grades, [])


class MarksPageTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        self.student = f.make_student(self.klass, username='pupil')
        self.course = f.make_course(dept)
        teacher = f.make_teacher(dept, id='t001', username='owner')
        self.assign = f.make_assign(self.klass, self.course, teacher)

    def url(self):
        return reverse('marks_list', args=(self.student.pk,))

    def score(self, name, marks, submitted=True):
        """Entered and released.

        These tests are about what the student page computes, and since pass 23
        a mark has to be published before it gets there.
        """
        sc = StudentCourse.objects.get(student=self.student, course=self.course)
        Marks.objects.update_or_create(
            studentcourse=sc, name=name, defaults={'marks1': marks})
        MarksClass.objects.update_or_create(
            assign=self.assign, name=name,
            defaults={'status': submitted, 'is_published': submitted})

    def test_page_renders_with_nothing_entered(self):
        self.client.force_login(self.student.user)

        response = self.client.get(self.url())

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['sgpa'])

    def test_no_sgpa_is_invented_before_any_result_is_in(self):
        """A fabricated "3.8 / 4.0" was the thing to avoid here - with no SEE
        marked, there is no grade point to weight."""
        self.score('Internal test 1', 18)
        self.client.force_login(self.student.user)

        response = self.client.get(self.url())

        self.assertIsNone(response.context['sgpa'])
        self.assertContains(response, 'Average CIE')

    def test_sgpa_appears_once_a_result_is_published(self):
        # CIE 30 (three 20s, halved) + SEE 80/2 = a final of 70, which is an A
        # and 8 points on the VTU scale.
        self.score('Internal test 1', 20)
        self.score('Internal test 2', 20)
        self.score('Internal test 3', 20)
        self.score(SEE_NAME, 80)
        self.client.force_login(self.student.user)

        response = self.client.get(self.url())

        self.assertEqual(response.context['sgpa'], 8.0)
        self.assertContains(response, 'SGPA')

    def test_pending_component_is_labelled_not_shown_as_zero(self):
        self.score('Internal test 1', 0, submitted=False)
        self.client.force_login(self.student.user)

        response = self.client.get(self.url())

        self.assertContains(response, 'Not yet conducted')

    def test_an_incomplete_cie_is_not_given_a_verdict(self):
        """21/50 with components outstanding is a subtotal, not a standing."""
        self.score('Internal test 1', 14)
        self.client.force_login(self.student.user)

        response = self.client.get(self.url())

        self.assertContains(response, 'erp-meter-pending')
        self.assertNotContains(response, 'erp-meter-safe')

    def test_a_course_that_has_not_started_is_not_flagged_ineligible(self):
        """Nothing has been sat, so the CIE is 0 - which must not be presented
        as having already failed out of the exam."""
        self.client.force_login(self.student.user)

        response = self.client.get(self.url())

        self.assertNotContains(response, 'Not eligible for SEE')

    def test_query_count_does_not_grow_with_the_number_of_courses(self):
        self.client.force_login(self.student.user)

        with self.assertNumQueries(11):
            self.assertEqual(self.client.get(self.url()).status_code, 200)

        dept = self.course.dept
        teacher = self.assign.teacher
        for n in range(5):
            extra = f.make_course(dept, id='EX%d' % n, name='Extra %d' % n,
                                  shortname='EX%d' % n)
            f.make_assign(self.klass, extra, teacher)

        with self.assertNumQueries(11):
            self.assertEqual(self.client.get(self.url()).status_code, 200)
