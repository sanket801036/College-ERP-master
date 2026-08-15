from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse


class ForcePasswordChangeMiddleware:
    """Send users with a generated password to the change-password page.

    Accounts are created with a random password that an admin reads off the
    screen and hands over, so until it is changed it has been seen by at least
    one other person and probably written down. Nothing previously prompted for
    a change - the original scheme derived the password from the user's name and
    birth year and left it in place indefinitely.
    """

    # Reachable while the flag is set, or the user would be stuck in a loop.
    ALLOWED = {'password_change', 'password_change_done', 'logout', 'login'}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        """Runs after URL resolution, which is when the view name is known."""
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated:
            return None
        if not user.must_change_password:
            return None

        match = request.resolver_match
        if match and (match.url_name in self.ALLOWED
                      or match.app_name == 'admin'):
            return None

        messages.info(request, 'Choose your own password before continuing.')
        return redirect(reverse('password_change'))
