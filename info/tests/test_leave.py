"""Leave applications, and what approving one actually does.

The workflow is the easy half. The half worth testing is the arithmetic:
approved leave must leave the percentage alone rather than counting against
the student, and it has to apply to sessions marked after the approval as
well as before it - otherwise applying in advance means nothing.
"""
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from info import services
from info.models import (
    LEAVE_APPROVED,
    LEAVE_OPEN,
    LEAVE_REJECTED,
    LEAVE_WITHDRAWN,
    Attendance,
    AttendanceClass,
    AuditLog,
    LeaveRequest,
    Notification,
)
from info.tests import factories as f


class LeaveBase(TestCase):
    def setUp(self):
        self.dept = f.make_dept()
        self.klass = f.make_class(self.dept)
        self.course = f.make_course(self.dept)
        self.teacher = f.make_teacher(self.dept, id='T001', username='staff')
        self.student = f.make_student(self.klass, usn='1CS20CS001',
                                      name='Asha Rao', username='asha')
        self.assign = f.make_assign(self.klass, self.course, self.teacher)
        self.today = timezone.localdate()

    def apply(self, from_days=1, to_days=2, category='Medical',
              reason='Down with a fever, certificate attached.'):
        return services.apply_for_leave(
            student=self.student, category=category,
            from_date=self.today + timedelta(days=from_days),
            to_date=self.today + timedelta(days=to_days),
            reason=reason, actor=self.student.user)

    def session(self, day_offset, present):
        """Hold a class that many days from today and mark the student."""
        date = self.today + timedelta(days=day_offset)
        cls = AttendanceClass.objects.create(assign=self.assign, date=date,
                                             status=1)
        return Attendance.objects.create(
            student=self.student, course=self.course, attendanceclass=cls,
            date=date, status=present)

    def total(self):
        """The student's attendance for the course, the way the pages get it.

        Through attendance_rows() rather than an AttendanceTotal row: those
        only exist once somebody has opened the attendance page.
        """
        rows = services.attendance_rows(students=[self.student],
                                        courses=[self.course])
        return rows[0] if rows else None

    def percentage(self):
        total = self.total()
        return total.attendance if total else 0


class ApplyingTests(LeaveBase):
    def test_an_application_starts_open(self):
        leave = self.apply()

        self.assertEqual(leave.status, LEAVE_OPEN)
        self.assertEqual(leave.days, 2)

    def test_the_last_day_cannot_precede_the_first(self):
        with self.assertRaises(services.LeaveNotAllowed):
            services.apply_for_leave(
                self.student, 'Medical', self.today + timedelta(days=5),
                self.today, 'Typed the dates the wrong way round.',
                self.student.user)

    def test_recent_days_can_be_claimed_afterwards(self):
        # Nobody plans a fever, so a few days back has to be allowed.
        leave = services.apply_for_leave(
            self.student, 'Medical', self.today - timedelta(days=3),
            self.today - timedelta(days=2), 'I was ill and could not apply.',
            self.student.user)

        self.assertEqual(leave.status, LEAVE_OPEN)

    def test_the_distant_past_cannot(self):
        with self.assertRaises(services.LeaveNotAllowed) as caught:
            services.apply_for_leave(
                self.student, 'Medical', self.today - timedelta(days=60),
                self.today - timedelta(days=59), 'Backdating the whole term.',
                self.student.user)

        self.assertIn('after the event', str(caught.exception))

    def test_a_very_long_application_is_refused(self):
        with self.assertRaises(services.LeaveNotAllowed) as caught:
            services.apply_for_leave(
                self.student, 'Medical', self.today,
                self.today + timedelta(days=90), 'Away for the term.',
                self.student.user)

        self.assertIn('at most', str(caught.exception))

    def test_two_applications_cannot_overlap(self):
        self.apply(from_days=1, to_days=5)

        with self.assertRaises(services.LeaveNotAllowed) as caught:
            self.apply(from_days=4, to_days=6)

        self.assertIn('already have an application', str(caught.exception))

    def test_a_withdrawn_one_does_not_block_a_new_one(self):
        first = self.apply(from_days=1, to_days=5)
        services.withdraw_leave(first, self.student.user)

        second = self.apply(from_days=4, to_days=6)

        self.assertEqual(second.status, LEAVE_OPEN)

    def test_applying_is_recorded_in_the_audit_log(self):
        self.apply()

        self.assertTrue(AuditLog.objects.filter(action='leave.applied').exists())


class ApprovalArithmeticTests(LeaveBase):
    def test_an_excused_session_leaves_the_percentage_alone(self):
        self.session(-3, present=True)
        self.session(-2, present=True)
        absent = self.session(-1, present=False)
        self.assertAlmostEqual(self.percentage(), 66.67, places=1)

        leave = services.apply_for_leave(
            self.student, 'Medical', absent.date, absent.date,
            'Hospital appointment, letter attached.', self.student.user)
        services.approve_leave(leave, self.teacher.user, 'Fine.')

        # Two held, two attended - the excused one is out of the sum entirely
        # rather than counted as attended.
        self.assertEqual(self.percentage(), 100)

    def test_approval_reports_how_many_sessions_it_excused(self):
        self.session(-2, present=False)
        self.session(-1, present=False)
        leave = services.apply_for_leave(
            self.student, 'Medical', self.today - timedelta(days=2),
            self.today - timedelta(days=1), 'Ill for two days running.',
            self.student.user)

        services.approve_leave(leave, self.teacher.user)

        leave.refresh_from_db()
        self.assertEqual(leave.sessions_excused, 2)
        self.assertIn('2 sessions excused', leave.outcome)

    def test_a_session_the_student_attended_is_left_alone(self):
        present = self.session(-1, present=True)
        leave = services.apply_for_leave(
            self.student, 'Official duty', present.date, present.date,
            'Inter-college match, but I made the morning class.',
            self.student.user)

        services.approve_leave(leave, self.teacher.user)

        present.refresh_from_db()
        self.assertFalse(present.is_excused)
        self.assertTrue(present.status)

    def test_sessions_outside_the_range_are_untouched(self):
        outside = self.session(-5, present=False)
        leave = services.apply_for_leave(
            self.student, 'Medical', self.today - timedelta(days=1),
            self.today, 'Two days of flu.', self.student.user)

        services.approve_leave(leave, self.teacher.user)

        outside.refresh_from_db()
        self.assertFalse(outside.is_excused)

    def test_a_rejected_application_changes_nothing(self):
        absent = self.session(-1, present=False)
        leave = services.apply_for_leave(
            self.student, 'Personal', absent.date, absent.date,
            'Family function I could not miss.', self.student.user)

        services.reject_leave(leave, self.teacher.user,
                              'Personal leave does not excuse attendance.')

        absent.refresh_from_db()
        self.assertFalse(absent.is_excused)
        self.assertEqual(leave.status, LEAVE_REJECTED)

    def test_a_refusal_has_to_say_why(self):
        leave = self.apply()

        with self.assertRaises(services.LeaveNotAllowed):
            services.reject_leave(leave, self.teacher.user, '   ')

    def test_answering_twice_is_refused(self):
        leave = self.apply()
        services.approve_leave(leave, self.teacher.user)

        with self.assertRaises(services.LeaveNotAllowed):
            services.reject_leave(leave, self.teacher.user, 'Changed my mind.')

    def test_a_course_with_only_excused_sessions_reads_as_no_classes(self):
        absent = self.session(-1, present=False)
        leave = services.apply_for_leave(
            self.student, 'Medical', absent.date, absent.date,
            'Ill on the only day the class met.', self.student.user)

        services.approve_leave(leave, self.teacher.user)

        # Nothing counted at all, which is not the same as zero per cent -
        # the pages say "no classes yet" rather than showing an alarming 0.
        self.assertIsNone(self.total())


class LeaveInAdvanceTests(LeaveBase):
    """Approving leave for a session nobody has marked yet."""

    def test_a_session_marked_later_is_excused_on_submission(self):
        leave = services.apply_for_leave(
            self.student, 'Official duty', self.today, self.today,
            'Representing the college at the state meet.', self.student.user)
        services.approve_leave(leave, self.teacher.user)

        session = AttendanceClass.objects.create(assign=self.assign,
                                                 date=self.today, status=0)
        services.submit_attendance(session, present_usns=set(),
                                   actor=self.teacher.user)

        row = Attendance.objects.get(student=self.student,
                                     attendanceclass=session)
        self.assertTrue(row.is_excused)
        self.assertFalse(row.status)

    def test_turning_up_anyway_counts_as_attended(self):
        leave = services.apply_for_leave(
            self.student, 'Medical', self.today, self.today,
            'Doctor in the morning, back for the afternoon class.',
            self.student.user)
        services.approve_leave(leave, self.teacher.user)

        session = AttendanceClass.objects.create(assign=self.assign,
                                                 date=self.today, status=0)
        services.submit_attendance(session, present_usns={self.student.USN},
                                   actor=self.teacher.user)

        row = Attendance.objects.get(student=self.student,
                                     attendanceclass=session)
        self.assertFalse(row.is_excused)
        self.assertTrue(row.status)

    def test_an_unapproved_application_excuses_nothing(self):
        services.apply_for_leave(
            self.student, 'Medical', self.today, self.today,
            'Applied but nobody has answered yet.', self.student.user)

        session = AttendanceClass.objects.create(assign=self.assign,
                                                 date=self.today, status=0)
        services.submit_attendance(session, present_usns=set(),
                                   actor=self.teacher.user)

        row = Attendance.objects.get(student=self.student,
                                     attendanceclass=session)
        self.assertFalse(row.is_excused)

    def test_another_student_is_not_excused_by_it(self):
        other = f.make_student(self.klass, usn='1CS20CS002', name='Bala',
                               username='bala')
        leave = services.apply_for_leave(
            self.student, 'Medical', self.today, self.today,
            'Only I am ill.', self.student.user)
        services.approve_leave(leave, self.teacher.user)

        session = AttendanceClass.objects.create(assign=self.assign,
                                                 date=self.today, status=0)
        services.submit_attendance(session, present_usns=set(),
                                   actor=self.teacher.user)

        self.assertFalse(Attendance.objects.get(student=other,
                                                attendanceclass=session)
                         .is_excused)


class PageTests(LeaveBase):
    def test_a_student_can_apply_from_the_page(self):
        self.client.force_login(self.student.user)

        response = self.client.post(reverse('leave_list'), {
            'category': 'Medical',
            'from_date': (self.today + timedelta(days=1)).isoformat(),
            'to_date': (self.today + timedelta(days=2)).isoformat(),
            'reason': 'Down with a fever, certificate to follow.'})

        self.assertRedirects(response, reverse('leave_list'))
        self.assertEqual(LeaveRequest.objects.count(), 1)

    def test_a_reason_that_says_nothing_is_refused(self):
        self.client.force_login(self.student.user)

        self.client.post(reverse('leave_list'), {
            'category': 'Medical',
            'from_date': (self.today + timedelta(days=1)).isoformat(),
            'to_date': (self.today + timedelta(days=1)).isoformat(),
            'reason': 'ill'})

        self.assertFalse(LeaveRequest.objects.exists())

    def test_a_certificate_can_be_attached(self):
        self.client.force_login(self.student.user)
        document = SimpleUploadedFile('certificate.pdf', b'%PDF-1.4 fake',
                                      content_type='application/pdf')

        self.client.post(reverse('leave_list'), {
            'category': 'Medical',
            'from_date': (self.today + timedelta(days=1)).isoformat(),
            'to_date': (self.today + timedelta(days=1)).isoformat(),
            'reason': 'Fever - certificate attached to this application.',
            'document': document})

        leave = LeaveRequest.objects.get()
        self.assertTrue(leave.document.name.endswith('.pdf'))

    def test_an_executable_is_not_a_certificate(self):
        self.client.force_login(self.student.user)
        document = SimpleUploadedFile('payload.exe', b'MZ',
                                      content_type='application/octet-stream')

        self.client.post(reverse('leave_list'), {
            'category': 'Medical',
            'from_date': (self.today + timedelta(days=1)).isoformat(),
            'to_date': (self.today + timedelta(days=1)).isoformat(),
            'reason': 'Fever - certificate attached to this application.',
            'document': document})

        self.assertFalse(LeaveRequest.objects.exists())

    def test_the_page_lists_only_your_own(self):
        other = f.make_student(self.klass, usn='1CS20CS002', name='Bala',
                               username='bala')
        services.apply_for_leave(other, 'Medical', self.today,
                                 self.today, 'Bala is ill, not Asha.',
                                 other.user)
        self.apply()
        self.client.force_login(self.student.user)

        response = self.client.get(reverse('leave_list'))

        self.assertEqual(len(response.context['leaves']), 1)

    def test_a_student_can_withdraw_their_own(self):
        leave = self.apply()
        self.client.force_login(self.student.user)

        self.client.post(reverse('withdraw_leave', args=[leave.pk]))

        leave.refresh_from_db()
        self.assertEqual(leave.status, LEAVE_WITHDRAWN)

    def test_a_student_cannot_withdraw_anybody_else_s(self):
        leave = self.apply()
        other = f.make_student(self.klass, usn='1CS20CS002', name='Bala',
                               username='bala')
        self.client.force_login(other.user)

        response = self.client.post(reverse('withdraw_leave', args=[leave.pk]))

        self.assertEqual(response.status_code, 403)
        leave.refresh_from_db()
        self.assertEqual(leave.status, LEAVE_OPEN)

    def test_a_teacher_has_no_application_page(self):
        self.client.force_login(self.teacher.user)

        self.assertEqual(
            self.client.get(reverse('leave_list')).status_code, 403)


class QueueTests(LeaveBase):
    def setUp(self):
        super().setUp()
        self.leave = self.apply()

    def test_the_queue_shows_applications_from_a_class_they_teach(self):
        self.client.force_login(self.teacher.user)

        response = self.client.get(reverse('leave_queue'))

        self.assertContains(response, 'Asha Rao')
        self.assertEqual(response.context['open_count'], 1)

    def test_it_does_not_show_another_class_s(self):
        stranger = f.make_teacher(self.dept, id='T002', username='other')
        self.client.force_login(stranger.user)

        response = self.client.get(reverse('leave_queue'))

        self.assertNotContains(response, 'Asha Rao')

    def test_a_student_cannot_open_the_queue(self):
        self.client.force_login(self.student.user)

        self.assertEqual(
            self.client.get(reverse('leave_queue')).status_code, 403)

    def test_a_teacher_can_approve_from_the_review_page(self):
        self.client.force_login(self.teacher.user)

        response = self.client.post(
            reverse('review_leave', args=[self.leave.pk]),
            {'decision': 'approve', 'response': 'Get well.'})

        self.assertRedirects(response, reverse('leave_queue'))
        self.leave.refresh_from_db()
        self.assertEqual(self.leave.status, LEAVE_APPROVED)

    def test_refusing_without_a_reason_leaves_it_open(self):
        self.client.force_login(self.teacher.user)

        self.client.post(reverse('review_leave', args=[self.leave.pk]),
                         {'decision': 'reject', 'response': ''})

        self.leave.refresh_from_db()
        self.assertEqual(self.leave.status, LEAVE_OPEN)

    def test_a_teacher_of_another_class_cannot_decide(self):
        stranger = f.make_teacher(self.dept, id='T002', username='other')
        self.client.force_login(stranger.user)

        response = self.client.post(
            reverse('review_leave', args=[self.leave.pk]),
            {'decision': 'approve', 'response': 'Not my class.'})

        self.assertEqual(response.status_code, 403)
        self.leave.refresh_from_db()
        self.assertEqual(self.leave.status, LEAVE_OPEN)


class TellingPeopleTests(LeaveBase):
    def test_applying_notifies_the_teachers_of_that_class(self):
        self.client.force_login(self.student.user)

        self.client.post(reverse('leave_list'), {
            'category': 'Medical',
            'from_date': (self.today + timedelta(days=1)).isoformat(),
            'to_date': (self.today + timedelta(days=1)).isoformat(),
            'reason': 'Fever, certificate to follow tomorrow.'})

        notification = Notification.objects.get(user=self.teacher.user)
        self.assertEqual(notification.kind, 'leave')
        self.assertIn('Asha Rao', notification.body)

    def test_a_decision_notifies_the_student(self):
        leave = self.apply()
        self.client.force_login(self.teacher.user)

        self.client.post(reverse('review_leave', args=[leave.pk]),
                         {'decision': 'approve', 'response': 'Get well.'})

        notification = Notification.objects.get(user=self.student.user)
        self.assertIn('Approved', notification.body)
