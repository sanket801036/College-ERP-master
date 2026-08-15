"""Custom error pages.

With DEBUG=False these are what users actually see, and the app raises 403 in
a fair number of places now that the teacher views check roles and ownership.
"""
from django.test import TestCase, override_settings

from info.tests import factories as f


@override_settings(DEBUG=False, ALLOWED_HOSTS=['testserver'])
class ErrorPageTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        klass = f.make_class(dept)
        self.student = f.make_student(klass, username='pupil')
        teacher = f.make_teacher(dept, id='t001', username='owner')
        self.assign = f.make_assign(klass, f.make_course(dept), teacher)

    def test_404_uses_the_custom_template(self):
        response = self.client.get('/no-such-page/')

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "That page doesn't exist",
                            status_code=404)

    def test_403_uses_the_custom_template(self):
        """A student hitting a teacher view gets an explanation rather than
        Django's bare default page."""
        self.client.force_login(self.student.user)

        response = self.client.get('/teacher/%d/Report/' % self.assign.id)

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "You don't have access to this page",
                            status_code=403)

    def test_error_pages_link_back_to_the_dashboard(self):
        response = self.client.get('/no-such-page/')

        self.assertContains(response, 'Back to dashboard', status_code=404)
