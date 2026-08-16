from datetime import date

from django.template import Context, Template
from django.test import TestCase, override_settings
from django.urls import reverse

from info.models import Attendance, AttendanceClass, AssignTime
from info.templatetags.charts import attendance_trend, meter, zone_for
from info.tests import factories as f


class Session:
    """The two attributes attendance_trend reads off an Attendance row."""

    def __init__(self, day, present):
        self.date = date(2026, 8, day)
        self.status = present


class ZoneTests(TestCase):
    def test_at_the_threshold_is_safe(self):
        self.assertEqual(zone_for(75), 'safe')

    def test_just_below_the_threshold_is_at_risk(self):
        self.assertEqual(zone_for(74.9), 'risk')

    def test_below_sixty_five_is_critical(self):
        self.assertEqual(zone_for(64.9), 'critical')

    def test_zero_is_critical(self):
        self.assertEqual(zone_for(0), 'critical')


class MeterTests(TestCase):
    def test_geometry_is_clamped_but_the_number_is_not(self):
        """A percentage over 100 must not draw a bar past the track - but the
        printed value stays whatever the data actually said."""
        context = meter(140)

        self.assertEqual(context['width'], 100)
        self.assertEqual(context['percent'], 140)

    def test_negative_does_not_draw_backwards(self):
        self.assertEqual(meter(-10)['width'], 0)

    def test_none_reads_as_zero(self):
        self.assertEqual(meter(None)['width'], 0)

    def test_state_carries_a_word_and_an_icon_not_just_colour(self):
        context = meter(40)

        self.assertEqual(context['label'], 'Critical')
        self.assertTrue(context['icon'])

    def test_zones_follow_the_threshold_they_are_given(self):
        """A CIE meter reads against 40, not attendance's 75 - pinning the
        bands to 75 called a passing CIE critical."""
        self.assertEqual(zone_for(42, threshold=40), 'safe')
        self.assertEqual(zone_for(35, threshold=40), 'risk')
        self.assertEqual(zone_for(20, threshold=40), 'critical')

    def test_an_unsettled_ratio_withholds_the_verdict(self):
        context = meter(42, threshold=40, settled=False)

        self.assertEqual(context['zone'], 'pending')
        self.assertEqual(context['label'], 'In progress')

    def test_renders_the_threshold_marker(self):
        html = Template(
            '{% load charts %}{% meter 83 %}'
        ).render(Context({}))

        self.assertIn('erp-meter-safe', html)
        self.assertIn('left: 75%', html)
        self.assertIn('Safe', html)


class TrendTests(TestCase):
    def test_no_sessions_renders_nothing(self):
        html = Template(
            '{% load charts %}{% attendance_trend rows %}'
        ).render(Context({'rows': []}))

        self.assertNotIn('<svg', html)

    def test_running_percentage_is_cumulative_not_per_session(self):
        rows = [Session(1, True), Session(2, False), Session(3, True),
                Session(4, True)]

        points = attendance_trend(rows)['points']

        self.assertEqual([p['percent'] for p in points], [100.0, 50.0, 66.7, 75.0])

    def test_a_single_session_is_not_a_trend(self):
        """One point draws an empty plot with a lone dot and says nothing the
        table row below does not."""
        self.assertEqual(attendance_trend([Session(1, True)])['points'], [])

    def test_two_sessions_span_the_plot(self):
        context = attendance_trend([Session(1, True), Session(2, False)])

        self.assertEqual(context['points'][0]['x'], context['left'])
        self.assertEqual(context['points'][-1]['x'], context['plot_right'])

    def test_the_line_ends_where_the_last_point_is(self):
        rows = [Session(1, True), Session(2, False)]

        context = attendance_trend(rows)

        self.assertEqual(context['last'], context['points'][-1])
        self.assertTrue(context['line'].endswith(
            '%s,%s' % (context['last']['x'], context['last']['y'])))

    def test_the_area_closes_on_the_baseline(self):
        context = attendance_trend([Session(1, True), Session(2, True)])

        self.assertTrue(context['area'].endswith('Z'))
        self.assertIn(str(context['baseline']), context['area'])

    def test_zone_follows_where_the_line_ended(self):
        all_absent = [Session(1, False), Session(2, False)]

        self.assertEqual(attendance_trend(all_absent)['zone'], 'critical')

    def test_hit_targets_tile_the_plot_without_gaps(self):
        """A 2px dot is not a hover target. The bands are as wide as the
        spacing, so there is nowhere between two points to land and get
        nothing - which matters most on a dense semester, where the spacing
        falls below a comfortable 24px."""
        rows = [Session(day, True) for day in range(1, 26)]

        points = attendance_trend(rows)['points']

        for earlier, later in zip(points, points[1:]):
            self.assertAlmostEqual(earlier['hit_x'] + earlier['hit_w'],
                                   later['hit_x'], places=1)

    def test_hit_targets_are_comfortable_when_there_is_room(self):
        rows = [Session(day, True) for day in range(1, 11)]

        points = attendance_trend(rows)['points']

        self.assertTrue(all(p['hit_w'] >= 24 for p in points))

    def test_only_the_endpoint_is_labelled(self):
        rows = [Session(1, True), Session(2, False), Session(3, True)]
        html = Template(
            '{% load charts %}{% attendance_trend rows %}'
        ).render(Context({'rows': rows}))

        self.assertEqual(html.count('erp-chart-endlabel'), 1)


class LocalisationTests(TestCase):
    """Geometry is not a number to be formatted for a reader.

    Under a locale that uses a comma as the decimal separator, an unguarded
    {{ x }} renders "38,5" straight into an SVG attribute or a CSS length and
    the chart silently falls apart.
    """

    @override_settings(USE_THOUSAND_SEPARATOR=True, LANGUAGE_CODE='de')
    def test_trend_coordinates_survive_a_comma_decimal_locale(self):
        rows = [Session(day, day % 2 == 0) for day in range(1, 13)]

        html = Template(
            '{% load charts %}{% attendance_trend rows %}'
        ).render(Context({'rows': rows}))

        self.assertIn('viewBox="0 0 640 200"', html)
        self.assertNotIn(',5"', html)
        self.assertNotIn('38,', html)

    @override_settings(USE_THOUSAND_SEPARATOR=True, LANGUAGE_CODE='de')
    def test_meter_width_survives_a_comma_decimal_locale(self):
        html = Template(
            '{% load charts %}{% meter 71.4 %}'
        ).render(Context({}))

        self.assertIn('width: 71.4%', html)


class TemplateCommentTests(TestCase):
    """Django's {# #} comment is single-line only.

    A multi-line one is not a comment at all - the text renders into the page.
    Inside an <svg> it is invisible, which is how several survived unnoticed
    until a chart comment landed outside one and appeared on screen.
    """

    def test_no_template_uses_a_multiline_hash_comment(self):
        import glob
        import re

        offenders = []
        for path in glob.glob('info/templates/**/*.html', recursive=True):
            with open(path, encoding='utf-8', errors='replace') as handle:
                body = handle.read()
            for match in re.finditer(r'\{#(.*?)#\}', body, re.S):
                if '\n' in match.group(1):
                    offenders.append(path)

        self.assertEqual(offenders, [],
                         'these need a block comment tag: ' + repr(offenders))


class AttendancePageTests(TestCase):
    """The charts have to survive the real pages, not just the tag."""

    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        self.student = f.make_student(self.klass, username='pupil')
        self.course = f.make_course(dept)
        teacher = f.make_teacher(dept, id='t001', username='owner')
        self.assign = f.make_assign(self.klass, self.course, teacher)
        AssignTime.objects.create(assign=self.assign, day='Monday',
                                  period='7:30 - 8:30')

    def hold_session(self, day=17, present=True):
        session = AttendanceClass.objects.create(
            assign=self.assign, date=date(2026, 8, day), status=1)
        Attendance.objects.create(student=self.student, course=self.course,
                                  attendanceclass=session,
                                  date=session.date, status=present)
        return session

    def test_summary_page_renders_a_meter_per_course(self):
        self.hold_session()
        self.client.force_login(self.student.user)

        response = self.client.get(
            reverse('attendance', args=(self.student.pk,)))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'erp-meter-track')

    def test_a_course_with_no_sessions_shows_no_meter(self):
        """A course that has not met yet must not render as a red 0% meter."""
        self.client.force_login(self.student.user)

        response = self.client.get(
            reverse('attendance', args=(self.student.pk,)))

        self.assertContains(response, 'No classes held yet')
        self.assertNotContains(response, 'erp-meter-track')

    def test_detail_page_renders_the_trend_above_the_table(self):
        self.hold_session(day=17, present=True)
        self.hold_session(day=18, present=False)
        self.client.force_login(self.student.user)

        response = self.client.get(reverse(
            'attendance_detail', args=(self.student.pk, self.course.pk)))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'erp-chart-line')

    def test_detail_page_without_sessions_skips_the_chart(self):
        self.client.force_login(self.student.user)

        response = self.client.get(reverse(
            'attendance_detail', args=(self.student.pk, self.course.pk)))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'erp-chart-line')

    def test_detail_page_with_one_session_renders_no_empty_chart_card(self):
        """The card wrapper has to agree with the tag, or it renders a
        headed, empty box."""
        self.hold_session()
        self.client.force_login(self.student.user)

        response = self.client.get(reverse(
            'attendance_detail', args=(self.student.pk, self.course.pk)))

        self.assertNotContains(response, 'attendance trend')
