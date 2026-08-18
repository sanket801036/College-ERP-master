"""The primary-key overwrite, closed at the model rather than the form.

The add-student form already rejected a duplicate USN, but that only covered
one path. Anything creating these objects in code - a management command, a
shell session, a future import - had the original behaviour: Django tries an
UPDATE first when the key is already set, so the new object replaced the old
one silently.
"""
from datetime import date

from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from info.models import (
    Class,
    Course,
    Dept,
    Marks,
    MarksClass,
    Student,
    StudentCourse,
    Teacher,
)
from info.tests import factories as f


class PrimaryKeyGuardTests(TestCase):
    def setUp(self):
        self.dept = f.make_dept()
        self.klass = f.make_class(self.dept)

    def _expect_refusal(self, make):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make()

    def test_a_duplicate_department_is_refused(self):
        self._expect_refusal(
            lambda: Dept(id=self.dept.pk, name='Something Else').save())

        self.dept.refresh_from_db()
        self.assertEqual(self.dept.name, 'Computer Science')

    def test_a_duplicate_course_is_refused(self):
        course = f.make_course(self.dept)

        self._expect_refusal(
            lambda: Course(id=course.pk, dept=self.dept, name='Other',
                           shortname='X').save())

        course.refresh_from_db()
        self.assertEqual(course.name, 'Data Structures')

    def test_a_duplicate_class_is_refused(self):
        self._expect_refusal(
            lambda: Class(id=self.klass.pk, dept=self.dept, section='Z',
                          sem=9).save())

        self.klass.refresh_from_db()
        self.assertEqual(self.klass.section, 'A')

    def test_a_duplicate_usn_is_refused_in_code_too(self):
        """This is the one that wiped a student's record."""
        student = f.make_student(self.klass, usn='1CS20CS001',
                                 name='Original Name', username='original')

        self._expect_refusal(
            lambda: Student(USN='1CS20CS001', class_id=self.klass,
                            name='Impostor', sex='Male',
                            DOB=date(2000, 1, 1)).save())

        student.refresh_from_db()
        self.assertEqual(student.name, 'Original Name')
        self.assertIsNotNone(student.user)

    def test_a_duplicate_staff_id_is_refused_in_code_too(self):
        teacher = f.make_teacher(self.dept, id='t001', name='Original',
                                 username='original')

        self._expect_refusal(
            lambda: Teacher(id='t001', dept=self.dept, name='Impostor',
                            sex='Male', DOB=date(1980, 1, 1)).save())

        teacher.refresh_from_db()
        self.assertEqual(teacher.name, 'Original')

    def test_updating_a_loaded_row_still_works(self):
        """The guard is about creating, not saving - a row read from the
        database is no longer 'adding'."""
        student = f.make_student(self.klass, usn='1CS20CS001', name='Asha',
                                 username='asha')

        student.name = 'Asha Rao'
        student.save()

        student.refresh_from_db()
        self.assertEqual(student.name, 'Asha Rao')


class MarkSeedingTests(TestCase):
    def setUp(self):
        self.dept = f.make_dept()
        self.klass = f.make_class(self.dept)
        self.teacher = f.make_teacher(self.dept, id='t001', username='owner')
        self.course = f.make_course(self.dept)

    def test_a_new_student_gets_mark_rows_for_every_course(self):
        f.make_assign(self.klass, self.course, self.teacher)
        second = f.make_course(self.dept, id='CS102', name='OS', shortname='OS')
        f.make_assign(self.klass, second, self.teacher)

        student = f.make_student(self.klass, username='pupil')

        self.assertEqual(
            StudentCourse.objects.filter(student=student).count(), 2)
        self.assertEqual(
            Marks.objects.filter(studentcourse__student=student).count(), 12)

    def test_a_new_assignment_gets_mark_rows_for_every_student(self):
        students = [f.make_student(self.klass, usn='1CS20CS00%d' % i,
                                   name='Student %d' % i, username='s%d' % i)
                    for i in range(1, 4)]

        f.make_assign(self.klass, self.course, self.teacher)

        self.assertEqual(
            StudentCourse.objects.filter(student__in=students).count(), 3)
        self.assertEqual(Marks.objects.count(), 18)

    def test_an_assignment_gets_its_six_components(self):
        assign = f.make_assign(self.klass, self.course, self.teacher)

        self.assertEqual(MarksClass.objects.filter(assign=assign).count(), 6)

    def test_seeding_does_not_scale_its_queries_with_class_size(self):
        """It ran a SELECT and six INSERTs per pair - adding one assignment to
        a sixty-student class was over four hundred round trips."""
        small = f.make_class(self.dept, id='CS-SM', section='S')
        for i in range(2):
            f.make_student(small, usn='2CS20CS00%d' % i, name='S%d' % i,
                           username='sm%d' % i)

        large = f.make_class(self.dept, id='CS-LG', section='L')
        for i in range(20):
            f.make_student(large, usn='3CS20CS0%02d' % i, name='L%d' % i,
                           username='lg%d' % i)

        with CaptureQueriesContext(connection) as few:
            f.make_assign(small, self.course, self.teacher)

        with CaptureQueriesContext(connection) as many:
            f.make_assign(large, self.course, self.teacher)

        self.assertEqual(len(few), len(many))

    def test_re_saving_a_student_does_not_duplicate_their_marks(self):
        f.make_assign(self.klass, self.course, self.teacher)
        student = f.make_student(self.klass, username='pupil')

        student.name = 'Renamed'
        student.save()

        self.assertEqual(
            Marks.objects.filter(studentcourse__student=student).count(), 6)
