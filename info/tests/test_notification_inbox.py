"""The notification list in the app.

Email is one way a notification is delivered; this is the other, and it is the
one that works for somebody whose account has no address on it.
"""
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from info import notifications
from info.models import Marks, MarksClass, Notice, Notification
from info.tests import factories as f


class InboxBase(TestCase):
    def setUp(self):
        self.dept = f.make_dept()
        self.klass = f.make_class(self.dept)
        self.course = f.make_course(self.dept)
        self.teacher = f.make_teacher(self.dept, id='T001', username='staff')
        self.student = f.make_student(self.klass, usn='1CS20CS001',
                                      name='Asha Rao', username='asha')
        self.client.force_login(self.student.user)

    def make_notification(self, key='notice:1', **extra):
        fields = {'kind': 'notice', 'subject': 'Exam timetable',
                  'body': 'Out now.', 'url': '/notices/'}
        fields.update(extra)
        return Notification.objects.create(user=self.student.user, key=key,
                                           **fields)


class InboxTests(InboxBase):
    def test_the_list_shows_what_the_person_has_been_told(self):
        self.make_notification()

        response = self.client.get(reverse('notifications'))

        self.assertContains(response, 'Exam timetable')
        self.assertEqual(response.context['unread'], 1)

    def test_an_empty_list_says_so_rather_than_showing_nothing(self):
        response = self.client.get(reverse('notifications'))

        self.assertContains(response, 'Nothing yet')

    def test_nobody_sees_anybody_else_s_notifications(self):
        other = f.make_student(self.klass, usn='1CS20CS002', name='Bala',
                               username='bala')
        Notification.objects.create(user=other.user, kind='fee',
                                    key='fee:1CS20CS002:2026W01',
                                    subject='Fee overdue', body='Pay up.')

        response = self.client.get(reverse('notifications'))

        self.assertNotContains(response, 'Fee overdue')
        self.assertEqual(response.context['notifications'], [])

    def test_opening_the_list_does_not_clear_the_badge(self):
        self.make_notification()

        self.client.get(reverse('notifications'))

        # Clearing here would drop the badge before anybody had looked at what
        # caused it.
        self.assertTrue(Notification.objects.get().read_at is None)

    def test_opening_one_marks_it_read_and_goes_where_it_points(self):
        item = self.make_notification(url='/notices/')

        response = self.client.get(
            reverse('notification_open', args=[item.pk]))

        self.assertRedirects(response, '/notices/',
                             fetch_redirect_response=False)
        item.refresh_from_db()
        self.assertTrue(item.is_read)

    def test_one_without_a_destination_comes_back_to_the_list(self):
        item = self.make_notification(url='')

        response = self.client.get(
            reverse('notification_open', args=[item.pk]))

        self.assertRedirects(response, reverse('notifications'))

    def test_reading_twice_keeps_the_first_time(self):
        item = self.make_notification()
        self.client.get(reverse('notification_open', args=[item.pk]))
        item.refresh_from_db()
        first = item.read_at

        self.client.get(reverse('notification_open', args=[item.pk]))

        item.refresh_from_db()
        self.assertEqual(item.read_at, first)

    def test_nobody_can_open_somebody_else_s_notification(self):
        other = f.make_student(self.klass, usn='1CS20CS002', name='Bala',
                               username='bala')
        item = Notification.objects.create(user=other.user, kind='fee',
                                           key='fee:x', subject='Fee overdue')

        response = self.client.get(
            reverse('notification_open', args=[item.pk]))

        self.assertEqual(response.status_code, 404)
        item.refresh_from_db()
        self.assertFalse(item.is_read)

    def test_everything_can_be_marked_read_at_once(self):
        self.make_notification(key='notice:1')
        self.make_notification(key='notice:2')

        self.client.post(reverse('notifications_read_all'))

        self.assertEqual(Notification.objects.unread().count(), 0)

    def test_marking_all_read_is_not_a_get(self):
        self.make_notification()

        response = self.client.get(reverse('notifications_read_all'))

        self.assertEqual(response.status_code, 405)

    def test_the_list_needs_a_login(self):
        self.client.logout()

        response = self.client.get(reverse('notifications'))

        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response['Location'])


class BadgeTests(InboxBase):
    def test_the_topbar_counts_unread_notifications(self):
        self.make_notification(key='notice:1')
        self.make_notification(key='notice:2')

        response = self.client.get(reverse('index'))

        self.assertEqual(response.context['unread_notifications'], 2)

    def test_a_read_one_stops_counting(self):
        item = self.make_notification()
        item.read_at = timezone.now()
        item.save(update_fields=['read_at'])

        response = self.client.get(reverse('index'))

        self.assertEqual(response.context['unread_notifications'], 0)

    def test_a_signed_out_visitor_gets_no_count(self):
        self.client.logout()

        response = self.client.get(reverse('login'))

        self.assertNotIn('unread_notifications', response.context)


class RecordedOnTheSpotTests(InboxBase):
    """Publishing is an event the app already knows about.

    Waiting for the nightly run to tell somebody their marks are out would be
    a strange thing to explain, so the row is written when it happens and the
    scheduled run has only the email left to do.
    """

    def test_posting_a_notice_reaches_the_audience_immediately(self):
        self.client.force_login(self.teacher.user)

        self.client.post(reverse('add_notice'), {
            'title': 'Holiday', 'message': 'Monday is off.',
            'audience': 'All', 'category': 'General', 'is_published': 'on'})

        notice = Notice.objects.get()
        self.assertTrue(
            Notification.objects.filter(user=self.student.user,
                                        key='notice:%d' % notice.pk).exists())

    def test_an_unpublished_notice_tells_nobody(self):
        self.client.force_login(self.teacher.user)

        self.client.post(reverse('add_notice'), {
            'title': 'Draft', 'message': 'Not ready.',
            'audience': 'All', 'category': 'General'})

        self.assertFalse(Notification.objects.exists())

    def test_publishing_marks_tells_the_class_at_once(self):
        assign = f.make_assign(self.klass, self.course, self.teacher)
        batch = MarksClass.objects.get(assign=assign, name='Internal test 1')
        batch.status = True
        batch.save(update_fields=['status'])
        Marks.objects.filter(studentcourse__student=self.student,
                             name='Internal test 1').update(marks1=17)
        self.client.force_login(self.teacher.user)

        self.client.post(reverse('publish_marks', args=[batch.pk]))

        notification = Notification.objects.get(user=self.student.user)
        self.assertIn('Internal test 1', notification.subject)
        self.assertIn('17 out of 20', notification.body)

    def test_the_scheduled_run_then_only_has_the_email_left(self):
        self.student.user.email = 'asha@example.com'
        self.student.user.save(update_fields=['email'])
        notice = Notice.objects.create(title='Holiday', message='Monday off.')
        notifications.announce(notifications.messages_for_notice(notice))
        before = Notification.objects.count()

        result = notifications.send_all(notifications.notice_alerts())

        self.assertEqual(Notification.objects.count(), before)
        self.assertEqual(result.recorded, 0)
        self.assertEqual(result.sent, 1)
