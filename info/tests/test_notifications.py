"""The scheduled emails.

These run unattended, which makes the interesting cases the ones nobody would
notice going wrong: a job that runs twice, a first run against a database full
of history, a mail server that is down for one of the five hundred messages.
"""
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from info import notifications
from info.models import (
    Attendance,
    AttendanceClass,
    Fee,
    Marks,
    MarksClass,
    Notice,
    Notification,
    StudentCourse,
)
from info.tests import factories as f


class BrokenBackend:
    """An SMTP server that will not take the message."""

    def __init__(self, *args, **kwargs):
        pass

    def send_messages(self, messages):
        raise OSError('the mail server is not answering')


class NotificationBase(TestCase):
    def setUp(self):
        self.dept = f.make_dept()
        self.klass = f.make_class(self.dept)
        self.course = f.make_course(self.dept)
        self.teacher = f.make_teacher(self.dept, id='T001', username='staff')
        self.teacher.user.email = 'staff@example.com'
        self.teacher.user.save(update_fields=['email'])

        self.student = f.make_student(self.klass, usn='1CS20CS001',
                                      name='Asha Rao', username='asha')
        self.student.user.email = 'asha@example.com'
        self.student.user.save(update_fields=['email'])

        self.today = timezone.localdate()

    def run_command(self, *args, **kwargs):
        out = StringIO()
        call_command('send_notifications', *args, stdout=out,
                     stderr=StringIO(), **kwargs)
        return out.getvalue()


class FeeReminderTests(NotificationBase):
    def _fee(self, amount='10000', due_in_days=3, paid='0', fee_type='Tuition Fee'):
        return Fee.objects.create(
            student=self.student, fee_type=fee_type, amount=Decimal(amount),
            paid_amount=Decimal(paid),
            due_date=self.today + timedelta(days=due_in_days))

    def test_a_fee_falling_due_is_reminded_about(self):
        self._fee(due_in_days=3)

        messages = notifications.fee_reminders()

        self.assertEqual(len(messages), 1)
        self.assertIn('Due soon', messages[0].body)
        self.assertIn('Rs 10,000.00', messages[0].body)

    def test_a_fee_further_out_than_the_window_is_left_alone(self):
        self._fee(due_in_days=30)

        self.assertEqual(notifications.fee_reminders(), [])

    def test_an_overdue_fee_says_so_in_the_subject(self):
        self._fee(due_in_days=-5)

        message = notifications.fee_reminders()[0]

        self.assertIn('overdue', message.subject.lower())
        self.assertIn('Overdue', message.body)

    def test_several_fees_arrive_as_one_email(self):
        self._fee(due_in_days=-5, fee_type='Tuition Fee')
        self._fee(due_in_days=2, fee_type='Exam Fee', amount='2000')
        self._fee(due_in_days=4, fee_type='Library Fee', amount='500')

        messages = notifications.fee_reminders()

        self.assertEqual(len(messages), 1)
        for label in ['Tuition Fee', 'Exam Fee', 'Library Fee']:
            self.assertIn(label, messages[0].body)
        self.assertIn('Rs 12,500.00', messages[0].body)

    def test_only_the_unpaid_balance_is_chased(self):
        self._fee(amount='10000', paid='10000', due_in_days=-5)

        self.assertEqual(notifications.fee_reminders(), [])

    def test_a_partly_paid_fee_is_chased_for_the_remainder(self):
        self._fee(amount='10000', paid='4000', due_in_days=-1)

        self.assertIn('Rs 6,000.00', notifications.fee_reminders()[0].body)

    def test_a_deactivated_student_is_not_chased(self):
        self._fee()
        self.student.is_active = False
        self.student.save()

        self.assertEqual(notifications.fee_reminders(), [])

    def test_the_reminder_repeats_weekly_rather_than_every_run(self):
        self._fee(due_in_days=-5)

        notifications.send_all(notifications.fee_reminders(today=self.today))
        notifications.send_all(notifications.fee_reminders(today=self.today))
        notifications.send_all(
            notifications.fee_reminders(today=self.today + timedelta(days=1)))

        self.assertEqual(len(mail.outbox), 1)

        # A week later it nags again - the fee is still unpaid.
        notifications.send_all(
            notifications.fee_reminders(today=self.today + timedelta(days=7)))
        self.assertEqual(len(mail.outbox), 2)


class AttendanceAlertTests(NotificationBase):
    def setUp(self):
        super().setUp()
        self.assign = f.make_assign(self.klass, self.course, self.teacher)

    def _sessions(self, held, attended):
        """Hold `held` classes and have the student attend `attended` of them."""
        sc = StudentCourse.objects.get(student=self.student, course=self.course)
        for index in range(held):
            session = AttendanceClass.objects.create(
                assign=self.assign, date=self.today - timedelta(days=index),
                status=1)
            Attendance.objects.create(
                student=self.student, course=self.course,
                attendanceclass=session, date=session.date,
                status=index < attended)
        return sc

    def test_a_student_below_the_threshold_is_warned(self):
        self._sessions(held=10, attended=5)

        messages = notifications.attendance_alerts()

        self.assertEqual(len(messages), 1)
        self.assertIn('50.00%', messages[0].body)
        self.assertIn(self.course.name, messages[0].body)

    def test_a_student_above_the_threshold_is_left_alone(self):
        self._sessions(held=10, attended=9)

        self.assertEqual(notifications.attendance_alerts(), [])

    def test_a_course_that_has_not_met_is_not_reported_as_zero(self):
        # The assign exists and the student is enrolled on it, but no session
        # has been held - which reads as 0% if anything counts it.
        self.assertEqual(notifications.attendance_alerts(), [])

    def test_the_warning_says_how_many_classes_would_fix_it(self):
        self._sessions(held=10, attended=5)

        # 5 of 10 attended: ten consecutive classes take it to 15/20, or 75%.
        self.assertIn('attend 10 more', notifications.attendance_alerts()[0].body)

    def test_the_digest_covers_every_failing_course_at_once(self):
        second = f.make_course(self.dept, id='CS102', name='Algorithms',
                               shortname='ALGO')
        second_assign = f.make_assign(self.klass, second, self.teacher)
        self._sessions(held=10, attended=5)
        for index in range(4):
            session = AttendanceClass.objects.create(
                assign=second_assign, date=self.today - timedelta(days=index),
                status=1)
            Attendance.objects.create(student=self.student, course=second,
                                      attendanceclass=session, date=session.date,
                                      status=False)

        messages = notifications.attendance_alerts()

        self.assertEqual(len(messages), 1)
        self.assertIn('2 courses', messages[0].subject)
        self.assertIn('Data Structures', messages[0].body)
        self.assertIn('Algorithms', messages[0].body)

    def test_the_warning_repeats_weekly_rather_than_every_run(self):
        self._sessions(held=10, attended=5)

        for _ in range(3):
            notifications.send_all(
                notifications.attendance_alerts(today=self.today))

        self.assertEqual(len(mail.outbox), 1)


class MarksReleaseTests(NotificationBase):
    def setUp(self):
        super().setUp()
        self.assign = f.make_assign(self.klass, self.course, self.teacher)
        self.batch = MarksClass.objects.get(assign=self.assign,
                                            name='Internal test 1')
        self.mark = Marks.objects.get(
            studentcourse__student=self.student,
            studentcourse__course=self.course, name='Internal test 1')

    def test_nothing_goes_out_until_the_batch_is_published(self):
        self.mark.marks1 = 17
        self.mark.save()

        self.assertEqual(notifications.marks_release_alerts(), [])

    def test_publishing_tells_the_class_what_they_scored(self):
        self.mark.marks1 = 17
        self.mark.save()
        self.batch.publish()

        messages = notifications.marks_release_alerts()

        self.assertEqual(len(messages), 1)
        self.assertIn('Internal test 1', messages[0].subject)
        self.assertIn('17 out of 20', messages[0].body)

    def test_an_absent_student_is_not_told_they_scored_zero(self):
        self.mark.is_absent = True
        self.mark.marks1 = 0
        self.mark.save()
        self.batch.publish()

        self.assertIn('absent', notifications.marks_release_alerts()[0].body)

    def test_a_batch_published_before_the_window_is_treated_as_history(self):
        self.batch.publish()
        MarksClass.objects.filter(pk=self.batch.pk).update(
            published_at=timezone.now() - timedelta(days=30))

        self.assertEqual(notifications.marks_release_alerts(), [])

    def test_each_student_is_told_once_per_batch(self):
        self.batch.publish()

        for _ in range(3):
            notifications.send_all(notifications.marks_release_alerts())

        self.assertEqual(len(mail.outbox), 1)


class NoticeAlertTests(NotificationBase):
    def _notice(self, audience='All', **extra):
        return Notice.objects.create(title='Exam timetable',
                                     message='Out now.', audience=audience,
                                     **extra)

    def test_a_published_notice_reaches_both_audiences(self):
        self._notice(audience='All')

        recipients = {m.user.username for m in notifications.notice_alerts()}

        self.assertEqual(recipients, {'asha', 'staff'})

    def test_a_students_notice_does_not_go_to_teachers(self):
        self._notice(audience='Students')

        recipients = {m.user.username for m in notifications.notice_alerts()}

        self.assertEqual(recipients, {'asha'})

    def test_a_teachers_notice_does_not_go_to_students(self):
        self._notice(audience='Teachers')

        recipients = {m.user.username for m in notifications.notice_alerts()}

        self.assertEqual(recipients, {'staff'})

    def test_an_unpublished_notice_is_not_announced(self):
        self._notice(is_published=False)

        self.assertEqual(notifications.notice_alerts(), [])

    def test_an_expired_notice_is_not_announced(self):
        self._notice(expires_at=self.today - timedelta(days=1))

        self.assertEqual(notifications.notice_alerts(), [])

    def test_the_archive_is_not_emailed_on_the_first_run(self):
        old = self._notice()
        Notice.objects.filter(pk=old.pk).update(
            published_at=timezone.now() - timedelta(days=60))

        self.assertEqual(notifications.notice_alerts(), [])

    def test_a_notice_is_announced_once(self):
        self._notice()

        for _ in range(3):
            notifications.send_all(notifications.notice_alerts())

        self.assertEqual(len(mail.outbox), 2)  # one student, one teacher


class DeliveryTests(NotificationBase):
    def _message(self, key='notice:1'):
        return notifications.Message(
            user=self.student.user, kind='notice', key=key,
            subject='Something happened', body='Body', url='/notices/')

    def test_a_send_is_recorded(self):
        notifications.send_all([self._message()])

        record = Notification.objects.get()
        self.assertEqual(record.user, self.student.user)
        self.assertEqual(record.key, 'notice:1')
        self.assertEqual(len(mail.outbox), 1)

    def test_a_person_without_an_email_is_still_told_in_the_app(self):
        self.student.user.email = ''
        self.student.user.save(update_fields=['email'])

        result = notifications.send_all([self._message()])

        self.assertEqual(result.sent, 0)
        self.assertEqual(len(mail.outbox), 0)
        # The notification is the row, not the email.
        record = Notification.objects.get()
        self.assertIsNone(record.emailed_at)
        self.assertFalse(record.is_read)

    def test_a_second_run_reports_what_it_skipped(self):
        notifications.send_all([self._message()])

        result = notifications.send_all([self._message()])

        self.assertEqual(result.sent, 0)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_a_failed_send_is_not_recorded_as_emailed(self):
        with self.settings(
                EMAIL_BACKEND='info.tests.test_notifications.BrokenBackend'):
            result = notifications.send_all([self._message()])

        self.assertEqual(result.failed, 1)
        # The person can still see it in the app; emailed_at staying null is
        # what makes the next run try again rather than call it delivered.
        self.assertIsNone(Notification.objects.get().emailed_at)

    def test_a_delivered_message_records_when_it_went(self):
        notifications.send_all([self._message()])

        self.assertIsNotNone(Notification.objects.get().emailed_at)

    def test_a_retry_after_a_failure_sends(self):
        with self.settings(
                EMAIL_BACKEND='info.tests.test_notifications.BrokenBackend'):
            notifications.send_all([self._message()])

        notifications.send_all([self._message()])

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(Notification.objects.count(), 1)

    def test_a_dry_run_neither_sends_nor_records(self):
        result = notifications.send_all([self._message()], dry_run=True)

        self.assertEqual(result.sent, 1)
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(Notification.objects.exists())

    def test_the_body_is_signed_so_nobody_replies_to_a_robot(self):
        notifications.send_all([self._message()])

        self.assertIn('sent automatically', mail.outbox[0].body)


class CommandTests(NotificationBase):
    def test_it_runs_everything_by_default(self):
        Fee.objects.create(student=self.student, amount=Decimal('5000'),
                           due_date=self.today + timedelta(days=1))
        Notice.objects.create(title='Holiday', message='Monday off.')

        output = self.run_command()

        for label in ['fee reminders', 'low-attendance alerts',
                      'marks-release alerts', 'notice announcements']:
            self.assertIn(label, output)
        self.assertEqual(len(mail.outbox), 3)  # fee + notice to two people

    def test_it_can_be_asked_for_one_kind(self):
        Fee.objects.create(student=self.student, amount=Decimal('5000'),
                           due_date=self.today + timedelta(days=1))
        Notice.objects.create(title='Holiday', message='Monday off.')

        self.run_command('fee')

        self.assertEqual(len(mail.outbox), 1)

    def test_a_dry_run_sends_nothing(self):
        Notice.objects.create(title='Holiday', message='Monday off.')

        output = self.run_command('--dry-run')

        self.assertIn('Dry run', output)
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(Notification.objects.exists())

    def test_an_unknown_kind_is_refused(self):
        with self.assertRaises(CommandError):
            self.run_command('everything')

    def test_a_failed_send_exits_with_an_error(self):
        Notice.objects.create(title='Holiday', message='Monday off.')

        with self.settings(
                EMAIL_BACKEND='info.tests.test_notifications.BrokenBackend'):
            with self.assertRaises(CommandError):
                self.run_command('notice')

    def test_the_window_can_be_widened_for_a_first_run(self):
        notice = Notice.objects.create(title='Old news', message='From before.')
        Notice.objects.filter(pk=notice.pk).update(
            published_at=timezone.now() - timedelta(days=40))

        self.run_command('notice', '--window-days', '90')

        self.assertEqual(len(mail.outbox), 2)
