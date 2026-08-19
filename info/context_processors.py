def notifications(request):
    """The topbar bell count, on every page.

    The bell is personal - fees, attendance, marks, and notices addressed to
    you - so it counts notifications rather than board posts. The board keeps
    its own unread count for the "New" markers on it, which answers a
    different question: not "has anybody told you" but "have you opened this".
    """
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {}
    return {'unread_notifications': user.notifications.unread().count()}
