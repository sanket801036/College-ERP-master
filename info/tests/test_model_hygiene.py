"""Defaults that pointed nowhere, dates stuck in 2018, and record ages."""
from datetime import date

from django.db import connection
from django.test import TestCase

from info.models import Attendance, AttendanceClass, Marks, Student, Teacher
from info.tests import factories as f


class DefaultsTests(TestCase):
    """Several fields carried defaults that were either wrong or misleading."""

    def test_student_class_has_no_default(self):
        """It defaulted to `1`, but Class uses a CharField primary key - so it
        pointed at a row that could not exist."""
        self.assertFalse(Student._meta.get_field('class_id').has_default())

    def test_teacher_department_has_no_default(self):
        self.assertFalse(Teacher._meta.get_field('dept').has_default())

    def test_attendance_session_has_no_default(self):
        self.assertFalse(
            Attendance._meta.get_field('attendanceclass').has_default())

    def test_attendance_date_has_no_default(self):
        """It defaulted to 2018-10-23, so a row saved without one was silently
        backdated by years."""
        self.assertFalse(Attendance._meta.get_field('date').has_default())

    def test_dates_of_birth_have_no_default(self):
        self.assertFalse(Student._meta.get_field('DOB').has_default())
        self.assertFalse(Teacher._meta.get_field('DOB').has_default())


class UpdatedAtTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        self.course = f.make_course(dept)
        teacher = f.make_teacher(dept, id='t001', username='owner')
        self.assign = f.make_assign(self.klass, self.course, teacher)
        self.student = f.make_student(self.klass, username='pupil')

    def test_saving_a_record_stamps_it(self):
        self.student.phone = '+91 90000 00000'
        self.student.save()

        self.student.refresh_from_db()
        self.assertIsNotNone(self.student.updated_at)

    def test_attendance_and_marks_carry_it_too(self):
        session = AttendanceClass.objects.create(assign=self.assign,
                                                 date=date(2026, 1, 6))
        record = Attendance.objects.create(course=self.course,
                                           student=self.student,
                                           attendanceclass=session,
                                           date=session.date, status=True)
        mark = Marks.objects.filter(studentcourse__student=self.student).first()
        mark.marks1 = 15
        mark.save()

        record.refresh_from_db()
        mark.refresh_from_db()
        self.assertIsNotNone(record.updated_at)
        self.assertIsNotNone(mark.updated_at)

    def test_the_column_is_nullable(self):
        """Rows that predate the column say NULL rather than claiming they
        changed on the day the migration ran."""
        for model in (Student, Teacher, Attendance, Marks):
            with self.subTest(model=model.__name__):
                self.assertTrue(model._meta.get_field('updated_at').null)

    def test_a_queryset_update_does_not_move_it(self):
        """auto_now only fires on save(), which is worth knowing before
        trusting this column after a bulk update."""
        self.student.save()
        self.student.refresh_from_db()
        stamped = self.student.updated_at

        Student.objects.filter(pk=self.student.pk).update(phone='+91 8')

        self.student.refresh_from_db()
        self.assertEqual(self.student.updated_at, stamped)


class MigrationStateTests(TestCase):
    def test_no_model_changes_are_missing_a_migration(self):
        """Catches a field edited without makemigrations - CI checks this too,
        but a failing test says which change was left behind."""
        from django.db.migrations.autodetector import MigrationAutodetector
        from django.db.migrations.executor import MigrationExecutor
        from django.db.migrations.state import ProjectState

        executor = MigrationExecutor(connection)
        autodetector = MigrationAutodetector(
            executor.loader.project_state(), ProjectState.from_apps(
                __import__('django').apps.apps))
        changes = autodetector.changes(graph=executor.loader.graph)

        self.assertEqual(changes.get('info', []), [])
