"""Entering marks over the API.

Attendance could be submitted; marks could not, so a client could see a class
but not finish the job for it.
"""
from django.test import TestCase
from django.urls import reverse

from info.models import AuditLog, Marks, MarksClass, StudentCourse
from info.tests import factories as f


class SubmitMarksTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        self.course = f.make_course(dept)
        self.teacher = f.make_teacher(dept, id='t001', username='owner')
        self.assign = f.make_assign(self.klass, self.course, self.teacher)
        self.asha = f.make_student(self.klass, usn='1CS20CS001', name='Asha',
                                   username='asha')
        self.bhavna = f.make_student(self.klass, usn='1CS20CS002',
                                     name='Bhavna', username='bhavna')
        self.mc = MarksClass.objects.get(assign=self.assign,
                                         name='Internal test 1')
        self.url = '/api/v1/marks/%d/entry/' % self.mc.id
        self.client.force_login(self.teacher.user)

    def _submit(self, marks, absent=None, url=None):
        payload = {'marks': marks}
        if absent is not None:
            payload['absent'] = absent
        return self.client.post(url or self.url, payload,
                                content_type='application/json')

    def _mark(self, student):
        sc = StudentCourse.objects.get(student=student, course=self.course)
        return sc.marks_set.get(name='Internal test 1')

    def test_records_marks_for_the_class(self):
        response = self._submit({self.asha.USN: 17, self.bhavna.USN: 12})

        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertTrue(data['first_entry'])
        self.assertEqual(data['students'], 2)

        self.assertEqual(self._mark(self.asha).marks1, 17)
        self.assertEqual(self._mark(self.bhavna).marks1, 12)
        self.mc.refresh_from_db()
        self.assertTrue(self.mc.status)

    def test_an_absentee_scores_zero_but_is_recorded_as_absent(self):
        """Zero towards the CIE is how the scheme works, but the record says
        which of the two it was."""
        self._submit({self.asha.USN: 17}, absent=[self.bhavna.USN])

        mark = self._mark(self.bhavna)
        self.assertEqual(mark.marks1, 0)
        self.assertTrue(mark.is_absent)
        self.assertFalse(self._mark(self.asha).is_absent)

    def test_a_mark_over_the_ceiling_is_rejected(self):
        """An internal is out of 20 and nothing else enforces it - model
        validators do not run on a plain .save()."""
        response = self._submit({self.asha.USN: 85, self.bhavna.USN: 12})

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Marks.objects.filter(marks1=12).exists())

    def test_a_negative_mark_is_rejected(self):
        response = self._submit({self.asha.USN: -5, self.bhavna.USN: 12})

        self.assertEqual(response.status_code, 400)

    def test_the_ceiling_follows_the_component(self):
        """The semester-end paper is out of 100, so 85 is fine there."""
        see = MarksClass.objects.get(assign=self.assign,
                                     name='Semester End Exam')

        response = self._submit({self.asha.USN: 85, self.bhavna.USN: 40},
                                url='/api/v1/marks/%d/entry/' % see.id)

        self.assertEqual(response.status_code, 200)

    def test_a_partial_submission_is_rejected(self):
        """Flagging the batch submitted with holes in it is what the "not yet
        conducted" state exists to prevent."""
        response = self._submit({self.asha.USN: 17})

        self.assertEqual(response.status_code, 400)
        self.mc.refresh_from_db()
        self.assertFalse(self.mc.status)

    def test_a_student_listed_twice_is_rejected(self):
        response = self._submit({self.asha.USN: 17, self.bhavna.USN: 10},
                                absent=[self.bhavna.USN])

        self.assertEqual(response.status_code, 400)

    def test_a_usn_from_another_class_is_rejected(self):
        other = f.make_class(self.klass.dept, id='CS-3B', section='B')
        stranger = f.make_student(other, usn='9CS20CS999', name='Stranger',
                                  username='stranger')

        response = self._submit({self.asha.USN: 17, self.bhavna.USN: 10,
                                 stranger.USN: 15})

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Marks.objects.filter(marks1=17).exists())

    def test_revising_logs_what_changed(self):
        self._submit({self.asha.USN: 12, self.bhavna.USN: 12})

        response = self._submit({self.asha.USN: 18, self.bhavna.USN: 12})

        data = response.json()['data']
        self.assertFalse(data['first_entry'])
        self.assertEqual(data['changed'], 1)
        entry = AuditLog.objects.get(action='marks.changed')
        self.assertEqual(entry.changes['marks1'], {'from': 12, 'to': 18})

    def test_another_teacher_cannot_enter_marks(self):
        stranger = f.make_teacher(self.klass.dept, id='t002', name='Stranger',
                                  username='stranger_t')
        self.client.force_login(stranger.user)

        response = self._submit({self.asha.USN: 17, self.bhavna.USN: 12})

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Marks.objects.filter(marks1=17).exists())

    def test_a_student_cannot_enter_marks(self):
        self.client.force_login(self.asha.user)

        response = self._submit({self.asha.USN: 20, self.bhavna.USN: 20})

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Marks.objects.filter(marks1=20).exists())

    def test_an_unauthenticated_caller_is_rejected(self):
        self.client.logout()

        self.assertEqual(
            self._submit({self.asha.USN: 1, self.bhavna.USN: 1}).status_code,
            401)


class SharedMarksRulesTests(TestCase):
    """The entry form and the API go through the same service."""

    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        self.course = f.make_course(dept)
        self.teacher = f.make_teacher(dept, id='t001', username='owner')
        self.assign = f.make_assign(self.klass, self.course, self.teacher)
        self.student = f.make_student(self.klass, usn='1CS20CS001',
                                      username='pupil')
        self.client.force_login(self.teacher.user)

    def test_both_routes_write_the_same_record_and_audit_entry(self):
        first = MarksClass.objects.get(assign=self.assign,
                                       name='Internal test 1')
        second = MarksClass.objects.get(assign=self.assign,
                                        name='Internal test 2')

        self.client.post(reverse('marks_confirm', args=(first.id,)),
                         {self.student.USN: '15'})
        self.client.post('/api/v1/marks/%d/entry/' % second.id,
                         {'marks': {self.student.USN: 15}},
                         content_type='application/json')

        sc = StudentCourse.objects.get(student=self.student, course=self.course)
        self.assertEqual(sc.marks_set.get(name='Internal test 1').marks1, 15)
        self.assertEqual(sc.marks_set.get(name='Internal test 2').marks1, 15)
        self.assertEqual(
            AuditLog.objects.filter(action='marks.entered').count(), 2)

    def test_both_routes_refuse_a_mark_over_the_ceiling(self):
        mc = MarksClass.objects.get(assign=self.assign, name='Internal test 1')

        form = self.client.post(reverse('marks_confirm', args=(mc.id,)),
                                {self.student.USN: '85'})
        api = self.client.post('/api/v1/marks/%d/entry/' % mc.id,
                               {'marks': {self.student.USN: 85}},
                               content_type='application/json')

        self.assertEqual(form.status_code, 200)  # re-rendered with errors
        self.assertEqual(api.status_code, 400)
        self.assertFalse(Marks.objects.filter(marks1=85).exists())
