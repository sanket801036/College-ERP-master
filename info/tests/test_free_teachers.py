from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse

from info.models import AssignTime, AttendanceClass
from info.tests import factories as f
from info.views import _next_weekday


class NextWeekdayTests(TestCase):
    """A slot is a recurring weekday; a cancellation belongs to one date."""

    def test_returns_the_coming_occurrence(self):
        monday = date(2026, 8, 17)

        self.assertEqual(_next_weekday('Wednesday', today=monday), date(2026, 8, 19))

    def test_today_counts_as_the_next_occurrence(self):
        monday = date(2026, 8, 17)

        self.assertEqual(_next_weekday('Monday', today=monday), monday)

    def test_wraps_into_the_following_week(self):
        wednesday = date(2026, 8, 19)

        self.assertEqual(_next_weekday('Monday', today=wednesday), date(2026, 8, 24))

    def test_unknown_day_gives_none(self):
        self.assertIsNone(_next_weekday('Sunday'))


class FreeTeachersTests(TestCase):
    def setUp(self):
        self.cs = f.make_dept()
        self.ec = f.make_dept(id='EC', name='Electronics')
        self.klass = f.make_class(self.cs)
        self.maths = f.make_course(self.cs, id='CS101', name='Maths', shortname='MA')
        self.physics = f.make_course(self.cs, id='CS102', name='Physics', shortname='PH')

        # Teaches the class in the slot we are looking to cover.
        self.owner = f.make_teacher(self.cs, id='t001', name='Owner', username='owner')
        self.assign = f.make_assign(self.klass, self.maths, self.owner)
        self.slot = AssignTime.objects.create(assign=self.assign, day='Monday',
                                              period='7:30 - 8:30')

        # Teaches nothing at all - the obvious substitute, and the case the old
        # class-scoped query could never return.
        self.outsider = f.make_teacher(self.ec, id='t002', name='Outsider',
                                       username='outsider')

    def url(self):
        return reverse('free_teachers', args=(self.slot.id,))

    def test_finds_a_teacher_from_outside_the_class(self):
        """The point of the page.

        The candidate pool was filtered to teachers already teaching this
        class, so the one person actually available never appeared.
        """
        self.client.force_login(self.owner.user)

        response = self.client.get(self.url())

        self.assertEqual(response.status_code, 200)
        self.assertIn(self.outsider, response.context['ft_list'])

    def test_a_teacher_busy_in_that_slot_is_excluded(self):
        other_class = f.make_class(self.cs, id='CS-3B', section='B')
        AssignTime.objects.create(
            assign=f.make_assign(other_class, self.physics, self.outsider),
            day='Monday', period='7:30 - 8:30')
        self.client.force_login(self.owner.user)

        response = self.client.get(self.url())

        self.assertNotIn(self.outsider, response.context['ft_list'])

    def test_a_teacher_busy_in_a_different_slot_is_still_free(self):
        other_class = f.make_class(self.cs, id='CS-3B', section='B')
        AssignTime.objects.create(
            assign=f.make_assign(other_class, self.physics, self.outsider),
            day='Monday', period='8:30 - 9:30')
        self.client.force_login(self.owner.user)

        response = self.client.get(self.url())

        self.assertIn(self.outsider, response.context['ft_list'])

    def test_the_slots_own_teacher_is_not_offered(self):
        self.client.force_login(self.owner.user)

        response = self.client.get(self.url())

        self.assertNotIn(self.owner, response.context['ft_list'])

    def test_a_teacher_appears_once_when_they_take_two_courses_for_the_class(self):
        """Filtering Teacher across the assign join returned a row per Assign."""
        f.make_assign(self.klass, self.physics, self.outsider)
        f.make_assign(self.klass, self.maths, self.outsider)
        self.client.force_login(self.owner.user)

        response = self.client.get(self.url())

        names = [t.pk for t in response.context['ft_list']]
        self.assertEqual(names.count(self.outsider.pk), 1)

    def test_a_cancelled_session_frees_its_teacher(self):
        """Availability came from the static timetable only, so a teacher whose
        class was cancelled still counted as busy."""
        other_class = f.make_class(self.cs, id='CS-3B', section='B')
        busy_assign = f.make_assign(other_class, self.physics, self.outsider)
        AssignTime.objects.create(assign=busy_assign, day='Monday',
                                  period='7:30 - 8:30')
        AttendanceClass.objects.create(
            assign=busy_assign, date=_next_weekday('Monday'), status=2)
        self.client.force_login(self.owner.user)

        response = self.client.get(self.url())

        self.assertIn(self.outsider, response.context['ft_list'])

    def test_a_cancellation_on_another_date_does_not_free_them(self):
        other_class = f.make_class(self.cs, id='CS-3B', section='B')
        busy_assign = f.make_assign(other_class, self.physics, self.outsider)
        AssignTime.objects.create(assign=busy_assign, day='Monday',
                                  period='7:30 - 8:30')
        AttendanceClass.objects.create(
            assign=busy_assign,
            date=_next_weekday('Monday') + timedelta(days=7), status=2)
        self.client.force_login(self.owner.user)

        response = self.client.get(self.url())

        self.assertNotIn(self.outsider, response.context['ft_list'])

    def test_query_count_does_not_grow_with_the_number_of_teachers(self):
        """Availability was decided in Python, one query per candidate."""
        self.client.force_login(self.owner.user)

        with self.assertNumQueries(9):
            self.assertEqual(self.client.get(self.url()).status_code, 200)

        for n in range(10):
            f.make_teacher(self.cs, id='extra%d' % n, name='Extra %d' % n,
                           username='extra%d' % n)

        with self.assertNumQueries(9):
            self.assertEqual(self.client.get(self.url()).status_code, 200)

    def test_a_student_cannot_open_it(self):
        student = f.make_student(self.klass, username='pupil')
        self.client.force_login(student.user)

        response = self.client.get(self.url())

        self.assertNotEqual(response.status_code, 200)
