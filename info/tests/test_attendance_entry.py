from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from info.models import (
    CLASS_CANCELLED,
    CLASS_PENDING,
    CLASS_TAKEN,
    AssignTime,
    Attendance,
    AttendanceClass,
)
from info.tests import factories as f


class SessionStateTests(TestCase):
    """`status` alone cannot tell a session the teacher owes from one that
    has not happened yet - both are stored as 0."""

    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        course = f.make_course(dept)
        teacher = f.make_teacher(dept, id='t001', username='owner')
        self.assign = f.make_assign(self.klass, course, teacher)
        self.today = timezone.localdate()

    def session(self, days=0, status=CLASS_PENDING):
        return AttendanceClass.objects.create(
            assign=self.assign, date=self.today + timedelta(days=days),
            status=status)

    def test_a_past_unmarked_session_is_pending(self):
        self.assertEqual(self.session(days=-1).state, 'pending')

    def test_todays_unmarked_session_is_pending_not_future(self):
        self.assertEqual(self.session(days=0).state, 'pending')

    def test_a_scheduled_session_is_future(self):
        self.assertEqual(self.session(days=3).state, 'future')

    def test_a_submitted_session_reads_submitted_whenever_it_is(self):
        self.assertEqual(self.session(days=-1, status=CLASS_TAKEN).state,
                         'submitted')

    def test_a_cancelled_session_reads_cancelled(self):
        self.assertEqual(self.session(days=-1, status=CLASS_CANCELLED).state,
                         'cancelled')

    def test_only_past_uncancelled_sessions_are_markable(self):
        self.assertTrue(self.session(days=-1).is_markable)
        self.assertTrue(self.session(days=0).is_markable)
        self.assertFalse(self.session(days=1).is_markable)
        self.assertFalse(self.session(days=-2, status=CLASS_CANCELLED).is_markable)


class MarkingPageTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        self.course = f.make_course(dept)
        self.teacher = f.make_teacher(dept, id='t001', username='owner')
        self.assign = f.make_assign(self.klass, self.course, self.teacher)
        AssignTime.objects.create(assign=self.assign, day='Monday',
                                  period='7:30 - 8:30')
        self.student = f.make_student(self.klass, usn='1CS001', name='Anita',
                                      username='anita')
        self.today = timezone.localdate()
        self.client.force_login(self.teacher.user)

    def session(self, days=0, status=CLASS_PENDING):
        return AttendanceClass.objects.create(
            assign=self.assign, date=self.today + timedelta(days=days),
            status=status)

    def test_the_roster_defaults_everyone_to_present(self):
        """Typical attendance is 80-95% present, so unchecking the absentees is
        far less work than ticking every box."""
        response = self.client.get(
            reverse('t_attendance', args=(self.session(days=-1).id,)))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="present" checked')

    def test_a_future_session_cannot_be_opened_for_marking(self):
        session = self.session(days=3)

        response = self.client.get(reverse('t_attendance', args=(session.id,)))

        self.assertRedirects(
            response, reverse('t_class_date', args=(self.assign.id,)))

    def test_a_cancelled_session_cannot_be_opened_for_marking(self):
        session = self.session(days=-1, status=CLASS_CANCELLED)

        response = self.client.get(reverse('t_attendance', args=(session.id,)))

        self.assertEqual(response.status_code, 302)

    def test_a_future_session_cannot_be_submitted_either(self):
        """The form is unreachable, but the POST endpoint has to refuse on its
        own - nothing stops a hand-built request."""
        session = self.session(days=3)

        response = self.client.post(reverse('confirm', args=(session.id,)),
                                    {self.student.pk: 'absent'})

        self.assertEqual(response.status_code, 302)
        session.refresh_from_db()
        self.assertEqual(session.status, CLASS_PENDING)
        self.assertFalse(Attendance.objects.exists())

    def test_marking_a_past_session_still_works(self):
        session = self.session(days=-1)

        self.client.post(reverse('confirm', args=(session.id,)),
                         {self.student.pk: 'absent'})

        session.refresh_from_db()
        self.assertEqual(session.status, CLASS_TAKEN)
        self.assertFalse(Attendance.objects.get(attendanceclass=session).status)


class SessionListTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        course = f.make_course(dept)
        self.teacher = f.make_teacher(dept, id='t001', username='owner')
        self.assign = f.make_assign(self.klass, course, self.teacher)
        self.today = timezone.localdate()
        self.client.force_login(self.teacher.user)

    def session(self, days=0, status=CLASS_PENDING):
        return AttendanceClass.objects.create(
            assign=self.assign, date=self.today + timedelta(days=days),
            status=status)

    def url(self):
        return reverse('t_class_date', args=(self.assign.id,))

    def test_upcoming_sessions_are_listed(self):
        """Filtered to date__lte=now, a teacher could not see what was coming
        and today's session only appeared once the day was under way."""
        future = self.session(days=5)

        response = self.client.get(self.url())

        self.assertIn(future, list(response.context['att_list']))
        self.assertContains(response, 'Scheduled')

    def test_todays_unmarked_session_is_surfaced(self):
        today = self.session(days=0)

        response = self.client.get(self.url())

        self.assertEqual(response.context['today_session'], today)

    def test_no_call_to_action_once_today_is_marked(self):
        self.session(days=0, status=CLASS_TAKEN)

        response = self.client.get(self.url())

        self.assertIsNone(response.context['today_session'])

    def test_a_cancelled_session_offers_no_marking_link(self):
        """The old list linked "Enter Attendance" on cancelled sessions, which
        the view would now only bounce."""
        cancelled = self.session(days=-1, status=CLASS_CANCELLED)

        response = self.client.get(self.url())

        self.assertNotContains(
            response, reverse('t_attendance', args=(cancelled.id,)))


class CancelClassTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        klass = f.make_class(dept)
        course = f.make_course(dept)
        self.teacher = f.make_teacher(dept, id='t001', username='owner')
        self.assign = f.make_assign(klass, course, self.teacher)
        self.session = AttendanceClass.objects.create(
            assign=self.assign, date=timezone.localdate(), status=CLASS_PENDING)
        self.client.force_login(self.teacher.user)

    def test_cancelling_needs_a_post(self):
        """It was a plain link, so it changed state on a GET - triggerable by
        anything that follows or prefetches a URL."""
        response = self.client.get(
            reverse('cancel_class', args=(self.session.id,)))

        self.assertEqual(response.status_code, 405)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, CLASS_PENDING)

    def test_a_post_cancels_it(self):
        self.client.post(reverse('cancel_class', args=(self.session.id,)))

        self.session.refresh_from_db()
        self.assertEqual(self.session.status, CLASS_CANCELLED)


class TeacherDashboardTodayTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        klass = f.make_class(dept)
        course = f.make_course(dept)
        self.teacher = f.make_teacher(dept, id='t001', username='owner')
        self.assign = f.make_assign(klass, course, self.teacher)
        self.client.force_login(self.teacher.user)

    def test_todays_session_appears_on_the_dashboard(self):
        session = AttendanceClass.objects.create(
            assign=self.assign, date=timezone.localdate(), status=CLASS_PENDING)

        response = self.client.get(reverse('index'))

        self.assertIn(session, list(response.context['todays_sessions']))

    def test_a_marked_session_does_not(self):
        AttendanceClass.objects.create(
            assign=self.assign, date=timezone.localdate(), status=CLASS_TAKEN)

        response = self.client.get(reverse('index'))

        self.assertEqual(list(response.context['todays_sessions']), [])

    def test_yesterdays_session_is_not_offered_as_today(self):
        AttendanceClass.objects.create(
            assign=self.assign,
            date=timezone.localdate() - timedelta(days=1), status=CLASS_PENDING)

        response = self.client.get(reverse('index'))

        self.assertEqual(list(response.context['todays_sessions']), [])
