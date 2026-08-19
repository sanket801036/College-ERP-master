"""Can one student read another student's record by editing the URL?

Every one of these pages takes the USN from the path. The fees page checks
that it belongs to the caller; the others were not checked at all, so this
file exists to state the rule for all of them at once.
"""
from django.urls import reverse

from info.tests import factories as f
from info.tests.test_leave import LeaveBase


class PeerAccessTests(LeaveBase):
    def setUp(self):
        super().setUp()
        self.other = f.make_student(self.klass, usn='1CS20CS002', name='Bala',
                                    username='bala')
        self.client.force_login(self.other.user)

    def urls(self):
        return {
            'attendance': reverse('attendance', args=[self.student.USN]),
            'attendance detail': reverse('attendance_detail',
                                         args=[self.student.USN,
                                               self.course.id]),
            'marks': reverse('marks_list', args=[self.student.USN]),
            'marks card': reverse('marks_card', args=[self.student.USN]),
            'fees': reverse('fees', args=[self.student.USN]),
        }

    def test_a_student_cannot_read_a_classmates_pages(self):
        for label, url in self.urls().items():
            with self.subTest(page=label):
                response = self.client.get(url)
                self.assertIn(response.status_code, (302, 403),
                              '%s returned %s' % (label, response.status_code))

    def test_a_student_can_read_their_own(self):
        self.client.force_login(self.student.user)

        for label, url in self.urls().items():
            with self.subTest(page=label):
                self.assertEqual(self.client.get(url).status_code, 200, label)

    def test_a_teacher_of_the_class_can_read_them(self):
        self.client.force_login(self.teacher.user)

        response = self.client.get(reverse('attendance',
                                           args=[self.student.USN]))

        self.assertEqual(response.status_code, 200)
