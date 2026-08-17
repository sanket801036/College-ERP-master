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


@register.inclusion_tag('info/charts/bar_chart.html')
def bar_chart(rows, max_value=None, caption='', unit='', highlight=None):
    """Horizontal bars for comparing magnitude.

    One hue, because the bars are one series - colouring each bar differently
    would spend the identity channel re-encoding what bar length already shows.
    `highlight` names one row to pick out in the accent colour with the rest in
    grey, which is the honest form when the story is about a single entry.

    `rows` is (label, value) pairs. Horizontal rather than vertical so class
    names and mark bands both fit without turning the labels sideways.
    """
    rows = [(str(label), float(value)) for label, value in rows]
    if not rows:
        return {'bars': []}

    top = max_value if max_value is not None else max(v for _, v in rows)
    # A zero scale would divide by zero and a chart of all-zeros is honestly
    # empty anyway; keep the axis but draw nothing.
    scale = top or 1

    width = 640
    label_w, value_w = 150, 54
    plot_left = label_w
    plot_w = width - label_w - value_w
    row_h, bar_h = 26, 14
    height = row_h * len(rows) + 24

    bars = []
    for index, (label, value) in enumerate(rows):
        y = index * row_h + 4
        length = max(0.0, min(1.0, value / scale)) * plot_w
        bars.append({
            'label': label,
            'value': value,
            'display': _fmt(value),
            'y': y,
            'text_y': y + bar_h - 2,
            # Square at the baseline, rounded at the data end - and the radius
            # collapses on a stub so a 2px bar is not drawn as a lozenge.
            'path': _bar_path(plot_left, y, length, bar_h),
            'value_x': plot_left + length + 8,
            'muted': highlight is not None and label != highlight,
        })

    return {
        'bars': bars,
        'caption': caption,
        'unit': unit,
        'width': width,
        'height': height,
        'plot_left': plot_left,
        'plot_right': plot_left + plot_w,
        'axis_y': height - 18,
        'top': top,
        'top_display': _fmt(top),
    }


def _fmt(value):
    """Counts are whole things. "3.0 students" is a float leaking into prose."""
    return '%g' % value


def _bar_path(x, y, length, thickness, radius=4):
    """A bar with square corners at the baseline and rounded ones at the tip."""
    r = min(radius, length)
    if r <= 0:
        return ''
    right = x + length
    return ('M %s,%s L %s,%s Q %s,%s %s,%s L %s,%s Q %s,%s %s,%s L %s,%s Z' % (
        round(x, 2), round(y, 2),
        round(right - r, 2), round(y, 2),
        round(right, 2), round(y, 2), round(right, 2), round(y + r, 2),
        round(right, 2), round(y + thickness - r, 2),
        round(right, 2), round(y + thickness, 2),
        round(right - r, 2), round(y + thickness, 2),
        round(x, 2), round(y + thickness, 2)))


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


@register.inclusion_tag('info/charts/sparkline.html')
def sparkline(points, max_value, caption=''):
    """A small multiple: one course's internals, in order.

    Deliberately not one multi-series line across every subject. Five courses on
    one plot needs a categorical palette, a legend and a colour-vision pass to
    say something each subject answers on its own - and the reader's question
    here is "am I climbing or slipping in this one", which a single line beside
    its own row answers directly.

    `points` is the (label, marks, total) run from
    StudentCourse.internal_trend().
    """
    rows = list(points)
    # Two points make a direction; one is just the mark, which the row already
    # shows.
    if len(rows) < 2:
        return {'points': []}

    width, height = 132, 34
    pad_x, pad_y = 4, 6
    plot_w = width - pad_x * 2
    plot_h = height - pad_y * 2
    scale = max_value or 1

    coords = []
    for index, row in enumerate(rows):
        x = pad_x + plot_w * index / (len(rows) - 1)
        y = pad_y + plot_h * (1 - min(1.0, row['marks'] / scale))
        coords.append({'x': round(x, 2), 'y': round(y, 2),
                       'label': row['label'], 'marks': row['marks'],
                       'total': row['total']})

    first, last = coords[0], coords[-1]
    direction = ('up' if last['marks'] > first['marks']
                 else 'down' if last['marks'] < first['marks']
                 else 'flat')

    return {
        'points': coords,
        'line': ' '.join('%s,%s' % (c['x'], c['y']) for c in coords),
        'last': last,
        'direction': direction,
        # Stated in words as well as slope, so the direction is not carried by
        # the shape alone.
        'summary': '%s to %s out of %s across %d internals'
                   % (first['marks'], last['marks'], last['total'], len(coords)),
        'width': width,
        'height': height,
        'caption': caption,
    }
