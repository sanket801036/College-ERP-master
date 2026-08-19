"""Application logic shared by the web views and the API.

Attendance and marks can each be submitted from two places. Keeping the rules
here rather than in either caller stops the two from drifting - an API that
reimplemented them would quietly become a way around the checks the web forms
perform.
"""
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from info.models import (  # noqa: F401
    CLASS_TAKEN,
    QUERY_ACCEPTED,
    QUERY_REJECTED,
    QUERY_WINDOW,
    QUERY_WITHDRAWN,
    Attendance,
    AttendanceClass,
    AttendanceTotal,
    AuditLog,
    Course,
    MarkQuery,
    Student,
    StudentCourse,
)


class SessionNotMarkable(Exception):
    """Raised when a session is cancelled, in the future, or otherwise closed."""

    def __init__(self, session):
        self.session = session
        super().__init__('That session cannot be marked: it is %s.'
                         % session.state)


@transaction.atomic
def submit_attendance(session, present_usns, actor):
    """Record attendance for every student in the session's class.

    `present_usns` is the set of students marked present; anybody in the class
    and not in it is recorded absent. A missing entry is deliberately not an
    error - the web form always submits one per student, so this only shapes
    what a malformed or partial payload does, and absent is the safe reading.

    Returns (created, changed): whether this was the first submission, and the
    number of students whose status actually moved.
    """
    if not session.is_markable:
        raise SessionNotMarkable(session)

    assign = session.assign
    course = assign.course
    present_usns = set(present_usns)

    resubmission = session.status == CLASS_TAKEN
    previous = {a.student_id: a.status
                for a in Attendance.objects.filter(attendanceclass=session)}

    entries = []
    for student in assign.class_id.student_set.all():
        present = student.USN in present_usns
        Attendance.objects.update_or_create(
            course=course, student=student, attendanceclass=session,
            defaults={'status': present, 'date': session.date},
        )
        was = previous.get(student.USN)
        # On a first submission there is nothing to compare against, so the
        # batch is logged rather than a change per student.
        if resubmission and was is not None and was != present:
            entries.append(AuditLog(
                actor=actor, actor_name=getattr(actor, 'username', ''),
                action='attendance.changed', target_type='Attendance',
                student=student, student_name=student.name,
                summary='%s on %s for %s' % (
                    'Marked present' if present else 'Marked absent',
                    session.date, course.id),
                changes={'status': {'from': was, 'to': present}},
            ))
    AuditLog.record_many(entries)

    if not resubmission:
        AuditLog.record(
            actor=actor, action='attendance.marked', target=session,
            summary='Attendance submitted for %s on %s'
                    % (assign.class_id, session.date))

    session.status = CLASS_TAKEN
    session.save(update_fields=['status'])

    return (not resubmission), len(entries)


@transaction.atomic
def submit_marks(marks_class, scores, actor):
    """Record one component's marks for a whole class.

    `scores` maps a Student to (mark, absent). Callers are responsible for
    validating the marks against the component's ceiling - the web form uses
    MarksEntryForm and the API its serializer - because the two report failures
    differently, but everything that touches the database happens here.

    Returns (first_entry, changed).
    """
    course = marks_class.assign.course
    revision = marks_class.status

    entries = []
    for student, (scored, absent) in scores.items():
        # get_or_create rather than get: a student without a StudentCourse row
        # used to raise DoesNotExist and take down the whole batch.
        sc, _ = StudentCourse.objects.get_or_create(course=course,
                                                    student=student)
        existing = sc.marks_set.filter(name=marks_class.name).first()
        was = existing.marks1 if existing else None
        sc.marks_set.update_or_create(
            name=marks_class.name,
            defaults={'marks1': scored, 'is_absent': absent})

        # Overwriting a grade with no record of the old value is the gap people
        # ask about first.
        if revision and was is not None and was != scored:
            entries.append(AuditLog(
                actor=actor, actor_name=getattr(actor, 'username', ''),
                action='marks.changed', target_type='Marks',
                student=student, student_name=student.name,
                summary='%s for %s changed from %s to %s'
                        % (marks_class.name, course.id, was, scored),
                changes={'marks1': {'from': was, 'to': scored}},
            ))
    AuditLog.record_many(entries)

    if not revision:
        AuditLog.record(
            actor=actor, action='marks.entered', target=marks_class,
            summary='%s entered for %s (%d students)'
                    % (marks_class.name, marks_class.assign.class_id,
                       len(scores)))

    marks_class.status = True
    marks_class.save(update_fields=['status'])

    return (not revision), len(entries)


def attendance_rows(students=None, courses=None):
    """Per (student, course) attendance, computed straight from Attendance.

    Nothing here may depend on AttendanceTotal rows existing - those are only
    backfilled when someone opens the attendance page, so a dashboard would
    read as empty until then, and the nightly alert job would never warn a
    student whose page nobody has opened. AttendanceTotal holds no data of its
    own anyway; the instances returned are unsaved carriers for the counts, so
    that the percentage and "classes needed" arithmetic lives in one place.
    """
    rows = Attendance.objects.all()
    if students is not None:
        rows = rows.filter(student__in=students)
    if courses is not None:
        rows = rows.filter(course__in=courses)

    summary = (rows.values('student', 'course')
               .annotate(held=Count('pk'),
                         attended=Count('pk', filter=Q(status=True))))

    # The login comes along because the alert job mails these people; without
    # it, building one message per student is one query per student.
    students_by_id = {s.USN: s for s in Student.objects.select_related('user')
                      .filter(USN__in={r['student'] for r in summary})}
    courses_by_id = {c.id: c for c in Course.objects.filter(
        id__in={r['course'] for r in summary})}

    out = []
    for row in summary:
        total = AttendanceTotal(student=students_by_id[row['student']],
                                course=courses_by_id[row['course']])
        total._held = row['held']
        total._attended = row['attended']
        out.append(total)
    return out


class QueryNotAllowed(Exception):
    """Raised when a mark cannot be questioned, with the reason to show."""


def query_window_closes(mark):
    """When the chance to question this mark runs out, or None if it never opened."""
    batch = mark.batch
    if batch is None or not batch.is_published or batch.published_at is None:
        return None
    return batch.published_at + QUERY_WINDOW


def can_query(mark, now=None):
    """(allowed, reason). The reason is written to be shown to the student."""
    closes = query_window_closes(mark)
    if closes is None:
        # Nothing to argue with yet: an unpublished mark is not a mark the
        # student has been given.
        return False, 'These marks have not been released yet.'

    now = now or timezone.now()
    if now > closes:
        return False, ('The window for questioning this mark closed on %s.'
                       % timezone.localtime(closes).strftime('%d %b %Y'))

    if mark.queries.open().exists():
        return False, 'You have already questioned this mark.'

    return True, ''


@transaction.atomic
def raise_mark_query(mark, student, reason, actor):
    """Record a student's objection to one mark."""
    allowed, why = can_query(mark)
    if not allowed:
        raise QueryNotAllowed(why)
    if mark.studentcourse.student_id != student.pk:
        raise QueryNotAllowed('That mark belongs to somebody else.')

    query = MarkQuery.objects.create(marks=mark, student=student,
                                     reason=reason.strip())
    AuditLog.record(
        actor=actor, action='marks.queried', target=query, student=student,
        summary='%s questioned their %s in %s'
                % (student.name, mark.name, mark.studentcourse.course.shortname))
    return query


@transaction.atomic
def resolve_mark_query(query, actor, accept, response, new_mark=None):
    """Answer a query, changing the mark if the teacher agrees with it.

    The mark is written through the same ceiling the entry form enforces, so
    re-evaluation cannot become the way an out-of-range mark gets in.
    """
    if not query.is_open:
        raise QueryNotAllowed('That query has already been answered.')

    mark = query.marks
    query.mark_before = mark.marks1
    query.response = (response or '').strip()
    query.reviewed_by = actor if getattr(actor, 'is_authenticated', False) else None
    query.reviewed_at = timezone.now()

    if accept:
        if new_mark is None:
            raise QueryNotAllowed('Accepting a query needs the corrected mark.')
        if not 0 <= new_mark <= mark.total_marks:
            raise QueryNotAllowed('A mark must be between 0 and %d.'
                                  % mark.total_marks)
        query.mark_after = new_mark
        query.status = QUERY_ACCEPTED
        if new_mark != mark.marks1:
            mark.marks1 = new_mark
            # A corrected mark is a mark that was sat, whatever the sheet said
            # before.
            mark.is_absent = False
            mark.save(update_fields=['marks1', 'is_absent', 'updated_at'])
    else:
        query.mark_after = mark.marks1
        query.status = QUERY_REJECTED

    query.save()

    AuditLog.record(
        actor=actor, action='marks.query_%s' % query.status, target=query,
        student=query.student,
        summary='%s in %s: %s' % (mark.name,
                                  mark.studentcourse.course.shortname,
                                  query.outcome),
        changes=({'marks1': [query.mark_before, query.mark_after]}
                 if query.mark_before != query.mark_after else None))
    return query


@transaction.atomic
def withdraw_mark_query(query, actor):
    """The student changing their mind, which is not the same as a rejection."""
    if not query.is_open:
        raise QueryNotAllowed('That query has already been answered.')

    query.status = QUERY_WITHDRAWN
    query.save(update_fields=['status'])
    AuditLog.record(
        actor=actor, action='marks.query_withdrawn', target=query,
        student=query.student,
        summary='%s withdrew their query about %s'
                % (query.student.name, query.marks.name))
    return query
