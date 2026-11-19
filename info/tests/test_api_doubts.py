"""Handing a question to a teacher over the API.

The same rules as the assistant page - the form validates, rag.escalate
enforces the cap - reached by a client that runs its own assistant.
"""
from django.test import TestCase
from rest_framework.authtoken.models import Token

from info.models import MAX_OPEN_ESCALATIONS, AssistantEscalation, Notification
from info.tests import factories as f

URL = '/api/v1/doubts/'


class DoubtsApiTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        self.course = f.make_course(dept)
        self.teacher = f.make_teacher(dept, id='t001', username='owner')
        f.make_assign(self.klass, self.course, self.teacher)
        self.student = f.make_student(self.klass, username='pupil')
        self.auth = {'HTTP_AUTHORIZATION': 'Token %s'
                     % Token.objects.create(user=self.student.user).key}

    def _post(self, **data):
        return self.client.post(URL, data, content_type='application/json',
                                **self.auth)

    def test_a_question_reaches_the_teachers_with_what_the_student_was_told(self):
        response = self._post(question='Can I sit the exam on 70% attendance?',
                              assistant_said='The handbook does not cover this.',
                              course_id=self.course.pk)

        self.assertEqual(response.status_code, 201)
        doubt = AssistantEscalation.objects.get()
        self.assertEqual(doubt.student, self.student)
        self.assertEqual(doubt.course, self.course)
        self.assertEqual(doubt.assistant_said, 'The handbook does not cover this.')
        self.assertEqual(response.json()['data']['outcome'], 'Waiting for a teacher')
        self.assertTrue(Notification.objects.filter(user=self.teacher.user).exists())

    def test_the_course_is_optional(self):
        response = self._post(question='When does the library close on Saturday?')

        self.assertEqual(response.status_code, 201)
        self.assertIsNone(AssistantEscalation.objects.get().course)

    def test_a_one_word_question_is_refused(self):
        response = self._post(question='help')

        self.assertEqual(response.status_code, 400)
        self.assertIn('question', response.json()['errors'])
        self.assertFalse(AssistantEscalation.objects.exists())

    def test_a_course_off_the_timetable_is_refused(self):
        other = f.make_course(f.make_dept(id='ME', name='Mechanical'), id='ME101')

        response = self._post(question='What is on the syllabus?', course_id=other.pk)

        self.assertEqual(response.status_code, 400)
        self.assertIn('course', response.json()['errors'])

    def test_the_open_question_cap_holds(self):
        for i in range(MAX_OPEN_ESCALATIONS):
            self.assertEqual(self._post(question='Question number %d here' % i)
                             .status_code, 201)

        response = self._post(question='One question too many')

        self.assertEqual(response.status_code, 409)
        self.assertEqual(AssistantEscalation.objects.count(), MAX_OPEN_ESCALATIONS)

    def test_the_list_holds_only_the_callers_own(self):
        other = f.make_student(self.klass, usn='1CS20CS002', username='other')
        AssistantEscalation.objects.create(student=other, question='Not yours at all')
        self._post(question='Mine, and only mine')

        data = self.client.get(URL, **self.auth).json()['data']

        self.assertEqual([d['question'] for d in data], ['Mine, and only mine'])

    def test_a_teacher_has_no_student_record_to_raise_one_against(self):
        auth = {'HTTP_AUTHORIZATION': 'Token %s'
                % Token.objects.create(user=self.teacher.user).key}

        response = self.client.post(URL, {'question': 'From the staff room'},
                                    content_type='application/json', **auth)

        self.assertEqual(response.status_code, 404)

    def test_signed_out_gets_401(self):
        self.assertEqual(self.client.get(URL).status_code, 401)
