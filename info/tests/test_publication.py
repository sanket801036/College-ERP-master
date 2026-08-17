from django.test import TestCase
from django.urls import reverse

from info.models import AuditLog, Marks, MarksClass, StudentCourse
from info.tests import factories as f


class Base(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        self.course = f.make_course(dept)
        self.teacher = f.make_teacher(dept, id='t001', username='owner')
        self.assign = f.make_assign(self.klass, self.course, self.teacher)
        self.student = f.make_student(self.klass, usn='1CS001', name='Anita',
                                      username='anita')
        self.mc = MarksClass.objects.get(assign=self.assign,
                                         name='Internal test 1')

    def enter(self, marks=16, absent=False):
        sc = StudentCourse.objects.get(student=self.student, course=self.course)
        Marks.objects.update_or_create(
            studentcourse=sc, name=self.mc.name,
            defaults={'marks1': marks, 'is_absent': absent})
        self.mc.status = True
        self.mc.save()


class PublicationTests(Base):
    def test_entering_marks_does_not_release_them(self):
        """A mark used to be visible the instant it was typed, including a slip
        the teacher was about to correct."""
        self.enter()
        self.client.force_login(self.student.user)

        response = self.client.get(
            reverse('marks_list', args=(self.student.pk,)))

        rows = response.context['sc_list'][0].component_rows()
        self.assertTrue(rows[0]['pending'])
        self.assertContains(response, 'Not yet conducted')

    def test_publishing_makes_them_visible(self):
        self.enter()
        self.mc.publish()
        self.client.force_login(self.student.user)

        response = self.client.get(
            reverse('marks_list', args=(self.student.pk,)))

        rows = response.context['sc_list'][0].component_rows()
        self.assertFalse(rows[0]['pending'])
        self.assertEqual(rows[0]['marks'], 16)

    def test_withdrawing_hides_them_again(self):
        self.enter()
        self.mc.publish()
        self.mc.unpublish()
        self.client.force_login(self.student.user)

        response = self.client.get(
            reverse('marks_list', args=(self.student.pk,)))

        self.assertTrue(
            response.context['sc_list'][0].component_rows()[0]['pending'])

    def test_publishing_stamps_the_time(self):
        self.enter()

        self.mc.publish()

        self.assertIsNotNone(self.mc.published_at)

    def test_withdrawing_clears_the_stamp(self):
        self.enter()
        self.mc.publish()

        self.mc.unpublish()

        self.assertIsNone(self.mc.published_at)

    def test_a_withheld_mark_cannot_be_recovered_from_the_cie(self):
        """Counting a withheld component towards the total let the student
        subtract the visible marks and read the hidden one straight off."""
        self.enter(marks=16)                       # test 1, published below
        sc = StudentCourse.objects.get(student=self.student, course=self.course)
        Marks.objects.update_or_create(
            studentcourse=sc, name='Internal test 2', defaults={'marks1': 14})
        second = MarksClass.objects.get(assign=self.assign,
                                        name='Internal test 2')
        second.status = True
        second.save()
        self.mc.publish()

        StudentCourse.attach_submitted([sc], self.klass.pk, published_only=True)

        self.assertEqual(sc.get_cie(), 8, 'only the published 16 counts')

    def test_a_held_back_result_does_not_read_as_never_conducted(self):
        self.enter()
        self.client.force_login(self.student.user)

        response = self.client.get(
            reverse('marks_list', args=(self.student.pk,)))

        rows = response.context['sc_list'][0].component_rows()
        self.assertTrue(rows[0]['awaiting_release'])
        self.assertContains(response, 'Results not released yet')

    def test_a_component_never_entered_reads_as_not_conducted(self):
        self.client.force_login(self.student.user)

        response = self.client.get(
            reverse('marks_list', args=(self.student.pk,)))

        rows = response.context['sc_list'][0].component_rows()
        self.assertFalse(rows[0]['awaiting_release'])
        self.assertContains(response, 'Not yet conducted')

    def test_the_teacher_report_shows_entered_marks_before_publication(self):
        """Entry and release are different questions - a teacher looking at
        their own class report should see what has been entered."""
        self.enter()
        self.client.force_login(self.teacher.user)

        response = self.client.get(reverse('t_report', args=(self.assign.id,)))

        self.assertEqual(response.context['avg_cie'], 8.0)


class PublishViewTests(Base):
    def url(self):
        return reverse('publish_marks', args=(self.mc.id,))

    def test_a_teacher_can_publish(self):
        self.enter()
        self.client.force_login(self.teacher.user)

        self.client.post(self.url())

        self.mc.refresh_from_db()
        self.assertTrue(self.mc.is_published)

    def test_publishing_is_logged(self):
        self.enter()
        self.client.force_login(self.teacher.user)

        self.client.post(self.url())

        self.assertTrue(
            AuditLog.objects.filter(action='marks.published').exists())

    def test_withdrawing_is_logged(self):
        self.enter()
        self.mc.publish()
        self.client.force_login(self.teacher.user)

        self.client.post(self.url(), {'action': 'unpublish'})

        self.mc.refresh_from_db()
        self.assertFalse(self.mc.is_published)
        self.assertTrue(
            AuditLog.objects.filter(action='marks.unpublished').exists())

    def test_an_unentered_batch_cannot_be_published(self):
        self.client.force_login(self.teacher.user)

        self.client.post(self.url())

        self.mc.refresh_from_db()
        self.assertFalse(self.mc.is_published)

    def test_publishing_needs_a_post(self):
        self.enter()
        self.client.force_login(self.teacher.user)

        response = self.client.get(self.url())

        self.assertEqual(response.status_code, 405)

    def test_a_student_cannot_publish(self):
        self.enter()
        self.client.force_login(self.student.user)

        response = self.client.post(self.url())

        self.assertNotEqual(response.status_code, 302)
        self.mc.refresh_from_db()
        self.assertFalse(self.mc.is_published)


class AbsentTests(Base):
    def test_an_absentee_is_not_shown_as_having_scored_zero(self):
        self.enter(marks=0, absent=True)
        self.mc.publish()
        self.client.force_login(self.student.user)

        response = self.client.get(
            reverse('marks_list', args=(self.student.pk,)))

        rows = response.context['sc_list'][0].component_rows()
        self.assertTrue(rows[0]['absent'])
        self.assertContains(response, 'Absent')

    def test_an_absentee_still_counts_as_zero_towards_the_cie(self):
        """That is how the scheme works - the record just says which it was."""
        self.enter(marks=0, absent=True)
        sc = StudentCourse.objects.get(student=self.student, course=self.course)

        self.assertEqual(sc.get_cie(), 0)

    def test_a_genuine_zero_is_not_marked_absent(self):
        self.enter(marks=0, absent=False)
        self.mc.publish()

        sc = StudentCourse.objects.get(student=self.student, course=self.course)
        StudentCourse.attach_submitted([sc], self.klass.pk, published_only=True)

        self.assertFalse(sc.component_rows()[0]['absent'])


class AbsentEntryTests(Base):
    def post(self, data):
        self.client.force_login(self.teacher.user)
        return self.client.post(
            reverse('marks_confirm', args=(self.mc.id,)), data)

    def test_marking_absent_saves_without_a_number(self):
        self.post({'absent_' + self.student.pk: 'on'})

        mark = Marks.objects.get(name=self.mc.name)
        self.assertTrue(mark.is_absent)
        self.assertEqual(mark.marks1, 0)

    def test_a_blank_is_rejected_rather_than_saved_as_zero(self):
        """The whole point of the field: leaving someone empty means the
        teacher has not got to them, not that they scored nothing."""
        response = self.post({self.student.pk: ''})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['rows'][0]['errors'])
        self.mc.refresh_from_db()
        self.assertFalse(self.mc.status, 'nothing should have been submitted')

    def test_a_mark_still_saves_normally(self):
        self.post({self.student.pk: '17'})

        mark = Marks.objects.get(name=self.mc.name)
        self.assertEqual(mark.marks1, 17)
        self.assertFalse(mark.is_absent)

    def test_absent_wins_over_a_stale_number(self):
        """The number input is disabled client-side, but a hand-built post
        could carry both."""
        self.post({self.student.pk: '12', 'absent_' + self.student.pk: 'on'})

        mark = Marks.objects.get(name=self.mc.name)
        self.assertTrue(mark.is_absent)
        self.assertEqual(mark.marks1, 0)
