"""Sign-in recording.

Kept out of models.py because these are wired to Django's auth signals rather
than to a model's own lifecycle.
"""
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.dispatch import receiver

from info.models import LoginEvent


def client_ip(request):
    """Best guess at the caller's address.

    Behind Render's proxy REMOTE_ADDR is the proxy, so the forwarded header is
    read first - the leftmost entry, which is the original client.
    """
    if request is None:
        return None
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        return forwarded.split(',')[0].strip() or None
    return request.META.get('REMOTE_ADDR') or None


@receiver(user_logged_in)
def record_login(sender, request, user, **kwargs):
    LoginEvent.objects.create(
        user=user, username=user.username, successful=True,
        ip=client_ip(request),
        user_agent=(request.META.get('HTTP_USER_AGENT', '')[:300]
                    if request else ''),
    )


@receiver(user_login_failed)
def record_failure(sender, credentials, request=None, **kwargs):
    # A failed attempt often names an account that does not exist, so there is
    # no user to link - the typed username is the whole point of the record.
    LoginEvent.objects.create(
        user=None, username=(credentials or {}).get('username', '')[:150],
        successful=False, ip=client_ip(request),
        user_agent=(request.META.get('HTTP_USER_AGENT', '')[:300]
                    if request else ''),
    )
