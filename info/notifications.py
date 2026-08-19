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
from django.db.models import F
from django.urls import reverse
from django.utils import timezone

from .models import (
    ATTENDANCE_THRESHOLD,
    Assign,
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

Message = namedtuple('Message', 'user kind key subject body url')

Result = namedtuple('Result', 'sent skipped failed recorded')

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


def _record(message):
    """Put the notification in the recipient's list. Returns (row, created)."""
    return Notification.objects.get_or_create(
        user=message.user, key=message.key,
        defaults={'kind': message.kind, 'subject': message.subject[:200],
                  'body': message.body, 'url': message.url})


def _email(record, message):
    """Try to deliver `record` by mail. True if it left the building."""
    try:
        send_mail(message.subject, message.body + SIGN_OFF,
                  settings.DEFAULT_FROM_EMAIL, [message.user.email],
                  fail_silently=False)
    except Exception:
        # The row stays: the person can still see the notification when they
        # sign in, and emailed_at being null is what makes the next run try
        # again rather than treating a failure as delivered.
        logger.exception('Could not email %s to user %s', message.key,
                         message.user.pk)
        return False

    record.emailed_at = timezone.now()
    record.save(update_fields=['emailed_at'])
    return True


def send_all(messages, dry_run=False):
    """Record what has happened, and email whoever can be emailed.

    Recording and emailing are separate on purpose. A student with no address
    on their account is still told - they just have to sign in to find out -
    and a mail server that is down costs a delivery, not the notification.
    """
    messages = [m for m in messages if m.user]
    if not messages:
        return Result(0, 0, 0, 0)

    if dry_run:
        existing = dict(
            Notification.objects
            .filter(key__in={m.key for m in messages},
                    user__in={m.user.pk for m in messages})
            .values_list('key', 'emailed_at'))
        recorded = sum(1 for m in messages if m.key not in existing)
        sendable = [m for m in messages
                    if m.user.email and existing.get(m.key) is None]
        return Result(len(sendable), len(messages) - len(sendable), 0, recorded)

    sent = skipped = failed = recorded = 0
    for message in messages:
        record, created = _record(message)
        recorded += int(created)

        if record.emailed_at is not None or not message.user.email:
            skipped += 1
        elif _email(record, message):
            sent += 1
        else:
            failed += 1

    return Result(sent, skipped, failed, recorded)


def record_only(messages):
    """Add notifications without mailing anything.

    Used where the app already knows something the moment it happens - a
    notice going up, a batch of marks being released - so the app can show it
    straight away and the scheduled run only has the mail left to do.
    """
    created = 0
    for message in messages:
        if message.user:
            _, was_created = _record(message)
            created += int(was_created)
    return created


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
            subject=subject, body='\n'.join(lines),
            url=reverse('fees', args=[student.pk])))

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
            url=reverse('attendance', args=[student.pk]),
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
        messages += messages_for_batch(batch)
    return messages


def messages_for_batch(batch):
    """One message per student in the class, carrying their own mark."""
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

    messages = []
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
            subject=subject, body=body,
            url=reverse('marks_list', args=[student.pk])))

    return messages


# -- mark queries ----------------------------------------------------------

def messages_for_query_raised(query):
    """Tell the teacher a mark of theirs has been questioned."""
    teacher = _teacher_for(query)
    if teacher is None or teacher.user is None:
        return []

    mark = query.marks
    body = '\n'.join([
        'Hello %s,' % teacher.name, '',
        '%s (%s) has questioned their %s in %s.'
        % (query.student.name, query.student.pk, mark.name,
           mark.studentcourse.course.name), '',
        'Current mark: %d out of %d' % (mark.marks1, mark.total_marks), '',
        'What they said:', query.reason, '',
        'Open the ERP to look at it again and either correct the mark or '
        'explain why it stands.',
    ])
    return [Message(user=teacher.user, kind='query',
                    key='query:%d:raised' % query.pk,
                    subject='Mark queried: %s, %s'
                            % (mark.studentcourse.course.shortname, mark.name),
                    body=body, url=reverse('mark_queries'))]


def messages_for_query_resolved(query):
    """Tell the student what came of it."""
    if query.student.user is None:
        return []

    mark = query.marks
    body = '\n'.join([
        'Hello %s,' % query.student.name, '',
        'Your query about %s in %s has been reviewed.'
        % (mark.name, mark.studentcourse.course.name), '',
        '  Outcome: %s' % query.outcome, '',
        ('What the teacher said:' + '\n' + query.response
         if query.response else ''),
        '',
        'Your marks page shows the current figure.',
    ])
    return [Message(user=query.student.user, kind='query',
                    key='query:%d:%s' % (query.pk, query.status),
                    subject='Mark query %s: %s'
                            % (query.status, mark.studentcourse.course.shortname),
                    body=body,
                    url=reverse('marks_list', args=[query.student.pk]))]


def _teacher_for(query):
    """Whoever teaches the course to that student's class."""
    assign = (Assign.objects
              .filter(class_id=query.student.class_id_id,
                      course=query.marks.studentcourse.course_id)
              .select_related('teacher__user')
              .first())
    return assign.teacher if assign else None


# -- notices ---------------------------------------------------------------

def notice_alerts(window_days=DEFAULT_WINDOW_DAYS, now=None):
    """Announce recently published notices to the audience they name."""
    now = now or timezone.now()
    since = now - timedelta(days=window_days)

    notices = (Notice.objects
               .filter(is_published=True, published_at__gte=since)
               .order_by('published_at'))

    messages = []
    for notice in notices:
        messages += messages_for_notice(notice)
    return messages


def messages_for_notice(notice):
    """One message per person the notice is addressed to."""
    if not notice.is_published or notice.is_expired:
        return []

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

    return [Message(user=user, kind='notice', key='notice:%d' % notice.pk,
                    subject='[%s] %s' % (notice.category, notice.title),
                    body=body, url=reverse('notice_detail', args=[notice.pk]))
            for user in recipients]


def announce(messages):
    """Record now, mail later - what the app calls when an event happens."""
    return record_only(messages)


# Kept for the commands to import as one list rather than four names.
GATHERERS = {
    'fee': fee_reminders,
    'attendance': attendance_alerts,
    'marks': marks_release_alerts,
    'notice': notice_alerts,
}
