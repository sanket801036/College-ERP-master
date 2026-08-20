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

    def test_the_bell_is_not_empty_on_a_fresh_demo(self):
        self.assertTrue(Notification.objects.unread().exists())

    def test_running_it_twice_refuses_rather_than_doubling_everything(self):
        before = Student.objects.count()

        output = StringIO()
        call_command('seed_demo', stdout=output)

        self.assertIn('already has students', output.getvalue())
        self.assertEqual(Student.objects.count(), before)
