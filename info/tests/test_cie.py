from django.test import TestCase

from info.models import StudentCourse
from info.tests import factories as f


class CieTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        klass = f.make_class(dept)
        self.course = f.make_course(dept)
        teacher = f.make_teacher(dept, id='t001', username='owner')
        f.make_assign(klass, self.course, teacher)
        self.student = f.make_student(klass, username='pupil')
        self.sc = StudentCourse.objects.get(student=self.student,
                                            course=self.course)

    def _set(self, **marks):
        for name, value in marks.items():
            self.sc.marks_set.filter(name=name.replace('_', ' ')).update(marks1=value)

    def test_cie_is_half_the_five_internal_components(self):
        self._set(**{'Internal test 1': 18, 'Internal test 2': 16,
                     'Internal test 3': 14, 'Event 1': 20, 'Event 2': 12})

        self.assertEqual(self.sc.get_cie(), 40)

    def test_semester_end_exam_is_excluded(self):
        """get_cie() summed 'the first five' rows of an unordered queryset.

        Marks has no Meta.ordering, so the database was free to return the SEE
        row inside that window - counting a mark out of 100 as an internal and
        dropping a real one, with no error anywhere.
        """
        self._set(**{'Internal test 1': 10, 'Internal test 2': 10,
                     'Internal test 3': 10, 'Event 1': 10, 'Event 2': 10})
        self.sc.marks_set.filter(name='Semester End Exam').update(marks1=100)

        self.assertEqual(self.sc.get_cie(), 25)

    def test_cie_when_nothing_has_been_entered(self):
        self.assertEqual(self.sc.get_cie(), 0)

    def test_attendance_without_a_total_row_returns_zero(self):
        """Was a bare .get(), so a missing row raised DoesNotExist and took the
        class report down with it."""
        self.assertEqual(self.sc.get_attendance(), 0)
