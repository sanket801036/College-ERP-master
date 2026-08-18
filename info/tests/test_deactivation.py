"""Deleting a login used to delete the person's whole academic record.

This was hit for real during the review: removing one User took a student's
attendance, marks and fees with it.
"""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from info.models import Attendance, AttendanceClass, Fee, Marks, Student, StudentCourse
from info.tests import factories as f

User = get_user_model()


class RecordSurvivesUserDeletionTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        self.course = f.make_course(dept)
        teacher = f.make_teacher(dept, id='t001', username='owner')
        self.assign = f.make_assign(self.klass, self.course, teacher)
        self.student = f.make_student(self.klass, usn='1CS20CS001',
                                      name='Asha Rao', username='asha')

        session = AttendanceClass.objects.create(assign=self.assign,
                                                 date=date(2026, 1, 6))
        Attendance.objects.create(course=self.course, student=self.student,
                                  attendanceclass=session, date=session.date,
                                  status=True)
        Fee.objects.create(student=self.student, fee_type='Tuition Fee',
                           amount=10000, due_date=date(2026, 9, 1))

    def test_deleting_the_login_keeps_the_student(self):
        self.student.user.delete()

        student = Student.objects.get(USN='1CS20CS001')
        self.assertIsNone(student.user)
        self.assertEqual(student.name, 'Asha Rao')

    def test_deleting_the_login_keeps_attendance_marks_and_fees(self):
        self.student.user.delete()

        self.assertEqual(Attendance.objects.filter(student=self.student).count(), 1)
        self.assertEqual(Fee.objects.filter(student=self.student).count(), 1)
        self.assertTrue(
            Marks.objects.filter(studentcourse__student=self.student).exists())
        self.assertTrue(
            StudentCourse.objects.filter(student=self.student).exists())

    def test_the_same_holds_for_a_teacher(self):
        teacher = f.make_teacher(self.klass.dept, id='t002', name='Ravi',
                                 username='ravi')

        teacher.user.delete()

        teacher.refresh_from_db()
        self.assertIsNone(teacher.user)
        self.assertEqual(teacher.name, 'Ravi')


class DeactivationTests(TestCase):
    def setUp(self):
        self.dept = f.make_dept()
        self.klass = f.make_class(self.dept)
        self.student = f.make_student(self.klass, usn='1CS20CS001',
                                      name='Asha Rao', username='asha',
                                      password='pass12345')
        self.teacher = f.make_teacher(self.dept, id='t001', username='staff')

    def test_new_people_are_active(self):
        self.assertTrue(self.student.is_active)
        self.assertTrue(self.student.user.is_active)

    def test_deactivating_blocks_sign_in(self):
        """Otherwise the flag is only a label."""
        self.student.is_active = False
        self.student.save()

        signed_in = self.client.login(username='asha', password='pass12345')

        self.assertFalse(signed_in)
        self.student.user.refresh_from_db()
        self.assertFalse(self.student.user.is_active)

    def test_reactivating_restores_the_login(self):
        self.student.is_active = False
        self.student.save()

        self.student.is_active = True
        self.student.save()

        self.assertTrue(self.client.login(username='asha', password='pass12345'))

    def test_deactivating_keeps_the_records(self):
        session_class = f.make_course(self.dept)
        assign = f.make_assign(self.klass, session_class, self.teacher)
        session = AttendanceClass.objects.create(
            assign=assign, date=timezone.localdate() - timedelta(days=1))
        Attendance.objects.create(course=session_class, student=self.student,
                                  attendanceclass=session, date=session.date,
                                  status=True)

        self.student.is_active = False
        self.student.save()

        self.assertEqual(Attendance.objects.filter(student=self.student).count(), 1)


class DirectoryFilteringTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        self.teacher = f.make_teacher(dept, id='t001', username='staff')
        self.active = f.make_student(self.klass, usn='1CS20CS001',
                                     name='Asha Rao', username='asha')
        self.gone = f.make_student(self.klass, usn='1CS20CS002',
                                   name='Graduated Student', username='old')
        self.gone.is_active = False
        self.gone.save()
        self.client.force_login(self.teacher.user)

    def _names(self, **params):
        page = self.client.get(reverse('directory'), params).context['page']
        return [p.name for p in page]

    def test_deactivated_people_are_hidden_by_default(self):
        """A directory of everybody who ever enrolled is not a directory."""
        self.assertEqual(self._names(), ['Asha Rao'])

    def test_they_can_be_shown_on_request(self):
        names = self._names(inactive='1')

        self.assertIn('Graduated Student', names)
        self.assertIn('Asha Rao', names)

    def test_they_are_labelled_when_shown(self):
        response = self.client.get(reverse('directory'), {'inactive': '1'})

        self.assertContains(response, 'Deactivated')
