"""The sidebar on a phone.

The stylesheet used to pin the sidebar open at 270px at every width - there is
a comment in `theme.css` saying so deliberately - and no template rendered any
control that could close it. On a 360px screen that left 90px for the page,
permanently. Nothing failed, because nothing was looking: the layout was only
ever checked on a desktop.

Most of a drawer is CSS, which a test cannot see moving. What it can hold is
the part that went wrong: that a control exists, that it points at the thing
it opens, and that the stylesheet stops pinning the rail below the breakpoint.
"""
import re
from pathlib import Path

from django.test import TestCase
from django.urls import reverse

from info.tests import factories as f

THEME = Path('info/static/info/css/theme.css')

# Where the rail becomes a drawer. Bootstrap 4's `lg`, so `d-lg-none` on the
# button lines up with it without a second breakpoint of our own.
DRAWER_QUERY = '@media (max-width: 991.98px) {'


def media_block(css, query):
    """The body of a media query, braces balanced."""
    start = css.index(query) + len(query)
    depth = 1
    for i in range(start, len(css)):
        if css[i] == '{':
            depth += 1
        elif css[i] == '}':
            depth -= 1
            if depth == 0:
                return css[start:i]
    raise AssertionError('unterminated media query: %s' % query)


class MarkupTests(TestCase):
    """The chrome, which base.html renders the same way for every role."""

    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        self.student = f.make_student(self.klass, username='asha',
                                      password='pass12345')

    def page(self):
        self.client.login(username='asha', password='pass12345')
        return self.client.get(reverse('index')).content.decode()

    def test_there_is_a_control_that_opens_the_menu(self):
        # The whole bug in one assertion: there was no such button anywhere.
        self.assertIn('id="erpSidebarToggle"', self.page())

    def test_the_control_names_what_it_opens(self):
        html = self.page()

        # A toggle whose aria-controls points at nothing tells a screen reader
        # a button exists and nothing about what it does.
        self.assertIn('aria-controls="erpSidebar"', html)
        self.assertIn('id="erpSidebar"', html)

    def test_the_control_is_hidden_where_the_rail_is_permanent(self):
        # Above the breakpoint the sidebar is always on screen, so a button
        # offering to open it is a lie.
        html = self.page()
        button = html[html.index('id="erpSidebarToggle"') - 300:
                      html.index('id="erpSidebarToggle"')]

        self.assertIn('d-lg-none', button)

    def test_there_is_something_to_tap_beside_the_drawer(self):
        # Tapping the page next to an open drawer is the first thing anyone
        # tries; without the backdrop there is nothing listening.
        self.assertIn('id="erpNavBackdrop"', self.page())

    def test_the_drawer_starts_closed(self):
        # The open state lives on the body as a class the script adds. If the
        # server ever rendered it, every page would load with the menu over
        # it. Read the body tag rather than the page: the class name also
        # appears in the script that sets it, which is not the same thing.
        html = self.page()
        body = html[html.index('<body'):html.index('>', html.index('<body'))]

        self.assertNotIn('erp-nav-open', body)


class StylesheetTests(TestCase):
    def setUp(self):
        self.css = THEME.read_text(encoding='utf-8')

    def test_the_sidebar_leaves_the_layout_below_the_breakpoint(self):
        block = media_block(self.css, DRAWER_QUERY)

        # Still a flex child down here and the page keeps being squeezed into
        # whatever is left, which is the state this replaced.
        self.assertIn('position: fixed', block)

    def test_the_drawer_is_off_screen_until_it_is_opened(self):
        block = media_block(self.css, DRAWER_QUERY)

        self.assertIn('translateX(-100%)', block)
        self.assertIn('body.erp-nav-open .sidebar', block)

    def test_the_drawer_never_takes_the_whole_screen(self):
        block = media_block(self.css, DRAWER_QUERY)
        width = re.search(r'\.sidebar\s*\{[^}]*?width:\s*([0-9.]+)vw', block)

        # At a fixed 270px a 320px phone has 50px of backdrop left to tap.
        self.assertIsNotNone(width, 'the drawer has no relative width')
        self.assertLessEqual(float(width.group(1)), 85)

    def test_the_page_behind_the_drawer_does_not_scroll(self):
        block = media_block(self.css, DRAWER_QUERY)
        body = re.search(r'body\.erp-nav-open\s*\{([^}]*)\}', block)

        self.assertIsNotNone(body)
        self.assertIn('overflow: hidden', body.group(1))

    def test_controls_are_big_enough_to_tap(self):
        # 44px is the smallest target that is reliably hit with a thumb.
        block = media_block(self.css, '@media (max-width: 767.98px) {')

        self.assertIn('min-height: 44px', block)

    def test_form_controls_do_not_trigger_ios_zoom(self):
        # Under 16px iOS zooms the page in on focus and leaves it zoomed,
        # which misframes every screen after the first tap.
        block = media_block(self.css, '@media (max-width: 767.98px) {')
        rule = re.search(r'\.form-control,(.*?)\}', block, re.S)

        self.assertIsNotNone(rule)
        self.assertIn('font-size: 16px', rule.group(1))


class TimetableTests(TestCase):
    """A grid is the one thing that cannot be stacked into cards."""

    def test_both_timetables_scroll_rather_than_overflow(self):
        for name in ('timetable.html', 't_timetable.html'):
            html = Path('info/templates/info/%s' % name).read_text(
                encoding='utf-8')

            self.assertIn('erp-timetable-scroll', html, name)

    def test_the_day_column_stays_put_while_it_scrolls(self):
        css = THEME.read_text(encoding='utf-8')
        rule = re.search(
            r'\.erp-timetable-scroll table th:first-child,\s*'
            r'\.erp-timetable-scroll table td:first-child\s*\{([^}]*)\}', css)

        # Scrolling sideways past the day column leaves you reading a row you
        # can no longer name.
        self.assertIsNotNone(rule)
        self.assertIn('position: sticky', rule.group(1))
