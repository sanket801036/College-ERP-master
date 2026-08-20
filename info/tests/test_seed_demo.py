"""The demo seed.

This is what somebody sees when they open the deployed link, so an empty queue
or a missing certificate is not a cosmetic problem - it is the difference
between a demo that shows the app working and one that shows empty tables.

The command is slow enough (it marks a term of attendance) that this file runs
it once for the whole class rather than per test.
"""
import shutil
import tempfile
from io import StringIO

from django.contrib.auth import authenticate, get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings

from info.models import (
    LEAVE_APPROVED,
    LEAVE_OPEN,
    QUERY_ACCEPTED,
    QUERY_OPEN,
    Attendance,
    AttendanceCorrection,
    LeaveRequest,
    MarkQuery,
    MarksClass,
    Notification,
    Student,
)

User = get_user_model()

MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=MEDIA)
class SeedDemoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        with override_settings(MEDIA_ROOT=MEDIA):
            cls.output = StringIO()
            call_command('seed_demo', stdout=cls.output)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA, ignore_errors=True)
        super().tearDownClass()

    def test_it_builds_a_class_with_history(self):
        self.assertEqual(Student.objects.count(), 12)
        self.assertTrue(Attendance.objects.exists())

    def test_it_prints_credentials_to_sign_in_with(self):
        self.assertIn('USERNAME', self.output.getvalue())
        self.assertIn('teacher', self.output.getvalue())

    def test_marks_are_released_so_a_student_can_see_them(self):
        published = MarksClass.objects.filter(is_published=True)

        self.assertTrue(published.exists())
        self.assertTrue(all(mc.name == 'Internal test 1' for mc in published))

    def test_every_queue_has_something_answered_and_something_waiting(self):
        # A queue with nothing in it demonstrates nothing.
        for model in (MarkQuery, LeaveRequest, AttendanceCorrection):
            with self.subTest(model=model.__name__):
                self.assertTrue(model.objects.filter(status=QUERY_OPEN).exists()
                                or model.objects.filter(status=LEAVE_OPEN).exists())
                self.assertTrue(model.objects.exclude(status=QUERY_OPEN)
                                .exclude(status=LEAVE_OPEN).exists())

    def test_an_accepted_query_actually_moved_a_mark(self):
        query = MarkQuery.objects.filter(status=QUERY_ACCEPTED).first()

        self.assertIsNotNone(query)
        self.assertEqual(query.marks.marks1, query.mark_after)
        self.assertGreater(query.mark_after, query.mark_before)

    def test_approved_leave_left_a_certificate_in_storage(self):
        leave = LeaveRequest.objects.filter(status=LEAVE_APPROVED).get()

        self.assertTrue(leave.document.name.endswith('.pdf'))
        # Opening it is the part that proves the file reached storage rather
        # than only the database row being written.
        with leave.document.open('rb') as handle:
            self.assertTrue(handle.read(4).startswith(b'%PDF'))

    def test_the_approved_leave_actually_excused_something(self):
        leave = LeaveRequest.objects.filter(status=LEAVE_APPROVED).get()

        # An approval that excused nothing reads as the feature not working.
        self.assertGreaterEqual(leave.sessions_excused, 1)
        self.assertIn('excused', leave.outcome)
        self.assertTrue(
            Attendance.objects.filter(student=leave.student,
                                      is_excused=True).exists())

    def test_the_bell_is_not_empty_on_a_fresh_demo(self):
        self.assertTrue(Notification.objects.unread().exists())

    def test_demo_logins_are_off_unless_asked_for(self):
        # The published passwords are weak on purpose; nothing should create
        # them without being told to.
        self.assertNotIn('admin12345', self.output.getvalue())

    def test_running_it_twice_refuses_rather_than_doubling_everything(self):
        before = Student.objects.count()

        output = StringIO()
        call_command('seed_demo', stdout=output)

        self.assertIn('already has students', output.getvalue())
        self.assertEqual(Student.objects.count(), before)


@override_settings(MEDIA_ROOT=MEDIA)
class DemoLoginTests(TestCase):
    """The three accounts the portfolio page advertises."""

    @classmethod
    def setUpTestData(cls):
        with override_settings(MEDIA_ROOT=MEDIA):
            call_command('seed_demo', '--demo-logins', stdout=StringIO())

    def test_all_three_can_sign_in(self):
        for username, password in [('admin', 'admin12345'),
                                   ('teststud', 'testpass123'),
                                   ('testteach', 'testpass123')]:
            with self.subTest(user=username):
                self.assertIsNotNone(authenticate(username=username,
                                                  password=password))

    def test_they_land_on_their_own_role(self):
        admin = User.objects.get(username='admin')
        student = User.objects.get(username='teststud')
        teacher = User.objects.get(username='testteach')

        self.assertTrue(admin.is_superuser)
        self.assertTrue(student.is_student)
        self.assertTrue(teacher.is_teacher)

    def test_the_demo_student_has_a_populated_record(self):
        # Attached to somebody the seed already built, so signing in shows a
        # term of attendance rather than an empty shell.
        student = User.objects.get(username='teststud').student

        self.assertTrue(student.attendance_set.exists()
                        if hasattr(student, 'attendance_set')
                        else Attendance.objects.filter(student=student).exists())

    def test_nobody_is_met_by_the_change_password_screen(self):
        for username in ('admin', 'teststud', 'testteach'):
            with self.subTest(user=username):
                self.assertFalse(
                    User.objects.get(username=username).must_change_password)

    def test_the_replaced_login_does_not_linger(self):
        # The seeded student had their own random-password account; two logins
        # pointing at one student is not a state worth having.
        self.assertEqual(
            User.objects.filter(student__isnull=False).count(),
            Student.objects.filter(user__isnull=False).count())
