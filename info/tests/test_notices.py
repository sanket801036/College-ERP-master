"""The notice board was a flat list with no search, filters, pagination,
detail page, read state, drafts, editing or validation."""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from info.models import Notice, NoticeRead
from info.tests import factories as f


class NoticeBase(TestCase):
    def setUp(self):
        dept = f.make_dept()
        klass = f.make_class(dept)
        self.student = f.make_student(klass, username='pupil')
        self.teacher = f.make_teacher(dept, id='t001', username='staff')
        self.admin = f.make_admin()

    def make(self, title='Exam schedule released', **kwargs):
        defaults = {'message': 'The Semester 5 examination schedule is out.',
                    'audience': 'All', 'posted_by': self.teacher.user}
        defaults.update(kwargs)
        return Notice.objects.create(title=title, **defaults)


class VisibilityTests(NoticeBase):
    def test_students_see_notices_for_students_and_everyone(self):
        self.make('For everybody here', audience='All')
        self.make('For students only', audience='Students')
        self.make('For teachers only', audience='Teachers')
        self.client.force_login(self.student.user)

        titles = [n.title for n in self.client.get(reverse('notices')).context['page']]

        self.assertIn('For everybody here', titles)
        self.assertIn('For students only', titles)
        self.assertNotIn('For teachers only', titles)

    def test_students_do_not_see_drafts(self):
        self.make('Still being written', is_published=False)
        self.client.force_login(self.student.user)

        self.assertEqual(len(self.client.get(reverse('notices')).context['page']), 0)

    def test_staff_do_see_drafts(self):
        self.make('Still being written', is_published=False)
        self.client.force_login(self.teacher.user)

        self.assertEqual(len(self.client.get(reverse('notices')).context['page']), 1)

    def test_students_do_not_see_expired_notices(self):
        self.make('Old news',
                  expires_at=timezone.localdate() - timedelta(days=1))
        self.client.force_login(self.student.user)

        self.assertEqual(len(self.client.get(reverse('notices')).context['page']), 0)

    def test_pinned_notices_come_first(self):
        self.make('Ordinary notice')
        self.make('Pinned notice', pinned=True)
        self.client.force_login(self.student.user)

        page = self.client.get(reverse('notices')).context['page']

        self.assertEqual(page[0].title, 'Pinned notice')


class SearchAndFilterTests(NoticeBase):
    def setUp(self):
        super().setUp()
        self.make('Exam schedule released', category='Exam')
        self.make('Library closed Saturday', category='General')
        self.make('Fee deadline approaching', category='Fee')
        self.client.force_login(self.student.user)

    def test_search_matches_title_and_body(self):
        page = self.client.get(reverse('notices'), {'q': 'library'}).context['page']

        self.assertEqual([n.title for n in page], ['Library closed Saturday'])

    def test_filter_by_category(self):
        page = self.client.get(reverse('notices'), {'category': 'Fee'}).context['page']

        self.assertEqual([n.title for n in page], ['Fee deadline approaching'])

    def test_filter_by_period(self):
        old = self.make('Ancient history')
        Notice.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=40))

        page = self.client.get(reverse('notices'), {'period': 'week'}).context['page']

        self.assertNotIn('Ancient history', [n.title for n in page])

    def test_no_results_says_so(self):
        response = self.client.get(reverse('notices'), {'q': 'nothing matches this'})

        self.assertContains(response, 'No notices match that search')

    def test_the_list_is_paginated(self):
        for i in range(15):
            self.make('Notice number %d' % i)

        page = self.client.get(reverse('notices')).context['page']

        self.assertEqual(len(page), 10)
        self.assertTrue(page.has_next())


class ReadStateTests(NoticeBase):
    def setUp(self):
        super().setUp()
        self.notice = self.make()
        self.client.force_login(self.student.user)

    def test_a_new_notice_counts_as_unread(self):
        self.assertEqual(
            self.client.get(reverse('notices')).context['unread_count'], 1)

    def test_opening_a_notice_marks_it_read(self):
        self.client.get(reverse('notice_detail', args=(self.notice.id,)))

        self.assertTrue(NoticeRead.objects.filter(notice=self.notice,
                                                  user=self.student.user).exists())
        self.assertEqual(
            self.client.get(reverse('notices')).context['unread_count'], 0)

    def test_opening_twice_does_not_duplicate(self):
        url = reverse('notice_detail', args=(self.notice.id,))
        self.client.get(url)
        self.client.get(url)

        self.assertEqual(NoticeRead.objects.count(), 1)

    def test_the_unread_badge_is_available_on_every_page(self):
        response = self.client.get(reverse('index'))

        self.assertEqual(response.context['unread_notices'], 1)

    def test_a_student_cannot_open_a_notice_meant_for_teachers(self):
        staff_only = self.make('Staff meeting', audience='Teachers')

        response = self.client.get(reverse('notice_detail', args=(staff_only.id,)))

        self.assertEqual(response.status_code, 404)


class PostingTests(NoticeBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.teacher.user)

    def _payload(self, **overrides):
        data = {'title': 'Exam schedule released',
                'message': 'The timetable is on the department board.',
                'audience': 'All', 'category': 'Exam', 'is_published': 'on',
                'expires_at': ''}
        data.update(overrides)
        return data

    def test_a_teacher_can_post(self):
        response = self.client.post(reverse('add_notice'), self._payload())

        self.assertEqual(response.status_code, 302)
        notice = Notice.objects.get()
        self.assertEqual(notice.posted_by, self.teacher.user)
        self.assertIsNotNone(notice.published_at)

    def test_a_student_cannot_post(self):
        self.client.force_login(self.student.user)

        response = self.client.post(reverse('add_notice'), self._payload())

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Notice.objects.exists())

    def test_an_invalid_audience_is_rejected(self):
        """audience went straight from POST into the database, so an arbitrary
        string could be stored - after which the notice matched no filter and
        was invisible to everyone."""
        response = self.client.post(reverse('add_notice'),
                                    self._payload(audience='Nobody'))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Notice.objects.exists())

    def test_a_missing_field_is_a_form_error_not_a_500(self):
        response = self.client.post(reverse('add_notice'), {'title': 'Hello there'})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Notice.objects.exists())

    def test_a_past_expiry_date_is_rejected(self):
        yesterday = timezone.localdate() - timedelta(days=1)

        response = self.client.post(
            reverse('add_notice'), self._payload(expires_at=yesterday.isoformat()))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Notice.objects.exists())

    def test_saving_as_a_draft_leaves_it_unpublished(self):
        self.client.post(reverse('add_notice'), self._payload(is_published=''))

        notice = Notice.objects.get()
        self.assertFalse(notice.is_published)
        self.assertIsNone(notice.published_at)

    def test_teachers_cannot_address_the_whole_staff(self):
        """Addressing every teacher in the institution is an administrator's
        call, not any teacher's."""
        response = self.client.post(reverse('add_notice'),
                                    self._payload(audience='Teachers'))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Notice.objects.exists())

    def test_an_admin_can_address_the_whole_staff(self):
        self.client.force_login(self.admin)

        self.client.post(reverse('add_notice'), self._payload(audience='Teachers'))

        self.assertEqual(Notice.objects.get().audience, 'Teachers')


class EditAndDeleteTests(NoticeBase):
    def setUp(self):
        super().setUp()
        self.notice = self.make()

    def test_the_author_can_edit(self):
        self.client.force_login(self.teacher.user)

        self.client.post(reverse('edit_notice', args=(self.notice.id,)), {
            'title': 'Exam schedule corrected', 'message': 'Updated details.',
            'audience': 'All', 'category': 'Exam', 'is_published': 'on',
            'expires_at': ''})

        self.notice.refresh_from_db()
        self.assertEqual(self.notice.title, 'Exam schedule corrected')

    def test_another_teacher_cannot_edit(self):
        stranger = f.make_teacher(self.teacher.dept, id='t002',
                                  name='Stranger', username='stranger')
        self.client.force_login(stranger.user)

        response = self.client.get(reverse('edit_notice', args=(self.notice.id,)))

        self.assertEqual(response.status_code, 403)

    def test_the_author_can_delete(self):
        self.client.force_login(self.teacher.user)

        self.client.post(reverse('delete_notice', args=(self.notice.id,)))

        self.assertFalse(Notice.objects.exists())

    def test_delete_requires_post(self):
        self.client.force_login(self.teacher.user)

        response = self.client.get(reverse('delete_notice', args=(self.notice.id,)))

        self.assertEqual(response.status_code, 405)
        self.assertTrue(Notice.objects.exists())

    def test_a_student_cannot_delete(self):
        self.client.force_login(self.student.user)

        response = self.client.post(reverse('delete_notice', args=(self.notice.id,)))

        self.assertEqual(response.status_code, 403)
        self.assertTrue(Notice.objects.exists())
