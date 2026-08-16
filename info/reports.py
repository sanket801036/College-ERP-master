"""PDF generation.

reportlab has been an installed, unused dependency since the beginning. This is
the first thing to use it: a marks card a student can hand to a parent or an
office, which is what people actually want off a marks page.

Everything here is laid out by hand rather than through platypus templates -
one page, a fixed structure, and no need for flowables.
"""
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from info.models import CIE_MAX, SEE_MAX

# Matches --erp-primary in theme.css, so the PDF looks like the app it came from.
PRIMARY = colors.HexColor('#4f46e5')
INK = colors.HexColor('#1e293b')
MUTED = colors.HexColor('#64748b')
RULE = colors.HexColor('#e2e8f0')

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm


def _header(pdf, student, subtitle):
    pdf.setFillColor(PRIMARY)
    pdf.rect(0, PAGE_H - 30 * mm, PAGE_W, 30 * mm, stroke=0, fill=1)

    pdf.setFillColor(colors.white)
    pdf.setFont('Helvetica-Bold', 16)
    pdf.drawString(MARGIN, PAGE_H - 15 * mm, 'College ERP')
    pdf.setFont('Helvetica', 10)
    pdf.drawString(MARGIN, PAGE_H - 21 * mm, subtitle)

    pdf.setFillColor(INK)
    pdf.setFont('Helvetica-Bold', 13)
    pdf.drawString(MARGIN, PAGE_H - 42 * mm, student.name)
    pdf.setFont('Helvetica', 9)
    pdf.setFillColor(MUTED)
    pdf.drawString(MARGIN, PAGE_H - 48 * mm,
                   '%s   ·   %s' % (student.USN, student.class_id))


# Column positions, in mm from the left margin, with the alignment of each.
# Absolute rather than accumulated widths: an earlier version added widths as
# it went and put the last three columns at x = 872, 1323 and 1828pt on a
# 595pt page, so they were drawn but never visible. The last right edge lands
# exactly on PAGE_W - MARGIN.
COLUMNS = (
    (0, 'left'),        # Course
    (86, 'right'),      # CIE
    (116, 'right'),     # SEE
    (146, 'right'),     # Final
    (174, 'right'),     # Grade
)


def _row(pdf, y, cells, bold=False, colour=INK):
    pdf.setFont('Helvetica-Bold' if bold else 'Helvetica', 9)
    pdf.setFillColor(colour)
    for cell, (offset, align) in zip(cells, COLUMNS):
        x = MARGIN + offset * mm
        if align == 'right':
            pdf.drawRightString(x, y, str(cell))
        else:
            pdf.drawString(x, y, str(cell))
    return y


def report_card(student, rows, sgpa, generated_on):
    """A one-page marks card.

    `rows` is the same StudentCourse list the marks page renders, with its
    caches already attached - this deliberately computes nothing itself, so the
    paper and the screen cannot disagree.
    """
    from io import BytesIO

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setTitle('%s - marks card' % student.USN)

    _header(pdf, student, 'Statement of marks')

    y = PAGE_H - 60 * mm
    headings = ['Course', 'CIE', 'SEE', 'Final', 'Grade']

    _row(pdf, y, headings, bold=True, colour=MUTED)
    y -= 3 * mm
    pdf.setStrokeColor(RULE)
    pdf.line(MARGIN, y, PAGE_W - MARGIN, y)
    y -= 6 * mm

    for sc in rows:
        see = sc.get_see()
        final = sc.final_marks
        grade = sc.grade
        _row(pdf, y, [
            sc.course.name[:38],
            '%s / %d' % (sc.get_cie(), CIE_MAX),
            '%s / %d' % (see, SEE_MAX) if see is not None else 'Pending',
            '%.1f' % final if final is not None else '-',
            '%s (%d)' % grade if grade else '-',
        ])
        y -= 7 * mm
        if y < 45 * mm:                    # leave room for the footer block
            pdf.showPage()
            _header(pdf, student, 'Statement of marks (continued)')
            y = PAGE_H - 60 * mm

    y -= 4 * mm
    pdf.setStrokeColor(RULE)
    pdf.line(MARGIN, y, PAGE_W - MARGIN, y)
    y -= 10 * mm

    pdf.setFont('Helvetica-Bold', 11)
    pdf.setFillColor(INK)
    if sgpa is not None:
        pdf.drawString(MARGIN, y, 'SGPA  %.2f / 10' % sgpa)
    else:
        # Saying nothing beats printing a figure that cannot be computed yet.
        pdf.drawString(MARGIN, y, 'SGPA  not available')
        pdf.setFont('Helvetica', 8)
        pdf.setFillColor(MUTED)
        pdf.drawString(MARGIN + 42 * mm, y,
                       'no semester-end result published yet')

    pdf.setFont('Helvetica', 8)
    pdf.setFillColor(MUTED)
    pdf.drawString(MARGIN, 15 * mm,
                   'Generated %s. Shows published results only; '
                   'not a substitute for the official transcript.'
                   % generated_on.strftime('%d %b %Y'))

    pdf.showPage()
    pdf.save()
    buffer.seek(0)
    return buffer
