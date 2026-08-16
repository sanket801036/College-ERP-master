from django.test import TestCase
from django.urls import reverse

from info.models import Marks, MarksClass, StudentCourse
from info.tests import factories as f
from info.views import _previous_component


class PreviousComponentTests(TestCase):
    def test_the_component_before_this_one(self):
        self.assertEqual(_previous_component('Internal test 2'),
                         'Internal test 1')

    def test_the_first_component_has_nothing_before_it(self):
        self.assertIsNone(_previous_component('Internal test 1'))

    def test_the_semester_end_exam_follows_the_last_event(self):
        self.assertEqual(_previous_component('Semester End Exam'), 'Event 2')


class MarksEntryPageTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        self.course = f.make_course(dept)
        self.teacher = f.make_teacher(dept, id='t001', username='owner')
        self.assign = f.make_assign(self.klass, self.course, self.teacher)
        self.anita = f.make_student(self.klass, usn='1CS002', name='Anita',
                                    username='anita')
        self.bharat = f.make_student(self.klass, usn='1CS001', name='Bharat',
                                     username='bharat')
        self.mc = MarksClass.objects.get(assign=self.assign,
                                         name='Internal test 2')
        self.client.force_login(self.teacher.user)

    def url(self, **params):
        base = reverse('t_marks_entry', args=(self.mc.id,))
        return base + ('?' + '&'.join('%s=%s' % kv for kv in params.items())
                       if params else '')

    def score(self, student, name, marks):
        sc = StudentCourse.objects.get(student=student, course=self.course)
        Marks.objects.update_or_create(studentcourse=sc, name=name,
                                       defaults={'marks1': marks})

    def test_inputs_start_blank_not_at_zero(self):
        """A pre-filled 0 is indistinguishable from a mark of 0, so a student
        the teacher scrolled past was recorded as having scored nothing."""
        response = self.client.get(self.url())

        self.assertEqual(response.status_code, 200)
        for row in response.context['rows']:
            self.assertEqual(row['value'], '')

    def test_the_previous_component_is_shown_for_context(self):
        """Seeing Internal test 1 beside Internal test 2 is how a transposed
        row gets caught at entry time."""
        self.score(self.anita, 'Internal test 1', 17)

        response = self.client.get(self.url())

        self.assertEqual(response.context['previous_name'], 'Internal test 1')
        by_usn = {r['student'].pk: r['previous'] for r in response.context['rows']}
        self.assertEqual(by_usn[self.anita.pk], 17)

    def test_the_first_component_shows_no_previous_column(self):
        first = MarksClass.objects.get(assign=self.assign,
                                       name='Internal test 1')

        response = self.client.get(reverse('t_marks_entry', args=(first.id,)))

        self.assertIsNone(response.context['previous_name'])

    def test_the_roster_sorts_by_name_by_default(self):
        response = self.client.get(self.url())

        self.assertEqual([r['student'].name for r in response.context['rows']],
                         ['Anita', 'Bharat'])

    def test_the_roster_can_sort_by_usn(self):
        response = self.client.get(self.url(sort='usn'))

        self.assertEqual([r['student'].pk for r in response.context['rows']],
                         ['1CS001', '1CS002'])

    def test_the_max_is_shown_beside_the_input(self):
        response = self.client.get(self.url())

        self.assertContains(response, '/ %d' % self.mc.total_marks)


class MarksEditTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        self.course = f.make_course(dept)
        self.teacher = f.make_teacher(dept, id='t001', username='owner')
        self.assign = f.make_assign(self.klass, self.course, self.teacher)
        self.student = f.make_student(self.klass, usn='1CS001', name='Anita',
                                      username='anita')
        self.mc = MarksClass.objects.get(assign=self.assign,
                                         name='Internal test 1')
        self.mc.status = True
        self.mc.save()
        self.client.force_login(self.teacher.user)

    def url(self):
        return reverse('edit_marks', args=(self.mc.id,))

    def test_editing_prefills_the_existing_marks(self):
        sc = StudentCourse.objects.get(student=self.student, course=self.course)
        Marks.objects.update_or_create(studentcourse=sc, name=self.mc.name,
                                       defaults={'marks1': 14})

        response = self.client.get(self.url())

        self.assertEqual(response.context['rows'][0]['value'], 14)
        self.assertTrue(response.context['is_revision'])

    def test_a_missing_studentcourse_row_does_not_take_down_the_page(self):
        """It walked the roster with bare .get() calls, so one missing row
        raised DoesNotExist and 500'd the page for the whole class."""
        StudentCourse.objects.filter(student=self.student).delete()

        response = self.client.get(self.url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['rows'][0]['value'], '')

    def test_a_missing_marks_row_does_not_take_down_the_page(self):
        sc = StudentCourse.objects.get(student=self.student, course=self.course)
        sc.marks_set.filter(name=self.mc.name).delete()

        response = self.client.get(self.url())

        self.assertEqual(response.status_code, 200)

    def test_editing_and_entry_share_one_template(self):
        """The edit template had no error display, so a failed edit rendered
        the other one and the teacher lost their place."""
        response = self.client.get(self.url())

        self.assertTemplateUsed(response, 'info/t_marks_entry.html')

    def test_a_validation_error_re_renders_with_the_entered_values(self):
        response = self.client.post(
            reverse('marks_confirm', args=(self.mc.id,)),
            {self.student.pk: '85'})

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'info/t_marks_entry.html')
        self.assertEqual(response.context['rows'][0]['value'], '85')
        self.assertTrue(response.context['rows'][0]['errors'])
        self.assertFalse(
            Marks.objects.filter(name=self.mc.name, marks1=85).exists())
