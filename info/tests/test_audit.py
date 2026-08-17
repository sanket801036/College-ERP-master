"""Attendance, marks and fees could all be altered with no record of who did
it, when, or what the value was before."""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from info.models import (
    Attendance,
    AttendanceClass,
    AuditLog,
    Fee,
    MarksClass,
)
from info.tests import factories as f


class AuditBase(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        self.course = f.make_course(dept)
        self.teacher = f.make_teacher(dept, id='t001', name='Ravi Shankar',
                                      username='owner')
        self.assign = f.make_assign(self.klass, self.course, self.teacher)
        self.student = f.make_student(self.klass, name='Asha Rao',
                                      username='pupil')
        self.session = AttendanceClass.objects.create(assign=self.assign,
                                                      date=date(2026, 1, 6))
        self.client.force_login(self.teacher.user)


class AttendanceAuditTests(AuditBase):
    def test_flipping_a_record_is_logged_with_the_old_value(self):
        record = Attendance.objects.create(
            course=self.course, student=self.student,
            attendanceclass=self.session, date=self.session.date, status=False)

        self.client.post(reverse('change_att', args=(record.id,)))

        entry = AuditLog.objects.get(action='attendance.changed')
        self.assertEqual(entry.actor, self.teacher.user)
        self.assertEqual(entry.student, self.student)
        self.assertEqual(entry.changes['status'], {'from': False, 'to': True})
        self.assertIn('Marked present', entry.summary)

    def test_first_submission_logs_the_batch(self):
        self.client.post(reverse('confirm', args=(self.session.id,)),
                         {self.student.USN: 'present'})

        entry = AuditLog.objects.get(action='attendance.marked')
        self.assertIn('Attendance submitted', entry.summary)
        self.assertFalse(AuditLog.objects.filter(action='attendance.changed').exists())

    def test_resubmission_logs_only_what_changed(self):
        url = reverse('confirm', args=(self.session.id,))
        other = f.make_student(self.klass, usn='1CS20CS002', name='Bhavna',
                               username='b')
        self.client.post(url, {self.student.USN: 'present', other.USN: 'present'})

        self.client.post(url, {self.student.USN: 'absent', other.USN: 'present'})

        changes = AuditLog.objects.filter(action='attendance.changed')
        self.assertEqual(changes.count(), 1, 'only the student who changed')
        entry = changes.get()
        self.assertEqual(entry.student, self.student)
        self.assertEqual(entry.changes['status'], {'from': True, 'to': False})

    def test_cancelling_a_class_is_logged(self):
        # POST since pass 21 - it used to change state on a GET.
        self.client.post(reverse('cancel_class', args=(self.session.id,)))

        entry = AuditLog.objects.get(action='attendance.cancelled')
        self.assertIn('Class cancelled', entry.summary)


class MarksAuditTests(AuditBase):
    def setUp(self):
        super().setUp()
        self.mc = MarksClass.objects.get(assign=self.assign,
                                         name='Internal test 1')
        self.url = reverse('marks_confirm', args=(self.mc.id,))

    def test_first_entry_logs_the_batch(self):
        self.client.post(self.url, {self.student.USN: '15'})

        entry = AuditLog.objects.get(action='marks.entered')
        self.assertIn('Internal test 1', entry.summary)

    def test_changing_a_mark_records_the_old_value(self):
        self.client.post(self.url, {self.student.USN: '15'})

        self.client.post(self.url, {self.student.USN: '18'})

        entry = AuditLog.objects.get(action='marks.changed')
        self.assertEqual(entry.student, self.student)
        self.assertEqual(entry.changes['marks1'], {'from': 15, 'to': 18})
        self.assertIn('changed from 15 to 18', entry.summary)

    def test_unchanged_marks_are_not_logged(self):
        self.client.post(self.url, {self.student.USN: '15'})

        self.client.post(self.url, {self.student.USN: '15'})

        self.assertFalse(AuditLog.objects.filter(action='marks.changed').exists())


class FeeAuditTests(AuditBase):
    def test_recording_a_payment_is_logged(self):
        fee = Fee.objects.create(student=self.student, fee_type='Tuition Fee',
                                 amount=Decimal('10000'),
                                 due_date=date(2026, 9, 1))

        self.client.post(reverse('edit_fee', args=(fee.id,)), {
            'amount': '4000', 'mode': 'UPI', 'reference': 'TXN1',
            'paid_on': '2026-08-01', 'note': ''})

        entry = AuditLog.objects.get(action='fee.payment')
        self.assertEqual(entry.student, self.student)
        self.assertIn('4000', entry.summary)
        self.assertIn('UPI', entry.summary)


class AuditLogBehaviourTests(AuditBase):
    def test_entries_survive_the_actor_being_deleted(self):
        """The name is stored as well as the link, so the log still reads
        correctly once an account is removed."""
        record = Attendance.objects.create(
            course=self.course, student=self.student,
            attendanceclass=self.session, date=self.session.date, status=False)
        self.client.post(reverse('change_att', args=(record.id,)))

        self.teacher.user.delete()

        entry = AuditLog.objects.get(action='attendance.changed')
        self.assertIsNone(entry.actor)
        self.assertEqual(entry.actor_name, 'owner')

    def test_admin_dashboard_shows_recent_activity(self):
        Attendance.objects.create(course=self.course, student=self.student,
                                  attendanceclass=self.session,
                                  date=self.session.date, status=False)
        self.client.get(reverse('index'))

        self.client.force_login(f.make_admin())
        response = self.client.get(reverse('index'))

        self.assertIn('recent_activity', response.context)
