"""Application logic shared by the web views and the API.

Attendance can now be submitted from two places. Keeping the rules here rather
than in either caller stops the two from drifting - an API that reimplemented
this would quietly become a way around the checks the web form performs.
"""
from django.db import transaction

from info.models import CLASS_TAKEN, Attendance, AttendanceClass, AuditLog  # noqa: F401


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
