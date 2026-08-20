"""Guessing passwords, and the health endpoint.

The reset flow has been rate limited since it was written and the login form
had not, which is backwards: a reset code is six digits and lives ten minutes,
while a password handed over by an administrator is often kept for a year.
"""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from info.models import LoginEvent
from info.security import IP_THRESHOLD, LOCKOUT_THRESHOLD, LOCKOUT_WINDOW
from info.tests import factories as f


class LockoutTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        klass = f.make_class(dept)
        self.student = f.make_student(klass, username='pupil',
                                      password='right-password-12')
        self.url = reverse('login')

    def attempt(self, password='wrong', username='pupil'):
        return self.client.post(self.url, {'username': username,
                                           'password': password,
                                           'role': 'student'})

    def fail_times(self, count, username='pupil'):
        for _ in range(count):
            self.attempt(username=username)

    def test_a_few_wrong_tries_are_only_wrong(self):
        self.fail_times(LOCKOUT_THRESHOLD - 1)

        response = self.attempt(password='right-password-12')

        self.assertEqual(response.status_code, 302)

    def test_the_right_password_is_refused_once_the_count_is_spent(self):
        self.fail_times(LOCKOUT_THRESHOLD)

        response = self.attempt(password='right-password-12')

        # The sixth attempt is the one worth stopping, so the password is not
        # even checked.
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Too many failed sign-in attempts')

    def test_the_message_says_how_long_to_wait(self):
        self.fail_times(LOCKOUT_THRESHOLD)

        response = self.attempt()

        self.assertRegex(response.content.decode(),
                         r'Try again in \d+ minutes?')

    def test_a_locked_attempt_does_not_record_another_failure(self):
        self.fail_times(LOCKOUT_THRESHOLD)
        before = LoginEvent.objects.count()

        self.attempt()

        # Otherwise hammering the form both extends the block and fills the
        # table, which is a way of being refused into a denial of service.
        self.assertEqual(LoginEvent.objects.count(), before)

    def test_the_block_lifts_when_the_window_passes(self):
        self.fail_times(LOCKOUT_THRESHOLD)
        LoginEvent.objects.update(
            created_at=timezone.now() - LOCKOUT_WINDOW - timedelta(minutes=1))

        response = self.attempt(password='right-password-12')

        self.assertEqual(response.status_code, 302)

    def test_signing_in_clears_the_slate(self):
        self.fail_times(LOCKOUT_THRESHOLD - 1)
        self.assertEqual(self.attempt(password='right-password-12').status_code,
                         302)
        self.client.logout()

        # Four fumbles, a correct password, then two more is not five strikes.
        self.fail_times(2)
        response = self.attempt(password='right-password-12')

        self.assertEqual(response.status_code, 302)

    def test_one_account_locking_does_not_lock_another(self):
        other = f.make_student(f.make_class(f.make_dept(id='EC', name='ECE'),
                                            id='EC-3A'),
                               usn='1EC20EC001', username='other',
                               password='right-password-12')
        self.fail_times(LOCKOUT_THRESHOLD)

        response = self.attempt(username='other',
                                password='right-password-12')

        self.assertEqual(response.status_code, 302)
        self.assertEqual(other.user.username, 'other')

    def test_an_unknown_username_locks_the_same_way(self):
        # Otherwise the block itself says which accounts exist.
        self.fail_times(LOCKOUT_THRESHOLD, username='does-not-exist')

        response = self.attempt(username='does-not-exist')

        self.assertContains(response, 'Too many failed sign-in attempts')

    def test_spraying_many_accounts_from_one_address_is_caught(self):
        # No single account is attacked twice, so the per-account count never
        # notices; the address is what gives it away.
        for n in range(IP_THRESHOLD):
            self.attempt(username='student-%d' % n)

        response = self.attempt(username='someone-new')

        self.assertContains(response, 'Too many failed sign-in attempts')


class HealthTests(TestCase):
    def test_it_answers_without_signing_in(self):
        response = self.client.get('/healthz')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok', 'database': True})

    def test_it_reports_the_database_being_unreachable(self):
        from unittest import mock

        # An instance that booted but cannot reach Postgres serves 500s on
        # every page; a check that only proves gunicorn is listening would
        # call that healthy.
        with mock.patch('info.views.connection.ensure_connection',
                        side_effect=OSError('no route to host')):
            response = self.client.get('/healthz')

        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()['database'])
