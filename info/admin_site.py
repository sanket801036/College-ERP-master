"""The admin site itself, rather than two lines tacked onto a URLConf.

The branding used to live at the bottom of `info/urls.py` as an import-time
side effect - `admin.site.site_header = 'My Site'` - which is why every admin
page announced itself as somebody's unnamed test project. Nobody looks for copy
in a URLConf.

Subclassing costs nothing here: `django.contrib.admin.sites.site` is a
`LazyObject` that resolves `apps.get_app_config('admin').default_site`, so
every existing `admin.site.register(...)` in `info/admin.py` lands on this
class without a single one of them changing.
"""
import re

from django.contrib import admin

from info.models import (
    AuditLog,
    Fee,
    LoginEvent,
    Student,
    SupportRequest,
    Teacher,
)

# The index is otherwise one alphabetical run of sixteen model names, which
# tells a newcomer nothing about what this system is. Grouping is by what a
# person came here to do, not by app label - `auth.Group` belongs with the
# people, not in a module of its own.
#
# Anything not named here still appears, under "Other" - see get_app_list. A
# model must never fall off the index just because nobody updated this tuple.
# The heading is all a group gets: admin/app_list.html renders app.name and
# nothing else, and it is included by the nav sidebar as well as the index, so
# a description would have meant overriding that template for both. The names
# have to carry the meaning on their own.
GROUPS = (
    ('People and access', (
        'info.student', 'info.teacher', 'info.user', 'auth.group',
        'authtoken.tokenproxy',
    )),
    ('Academics', (
        'info.dept', 'info.class', 'info.course', 'info.assign',
        'info.studentcourse', 'info.attendanceclass',
    )),
    ('Money, notices and support', (
        'info.fee', 'info.feetransaction', 'info.notice',
        'info.supportrequest',
    )),
    ('Assistant', (
        'info.coursematerial', 'info.aiusage',
    )),
    ('Records (append-only)', (
        'info.auditlog', 'info.loginevent',
    )),
)


class ErpAdminSite(admin.AdminSite):
    site_header = 'College ERP'
    site_title = 'College ERP admin'
    index_title = 'Administration'

    # Was None, which suppressed the "View site" link entirely. On a demo the
    # way back to the app is worth more than the pixel it costs.
    site_url = '/'

    # A different filename from Django's, deliberately: it means erp_index.html
    # can `{% extends "admin/index.html" %}` and inherit the whole page instead
    # of copying it in order to add one block.
    index_template = 'admin/erp_index.html'

    def get_app_list(self, request, app_label=None):
        """The index and the nav sidebar, regrouped by subject.

        Built by re-bucketing what `super()` returns rather than reading
        `self._registry` directly. That is the whole trick: the dicts handed
        back have already been through `has_module_permission` and
        `get_model_perms`, so an append-only admin like AuditLog keeps
        rendering as "View" instead of gaining a "Change" link it does not
        honour.
        """
        # `/admin/info/` asks for one app by label, and `app_index` 404s on an
        # empty list before reading `app_list[0]['name']` for its title. Our
        # synthetic groups are not app labels, so that view has to keep getting
        # the real ones.
        if app_label:
            return super().get_app_list(request, app_label)

        models_by_key = {}
        for app in super().get_app_list(request):
            for entry in app['models']:
                meta = entry['model']._meta
                models_by_key['%s.%s' % (meta.app_label,
                                         meta.model_name)] = entry

        app_list = []
        for name, keys in GROUPS:
            models = [models_by_key.pop(key) for key in keys
                      if key in models_by_key]
            if models:
                app_list.append(self._group(name, models))

        # Whatever nobody classified. Registering a model and finding it
        # nowhere on the index would be a worse bug than an untidy heading.
        if models_by_key:
            app_list.append(self._group('Other',
                                        list(models_by_key.values())))

        return app_list

    def _group(self, name, models):
        """One synthetic entry shaped like the app dict a template expects."""
        return {
            'name': name,
            # app_list.html interpolates this straight into a CSS class and an
            # element id, so it has to survive being one: "Money, notices and
            # support" would otherwise emit `class="app-money,"`.
            'app_label': re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-'),
            # app_list.html marks the current module by testing whether
            # app_url is a prefix of the path. Every group pointing at
            # /admin/info/ would light all of them up at once, so each points
            # at its own first changelist instead.
            'app_url': models[0]['admin_url'] or '',
            'has_module_perms': True,
            'models': models,
        }

    def index(self, request, extra_context=None):
        """The index, with a row of counts above the model list.

        Six aggregates on one page, not a count per model on every page: the
        app list is rebuilt for the sidebar of every admin screen, so counting
        there would put a COUNT(*) per registered model behind every click.

        Each one is a query the database answers. `Fee.status` is a property,
        so it cannot be filtered on - `FeeQuerySet.unpaid()` exists precisely
        because that distinction kept getting looped over in Python, and
        restating its predicate here would be the same mistake in a new file.
        """
        return super().index(request, {
            'erp_stats': [
                ('Students', Student.objects.filter(is_active=True).count()),
                ('Teachers', Teacher.objects.filter(is_active=True).count()),
                ('Fees unpaid', Fee.objects.unpaid().count()),
                # Matches the app dashboard's own definition of open, rather
                # than inventing a second one that drifts from it.
                ('Support open',
                 SupportRequest.objects.exclude(status='Resolved').count()),
                ('Audit entries', AuditLog.objects.count()),
                ('Failed sign-ins',
                 LoginEvent.objects.filter(successful=False).count()),
            ],
            **(extra_context or {}),
        })
