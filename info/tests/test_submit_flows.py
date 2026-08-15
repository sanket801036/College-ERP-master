"""Attendance and marks submission: transactions, validation, POST-only."""
from datetime import date

from django.test import TestCase
from django.urls import reverse

from info.models import (Attendance, AttendanceClass, AttendanceRange, Marks,
                         MarksClass, StudentCourse)
from info.tests import factories as f


class BaseClassTest(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        self.course = f.make_course(dept)
        self.teacher = f.make_teacher(dept, id='t001', username='owner')
        self.assign = f.make_assign(self.klass, self.course, self.teacher)
        self.a = f.make_student(self.klass, usn='1CS20CS001', name='Asha',
                                username='asha')
        self.b = f.make_student(self.klass, usn='1CS20CS002', name='Bhavna',
                                username='bhavna')
        self.session = AttendanceClass.objects.create(assign=self.assign,
                                                      date=date(2026, 1, 6))
        self.client.force_login(self.teacher.user)


class ConfirmAttendanceTests(BaseClassTest):
    def test_records_the_whole_class(self):
        response = self.client.post(
            reverse('confirm', args=(self.session.id,)),
            {self.a.USN: 'present', self.b.USN: 'absent'})

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Attendance.objects.get(student=self.a).status)
        self.assertFalse(Attendance.objects.get(student=self.b).status)

        self.session.refresh_from_db()
        self.assertEqual(self.session.status, 1)

    def test_missing_field_does_not_500_midway(self):
        """A student absent from the payload used to raise KeyError, leaving
        part of the class saved and the session already flagged submitted."""
        response = self.client.post(reverse('confirm', args=(self.session.id,)),
                                    {self.a.USN: 'present'})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Attendance.objects.count(), 2)
        self.assertFalse(Attendance.objects.get(student=self.b).status)

    def test_resubmitting_updates_rather_than_duplicates(self):
        url = reverse('confirm', args=(self.session.id,))
        self.client.post(url, {self.a.USN: 'present', self.b.USN: 'present'})
        self.client.post(url, {self.a.USN: 'absent', self.b.USN: 'present'})

        self.assertEqual(Attendance.objects.count(), 2)
        self.assertFalse(Attendance.objects.get(student=self.a).status)

    def test_get_is_rejected(self):
        response = self.client.get(reverse('confirm', args=(self.session.id,)))
        self.assertEqual(response.status_code, 405)


class MarksConfirmTests(BaseClassTest):
    def setUp(self):
        super().setUp()
        self.mc = MarksClass.objects.get(assign=self.assign,
                                         name='Internal test 1')

    def test_records_marks_for_the_class(self):
        response = self.client.post(
            reverse('marks_confirm', args=(self.mc.id,)),
            {self.a.USN: '17', self.b.USN: '12'})

        self.assertEqual(response.status_code, 302)
        sc = StudentCourse.objects.get(student=self.a, course=self.course)
        self.assertEqual(sc.marks_set.get(name='Internal test 1').marks1, 17)
        self.mc.refresh_from_db()
        self.assertTrue(self.mc.status)

    def test_mark_above_the_maximum_is_rejected(self):
        """An internal is out of 20, but 85 saved cleanly - model validators
        never run on a plain .save()."""
        response = self.client.post(
            reverse('marks_confirm', args=(self.mc.id,)),
            {self.a.USN: '85', self.b.USN: '12'})

        self.assertEqual(response.status_code, 200)
        self.assertIn('Maximum for this test is 20.',
                      response.context['form'].errors[self.a.USN])

    def test_nothing_is_saved_when_one_entry_is_invalid(self):
        self.client.post(reverse('marks_confirm', args=(self.mc.id,)),
                         {self.a.USN: '85', self.b.USN: '12'})

        self.assertFalse(Marks.objects.filter(marks1=12).exists(),
                         'a valid row must not be written when the batch fails')
        self.mc.refresh_from_db()
        self.assertFalse(self.mc.status)

    def test_negative_mark_is_rejected(self):
        response = self.client.post(
            reverse('marks_confirm', args=(self.mc.id,)),
            {self.a.USN: '-5', self.b.USN: '12'})

        self.assertIn('Marks cannot be negative.',
                      response.context['form'].errors[self.a.USN])

    def test_non_numeric_mark_is_rejected_not_a_500(self):
        response = self.client.post(
            reverse('marks_confirm', args=(self.mc.id,)),
            {self.a.USN: 'abc', self.b.USN: '12'})

        self.assertEqual(response.status_code, 200)
        self.assertIn('Enter a whole number.',
                      response.context['form'].errors[self.a.USN])

    def test_missing_studentcourse_row_does_not_break_the_batch(self):
        """This lookup used to be a bare .get(), so one missing row 500'd the
        whole submission - and the fallback that would have created it raised
        TypeError anyway."""
        StudentCourse.objects.filter(student=self.a, course=self.course).delete()

        response = self.client.post(
            reverse('marks_confirm', args=(self.mc.id,)),
            {self.a.USN: '15', self.b.USN: '12'})

        self.assertEqual(response.status_code, 302)
        sc = StudentCourse.objects.get(student=self.a, course=self.course)
        self.assertEqual(sc.marks_set.get(name='Internal test 1').marks1, 15)


class ExtraClassTests(BaseClassTest):
    def setUp(self):
        super().setUp()
        AttendanceRange.objects.create(start_date=date(2026, 1, 1),
                                       end_date=date(2026, 6, 1))
        self.url = reverse('e_confirm', args=(self.assign.id,))

    def test_creates_a_session(self):
        response = self.client.post(self.url, {
            'date': '2026-03-10', self.a.USN: 'present', self.b.USN: 'absent'})

        self.assertEqual(response.status_code, 302)
        session = AttendanceClass.objects.get(date=date(2026, 3, 10))
        self.assertEqual(session.status, 1)
        self.assertEqual(Attendance.objects.filter(attendanceclass=session).count(), 2)

    def test_date_outside_the_term_is_rejected(self):
        response = self.client.post(self.url, {
            'date': '2027-03-10', self.a.USN: 'present', self.b.USN: 'present'})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(AttendanceClass.objects.filter(date=date(2027, 3, 10)).exists())

    def test_duplicate_session_date_is_rejected(self):
        response = self.client.post(self.url, {
            'date': '2026-01-06', self.a.USN: 'present', self.b.USN: 'present'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            AttendanceClass.objects.filter(assign=self.assign,
                                           date=date(2026, 1, 6)).count(), 1)

    def test_invalid_date_is_rejected_not_a_500(self):
        response = self.client.post(self.url, {
            'date': 'not-a-date', self.a.USN: 'present', self.b.USN: 'present'})

        self.assertEqual(response.status_code, 200)
