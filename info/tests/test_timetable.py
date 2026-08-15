from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from info.models import AssignTime
from info.tests import factories as f


class TimetableClashTests(TestCase):
    def setUp(self):
        self.dept = f.make_dept()
        self.klass = f.make_class(self.dept)
        self.teacher = f.make_teacher(self.dept, id='t001', username='owner')
        self.maths = f.make_course(self.dept, id='CS101', name='Maths', shortname='MA')
        self.physics = f.make_course(self.dept, id='CS102', name='Physics', shortname='PH')
        self.assign_maths = f.make_assign(self.klass, self.maths, self.teacher)
        AssignTime.objects.create(assign=self.assign_maths, day='Monday',
                                  period='7:30 - 8:30')

    def test_two_courses_for_one_class_in_the_same_slot_is_rejected(self):
        """This is what made the timetable page 500.

        Nothing stopped a class being scheduled for two courses at once, and the
        page's .get() then raised MultipleObjectsReturned - caught nowhere,
        because only DoesNotExist was handled.
        """
        clashing = AssignTime(
            assign=f.make_assign(self.klass, self.physics, self.teacher),
            day='Monday', period='7:30 - 8:30')

        with self.assertRaises(ValidationError):
            clashing.full_clean()

    def test_a_teacher_cannot_be_in_two_places_at_once(self):
        other_class = f.make_class(self.dept, id='CS-3B', section='B')
        clashing = AssignTime(
            assign=f.make_assign(other_class, self.physics, self.teacher),
            day='Monday', period='7:30 - 8:30')

        with self.assertRaises(ValidationError):
            clashing.full_clean()

    def test_exact_duplicate_is_rejected_by_the_database(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AssignTime.objects.create(assign=self.assign_maths, day='Monday',
                                          period='7:30 - 8:30')

    def test_a_free_slot_is_accepted(self):
        slot = AssignTime(
            assign=f.make_assign(self.klass, self.physics, self.teacher),
            day='Monday', period='8:30 - 9:30')

        slot.full_clean()  # must not raise
        slot.save()

        self.assertEqual(AssignTime.objects.count(), 2)

    def test_editing_a_slot_does_not_clash_with_itself(self):
        slot = AssignTime.objects.get(assign=self.assign_maths)

        slot.full_clean()  # must not raise


class TimetableRenderTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        self.teacher = f.make_teacher(dept, id='t001', username='owner')
        self.student = f.make_student(self.klass, username='pupil')
        course = f.make_course(dept)
        self.assign = f.make_assign(self.klass, course, self.teacher)
        AssignTime.objects.create(assign=self.assign, day='Monday',
                                  period='7:30 - 8:30')
        AssignTime.objects.create(assign=self.assign, day='Wednesday',
                                  period='2:30 - 3:30')

    def test_student_timetable_renders_the_grid(self):
        self.client.force_login(self.student.user)

        response = self.client.get(reverse('timetable', args=(self.klass.pk,)))

        self.assertEqual(response.status_code, 200)
        matrix = response.context['matrix']
        self.assertEqual(len(matrix), 6, 'one row per weekday')
        self.assertEqual(len(matrix[0]), 12, 'day label + 9 periods + 2 breaks')
        self.assertEqual(matrix[0][0], 'Monday')
        self.assertEqual(matrix[0][1], self.assign.course_id)
        self.assertEqual(matrix[0][4], '', 'column 4 is the morning break')

    def test_timetable_costs_a_fixed_number_of_queries(self):
        """Was a .get() per cell: 54 queries whether or not anything was
        scheduled, every empty one raising DoesNotExist."""
        self.client.force_login(self.student.user)
        url = reverse('timetable', args=(self.klass.pk,))

        with self.assertNumQueries(6):
            self.assertEqual(self.client.get(url).status_code, 200)

    def test_teacher_timetable_renders(self):
        self.client.force_login(self.teacher.user)

        response = self.client.get(reverse('t_timetable', args=(self.teacher.pk,)))

        self.assertEqual(response.status_code, 200)
        matrix = response.context['class_matrix']
        self.assertEqual(matrix[0][0], 'Monday')
        self.assertEqual(matrix[0][1].assign_id, self.assign.id)
        self.assertIs(matrix[0][2], True, 'empty teacher cells stay True')
