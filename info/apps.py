from django.apps import AppConfig


class InfoConfig(AppConfig):
    default_auto_field = 'django.db.models.AutoField'
    name = 'info'

    def ready(self):
        # Importing for the side effect of connecting the auth signal
        # receivers; nothing else references this module.
        from info import signals  # noqa: F401
