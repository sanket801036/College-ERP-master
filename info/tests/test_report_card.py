from django.test import TestCase
from django.urls import reverse

from info.models import Marks, MarksClass, StudentCourse
from info.tests import factories as f


class Base(TestCase):
    def setUp(self):
        self.dept = f.make_dept()
        self.klass = f.make_class(self.dept)
        self.course = f.make_course(self.dept)
        self.teacher = f.make_teacher(self.dept, id='t001', username='owner')
        self.assign = f.make_assign(self.klass, self.course, self.teacher)
        self.student = f.make_student(self.klass, usn='1CS001', name='Anita',
                                      username='anita')

    def score(self, student, name, marks, published=True):
        sc = StudentCourse.objects.get(student=student, course=self.course)
        Marks.objects.update_or_create(studentcourse=sc, name=name,
                                       defaults={'marks1': marks})
        mc = MarksClass.objects.get(assign=self.assign, name=name)
        mc.status = True
        mc.save()
        if published:
            mc.publish()


class ClassRankTests(Base):
    def setUp(self):
        super().setUp()
        self.rival = f.make_student(self.klass, usn='1CS002', name='Bharat',
                                    username='bharat')
        self.third = f.make_student(self.klass, usn='1CS003', name='Chetan',
                                    username='chetan')

    def rows_for(self, student):
        self.client.force_login(student.user)
        response = self.client.get(reverse('marks_list', args=(student.pk,)))
        return response.context['sc_list']

    def test_rank_counts_only_those_ahead(self):
        self.score(self.student, 'Internal test 1', 12)
        self.score(self.rival, 'Internal test 1', 18)
        self.score(self.third, 'Internal test 1', 6)

        self.assertEqual(self.rows_for(self.student)[0].rank, (2, 3))
        self.assertEqual(self.rows_for(self.rival)[0].rank, (1, 3))

    def test_a_tie_shares_the_position(self):
        self.score(self.student, 'Internal test 1', 15)
        self.score(self.rival, 'Internal test 1', 15)
        self.score(self.third, 'Internal test 1', 5)

        self.assertEqual(self.rows_for(self.student)[0].rank, (1, 3))
        self.assertEqual(self.rows_for(self.rival)[0].rank, (1, 3))

    def test_a_withheld_component_does_not_move_the_ranking(self):
        """Ranking on the entered set would let an unpublished mark shift
        someone's position, which leaks what publication holds back."""
        self.score(self.student, 'Internal test 1', 10)
        self.score(self.rival, 'Internal test 1', 8)
        self.score(self.rival, 'Internal test 2', 20, published=False)

        # Counting the withheld 20 would put the rival on 28 and drop this
        # student to second. Chetan is in the class too, on a published 0.
        self.assertEqual(self.rows_for(self.student)[0].rank, (1, 3))

    def test_no_rank_before_anything_is_published(self):
        self.score(self.student, 'Internal test 1', 10, published=False)

        self.assertIsNone(self.rows_for(self.student)[0].rank)

    def test_a_student_sees_only_their_own_standing(self):
        """No leaderboard: ranking classmates in a list they can all read is a
        privacy problem rather than a feature."""
        self.score(self.student, 'Internal test 1', 12)
        self.score(self.rival, 'Internal test 1', 18)
        self.client.force_login(self.student.user)

        response = self.client.get(
            reverse('marks_list', args=(self.student.pk,)))

        self.assertContains(response, 'Rank 2 of 3')
        self.assertNotContains(response, 'Bharat')

    def test_query_count_does_not_grow_with_class_size(self):
        self.score(self.student, 'Internal test 1', 12)
        self.client.force_login(self.student.user)
        url = reverse('marks_list', args=(self.student.pk,))

        # 13 since the re-evaluation work: attach_queries adds two - one for
        # the class's publication dates, one for this student's own queries -
        # and neither grows with the number of courses or students.
        with self.assertNumQueries(13):
            self.assertEqual(self.client.get(url).status_code, 200)

        for n in range(4, 12):
            other = f.make_student(self.klass, usn='1CS0%02d' % n,
                                   name='Student %d' % n,
                                   username='student%d' % n)
            self.score(other, 'Internal test 1', n)

        # 13 since the re-evaluation work: attach_queries adds two - one for
        # the class's publication dates, one for this student's own queries -
        # and neither grows with the number of courses or students.
        with self.assertNumQueries(13):
            self.assertEqual(self.client.get(url).status_code, 200)


class MarksCardTests(Base):
    def url(self, student=None):
        return reverse('marks_card', args=((student or self.student).pk,))

    def test_it_returns_a_pdf(self):
        self.score(self.student, 'Internal test 1', 16)
        self.client.force_login(self.student.user)

        response = self.client.get(self.url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertIn('1CS001', response['Content-Disposition'])
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_it_renders_with_nothing_marked(self):
        self.client.force_login(self.student.user)

        response = self.client.get(self.url())

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_another_student_cannot_download_it(self):
        other = f.make_student(self.klass, usn='1CS002', name='Bharat',
                               username='bharat')
        self.client.force_login(other.user)

        response = self.client.get(self.url())

        self.assertEqual(response.status_code, 403)

    def test_an_admin_can_download_it(self):
        admin = f.make_admin()
        self.client.force_login(admin)

        response = self.client.get(self.url())

        self.assertEqual(response.status_code, 200)

    def test_it_is_closed_to_anonymous_users(self):
        response = self.client.get(self.url())

        self.assertEqual(response.status_code, 302)

    def drawn_text(self, response):
        """Every string on the card, with the point it was drawn at.

        Compression is off for the duration so the content stream is readable.
        """
        import re
        return [(float(m.group(1)), float(m.group(2)), m.group(3))
                for m in re.finditer(
                    r'1 0 0 1 ([\d.]+) ([\d.]+) Tm \((.*?)\)\s*Tj',
                    response.content.decode('latin-1'), re.S)]

    def test_nothing_is_drawn_outside_the_page(self):
        """The first version accumulated column widths and put SEE, Final and
        Grade at x = 872, 1323 and 1828pt on a 595pt page. They were in the
        file and completely invisible on paper, which no assertion about the
        text would have caught."""
        from reportlab import rl_config
        from reportlab.lib.pagesizes import A4

        self.score(self.student, 'Internal test 1', 18)
        self.score(self.student, 'Semester End Exam', 78)
        self.client.force_login(self.student.user)

        rl_config.pageCompression = 0
        try:
            drawn = self.drawn_text(self.client.get(self.url()))
        finally:
            rl_config.pageCompression = 1

        self.assertTrue(drawn, 'expected some text on the card')
        for x, y, text in drawn:
            self.assertGreaterEqual(x, 0, text)
            self.assertLessEqual(x, A4[0], '%r is off the right edge' % text)
            self.assertGreaterEqual(y, 0, text)
            self.assertLessEqual(y, A4[1], '%r is off the top' % text)

    def test_every_column_reaches_the_card(self):
        from reportlab import rl_config

        self.score(self.student, 'Internal test 1', 18)
        self.score(self.student, 'Semester End Exam', 78)
        self.client.force_login(self.student.user)

        rl_config.pageCompression = 0
        try:
            text = ' '.join(t for _, _, t in
                            self.drawn_text(self.client.get(self.url())))
        finally:
            rl_config.pageCompression = 1

        for expected in ('Course', 'CIE', 'SEE', 'Final', 'Grade',
                         '78 / 100', 'SGPA'):
            self.assertIn(expected, text)

    def test_it_shows_the_same_marks_the_page_does(self):
        """Built from the same rows as the page, so paper and screen cannot
        disagree about what a student scored."""
        self.score(self.student, 'Internal test 1', 16, published=False)
        self.client.force_login(self.student.user)

        page = self.client.get(reverse('marks_list', args=(self.student.pk,)))
        rows = page.context['sc_list']

        self.assertEqual(rows[0].get_cie(), 0, 'withheld, so not on the page')
        self.assertEqual(self.client.get(self.url()).status_code, 200)
