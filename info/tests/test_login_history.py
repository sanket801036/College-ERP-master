"""Nothing recorded who signed in, or from where.

That matters more here than it might elsewhere: accounts are issued with a
password an admin reads off a screen and hands over, so the window in which
somebody else could use one is real.
"""
from django.test import TestCase
from django.urls import reverse

from info.models import LoginEvent
from info.tests import factories as f


class RecordingTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        self.student = f.make_student(self.klass, username='asha',
                                      password='pass12345')

    def test_a_successful_sign_in_is_recorded(self):
        self.client.post(reverse('login'), {'username': 'asha',
                                            'password': 'pass12345',
                                            'role': 'student'})

        event = LoginEvent.objects.get()
        self.assertTrue(event.successful)
        self.assertEqual(event.user, self.student.user)
        self.assertEqual(event.username, 'asha')

    def test_a_failed_attempt_is_recorded_too(self):
        self.client.post(reverse('login'), {'username': 'asha',
                                            'password': 'wrong',
                                            'role': 'student'})

        event = LoginEvent.objects.get()
        self.assertFalse(event.successful)
        self.assertEqual(event.username, 'asha')

    def test_an_attempt_on_an_account_that_does_not_exist_is_kept(self):
        """There is no user to link, and that attempt is exactly the one worth
        keeping - which is why the username is stored as text."""
        self.client.post(reverse('login'), {'username': 'nobody',
                                            'password': 'guess',
                                            'role': 'student'})

        event = LoginEvent.objects.get()
        self.assertIsNone(event.user)
        self.assertEqual(event.username, 'nobody')
        self.assertFalse(event.successful)

    def test_the_address_is_recorded(self):
        self.client.post(reverse('login'), {'username': 'asha',
                                            'password': 'pass12345',
                                            'role': 'student'},
                         REMOTE_ADDR='198.51.100.7')

        self.assertEqual(LoginEvent.objects.get().ip, '198.51.100.7')

    def test_the_forwarded_address_wins_behind_a_proxy(self):
        """Render sits behind a proxy, so REMOTE_ADDR is the proxy - the
        leftmost forwarded entry is the actual client."""
        self.client.post(reverse('login'), {'username': 'asha',
                                            'password': 'pass12345',
                                            'role': 'student'},
                         REMOTE_ADDR='10.0.0.1',
                         HTTP_X_FORWARDED_FOR='203.0.113.9, 10.0.0.1')

        self.assertEqual(LoginEvent.objects.get().ip, '203.0.113.9')

    def test_a_very_long_user_agent_is_truncated_rather_than_erroring(self):
        self.client.post(reverse('login'), {'username': 'asha',
                                            'password': 'pass12345',
                                            'role': 'student'},
                         HTTP_USER_AGENT='x' * 1000)

        self.assertEqual(len(LoginEvent.objects.get().user_agent), 300)


class DeviceDescriptionTests(TestCase):
    def _device(self, agent):
        return LoginEvent(user_agent=agent).device

    def test_names_the_browser_and_platform(self):
        self.assertEqual(
            self._device('Mozilla/5.0 (Windows NT 10.0) Chrome/120.0'),
            'Chrome on Windows')

    def test_edge_is_not_reported_as_chrome(self):
        """Edge sends both tokens, and Edg appears first for that reason."""
        self.assertEqual(
            self._device('Mozilla/5.0 (Windows NT 10.0) Chrome/120 Edg/120'),
            'Edge on Windows')

    def test_a_phone(self):
        self.assertEqual(
            self._device('Mozilla/5.0 (Linux; Android 14) Chrome/120'),
            'Chrome on Android')

    def test_an_unknown_agent_says_so_rather_than_guessing(self):
        self.assertEqual(self._device('curl/8.0'), 'Unknown browser')

    def test_no_agent_at_all(self):
        self.assertEqual(self._device(''), 'Unknown')


class ProfileDisplayTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.student = f.make_student(f.make_class(dept), username='asha',
                                      password='pass12345')

    def test_the_profile_lists_recent_sign_ins(self):
        self.client.post(reverse('login'), {'username': 'asha',
                                            'password': 'pass12345',
                                            'role': 'student'},
                         HTTP_USER_AGENT='Mozilla/5.0 (Windows NT 10.0) Chrome/120')

        response = self.client.get(reverse('profile'))

        self.assertContains(response, 'Recent sign-ins')
        self.assertContains(response, 'Chrome on Windows')

    def test_failed_attempts_are_not_shown_to_the_user(self):
        """A list of failed attempts on your own account is alarming without
        being actionable; an administrator can see them."""
        self.client.post(reverse('login'), {'username': 'asha',
                                            'password': 'wrong',
                                            'role': 'student'})
        self.client.force_login(self.student.user)

        logins = self.client.get(reverse('profile')).context['logins']

        self.assertTrue(all(event.successful for event in logins))

    def test_only_your_own_sign_ins_are_listed(self):
        other = f.make_student(self.student.class_id, usn='1CS20CS999',
                               name='Someone', username='other',
                               password='pass12345')
        self.client.post(reverse('login'), {'username': 'other',
                                            'password': 'pass12345',
                                            'role': 'student'})
        self.client.logout()
        self.client.force_login(self.student.user)

        logins = self.client.get(reverse('profile')).context['logins']

        self.assertFalse(any(e.user == other.user for e in logins))
