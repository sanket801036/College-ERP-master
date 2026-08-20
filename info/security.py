"""Slowing down somebody guessing passwords.

The OTP reset has been rate limited since it was built, and the login form has
not, which is the wrong way round: a reset code is six digits and expires in
ten minutes, while a password issued by an administrator is typed once and
often kept for a year.

Nothing new is stored. `LoginEvent` already records every attempt and what it
was for; this reads it.
"""
from datetime import timedelta

from django.utils import timezone

from info.models import LoginEvent

# Five wrong passwords in a quarter of an hour is somebody guessing, not
# somebody who forgot which one they used. It is also low enough to be met by
# accident, so the block expires on its own rather than needing an
# administrator - see the message the form shows.
LOCKOUT_THRESHOLD = 5
LOCKOUT_WINDOW = timedelta(minutes=15)

# One address failing against many accounts is spraying: a common password
# tried against a whole class list. The per-account count never notices it,
# because no single account is attacked twice.
IP_THRESHOLD = 20


def _failures_since(**filters):
    return LoginEvent.objects.filter(successful=False, **filters).count()


def failure_count(username, now=None):
    """Failed attempts on this username since it last succeeded.

    Counting from the last success rather than over a flat window means
    proving who you are clears the slate: four fumbles, a correct password,
    then two more fumbles is not five strikes.
    """
    now = now or timezone.now()
    since = now - LOCKOUT_WINDOW

    last_success = (LoginEvent.objects
                    .filter(username__iexact=username, successful=True)
                    .values_list('created_at', flat=True)
                    .first())
    if last_success and last_success > since:
        since = last_success

    return _failures_since(username__iexact=username, created_at__gte=since)


def lockout_state(username, ip, now=None):
    """(locked, minutes_left). The reason is deliberately not returned.

    Whether the block is on the account or the address does not change what
    the person is told: naming which one leaks whether the account exists.
    """
    now = now or timezone.now()
    since = now - LOCKOUT_WINDOW

    locked = False
    if username and failure_count(username, now) >= LOCKOUT_THRESHOLD:
        locked = True
    elif ip and _failures_since(ip=ip, created_at__gte=since) >= IP_THRESHOLD:
        locked = True

    if not locked:
        return False, 0

    # How long until the oldest attempt in the window falls out of it. Rounded
    # up, because "0 minutes" reads as a broken message rather than a wait.
    oldest = (LoginEvent.objects
              .filter(successful=False, created_at__gte=since)
              .filter(username__iexact=username) if username else
              LoginEvent.objects.filter(successful=False, ip=ip,
                                        created_at__gte=since))
    first = oldest.order_by('created_at').values_list('created_at',
                                                      flat=True).first()
    if first is None:
        return True, int(LOCKOUT_WINDOW.total_seconds() // 60)

    remaining = (first + LOCKOUT_WINDOW) - now
    minutes = int(remaining.total_seconds() // 60) + 1
    return True, max(minutes, 1)
