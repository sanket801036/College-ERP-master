from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from info.models import SupportRequest
from info.tests import factories as f
from info.views import REMEMBER_ME_SECONDS


class LoginPageTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        klass = f.make_class(dept)
        self.student = f.make_student(klass, username='pupil',
                                      password='pass12345')
        self.teacher = f.make_teacher(dept, id='t001', username='staff',
                                      password='pass12345')
        self.admin = f.make_admin(username='boss', password='pass12345')
        self.url = reverse('login')

    def _post(self, username, role, password='pass12345', **extra):
        data = {'username': username, 'password': password, 'role': role}
        data.update(extra)
        return self.client.post(self.url, data)

    def test_page_offers_the_three_roles(self):
        response = self.client.get(self.url)

        self.assertContains(response, 'Student')
        self.assertContains(response, 'Faculty')
        self.assertContains(response, 'Admin')

    def test_each_role_signs_in_from_its_own_tab(self):
        for username, role in [('pupil', 'student'), ('staff', 'teacher'),
                               ('boss', 'admin')]:
            with self.subTest(role=role):
                self.client.logout()
                response = self._post(username, role)
                self.assertEqual(response.status_code, 302)

    def test_signing_in_from_the_wrong_tab_says_so(self):
        """Rather than silently landing on the student dashboard and leaving
        the person to work out what happened."""
        response = self._post('pupil', 'admin')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'not registered as Admin')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_a_wrong_password_does_not_reveal_the_role(self):
        response = self._post('pupil', 'student', password='wrong')

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_remember_me_extends_the_session(self):
        self._post('pupil', 'student', remember_me='on')

        self.assertEqual(self.client.session.get_expiry_age(),
                         REMEMBER_ME_SECONDS)

    def test_without_remember_me_the_session_ends_with_the_browser(self):
        self._post('pupil', 'student')

        self.assertTrue(self.client.session.get_expire_at_browser_close())

    def test_the_page_has_a_password_toggle_and_a_support_link(self):
        response = self.client.get(self.url)

        self.assertContains(response, 'togglePassword')
        self.assertContains(response, 'Contact Administrator')
        self.assertContains(response, 'Forgot password?')


class SupportRequestTests(TestCase):
    def setUp(self):
        cache.clear()
        self.url = reverse('support_request')

    def _payload(self, **overrides):
        data = {'name': 'Asha Rao', 'email': 'asha@example.com',
                'category': 'Login issue',
                'message': 'I cannot sign in, it says invalid password.',
                'website': ''}
        data.update(overrides)
        return data

    def test_anyone_can_submit_without_signing_in(self):
        """The people who need this are the ones who cannot log in."""
        response = self.client.post(self.url, self._payload())

        self.assertRedirects(response, reverse('login'))
        request = SupportRequest.objects.get()
        self.assertEqual(request.name, 'Asha Rao')
        self.assertEqual(request.status, 'New')

    def test_a_short_message_is_rejected(self):
        response = self.client.post(self.url, self._payload(message='help'))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(SupportRequest.objects.exists())

    def test_an_invalid_email_is_rejected(self):
        response = self.client.post(self.url, self._payload(email='nope'))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(SupportRequest.objects.exists())

    def test_the_honeypot_blocks_automated_submissions(self):
        response = self.client.post(self.url,
                                    self._payload(website='http://spam.example'))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(SupportRequest.objects.exists())

    def test_submissions_are_rate_limited(self):
        for _ in range(3):
            self.client.post(self.url, self._payload())

        response = self.client.post(self.url, self._payload())

        self.assertEqual(SupportRequest.objects.count(), 3)
        self.assertContains(response, 'Too many messages')

    def test_get_redirects_to_login(self):
        self.assertRedirects(self.client.get(self.url), reverse('login'))

    def test_resolving_a_request_stamps_the_time(self):
        request = SupportRequest.objects.create(
            name='A', email='a@example.com', message='x' * 20)
        self.assertIsNone(request.resolved_at)

        request.status = 'Resolved'
        request.save()

        self.assertIsNotNone(request.resolved_at)

    def test_admin_dashboard_flags_unresolved_requests(self):
        SupportRequest.objects.create(name='A', email='a@example.com',
                                      message='x' * 20)
        self.client.force_login(f.make_admin())

        response = self.client.get(reverse('index'))

        self.assertEqual(response.context['open_support'], 1)
        self.assertContains(response, 'unresolved support request')
