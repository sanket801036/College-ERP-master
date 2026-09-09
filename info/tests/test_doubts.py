"""Handing a question to a person when the assistant could not answer it.

This is the part most assistants do not have. A chatbot that always answers is
easy; one that knows it has nothing and routes the question to somebody who
does is the difference between a demo and a thing a college could run.

So the tests are mostly about the seams. Who sees a question - a teacher gets
their own classes and nobody else's. What a teacher may do with it - there is
no way to close one without writing something, because the student is already
here after a machine gave them nothing. And how many one student may have
open, because a queue one person can fill is a queue that is useless to
everybody else.
"""
from django.test import TestCase
from django.urls import reverse

from info import notifications, rag
from info.models import (
    ESCALATION_ANSWERED,
    ESCALATION_OPEN,
    ESCALATION_WITHDRAWN,
    MAX_OPEN_ESCALATIONS,
    AssistantEscalation,
    AuditLog,
    Notification,
)
from info.tests import factories as f


class DoubtBase(TestCase):
    def setUp(self):
        self.dept = f.make_dept()
        self.klass = f.make_class(self.dept)
        self.course = f.make_course(self.dept)
        self.teacher = f.make_teacher(self.dept, username='staff')
        self.student = f.make_student(self.klass, username='asha')
        f.make_assign(self.klass, self.course, self.teacher)
        self.admin = f.make_admin()

    def raise_doubt(self, question='What is the hostel fee?', course=None,
                    said='I do not have that in the college material.'):
        return rag.escalate(self.student, question, self.student.user,
                            assistant_said=said, course=course)


class RaisingTests(DoubtBase):
    def test_a_question_reaches_the_queue(self):
        doubt = self.raise_doubt()

        self.assertEqual(doubt.status, ESCALATION_OPEN)
        self.assertEqual(doubt.student, self.student)

    def test_what_the_assistant_said_is_kept_with_it(self):
        # The session history it came from is cleared routinely, and a
        # question without the answer it followed reads as if nobody tried.
        doubt = self.raise_doubt(said='I do not have that.')

        self.assertEqual(doubt.assistant_said, 'I do not have that.')

    def test_a_stray_keypress_is_not_a_question(self):
        with self.assertRaises(rag.EscalationNotAllowed):
            self.raise_doubt(question='hm')

    def test_a_course_off_the_timetable_is_refused(self):
        # Otherwise a question could be routed into a class the student is
        # not in, and answered by a teacher who does not teach them.
        other_dept = f.make_dept(id='ME', name='Mechanical')
        other = f.make_course(other_dept, id='ME101', name='Thermo')

        with self.assertRaises(rag.EscalationNotAllowed) as caught:
            self.raise_doubt(course=other)

        self.assertIn('not on your timetable', str(caught.exception))

    def test_one_student_cannot_fill_the_queue(self):
        for n in range(MAX_OPEN_ESCALATIONS):
            self.raise_doubt(question='Question number %d please' % n)

        with self.assertRaises(rag.EscalationNotAllowed) as caught:
            self.raise_doubt()

        self.assertIn('waiting for a teacher', str(caught.exception))

    def test_answering_one_frees_the_slot(self):
        doubts = [self.raise_doubt(question='Question number %d please' % n)
                  for n in range(MAX_OPEN_ESCALATIONS)]
        rag.answer_escalation(doubts[0], 'Here is a real answer for you.',
                              self.teacher.user)

        self.assertIsNotNone(self.raise_doubt())

    def test_withdrawing_frees_the_slot_too(self):
        doubts = [self.raise_doubt(question='Question number %d please' % n)
                  for n in range(MAX_OPEN_ESCALATIONS)]
        rag.withdraw_escalation(doubts[0], self.student.user)

        self.assertIsNotNone(self.raise_doubt())

    def test_raising_is_recorded(self):
        self.raise_doubt()

        self.assertTrue(
            AuditLog.objects.filter(action='assistant.escalated').exists())


class AnsweringTests(DoubtBase):
    def test_a_teacher_answers_in_writing(self):
        doubt = self.raise_doubt()

        rag.answer_escalation(doubt, 'The hostel fee is set by the office.',
                              self.teacher.user)

        doubt.refresh_from_db()
        self.assertEqual(doubt.status, ESCALATION_ANSWERED)
        self.assertEqual(doubt.answered_by, self.teacher.user)
        self.assertIsNotNone(doubt.answered_at)

    def test_there_is_no_closing_it_without_saying_anything(self):
        # The student is here because a machine already gave them nothing.
        # A one-word reply repeats that with a person attached to it.
        doubt = self.raise_doubt()

        with self.assertRaises(rag.EscalationNotAllowed) as caught:
            rag.answer_escalation(doubt, 'ok', self.teacher.user)

        self.assertIn('answer the student can use', str(caught.exception))

    def test_an_answered_question_cannot_be_answered_twice(self):
        doubt = self.raise_doubt()
        rag.answer_escalation(doubt, 'A perfectly good first answer.',
                              self.teacher.user)

        with self.assertRaises(rag.EscalationNotAllowed):
            rag.answer_escalation(doubt, 'A second, contradictory answer.',
                                  self.teacher.user)

    def test_a_withdrawn_question_cannot_be_answered(self):
        doubt = self.raise_doubt()
        rag.withdraw_escalation(doubt, self.student.user)

        with self.assertRaises(rag.EscalationNotAllowed):
            rag.answer_escalation(doubt, 'Answering something withdrawn.',
                                  self.teacher.user)

    def test_withdrawing_twice_is_refused(self):
        doubt = self.raise_doubt()
        rag.withdraw_escalation(doubt, self.student.user)

        with self.assertRaises(rag.EscalationNotAllowed):
            rag.withdraw_escalation(doubt, self.student.user)

        doubt.refresh_from_db()
        self.assertEqual(doubt.status, ESCALATION_WITHDRAWN)


class QueueScopeTests(DoubtBase):
    """Who sees which question. Every failure here shows one class another."""

    def setUp(self):
        super().setUp()
        self.other_klass = f.make_class(self.dept, id='CS-3B', section='B')
        self.other_teacher = f.make_teacher(self.dept, id='T002',
                                            name='Other', username='other')
        f.make_assign(self.other_klass, self.course, self.other_teacher)
        self.other_student = f.make_student(self.other_klass,
                                            usn='1CS20CS777', name='Bee',
                                            username='bee')

    def test_a_teacher_sees_their_own_class(self):
        self.raise_doubt()

        queue = AssistantEscalation.objects.for_teacher(self.teacher)

        self.assertEqual(queue.count(), 1)

    def test_a_teacher_does_not_see_another_section(self):
        self.raise_doubt()

        queue = AssistantEscalation.objects.for_teacher(self.other_teacher)

        self.assertEqual(queue.count(), 0)

    def test_the_queue_page_shows_only_what_that_teacher_teaches(self):
        self.raise_doubt()
        self.client.force_login(self.other_teacher.user)

        response = self.client.get(reverse('doubt_queue'))

        self.assertNotContains(response, self.student.name)


class TellingPeopleTests(DoubtBase):
    def test_the_teachers_of_that_class_are_told(self):
        doubt = self.raise_doubt()

        notifications.announce(
            notifications.messages_for_doubt_raised(doubt))

        note = Notification.objects.get(user=self.teacher.user)
        self.assertEqual(note.kind, 'doubt')
        self.assertIn(self.student.name, note.subject)

    def test_a_question_about_one_subject_only_reaches_its_teacher(self):
        other_course = f.make_course(self.dept, id='CS102', name='Algorithms')
        other_teacher = f.make_teacher(self.dept, id='T003', name='Third',
                                       username='third')
        f.make_assign(self.klass, other_course, other_teacher)
        doubt = self.raise_doubt(course=self.course)

        notifications.announce(
            notifications.messages_for_doubt_raised(doubt))

        self.assertTrue(
            Notification.objects.filter(user=self.teacher.user).exists())
        self.assertFalse(
            Notification.objects.filter(user=other_teacher.user).exists())

    def test_the_student_is_told_when_it_is_answered(self):
        doubt = self.raise_doubt()
        rag.answer_escalation(doubt, 'A real answer, written out.',
                              self.teacher.user)

        notifications.announce(
            notifications.messages_for_doubt_answered(doubt))

        note = Notification.objects.get(user=self.student.user)
        self.assertIn('answered your question', note.subject)

    def test_telling_them_twice_sends_one_notification(self):
        doubt = self.raise_doubt()
        messages = notifications.messages_for_doubt_raised(doubt)

        notifications.announce(messages)
        notifications.announce(messages)

        self.assertEqual(
            Notification.objects.filter(user=self.teacher.user).count(), 1)


class PageTests(DoubtBase):
    def test_a_student_sees_their_own_questions(self):
        self.raise_doubt()
        self.client.force_login(self.student.user)

        response = self.client.get(reverse('doubt_list'))

        self.assertContains(response, 'hostel fee')

    def test_a_student_cannot_open_the_teacher_queue(self):
        self.client.force_login(self.student.user)

        self.assertEqual(
            self.client.get(reverse('doubt_queue')).status_code, 403)

    def test_a_teacher_cannot_open_the_student_list(self):
        self.client.force_login(self.teacher.user)

        self.assertEqual(
            self.client.get(reverse('doubt_list')).status_code, 403)

    def test_a_student_cannot_withdraw_anybody_else_s(self):
        doubt = self.raise_doubt()
        other = f.make_student(self.klass, usn='1CS20CS888', name='Cee',
                               username='cee')
        self.client.force_login(other.user)

        response = self.client.post(
            reverse('withdraw_doubt', args=[doubt.id]))

        self.assertEqual(response.status_code, 403)
        doubt.refresh_from_db()
        self.assertEqual(doubt.status, ESCALATION_OPEN)

    def test_a_teacher_answers_through_the_page(self):
        doubt = self.raise_doubt()
        self.client.force_login(self.teacher.user)

        self.client.post(reverse('review_doubt', args=[doubt.id]),
                         {'response': 'The office sets the hostel fee.'})

        doubt.refresh_from_db()
        self.assertEqual(doubt.status, ESCALATION_ANSWERED)

    def test_a_teacher_cannot_answer_a_class_they_do_not_teach(self):
        other_klass = f.make_class(self.dept, id='CS-3C', section='C')
        outsider = f.make_teacher(self.dept, id='T009', name='Outsider',
                                  username='outsider')
        f.make_assign(other_klass, self.course, outsider)
        doubt = self.raise_doubt()
        self.client.force_login(outsider.user)

        response = self.client.post(reverse('review_doubt', args=[doubt.id]),
                                    {'response': 'Answering somebody else.'})

        self.assertEqual(response.status_code, 403)
        doubt.refresh_from_db()
        self.assertEqual(doubt.status, ESCALATION_OPEN)

    def test_the_escalate_button_posts_a_question(self):
        self.client.force_login(self.student.user)

        self.client.post(reverse('escalate_doubt'), {
            'question': 'What is the hostel fee?',
            'assistant_said': 'I do not have that in the college material.',
        })

        self.assertTrue(
            AssistantEscalation.objects.filter(student=self.student).exists())
