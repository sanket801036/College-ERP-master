"""Chart helpers that compute geometry in Python and render inline SVG/CSS.

Deliberately no chart library. The pages are server-rendered and static files
go out through whitenoise, so a CDN <script> tag would be one more thing to
fail offline, behind a proxy, or on a locked-down college network - and it
would put the numbers out of reach of the print stylesheet. Everything here
hands the template plain numbers.

Two forms, picked by the job the data does:

* `meter` - one ratio against a limit (75% attendance, 40% CIE for exam
  eligibility). A meter, not a donut:
  a two-slice ring is a pie of two slices, and the reader's real question is
  "am I above the line", which a track with a threshold marker answers
  directly.
* `attendance_trend` - one series over time. A line with a 10%-opacity area
  wash, labelled only at the endpoint.

Colour never carries meaning on its own here: every meter ships an icon and a
word, and every chart sits above the table it summarises.
"""
from django import template

register = template.Library()

# The attendance rule, and the default limit a meter is read against.
SAFE_FLOOR = 75

# How far below the limit still counts as a warning rather than a failure.
# Relative to the limit, so the same bands work for a 75% attendance rule and a
# 40% exam-eligibility rule.
RISK_MARGIN = 10

ZONES = {
    'safe': {'label': 'Safe', 'icon': 'fa-check-circle'},
    'risk': {'label': 'At risk', 'icon': 'fa-exclamation-triangle'},
    'critical': {'label': 'Critical', 'icon': 'fa-times-circle'},
    # For a ratio still being accumulated. A verdict on a running subtotal is
    # not a verdict - a CIE of 21/50 with two components unsat is neither safe
    # nor failing, and calling it either misleads.
    'pending': {'label': 'In progress', 'icon': 'fa-hourglass-half'},
}


def zone_for(percent, threshold=SAFE_FLOOR):
    """Which severity band a percentage falls in, relative to its own limit."""
    if percent >= threshold:
        return 'safe'
    if percent >= threshold - RISK_MARGIN:
        return 'risk'
    return 'critical'


@register.inclusion_tag('info/charts/meter.html')
def meter(percent, threshold=SAFE_FLOOR, subject='Attendance', settled=True):
    """A single ratio against a limit.

    The unfilled track is a lighter step of the fill's own hue rather than a
    neutral grey, so the state reads across the whole bar and not just the
    filled part. `threshold` is the limit the reader is judged against - 75 for
    the attendance rule, 40 for exam eligibility - and the zones follow it
    rather than being pinned to attendance's numbers.

    Pass settled=False while the ratio is still a running subtotal; the bar
    still draws, but it withholds the verdict instead of guessing one.
    """
    percent = float(percent or 0)
    zone = zone_for(percent, threshold) if settled else 'pending'
    return {
        'percent': percent,
        # Only the geometry is clamped - the printed number stays honest.
        'width': max(0.0, min(100.0, percent)),
        'threshold': threshold,
        'subject': subject,
        'zone': zone,
        'label': ZONES[zone]['label'],
        'icon': ZONES[zone]['icon'],
    }


@register.inclusion_tag('info/charts/trend_line.html')
def attendance_trend(sessions, threshold=SAFE_FLOOR):
    """Running attendance percentage after each session, oldest first.

    `sessions` is any iterable of objects with `.date` and a boolean `.status`
    - i.e. the Attendance rows the detail page already lists below the chart.
    """
    rows = list(sessions)
    # One session is a dot, not a trend - it says nothing the row in the table
    # below does not, and renders as an empty plot with a single marker.
    if len(rows) < 2:
        return {'points': []}

    # Plot box. The height leaves room for the x-axis band underneath rather
    # than letting the labels fall outside the viewBox.
    width, height = 640, 200
    left, right, top, bottom = 38, 52, 12, 28
    plot_w = width - left - right
    plot_h = height - top - bottom

    def x_at(index):
        return left + plot_w * index / (len(rows) - 1)

    def y_at(percent):
        return top + plot_h * (1 - percent / 100)

    # Hover bands are one point-spacing wide and centred on their point, so
    # they tile the plot with no dead gap between them - the spacing is
    # plot_w/(n-1), not plot_w/n, which is a point-fencepost apart and leaves a
    # ~1px strip that hovers nothing. Capped so a three-session course does not
    # get absurdly wide bands.
    band = min(48, plot_w / (len(rows) - 1))

    points = []
    attended = 0
    for index, row in enumerate(rows):
        attended += 1 if row.status else 0
        percent = attended / (index + 1) * 100
        points.append({
            'x': round(x_at(index), 2),
            'y': round(y_at(percent), 2),
            'percent': round(percent, 1),
            'date': row.date,
            'present': bool(row.status),
            'hit_x': round(x_at(index) - band / 2, 2),
            'hit_w': round(band, 2),
        })

    line = ' '.join('%s,%s' % (p['x'], p['y']) for p in points)
    baseline = top + plot_h
    area = 'M %s,%s L %s L %s,%s Z' % (
        points[0]['x'], baseline, line, points[-1]['x'], baseline)

    last = points[-1]
    return {
        'points': points,
        'line': line,
        'area': area,
        'last': last,
        'zone': zone_for(last['percent']),
        'width': width,
        'height': height,
        'left': left,
        'plot_right': width - right,
        'baseline': baseline,
        'top': top,
        'plot_h': plot_h,
        'threshold': threshold,
        'threshold_y': round(y_at(threshold), 2),
        # Solid hairlines only; the threshold gets its own weight and a label
        # so it is not mistaken for one of these.
        'gridlines': [{'percent': p, 'y': round(y_at(p), 2)} for p in (0, 50, 100)],
    }
