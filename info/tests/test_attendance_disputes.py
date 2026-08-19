"""A student saying the register has them wrong.

The teacher could always flip a record - and that edit was already recorded
against their name. What was missing was the other direction, and the rules
that keep it from being a way to award yourself attendance: your own record,
only an absence, only for a week, one at a time, and only the teacher who
keeps that register may agree.
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
    Attendance,
    AttendanceClass,
    AttendanceCorrection,
    AuditLog,
    Notification,
)
from info.tests import factories as f


class DisputeBase(TestCase):
    def setUp(self):
        self.dept = f.make_dept()
        self.klass = f.make_class(self.dept)
        self.course = f.make_course(self.dept)
        self.teacher = f.make_teacher(self.dept, id='T001', username='staff')
        self.student = f.make_student(self.klass, usn='1CS20CS001',
                                      name='Asha Rao', username='asha')
        self.assign = f.make_assign(self.klass, self.course, self.teacher)
        self.today = timezone.localdate()
        self.record = self.session(-1, present=False)

    def session(self, day_offset, present):
        date = self.today + timedelta(days=day_offset)
        cls = AttendanceClass.objects.create(assign=self.assign, date=date,
                                             status=1)
        return Attendance.objects.create(
            student=self.student, course=self.course, attendanceclass=cls,
            date=date, status=present)

    def dispute(self, record=None, reason='I signed the sheet in the second hour.'):
        return services.dispute_attendance(record or self.record, self.student,
                                           reason, self.student.user)


class RaisingTests(DisputeBase):
    def test_an_absence_can_be_disputed(self):
        correction = self.dispute()

        self.assertEqual(correction.status, QUERY_OPEN)

    def test_a_session_you_were_present_for_cannot_be(self):
        present = self.session(-1, present=True)

        with self.assertRaises(services.QueryNotAllowed) as caught:
            self.dispute(present)

        self.assertIn('already marked present', str(caught.exception))

    def test_an_excused_session_cannot_be(self):
        self.record.is_excused = True
        self.record.save(update_fields=['is_excused'])

        with self.assertRaises(services.QueryNotAllowed) as caught:
            self.dispute()

        self.assertIn('already excused', str(caught.exception))

    def test_an_old_register_has_closed(self):
        old = self.session(-30, present=False)

        with self.assertRaises(services.QueryNotAllowed) as caught:
            self.dispute(old)

        self.assertIn('closed', str(caught.exception))

    def test_only_one_dispute_at_a_time(self):
        self.dispute()

        with self.assertRaises(services.QueryNotAllowed):
            self.dispute()

        self.assertEqual(AttendanceCorrection.objects.count(), 1)

    def test_a_withdrawn_one_frees_the_slot(self):
        first = self.dispute()
        services.withdraw_correction(first, self.student.user)

        second = self.dispute(reason='Adding what I forgot to say first time.')

        self.assertEqual(second.status, QUERY_OPEN)

    def test_somebody_else_s_record_cannot_be_disputed(self):
        other = f.make_student(self.klass, usn='1CS20CS002', name='Bala',
                               username='bala')

        with self.assertRaises(services.QueryNotAllowed):
            services.dispute_attendance(self.record, other,
                                        'Not my register, but I will try.',
                                        other.user)

    def test_raising_one_is_recorded_in_the_audit_log(self):
        self.dispute()

        self.assertTrue(
            AuditLog.objects.filter(action='attendance.disputed').exists())


class ResolvingTests(DisputeBase):
    def setUp(self):
        super().setUp()
        self.correction = self.dispute()

    def test_agreeing_marks_the_student_present(self):
        services.resolve_correction(self.correction, self.teacher.user,
                                    accept=True, response='You are right.')

        self.record.refresh_from_db()
        self.assertTrue(self.record.status)
        self.correction.refresh_from_db()
        self.assertEqual(self.correction.status, QUERY_ACCEPTED)

    def test_the_correction_reads_the_same_as_a_teachers_own_edit(self):
        services.resolve_correction(self.correction, self.teacher.user,
                                    accept=True, response='You are right.')

        entry = AuditLog.objects.filter(action='attendance.changed').get()
        self.assertEqual(entry.changes, {'status': {'from': False, 'to': True}})

    def test_refusing_leaves_the_register_alone(self):
        services.resolve_correction(
            self.correction, self.teacher.user, accept=False,
            response='The sheet has no signature against your name.')

        self.record.refresh_from_db()
        self.assertFalse(self.record.status)
        self.correction.refresh_from_db()
        self.assertEqual(self.correction.status, QUERY_REJECTED)

    def test_a_refusal_has_to_say_why(self):
        with self.assertRaises(services.QueryNotAllowed):
            services.resolve_correction(self.correction, self.teacher.user,
                                        accept=False, response='  ')

    def test_answering_twice_is_refused(self):
        services.resolve_correction(self.correction, self.teacher.user,
                                    accept=True, response='Fine.')

        with self.assertRaises(services.QueryNotAllowed):
            services.resolve_correction(self.correction, self.teacher.user,
                                        accept=False, response='Changed my mind.')

    def test_the_percentage_moves_with_it(self):
        self.session(-2, present=True)
        before = services.attendance_rows(students=[self.student],
                                          courses=[self.course])[0].attendance
        self.assertEqual(before, 50)

        services.resolve_correction(self.correction, self.teacher.user,
                                    accept=True, response='You are right.')

        after = services.attendance_rows(students=[self.student],
                                         courses=[self.course])[0].attendance
        self.assertEqual(after, 100)


class PageTests(DisputeBase):
    def test_the_detail_page_offers_to_dispute_an_absence(self):
        self.client.force_login(self.student.user)

        response = self.client.get(
            reverse('attendance_detail', args=[self.student.USN,
                                               self.course.id]))

        self.assertContains(response, 'I was present')

    def test_a_student_can_raise_one_from_the_page(self):
        self.client.force_login(self.student.user)

        response = self.client.post(
            reverse('dispute_attendance', args=[self.record.pk]),
            {'reason': 'I signed the sheet in the second hour.'})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(AttendanceCorrection.objects.count(), 1)

    def test_a_reason_that_says_nothing_is_refused(self):
        self.client.force_login(self.student.user)

        self.client.post(reverse('dispute_attendance', args=[self.record.pk]),
                         {'reason': 'wrong'})

        self.assertFalse(AttendanceCorrection.objects.exists())

    def test_nobody_can_dispute_somebody_else_s_record(self):
        other = f.make_student(self.klass, usn='1CS20CS002', name='Bala',
                               username='bala')
        self.client.force_login(other.user)

        response = self.client.post(
            reverse('dispute_attendance', args=[self.record.pk]),
            {'reason': 'Awarding myself somebody else s attendance.'})

        self.assertEqual(response.status_code, 403)
        self.assertFalse(AttendanceCorrection.objects.exists())

    def test_a_student_can_withdraw_their_own(self):
        correction = self.dispute()
        self.client.force_login(self.student.user)

        self.client.post(reverse('withdraw_dispute', args=[correction.pk]))

        correction.refresh_from_db()
        self.assertEqual(correction.status, QUERY_WITHDRAWN)


class QueueTests(DisputeBase):
    def setUp(self):
        super().setUp()
        self.correction = self.dispute()

    def test_the_queue_shows_a_dispute_about_their_own_register(self):
        self.client.force_login(self.teacher.user)

        response = self.client.get(reverse('correction_queue'))

        self.assertContains(response, 'Asha Rao')
        self.assertEqual(response.context['open_count'], 1)

    def test_it_does_not_show_another_teacher_s(self):
        stranger = f.make_teacher(self.dept, id='T002', username='other')
        self.client.force_login(stranger.user)

        response = self.client.get(reverse('correction_queue'))

        self.assertNotContains(response, 'Asha Rao')

    def test_a_student_cannot_open_the_queue(self):
        self.client.force_login(self.student.user)

        self.assertEqual(
            self.client.get(reverse('correction_queue')).status_code, 403)

    def test_a_teacher_can_answer_from_the_review_page(self):
        self.client.force_login(self.teacher.user)

        response = self.client.post(
            reverse('review_correction', args=[self.correction.pk]),
            {'decision': 'accept', 'response': 'You are right.'})

        self.assertRedirects(response, reverse('correction_queue'))
        self.record.refresh_from_db()
        self.assertTrue(self.record.status)

    def test_a_teacher_who_does_not_keep_that_register_cannot(self):
        stranger = f.make_teacher(self.dept, id='T002', username='other')
        self.client.force_login(stranger.user)

        response = self.client.post(
            reverse('review_correction', args=[self.correction.pk]),
            {'decision': 'accept', 'response': 'Not my class.'})

        self.assertEqual(response.status_code, 403)
        self.record.refresh_from_db()
        self.assertFalse(self.record.status)


class TellingPeopleTests(DisputeBase):
    def test_raising_one_notifies_the_teacher(self):
        self.client.force_login(self.student.user)

        self.client.post(reverse('dispute_attendance', args=[self.record.pk]),
                         {'reason': 'I signed the sheet in the second hour.'})

        notification = Notification.objects.get(user=self.teacher.user)
        self.assertEqual(notification.kind, 'correction')
        self.assertIn('Asha Rao', notification.body)

    def test_answering_notifies_the_student(self):
        correction = self.dispute()
        self.client.force_login(self.teacher.user)

        self.client.post(reverse('review_correction', args=[correction.pk]),
                         {'decision': 'accept', 'response': 'You are right.'})

        notification = Notification.objects.get(user=self.student.user)
        self.assertIn('Marked present', notification.body)
