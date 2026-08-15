from datetime import date

from django.test import TestCase

from info.models import AssignTime, AttendanceClass, AttendanceRange
from info.tests import factories as f


class CreateAttendanceSignalTests(TestCase):
    """Covers the create_attendance signal on AssignTime."""

    def setUp(self):
        dept = f.make_dept()
        self.assign = f.make_assign(
            class_id=f.make_class(dept),
            course=f.make_course(dept),
            teacher=f.make_teacher(dept),
        )

    def test_saves_without_an_attendance_range_configured(self):
        """A fresh install has no AttendanceRange - saving must not blow up.

        This used to raise AttendanceRange.DoesNotExist, so the first timetable
        slot an admin added on a new deployment failed outright.
        """
        self.assertFalse(AttendanceRange.objects.exists())

        AssignTime.objects.create(assign=self.assign, day='Tuesday',
                                  period='8:30 - 9:30')

        self.assertEqual(AttendanceClass.objects.count(), 0)

    def test_generates_one_session_per_matching_weekday(self):
        AttendanceRange.objects.create(start_date=date(2026, 1, 1),
                                       end_date=date(2026, 2, 1))

        AssignTime.objects.create(assign=self.assign, day='Tuesday',
                                  period='8:30 - 9:30')

        sessions = AttendanceClass.objects.filter(assign=self.assign)
        self.assertEqual(sessions.count(), 4)
        for session in sessions:
            self.assertEqual(session.date.isoweekday(), 2, 'expected a Tuesday')

    def test_second_slot_on_the_same_day_does_not_duplicate_sessions(self):
        AttendanceRange.objects.create(start_date=date(2026, 1, 1),
                                       end_date=date(2026, 2, 1))

        AssignTime.objects.create(assign=self.assign, day='Tuesday',
                                  period='8:30 - 9:30')
        AssignTime.objects.create(assign=self.assign, day='Tuesday',
                                  period='9:30 - 10:30')

        self.assertEqual(AttendanceClass.objects.filter(assign=self.assign).count(), 4)
