from info.views import unread_notice_count


def notices(request):
    """Unread count for the topbar bell, on every page."""
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {}
    return {'unread_notices': unread_notice_count(user)}
