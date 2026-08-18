"""The email OTP reset flow.

The interesting tests here are not the happy path - they are the ones that
check the flow cannot be used to find out which usernames exist, to flood
somebody's inbox, or to guess a six-digit code by brute force.
"""
import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from info.models import OTP_MAX_ATTEMPTS, OTP_MAX_REQUESTS, PasswordResetOTP
from info.tests import factories as f
from info.views import RESET_USER_KEY, RESET_VERIFIED_KEY

User = get_user_model()

WRONG_CODE_MESSAGE = ('That code is not valid. It may have expired, or been '
                      'used already.')


class BrokenBackend:
    """Stands in for an SMTP server that will not take the message."""

    def __init__(self, *args, **kwargs):
        pass

    def send_messages(self, messages):
        raise OSError('the mail server is not answering')


class PasswordResetFlowTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        klass = f.make_class(dept)
        self.student = f.make_student(klass, username='pupil',
                                      password='old-pass-12345')
        self.user = self.student.user
        self.user.email = 'pupil@example.com'
        self.user.save(update_fields=['email'])

        self.request_url = reverse('password_reset')
        self.verify_url = reverse('password_reset_verify')
        self.set_url = reverse('password_reset_set')

    # -- helpers ---------------------------------------------------------

    def _ask(self, identifier='pupil'):
        return self.client.post(self.request_url, {'identifier': identifier})

    def _code_from_email(self):
        """The six digits out of the most recent message."""
        self.assertTrue(mail.outbox, 'no email was sent')
        match = re.search(r'\b(\d{6})\b', mail.outbox[-1].body)
        self.assertIsNotNone(match, mail.outbox[-1].body)
        return match.group(1)

    def _reach_verified(self):
        self._ask()
        code = self._code_from_email()
        self.client.post(self.verify_url, {'code': code})
        return code

    # -- the ordinary path -----------------------------------------------

    def test_login_page_links_to_the_reset_flow(self):
        response = self.client.get(reverse('login'))

        self.assertContains(response, self.request_url)

    def test_a_code_is_emailed_and_the_caller_moves_on_to_verify(self):
        response = self._ask()

        self.assertRedirects(response, self.verify_url)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])
        self.assertRegex(mail.outbox[0].body, r'\b\d{6}\b')

    def test_the_email_address_works_as_the_identifier_too(self):
        self._ask('pupil@example.com')

        self.assertEqual(len(mail.outbox), 1)

    def test_the_whole_flow_changes_the_password(self):
        self._reach_verified()

        response = self.client.post(self.set_url, {
            'new_password1': 'a-brand-new-pass-99',
            'new_password2': 'a-brand-new-pass-99'})

        self.assertRedirects(response, reverse('login'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('a-brand-new-pass-99'))

    def test_finishing_the_reset_satisfies_the_forced_change_flag(self):
        self.user.must_change_password = True
        self.user.save(update_fields=['must_change_password'])
        self._reach_verified()

        self.client.post(self.set_url, {'new_password1': 'a-brand-new-pass-99',
                                        'new_password2': 'a-brand-new-pass-99'})

        self.user.refresh_from_db()
        self.assertFalse(self.user.must_change_password)

    # -- not a way to discover accounts ----------------------------------

    def test_an_unknown_identifier_looks_exactly_like_a_known_one(self):
        known = self._ask('pupil')
        mail.outbox.clear()
        self.client.logout()
        unknown = self._ask('nobody-here')

        self.assertEqual(known.status_code, unknown.status_code)
        self.assertEqual(known['Location'], unknown['Location'])
        self.assertEqual(len(mail.outbox), 0)
        self.assertNotIn(RESET_USER_KEY, self.client.session)

    def test_the_same_wording_is_shown_either_way(self):
        def wording(identifier):
            self.client.logout()
            self.client.post(self.request_url, {'identifier': identifier})
            page = self.client.get(self.verify_url)
            return [str(m) for m in page.context['messages']]

        self.assertEqual(wording('pupil'), wording('nobody-here'))

    def test_an_account_without_an_email_is_not_singled_out(self):
        self.user.email = ''
        self.user.save(update_fields=['email'])

        response = self._ask()

        self.assertRedirects(response, self.verify_url)
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(PasswordResetOTP.objects.exists())

    def test_a_mail_failure_does_not_break_the_page(self):
        backend = 'info.tests.test_password_reset.BrokenBackend'
        with self.settings(EMAIL_BACKEND=backend):
            response = self._ask()

        # The code exists but never arrived; the caller learns nothing either way.
        self.assertRedirects(response, self.verify_url)
        self.assertEqual(len(mail.outbox), 0)

    # -- the code itself --------------------------------------------------

    def test_the_code_is_stored_hashed(self):
        self._ask()
        code = self._code_from_email()

        stored = PasswordResetOTP.objects.get().code_hash
        self.assertNotIn(code, stored)
        self.assertNotEqual(stored, code)

    def test_a_code_only_works_once(self):
        code = self._reach_verified()
        self.client.post(self.set_url, {'new_password1': 'a-brand-new-pass-99',
                                        'new_password2': 'a-brand-new-pass-99'})

        # Start again and offer the same digits.
        self.client.post(self.request_url, {'identifier': 'pupil'})
        response = self.client.post(self.verify_url, {'code': code})

        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context['form'], 'code',
                             WRONG_CODE_MESSAGE)

    def test_a_code_expires(self):
        self._ask()
        code = self._code_from_email()
        PasswordResetOTP.objects.update(
            expires_at=timezone.now() - timedelta(seconds=1))

        response = self.client.post(self.verify_url, {'code': code})

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(RESET_VERIFIED_KEY, self.client.session)

    def test_asking_again_voids_the_previous_code(self):
        self._ask()
        first = self._code_from_email()
        self._ask()
        second = self._code_from_email()
        self.assertNotEqual(first, second)

        stale = self.client.post(self.verify_url, {'code': first})
        self.assertNotIn(RESET_VERIFIED_KEY, self.client.session)
        self.assertEqual(stale.status_code, 200)

        self.client.post(self.verify_url, {'code': second})
        self.assertIn(RESET_VERIFIED_KEY, self.client.session)

    def test_guessing_is_capped(self):
        self._ask()
        code = self._code_from_email()
        wrong = '000000' if code != '000000' else '111111'

        for _ in range(OTP_MAX_ATTEMPTS):
            self.client.post(self.verify_url, {'code': wrong})

        # Even the right code is refused once the attempts are spent.
        self.client.post(self.verify_url, {'code': code})
        self.assertNotIn(RESET_VERIFIED_KEY, self.client.session)
        self.assertEqual(PasswordResetOTP.objects.get().state, 'locked')

    def test_requests_are_rate_limited(self):
        for _ in range(OTP_MAX_REQUESTS + 2):
            self.client.post(self.request_url, {'identifier': 'pupil'})

        self.assertEqual(len(mail.outbox), OTP_MAX_REQUESTS)
        self.assertEqual(PasswordResetOTP.objects.count(), OTP_MAX_REQUESTS)

    # -- the last step cannot be jumped to --------------------------------

    def test_the_new_password_page_needs_a_verified_code(self):
        response = self.client.get(self.set_url)

        self.assertRedirects(response, self.request_url)

    def test_asking_for_a_code_is_not_enough_to_reach_it(self):
        self._ask()

        response = self.client.get(self.set_url)

        self.assertRedirects(response, self.request_url)

    def test_a_verified_code_cannot_be_pointed_at_another_account(self):
        other = f.make_admin(username='boss', password='old-pass-12345')
        self._reach_verified()
        session = self.client.session
        session[RESET_USER_KEY] = other.pk
        session.save()

        response = self.client.post(self.set_url, {
            'new_password1': 'a-brand-new-pass-99',
            'new_password2': 'a-brand-new-pass-99'})

        self.assertRedirects(response, self.request_url)
        other.refresh_from_db()
        self.assertTrue(other.check_password('old-pass-12345'))
