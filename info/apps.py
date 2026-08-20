from django.apps import AppConfig


class InfoConfig(AppConfig):
    default_auto_field = 'django.db.models.AutoField'
    name = 'info'

    def ready(self):
        # Importing for the side effect of connecting the auth signal
        # receivers and registering the deployment checks; nothing else
        # references either module.
        from info import checks, signals  # noqa: F401
