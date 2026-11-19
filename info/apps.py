from django.apps import AppConfig
from django.contrib.admin.apps import AdminConfig


class InfoConfig(AppConfig):
    default_auto_field = 'django.db.models.AutoField'
    name = 'info'

    def ready(self):
        # Importing for the side effect of connecting the auth signal
        # receivers and registering the deployment checks; nothing else
        # references either module.
        from info import checks, signals  # noqa: F401


class ErpAdminConfig(AdminConfig):
    """Replaces `django.contrib.admin` in INSTALLED_APPS.

    Subclasses AdminConfig and not SimpleAdminConfig, which matters more than
    it looks: only AdminConfig.ready() calls autodiscover(). With the simple
    one `info/admin.py` is never imported and /admin/ comes up empty - not an
    error, just an admin site with nothing registered on it.
    """

    default_site = 'info.admin_site.ErpAdminSite'
