"""The messages the app sends when nobody is looking at it.

Everything here is built to be run from a scheduler, which shapes three
decisions:

- **Nothing is sent twice.** Each message carries a key naming the exact thing
  it reports, and `Notification` has a unique constraint on (user, key). The
  row is claimed before the mail goes out, so two overlapping runs cannot both
  send it.
- **Switching it on does not blast the archive.** The commands look at a
  window - a week by default - rather than at everything ever published. A
  student should not receive sixty notices on the day this is first scheduled.
- **Reminders are digests, one per person per week.** A student with five
  outstanding fees gets one email listing five fees, not five emails. The
  weekly key is what makes an unpaid fee nag rather than mention itself once
  and go quiet.

Each gather function returns a list of `Message`; `send_all()` does the
sending. Splitting the two is what lets `--dry-run` report exactly what would
go out, and what makes the tests able to check the wording without a mail
server.
"""
import logging
from collections import namedtuple
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from .models import (
    ATTENDANCE_THRESHOLD,
    Fee,
    Marks,
    MarksClass,
    Notice,
    Notification,
    Student,
    Teacher,
)
from .services import attendance_rows

logger = logging.getLogger(__name__)

Message = namedtuple('Message', 'user kind key subject body')

Result = namedtuple('Result', 'sent skipped failed')

# How far back a first run looks. Anything older is treated as history that
# people have already seen in the app.
DEFAULT_WINDOW_DAYS = 7
# How long before a fee is due the first reminder goes out.
DEFAULT_DUE_SOON_DAYS = 7

SIGN_OFF = '\n\n--\nCollege ERP\nThis message was sent automatically.\n'


def _week_key(when=None):
    """An ISO week stamp, so a recurring digest recurs weekly and no faster."""
    year, week, _ = (when or timezone.localdate()).isocalendar()
    return '%dW%02d' % (year, week)


def _deliver(message):
    """Send one message, once. True if it left the building."""
    try:
        with transaction.atomic():
            Notification.objects.create(user=message.user, kind=message.kind,
                                        key=message.key,
                                        subject=message.subject[:200])
    except IntegrityError:
        # Somebody else claimed it between the filter and here.
        return False

    try:
        send_mail(message.subject, message.body + SIGN_OFF,
                  settings.DEFAULT_FROM_EMAIL, [message.user.email],
                  fail_silently=False)
    except Exception:
        # Give the row back so the next run retries rather than recording a
        # message that never arrived.
        logger.exception('Could not send %s to user %s', message.key,
                         message.user.pk)
        Notification.objects.filter(user=message.user, key=message.key).delete()
        return False

    return True


def send_all(messages, dry_run=False):
    """Deliver what has not already gone out.

    The `already` lookup is one query for the whole batch; the unique
    constraint underneath it is what actually guarantees the rule.
    """
    messages = [m for m in messages if m.user and m.user.email]
    if not messages:
        return Result(0, 0, 0)

    already = set(
        Notification.objects
        .filter(key__in={m.key for m in messages},
                user__in={m.user.pk for m in messages})
        .values_list('user_id', 'key'))

    sent = skipped = failed = 0
    for message in messages:
        if (message.user.pk, message.key) in already:
            skipped += 1
        elif dry_run:
            sent += 1
        elif _deliver(message):
            sent += 1
        else:
            failed += 1

    return Result(sent, skipped, failed)


# -- fees ------------------------------------------------------------------

def fee_reminders(due_soon_days=DEFAULT_DUE_SOON_DAYS, today=None):
    """One digest per student with fees due soon or already overdue."""
    today = today or timezone.localdate()
    horizon = today + timedelta(days=due_soon_days)

    outstanding = (Fee.objects
                   .filter(paid_amount__lt=F('amount'), amount__gt=0,
                           due_date__lte=horizon,
                           student__is_active=True,
                           student__user__isnull=False)
                   .select_related('student', 'student__user')
                   .order_by('due_date'))

    by_student = {}
    for fee in outstanding:
        by_student.setdefault(fee.student, []).append(fee)

    week = _week_key(today)
    messages = []
    for student, fees in by_student.items():
        overdue = [f for f in fees if f.due_date < today]
        upcoming = [f for f in fees if f.due_date >= today]
        total = sum(f.balance for f in fees)

        lines = ['Hello %s,' % student.name, '']
        if overdue:
            lines.append('Overdue:')
            lines += ['  %s - %s outstanding, was due %s'
                      % (f.fee_type, _money(f.balance), f.due_date.strftime('%d %b %Y'))
                      for f in overdue]
            lines.append('')
        if upcoming:
            lines.append('Due soon:')
            lines += ['  %s - %s outstanding, due %s'
                      % (f.fee_type, _money(f.balance), f.due_date.strftime('%d %b %Y'))
                      for f in upcoming]
            lines.append('')
        lines.append('Total outstanding: %s' % _money(total))
        lines.append('')
        lines.append('Sign in to the ERP to see the full ledger, or contact the '
                     'accounts office if a payment is missing from it.')

        subject = ('Fee overdue: %s outstanding' % _money(total)) if overdue else (
            'Fee due soon: %s outstanding' % _money(total))

        messages.append(Message(
            user=student.user, kind='fee',
            key='fee:%s:%s' % (student.pk, week),
            subject=subject, body='\n'.join(lines)))

    return messages


def _money(amount):
    return 'Rs %s' % f'{amount:,.2f}'


# -- attendance ------------------------------------------------------------

def attendance_alerts(today=None):
    """One digest per student who is below the threshold in any course."""
    today = today or timezone.localdate()
    threshold = ATTENDANCE_THRESHOLD * 100

    # Computed from Attendance itself rather than from AttendanceTotal, whose
    # rows only appear when somebody opens the attendance page - a student
    # nobody has looked at would otherwise never be warned.
    rows = attendance_rows()

    by_student = {}
    for row in rows:
        # has_classes matters: a course that has not met yet reads as 0%, and
        # warning somebody about a course nobody has taught is noise.
        if not (row.has_classes and row.attendance < threshold):
            continue
        student = row.student
        if not (student.is_active and student.user_id):
            continue
        by_student.setdefault(student, []).append(row)

    week = _week_key(today)
    messages = []
    for student, rows_for_student in by_student.items():
        rows_for_student.sort(key=lambda r: r.attendance)
        lines = ['Hello %s,' % student.name, '',
                 'Your attendance is below %d%% in %d course%s:'
                 % (threshold, len(rows_for_student),
                    '' if len(rows_for_student) == 1 else 's'), '']
        for row in rows_for_student:
            lines.append('  %s - %.2f%% (%d of %d), attend %d more in a row to '
                         'reach %d%%'
                         % (row.course.name, row.attendance, row.att_class,
                            row.total_class, row.classes_to_attend, threshold))
        lines += ['', 'Attendance is checked against %d%% for exam eligibility. '
                      'Speak to the class teacher if any of these is wrong.'
                  % threshold]

        messages.append(Message(
            user=student.user, kind='attendance',
            key='attendance:%s:%s' % (student.pk, week),
            subject='Attendance below %d%% in %d course%s'
                    % (threshold, len(rows_for_student),
                       '' if len(rows_for_student) == 1 else 's'),
            body='\n'.join(lines)))

    return messages


# -- marks -----------------------------------------------------------------

def marks_release_alerts(window_days=DEFAULT_WINDOW_DAYS, now=None):
    """Tell a class its marks are out, once per published batch."""
    now = now or timezone.now()
    since = now - timedelta(days=window_days)

    batches = (MarksClass.objects
               .filter(is_published=True, published_at__gte=since)
               .select_related('assign__course', 'assign__class_id'))

    messages = []
    for batch in batches:
        students = (Student.objects
                    .filter(class_id=batch.assign.class_id, is_active=True,
                            user__isnull=False)
                    .select_related('user'))
        scores = {
            m.studentcourse.student_id: m
            for m in Marks.objects
            .filter(name=batch.name,
                    studentcourse__course=batch.assign.course,
                    studentcourse__student__class_id=batch.assign.class_id)
            .select_related('studentcourse')
        }

        course = batch.assign.course
        subject = '%s marks published: %s' % (batch.name, course.shortname)
        for student in students:
            mark = scores.get(student.pk)
            if mark is None:
                # No row for this student - nothing to tell them yet.
                continue
            scored = ('absent' if mark.is_absent
                      else '%d out of %d' % (mark.marks1, mark.total_marks))
            body = '\n'.join([
                'Hello %s,' % student.name, '',
                'Your %s marks for %s (%s) have been published.'
                % (batch.name, course.name, course.shortname), '',
                '  Your result: %s' % scored, '',
                'Sign in to the ERP to see this alongside your other '
                'components and your CIE total. If you think a mark is wrong, '
                'raise it with the course teacher.',
            ])
            messages.append(Message(
                user=student.user, kind='marks',
                key='marks:%d:%s' % (batch.pk, student.pk),
                subject=subject, body=body))

    return messages


# -- notices ---------------------------------------------------------------

def notice_alerts(window_days=DEFAULT_WINDOW_DAYS, now=None):
    """Email a newly published notice to the audience it names."""
    now = now or timezone.now()
    since = now - timedelta(days=window_days)

    notices = (Notice.objects
               .filter(is_published=True, published_at__gte=since)
               .order_by('published_at'))

    messages = []
    for notice in notices:
        if notice.is_expired:
            continue

        recipients = []
        if notice.audience in ('All', 'Students'):
            recipients += [s.user for s in Student.objects
                           .filter(is_active=True, user__isnull=False)
                           .select_related('user')]
        if notice.audience in ('All', 'Teachers'):
            recipients += [t.user for t in Teacher.objects
                           .filter(is_active=True, user__isnull=False)
                           .select_related('user')]

        body_lines = ['A notice has been posted on the ERP.', '',
                      notice.title, '', notice.message]
        if notice.expires_at:
            body_lines += ['', 'This notice applies until %s.'
                           % notice.expires_at.strftime('%d %b %Y')]
        body = '\n'.join(body_lines)

        for user in recipients:
            messages.append(Message(
                user=user, kind='notice', key='notice:%d' % notice.pk,
                subject='[%s] %s' % (notice.category, notice.title),
                body=body))

    return messages


# Kept for the commands to import as one list rather than four names.
GATHERERS = {
    'fee': fee_reminders,
    'attendance': attendance_alerts,
    'marks': marks_release_alerts,
    'notice': notice_alerts,
}
