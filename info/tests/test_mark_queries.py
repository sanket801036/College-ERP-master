"""Re-evaluation: a student saying a mark is wrong, and what comes of it.

The rules worth testing are the ones that keep this from being a second,
softer way to change a mark: only the student's own marks, only published
ones, only inside the window, only the teacher who taught the course, and
never outside the component's ceiling.
"""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from info import services
from info.models import (
    QUERY_ACCEPTED,
    QUERY_OPEN,
    QUERY_REJECTED,
    QUERY_WITHDRAWN,
    AuditLog,
    MarkQuery,
    Marks,
    MarksClass,
    Notification,
)
from info.tests import factories as f


class QueryBase(TestCase):
    def setUp(self):
        self.dept = f.make_dept()
        self.klass = f.make_class(self.dept)
        self.course = f.make_course(self.dept)
        self.teacher = f.make_teacher(self.dept, id='T001', username='staff')
        self.student = f.make_student(self.klass, usn='1CS20CS001',
                                      name='Asha Rao', username='asha')
        self.assign = f.make_assign(self.klass, self.course, self.teacher)

        self.batch = MarksClass.objects.get(assign=self.assign,
                                            name='Internal test 1')
        self.batch.status = True
        self.batch.save(update_fields=['status'])
        self.mark = Marks.objects.get(
            studentcourse__student=self.student,
            studentcourse__course=self.course, name='Internal test 1')
        self.mark.marks1 = 12
        self.mark.save(update_fields=['marks1'])

    def publish(self, when=None):
        self.batch.publish()
        if when is not None:
            MarksClass.objects.filter(pk=self.batch.pk).update(published_at=when)

    def raise_query(self, reason='Question 3b was marked out of five.'):
        return services.raise_mark_query(self.mark, self.student, reason,
                                         self.student.user)


class RaisingTests(QueryBase):
    def test_a_published_mark_can_be_questioned(self):
        self.publish()

        query = self.raise_query()

        self.assertEqual(query.status, QUERY_OPEN)
        self.assertEqual(query.student, self.student)

    def test_an_unpublished_mark_cannot_be(self):
        with self.assertRaises(services.QueryNotAllowed) as caught:
            self.raise_query()

        self.assertIn('not been released', str(caught.exception))

    def test_the_window_closes(self):
        self.publish(when=timezone.now() - timedelta(days=8))

        with self.assertRaises(services.QueryNotAllowed) as caught:
            self.raise_query()

        self.assertIn('closed', str(caught.exception))

    def test_the_window_is_a_week(self):
        self.publish(when=timezone.now() - timedelta(days=6, hours=23))

        self.assertEqual(self.raise_query().status, QUERY_OPEN)

    def test_only_one_query_at_a_time(self):
        self.publish()
        self.raise_query()

        with self.assertRaises(services.QueryNotAllowed) as caught:
            self.raise_query()

        self.assertIn('already', str(caught.exception))
        self.assertEqual(MarkQuery.objects.count(), 1)

    def test_a_withdrawn_query_frees_the_slot(self):
        self.publish()
        query = self.raise_query()
        services.withdraw_mark_query(query, self.student.user)

        second = self.raise_query('The total does not add up.')

        self.assertEqual(second.status, QUERY_OPEN)
        self.assertEqual(MarkQuery.objects.count(), 2)

    def test_raising_one_is_recorded_in_the_audit_log(self):
        self.publish()

        self.raise_query()

        entry = AuditLog.objects.filter(action='marks.queried').get()
        self.assertEqual(entry.student, self.student)


class ResolvingTests(QueryBase):
    def setUp(self):
        super().setUp()
        self.publish()
        self.query = self.raise_query()

    def test_accepting_changes_the_mark(self):
        services.resolve_mark_query(self.query, self.teacher.user, accept=True,
                                    response='You were right about 3b.',
                                    new_mark=17)

        self.mark.refresh_from_db()
        self.assertEqual(self.mark.marks1, 17)
        self.query.refresh_from_db()
        self.assertEqual(self.query.status, QUERY_ACCEPTED)
        self.assertEqual(self.query.mark_before, 12)
        self.assertEqual(self.query.mark_after, 17)

    def test_rejecting_leaves_it_alone(self):
        services.resolve_mark_query(self.query, self.teacher.user,
                                    accept=False,
                                    response='The scheme allows five there.')

        self.mark.refresh_from_db()
        self.assertEqual(self.mark.marks1, 12)
        self.query.refresh_from_db()
        self.assertEqual(self.query.status, QUERY_REJECTED)
        self.assertEqual(self.query.outcome, 'Mark unchanged')

    def test_a_correction_cannot_break_the_ceiling(self):
        with self.assertRaises(services.QueryNotAllowed):
            services.resolve_mark_query(self.query, self.teacher.user,
                                        accept=True, response='', new_mark=25)

        self.mark.refresh_from_db()
        self.assertEqual(self.mark.marks1, 12)

    def test_accepting_without_a_mark_is_refused(self):
        with self.assertRaises(services.QueryNotAllowed):
            services.resolve_mark_query(self.query, self.teacher.user,
                                        accept=True, response='Fine.')

    def test_a_corrected_mark_is_no_longer_absent(self):
        self.mark.is_absent = True
        self.mark.save(update_fields=['is_absent'])

        services.resolve_mark_query(self.query, self.teacher.user, accept=True,
                                    response='You did sit it.', new_mark=14)

        self.mark.refresh_from_db()
        self.assertFalse(self.mark.is_absent)

    def test_answering_twice_is_refused(self):
        services.resolve_mark_query(self.query, self.teacher.user,
                                    accept=False, response='Stands.')

        with self.assertRaises(services.QueryNotAllowed):
            services.resolve_mark_query(self.query, self.teacher.user,
                                        accept=True, response='', new_mark=20)

    def test_the_change_is_recorded_in_the_audit_log(self):
        services.resolve_mark_query(self.query, self.teacher.user, accept=True,
                                    response='Corrected.', new_mark=17)

        entry = AuditLog.objects.filter(action='marks.query_accepted').get()
        self.assertEqual(entry.changes, {'marks1': [12, 17]})


class PageTests(QueryBase):
    def test_the_marks_page_offers_to_question_a_published_mark(self):
        self.publish()
        self.client.force_login(self.student.user)

        response = self.client.get(
            reverse('marks_list', args=[self.student.pk]))

        self.assertContains(response, 'Question this')

    def test_it_does_not_offer_that_before_publication(self):
        self.client.force_login(self.student.user)

        response = self.client.get(
            reverse('marks_list', args=[self.student.pk]))

        self.assertNotContains(response, 'Question this')

    def test_a_student_can_raise_one_from_the_page(self):
        self.publish()
        self.client.force_login(self.student.user)

        response = self.client.post(
            reverse('raise_mark_query', args=[self.mark.pk]),
            {'reason': 'Question 3b was marked out of five, not ten.'})

        self.assertRedirects(response,
                             reverse('marks_list', args=[self.student.pk]))
        self.assertEqual(MarkQuery.objects.count(), 1)

    def test_a_reason_that_says_nothing_is_refused(self):
        self.publish()
        self.client.force_login(self.student.user)

        self.client.post(reverse('raise_mark_query', args=[self.mark.pk]),
                         {'reason': 'wrong'})

        self.assertFalse(MarkQuery.objects.exists())

    def test_nobody_can_question_somebody_else_s_mark(self):
        self.publish()
        other = f.make_student(self.klass, usn='1CS20CS002', name='Bala',
                               username='bala')
        self.client.force_login(other.user)

        response = self.client.post(
            reverse('raise_mark_query', args=[self.mark.pk]),
            {'reason': 'I want more marks than Asha got.'})

        self.assertEqual(response.status_code, 403)
        self.assertFalse(MarkQuery.objects.exists())

    def test_a_student_can_withdraw_their_own(self):
        self.publish()
        query = self.raise_query()
        self.client.force_login(self.student.user)

        self.client.post(reverse('withdraw_mark_query', args=[query.pk]))

        query.refresh_from_db()
        self.assertEqual(query.status, QUERY_WITHDRAWN)

    def test_a_student_cannot_withdraw_anybody_else_s(self):
        self.publish()
        query = self.raise_query()
        other = f.make_student(self.klass, usn='1CS20CS002', name='Bala',
                               username='bala')
        self.client.force_login(other.user)

        response = self.client.post(
            reverse('withdraw_mark_query', args=[query.pk]))

        self.assertEqual(response.status_code, 403)
        query.refresh_from_db()
        self.assertEqual(query.status, QUERY_OPEN)


class TeacherQueueTests(QueryBase):
    def setUp(self):
        super().setUp()
        self.publish()
        self.query = self.raise_query()

    def test_the_queue_shows_a_query_about_a_course_they_teach(self):
        self.client.force_login(self.teacher.user)

        response = self.client.get(reverse('mark_queries'))

        self.assertContains(response, 'Asha Rao')
        self.assertEqual(response.context['open_count'], 1)

    def test_it_does_not_show_another_teacher_s(self):
        stranger = f.make_teacher(self.dept, id='T002', username='other')
        self.client.force_login(stranger.user)

        response = self.client.get(reverse('mark_queries'))

        self.assertNotContains(response, 'Asha Rao')

    def test_a_student_cannot_open_the_queue(self):
        self.client.force_login(self.student.user)

        self.assertEqual(
            self.client.get(reverse('mark_queries')).status_code, 403)

    def test_answered_ones_drop_out_of_the_default_view(self):
        services.resolve_mark_query(self.query, self.teacher.user,
                                    accept=False, response='Stands.')
        self.client.force_login(self.teacher.user)

        response = self.client.get(reverse('mark_queries'))

        self.assertEqual(response.context['queries'], [])
        self.assertContains(response, 'Nothing to answer')

    def test_they_are_still_there_under_all(self):
        services.resolve_mark_query(self.query, self.teacher.user,
                                    accept=False, response='Stands.')
        self.client.force_login(self.teacher.user)

        response = self.client.get(reverse('mark_queries'), {'show': 'all'})

        self.assertEqual(len(response.context['queries']), 1)

    def test_the_teacher_can_answer_from_the_review_page(self):
        self.client.force_login(self.teacher.user)

        response = self.client.post(
            reverse('review_mark_query', args=[self.query.pk]),
            {'decision': 'accept', 'new_mark': '17',
             'response': 'You were right about 3b.'})

        self.assertRedirects(response, reverse('mark_queries'))
        self.mark.refresh_from_db()
        self.assertEqual(self.mark.marks1, 17)

    def test_a_rejection_has_to_say_why(self):
        self.client.force_login(self.teacher.user)

        self.client.post(reverse('review_mark_query', args=[self.query.pk]),
                         {'decision': 'reject', 'response': ''})

        self.query.refresh_from_db()
        self.assertEqual(self.query.status, QUERY_OPEN)

    def test_a_teacher_cannot_answer_for_a_course_they_do_not_teach(self):
        stranger = f.make_teacher(self.dept, id='T002', username='other')
        self.client.force_login(stranger.user)

        response = self.client.post(
            reverse('review_mark_query', args=[self.query.pk]),
            {'decision': 'accept', 'new_mark': '20', 'response': 'Sure.'})

        self.assertEqual(response.status_code, 403)
        self.mark.refresh_from_db()
        self.assertEqual(self.mark.marks1, 12)


class TellingPeopleTests(QueryBase):
    def test_raising_one_notifies_the_teacher(self):
        self.publish()
        self.client.force_login(self.student.user)

        self.client.post(reverse('raise_mark_query', args=[self.mark.pk]),
                         {'reason': 'Question 3b was marked out of five.'})

        notification = Notification.objects.get(user=self.teacher.user)
        self.assertEqual(notification.kind, 'query')
        self.assertIn('Asha Rao', notification.body)

    def test_answering_notifies_the_student(self):
        self.publish()
        query = self.raise_query()
        self.client.force_login(self.teacher.user)

        self.client.post(reverse('review_mark_query', args=[query.pk]),
                         {'decision': 'accept', 'new_mark': '17',
                          'response': 'Corrected.'})

        notification = Notification.objects.get(user=self.student.user)
        self.assertIn('Changed from 12 to 17', notification.body)
