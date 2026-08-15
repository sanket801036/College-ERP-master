from django.test import TestCase
from django.urls import reverse

from info.tests import factories as f


class PasswordChangeTests(TestCase):
    """Nobody could change their own password before this existed."""

    def setUp(self):
        dept = f.make_dept()
        self.student = f.make_student(f.make_class(dept), username='pupil',
                                      password='oldpass12345')
        self.url = reverse('password_change')

    def test_a_user_can_change_their_own_password(self):
        self.client.force_login(self.student.user)

        response = self.client.post(self.url, {
            'old_password': 'oldpass12345',
            'new_password1': 'a-much-better-one-42',
            'new_password2': 'a-much-better-one-42'})

        self.assertRedirects(response, reverse('password_change_done'))
        self.student.user.refresh_from_db()
        self.assertTrue(self.student.user.check_password('a-much-better-one-42'))

    def test_the_old_password_is_required(self):
        self.client.force_login(self.student.user)

        self.client.post(self.url, {
            'old_password': 'wrong',
            'new_password1': 'a-much-better-one-42',
            'new_password2': 'a-much-better-one-42'})

        self.student.user.refresh_from_db()
        self.assertTrue(self.student.user.check_password('oldpass12345'))

    def test_weak_passwords_are_rejected(self):
        self.client.force_login(self.student.user)

        response = self.client.post(self.url, {
            'old_password': 'oldpass12345',
            'new_password1': '1234', 'new_password2': '1234'})

        self.assertEqual(response.status_code, 200)
        self.student.user.refresh_from_db()
        self.assertTrue(self.student.user.check_password('oldpass12345'))

    def test_anonymous_users_are_sent_to_login(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])


class ForcePasswordChangeTests(TestCase):
    """Accounts are created with a password an admin reads off the screen, so
    it has been seen by someone else before the user ever signs in."""

    def setUp(self):
        dept = f.make_dept()
        self.student = f.make_student(f.make_class(dept), username='pupil',
                                      password='issued-by-admin-1')
        self.student.user.must_change_password = True
        self.student.user.save(update_fields=['must_change_password'])
        self.client.force_login(self.student.user)

    def test_other_pages_redirect_to_the_change_form(self):
        response = self.client.get(reverse('index'))

        self.assertRedirects(response, reverse('password_change'))

    def test_the_change_page_itself_is_reachable(self):
        self.assertEqual(self.client.get(reverse('password_change')).status_code,
                         200)

    def test_logout_is_reachable(self):
        self.assertEqual(self.client.get(reverse('logout')).status_code, 200)

    def test_changing_the_password_clears_the_flag(self):
        self.client.post(reverse('password_change'), {
            'old_password': 'issued-by-admin-1',
            'new_password1': 'chosen-by-the-user-9',
            'new_password2': 'chosen-by-the-user-9'})

        self.student.user.refresh_from_db()
        self.assertFalse(self.student.user.must_change_password)
        self.assertEqual(self.client.get(reverse('index')).status_code, 200)

    def test_users_without_the_flag_are_not_redirected(self):
        self.student.user.must_change_password = False
        self.student.user.save(update_fields=['must_change_password'])

        self.assertEqual(self.client.get(reverse('index')).status_code, 200)


class NewAccountsRequireAPasswordChange(TestCase):
    def test_a_created_student_must_change_their_password(self):
        dept = f.make_dept()
        klass = f.make_class(dept)
        self.client.force_login(f.make_admin())

        self.client.post(reverse('add_student'), {
            'USN': '1CS20CS002', 'name': 'Asha Rao', 'class_id': klass.pk,
            'sex': 'Female', 'DOB': '2002-05-14', 'email': 'asha@example.com'})

        from info.models import Student
        student = Student.objects.get(USN='1CS20CS002')
        self.assertTrue(student.user.must_change_password)
