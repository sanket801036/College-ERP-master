"""Django's admin, which had no tests at all.

Fifteen ModelAdmins, one custom view that deletes every attendance row in the
database, and not a single assertion anywhere - a bad `list_display` was a 500
that nobody would meet until somebody opened the page in front of an audience.

Most of what follows is a smoke pass driven off the registry, so a model
registered tomorrow is covered without anyone remembering to add a test. The
rest holds the two things that are easy to break by accident: the read-only
admins really refusing to write, and the theme resolution that Django's own
script used to undo.
"""
from datetime import date, timedelta

from django.contrib import admin
from django.test import TestCase
from django.urls import reverse

from info.admin_site import GROUPS
from info.models import (
    AssignTime,
    AttendanceClass,
    AuditLog,
    LoginEvent,
    Notice,
)
from info.tests import factories as f


def registered():
    """(app_label, model_name, model_admin) for everything on the site."""
    for model, model_admin in admin.site._registry.items():
        yield (model._meta.app_label, model._meta.model_name, model_admin)


class AdminSmokeTests(TestCase):
    def setUp(self):
        self.admin = f.make_admin()
        self.client.force_login(self.admin)

    def test_every_registered_changelist_renders(self):
        # The cheapest guard there is against a typo in list_display,
        # list_filter or ordering, none of which fail until the page is asked
        # for. It also fails loudly if ErpAdminConfig ever stops subclassing
        # AdminConfig, because then nothing is registered to iterate.
        for app_label, model_name, _ in registered():
            with self.subTest(model='%s.%s' % (app_label, model_name)):
                url = reverse('admin:%s_%s_changelist' % (app_label, model_name))

                self.assertEqual(self.client.get(url).status_code, 200)

    def test_something_is_actually_registered(self):
        # SimpleAdminConfig does not call autodiscover(), and the failure is
        # silent: an admin site that loads fine and lists nothing.
        self.assertGreater(len(admin.site._registry), 10)

    def test_add_forms_render_where_adding_is_allowed(self):
        request = self.client.get(reverse('admin:index')).wsgi_request

        for app_label, model_name, model_admin in registered():
            with self.subTest(model='%s.%s' % (app_label, model_name)):
                url = reverse('admin:%s_%s_add' % (app_label, model_name))
                response = self.client.get(url)

                if model_admin.has_add_permission(request):
                    self.assertEqual(response.status_code, 200)
                else:
                    self.assertEqual(response.status_code, 403)

    def test_the_index_renders(self):
        self.assertEqual(self.client.get(reverse('admin:index')).status_code, 200)

    def test_the_per_app_index_still_works(self):
        # get_app_list() regroups the index into headings that are not app
        # labels. app_index() passes a real label through and 404s on an empty
        # list, so the override has to hand that case back to super().
        self.assertEqual(self.client.get('/admin/info/').status_code, 200)


class BrandingTests(TestCase):
    def setUp(self):
        self.client.force_login(f.make_admin())
        self.response = self.client.get(reverse('admin:index'))

    def test_the_header_names_the_project(self):
        # It said "My Site" - the placeholder from a tutorial - set as an
        # import-time side effect at the bottom of info/urls.py.
        self.assertContains(self.response, 'College ERP')
        self.assertNotContains(self.response, 'My Site')

    def test_nothing_still_says_django_administration(self):
        self.assertNotContains(self.response, 'Django site admin')
        self.assertNotContains(self.response, 'Django administration')

    def test_the_way_back_to_the_app_exists(self):
        # site_url was None, which removes the "View site" link entirely.
        self.assertEqual(admin.site.site_url, '/')


class SkinTests(TestCase):
    def setUp(self):
        self.client.force_login(f.make_admin())
        self.response = self.client.get(reverse('admin:index'))

    def test_the_admin_loads_the_apps_stylesheets(self):
        # If base_site.html is ever shadowed or its {% load static %} dropped,
        # this is what says so.
        self.assertContains(self.response, 'info/css/theme.css')
        self.assertContains(self.response, 'info/css/erp-admin.css')

    def test_the_theme_is_resolved_before_the_first_paint(self):
        self.assertContains(self.response, "setAttribute('data-theme'")
        self.assertContains(self.response, 'erp-theme')

    def test_django_does_not_get_to_set_the_theme(self):
        # The regression this whole override exists for: admin/js/theme.js
        # reads a different localStorage key and writes data-theme="auto",
        # which theme.css's :root[data-theme="dark"] does not match - so a
        # dark mode chosen in the app was thrown away on every admin page.
        self.assertNotContains(self.response, 'admin/js/theme.js')

    def test_the_login_page_is_skinned_too(self):
        # Signed out. It is also the first admin page anybody sees.
        self.client.logout()
        response = self.client.get(reverse('admin:login'))

        self.assertContains(response, 'info/css/erp-admin.css')
        self.assertContains(response, 'erp-theme')


class GroupingTests(TestCase):
    def setUp(self):
        self.client.force_login(f.make_admin())
        self.response = self.client.get(reverse('admin:index'))

    def test_the_index_is_grouped_by_subject(self):
        for name, _ in GROUPS:
            with self.subTest(group=name):
                self.assertContains(self.response, name)

    def test_every_registered_model_is_reachable_from_the_index(self):
        # A model left out of GROUPS must land in "Other", not vanish. Losing
        # a model off the index would be invisible until somebody went looking
        # for it.
        listed = {model['object_name'].lower()
                  for app in self.response.context['app_list']
                  for model in app['models']}

        for _, model_name, _ in registered():
            with self.subTest(model=model_name):
                self.assertIn(model_name, listed)

    def test_an_unclassified_model_lands_in_other_rather_than_nowhere(self):
        # The safety net, forced open because everything registered today is
        # classified. A model registered tomorrow and forgotten here must still
        # appear somewhere - falling off the index entirely would be invisible
        # until somebody went looking for it.
        from unittest import mock

        from info import admin_site

        one_group = (('People', ('info.student',)),)
        with mock.patch.object(admin_site, 'GROUPS', one_group):
            response = self.client.get(reverse('admin:index'))
            names = [app['name'] for app in response.context['app_list']]

        self.assertEqual(names, ['People', 'Other'])

    def test_the_index_carries_the_counts(self):
        self.assertContains(self.response, 'erp-admin-stats')
        self.assertContains(self.response, 'Students')


class ReadOnlyAdminTests(TestCase):
    """The append-only logs, which are evidence rather than data entry.

    Each test works against a row that really exists. Asking for a missing pk
    redirects to the changelist with "does not exist" long before any
    permission is consulted, so it would pass whatever the admin allowed.
    """

    def setUp(self):
        self.client.force_login(f.make_admin())
        self.entry = AuditLog.objects.create(
            action='marks_published', actor_name='someone',
            student_name='a student', summary='published')
        self.event = LoginEvent.objects.create(username='someone',
                                               successful=False)

    def test_the_audit_log_cannot_be_added_to_or_deleted(self):
        for action, url in (
            ('add', reverse('admin:info_auditlog_add')),
            ('delete',
             reverse('admin:info_auditlog_delete', args=[self.entry.pk])),
        ):
            with self.subTest(action=action):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_an_audit_entry_opens_read_only(self):
        # Not a 403: with view permission but not change, Django renders the
        # object with every field frozen and no submit row. That is the "View"
        # the index offers, and the absence of a save button is the assertion
        # worth making - the page being reachable is the point of it.
        response = self.client.get(
            reverse('admin:info_auditlog_change', args=[self.entry.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="_save"')
        self.assertFalse(response.context['has_change_permission'])

    def test_the_audit_log_survives_a_posted_delete(self):
        # The GET being refused is not the same as the row being safe.
        self.client.post(
            reverse('admin:info_auditlog_delete', args=[self.entry.pk]),
            {'post': 'yes'})

        self.assertTrue(AuditLog.objects.filter(pk=self.entry.pk).exists())

    def test_login_events_cannot_be_added(self):
        self.assertEqual(
            self.client.get(reverse('admin:info_loginevent_add')).status_code,
            403)

    def test_a_login_event_opens_read_only(self):
        response = self.client.get(
            reverse('admin:info_loginevent_change', args=[self.event.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="_save"')
        self.assertFalse(response.context['has_change_permission'])

    def test_login_events_can_still_be_deleted(self):
        # Deliberately allowed, unlike the audit log: the rows are noisy and an
        # administrator clearing old ones is reasonable.
        response = self.client.get(
            reverse('admin:info_loginevent_delete', args=[self.event.pk]))

        self.assertEqual(response.status_code, 200)


class AttendanceResetTests(TestCase):
    """The custom view that deletes every attendance row in the database.

    `reset_attd` calls `Attendance.objects.all().delete()` and has never had a
    test. It is reached from a template override, so a restyle of the admin is
    exactly the kind of change that could quietly detach it.
    """

    def setUp(self):
        self.client.force_login(f.make_admin())
        dept = f.make_dept()
        klass = f.make_class(dept)
        course = f.make_course(dept)
        teacher = f.make_teacher(dept)
        self.assign = f.make_assign(klass, course, teacher)
        AssignTime.objects.create(assign=self.assign, period='1', day='Monday')

    def test_the_changelist_still_offers_the_reset_form(self):
        response = self.client.get(
            reverse('admin:info_attendanceclass_changelist'))

        self.assertContains(response, 'reset-attd')
        self.assertContains(response, reverse('admin:reset_attd'))

    def test_the_reset_creates_a_class_for_every_matching_weekday(self):
        # A Monday and the fortnight after it: two Mondays fall inside.
        monday = date(2026, 3, 2)
        response = self.client.post(reverse('admin:reset_attd'), {
            'startdate': monday.isoformat(),
            'enddate': (monday + timedelta(days=14)).isoformat(),
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            list(AttendanceClass.objects.values_list('date', flat=True)),
            [monday, monday + timedelta(days=7)])

    def test_the_reset_clears_what_was_there_before(self):
        AttendanceClass.objects.create(assign=self.assign,
                                       date=date(2020, 1, 1))
        monday = date(2026, 3, 2)

        self.client.post(reverse('admin:reset_attd'), {
            'startdate': monday.isoformat(),
            'enddate': (monday + timedelta(days=7)).isoformat(),
        })

        self.assertFalse(
            AttendanceClass.objects.filter(date=date(2020, 1, 1)).exists())


class NoticeAdminTests(TestCase):
    def test_the_notice_filters_were_not_overwritten(self):
        # info/admin.py assigned list_filter twice; the second, poorer tuple
        # won, so three of these filters were written down and never rendered.
        # ruff's selected rules do not include PIE794, so nothing caught it.
        model_admin = admin.site._registry[Notice]

        self.assertEqual(model_admin.list_filter,
                         ('category', 'audience', 'is_published', 'pinned'))


class TemplateOrderingTests(TestCase):
    def test_the_apps_admin_templates_still_win(self):
        # info comes before django.contrib.admin in INSTALLED_APPS, which is
        # what lets info/templates/admin/* override the shipped ones. Swap the
        # two and the admin silently reverts to stock with nothing failing.
        from django.template.loader import get_template

        template = get_template('admin/base_site.html')

        self.assertIn('info', template.origin.name.replace('\\', '/'))


class QueryShapeTests(TestCase):
    def test_the_counts_are_computed_on_the_index_only(self):
        """Counts belong on the index, not behind every admin click.

        `each_context` rebuilds the app list for the nav sidebar of every admin
        page. Putting a row count on each model there - the obvious way to get
        numbers beside the names - would mean a COUNT(*) per registered model
        behind every single click, which is why the stats live in `index()`.
        """
        self.client.force_login(f.make_admin())

        index = self.client.get(reverse('admin:index'))
        changelist = self.client.get(reverse('admin:info_dept_changelist'))

        self.assertContains(index, 'erp-admin-stats')
        self.assertNotContains(changelist, 'erp-admin-stats')
