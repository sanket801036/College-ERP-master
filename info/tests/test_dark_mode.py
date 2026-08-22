"""Dark mode.

Most of it is CSS, which a test cannot look at. What a test can do is hold the
two things that break silently: a colour token that gains a light value and
never gains a dark one, and a page that forgets the script that decides which
palette to paint before the first frame.
"""
import re
from pathlib import Path

from django.test import TestCase
from django.urls import reverse

from info.tests import factories as f

THEME = Path('info/static/info/css/theme.css')


def tokens_in(block):
    return set(re.findall(r'(--erp-[a-z0-9-]+)\s*:', block))


def block_after(text, selector):
    """The body of the first rule with this selector.

    The selectors passed in already carry their opening brace, so the body
    starts right after it. Looking for the next `{` instead - as this did -
    lands in the *following* rule and returns its body, which for `:root {`
    meant reading `body { ... }` and finding no tokens at all. Both palette
    tests were comparing empty sets and passing on anything.
    """
    start = text.index(selector) + len(selector)
    return text[start:text.index('}', start)]


class PaletteTests(TestCase):
    def setUp(self):
        self.css = THEME.read_text(encoding='utf-8')
        self.light = tokens_in(block_after(self.css, ':root {'))
        self.dark = tokens_in(block_after(self.css, ':root[data-theme="dark"] {'))

    def test_every_colour_token_has_a_dark_value(self):
        # Sizes and shapes stay put; only the colours change.
        structural = {'--erp-radius', '--erp-navbar-h'}
        missing = self.light - self.dark - structural

        self.assertEqual(missing, set(),
                         'these tokens have no dark value: %s' % sorted(missing))

    def test_the_dark_block_invents_nothing(self):
        # A token defined only in the dark block would be undefined in light,
        # which fails silently as an empty value.
        self.assertEqual(self.dark - self.light, set())

    def test_the_dark_palette_is_actually_dark(self):
        self.assertIn('--erp-bg: #0f172a', self.css)
        self.assertIn('color-scheme: dark', self.css)

    def test_printing_goes_back_to_paper_colours(self):
        # A dark page sent to a printer is either unreadable or a wasted
        # cartridge.
        printing = self.css[self.css.index('Paper is not dark'):]
        self.assertIn(':root[data-theme="dark"]', printing)
        self.assertIn('--erp-surface: #ffffff', printing)


class PageTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        klass = f.make_class(dept)
        self.student = f.make_student(klass, usn='1CS20CS001', username='asha')

    def test_the_signed_in_pages_resolve_the_theme_before_painting(self):
        self.client.force_login(self.student.user)

        response = self.client.get(reverse('index'))

        self.assertContains(response, "setAttribute('data-theme'")
        self.assertContains(response, 'themeToggle')

    def test_the_sign_in_page_does_too(self):
        # Whoever is signed out has the same eyes as whoever is signed in.
        response = self.client.get(reverse('login'))

        self.assertContains(response, "setAttribute('data-theme'")

    def test_the_password_reset_pages_do_too(self):
        response = self.client.get(reverse('password_reset'))

        self.assertContains(response, "setAttribute('data-theme'")

    def test_the_django_admin_shares_the_same_choice(self):
        # The admin is a different template tree with its own theme script, and
        # Django's reads a different localStorage key - so a preference set in
        # the app was discarded the moment somebody clicked "Full Admin". The
        # key, not just the presence of a script, is what makes it one setting.
        self.client.force_login(f.make_admin())

        response = self.client.get(reverse('admin:index'))

        self.assertContains(response, "setAttribute('data-theme'")
        self.assertContains(response, 'erp-theme')
