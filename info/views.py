from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponseRedirect, HttpResponse
from .models import Dept, Class, Student, Attendance, Course, Teacher, Assign, AttendanceTotal, time_slots, \
    DAYS_OF_WEEK, AssignTime, AttendanceClass, StudentCourse, Marks, MarksClass, Fee, Notice, fee_type_choice, AuditLog, SupportRequest, NoticeRead, notice_category_choice, \
    CIE_MAX, SEE_MAX, SEE_ELIGIBILITY_CIE, sgpa_for
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.db import transaction
from django.db.models import Count, Q
from django.core.paginator import Paginator
from django.core.exceptions import PermissionDenied
from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.contrib import messages
from django.core.cache import cache
from django.views.decorators.http import require_POST
from django.contrib.auth import get_user_model
from info.forms import (StudentForm, TeacherForm, MarksEntryForm,
                        ExtraClassForm, FeeForm, FeeTransactionForm,
                        ErpLoginForm, SupportRequestForm, NoticeForm)
from info.decorators import (teacher_required, owns_assign, owns_attendance_class,
                             owns_marks_class, owns_teacher_id, assert_teaches)
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill


import logging

User = get_user_model()
logger = logging.getLogger(__name__)

# Two weeks - long enough to be useful on a personal device, short enough that
# a shared machine does not stay signed in indefinitely.
REMEMBER_ME_SECONDS = 60 * 60 * 24 * 14

# AttendanceClass.status is a bare integer with no choices on the field.
# Naming the one value read outside cancel_class at least stops it being a
# magic 2 in two places.
CLASS_CANCELLED = 2

WEEKDAY_INDEX = {name: index for index, (name, _) in enumerate(DAYS_OF_WEEK)}

# Create your views here.


@login_required
def index(request):
    if request.user.is_teacher:
        return render(request, 'info/t_homepage.html',
                      _teacher_dashboard(request.user.teacher))
    if request.user.is_student:
        return render(request, 'info/homepage.html',
                      _student_dashboard(request.user.student))
    if request.user.is_superuser:
        return render(request, 'info/admin_page.html', _admin_dashboard())
    return render(request, 'info/logout.html')


def _student_dashboard(student):
    """Attendance standing, fees due and notices, rather than four links.

    Everything here is already computed elsewhere - classes_to_attend and
    classes_can_skip have been model properties all along and were never shown
    anywhere.
    """
    courses = Course.objects.filter(assign__class_id=student.class_id_id).distinct()
    AttendanceTotal.objects.bulk_create(
        [AttendanceTotal(student=student, course=c) for c in courses],
        ignore_conflicts=True,
    )
    totals = list(AttendanceTotal.objects
                  .filter(student=student, course__in=courses)
                  .select_related('course')
                  .with_counts())

    held = sum(t.total_class for t in totals)
    attended = sum(t.att_class for t in totals)
    fees = list(student.fees.all())

    return {
        'latest_notices': Notice.objects.filter(
            audience__in=['All', 'Students'])[:3],
        # Weighted across all sessions, not the mean of the percentages, which
        # would over-weight a course with only a handful of classes.
        'overall_attendance': round(attended / held * 100, 2) if held else None,
        'at_risk': [t for t in totals if t.has_classes and t.attendance < 75],
        'can_skip': [t for t in totals if t.has_classes and t.classes_can_skip],
        'fees_due': sum(f.balance for f in fees),
        'next_due': min((f for f in fees if f.balance > 0),
                        key=lambda f: f.due_date, default=None),
        'overdue_count': sum(1 for f in fees if f.is_overdue),
    }


def _attendance_rows(students=None, courses=None):
    """Per (student, course) attendance, computed straight from Attendance.

    The dashboards must not depend on AttendanceTotal rows existing - those are
    only backfilled when someone opens the attendance page, so a dashboard would
    read as empty until then. AttendanceTotal holds no data of its own anyway.
    """
    rows = Attendance.objects.all()
    if students is not None:
        rows = rows.filter(student__in=students)
    if courses is not None:
        rows = rows.filter(course__in=courses)

    summary = (rows.values('student', 'course')
               .annotate(held=Count('pk'),
                         attended=Count('pk', filter=Q(status=True))))

    students_by_id = {s.USN: s for s in Student.objects.filter(
        USN__in={r['student'] for r in summary})}
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


def _teacher_dashboard(teacher):
    """What still needs doing, rather than a menu of sections."""
    today = timezone.localdate()
    assigns = list(Assign.objects.filter(teacher=teacher)
                   .select_related('course', 'class_id'))

    # status 0 means the session happened but nobody submitted it.
    pending_sessions = (AttendanceClass.objects
                        .filter(assign__in=assigns, status=0, date__lte=today)
                        .select_related('assign__course', 'assign__class_id')
                        .order_by('-date')[:10])
    pending_marks = (MarksClass.objects
                     .filter(assign__in=assigns, status=False)
                     .select_related('assign__course', 'assign__class_id'))

    student_count = Student.objects.filter(
        class_id__in={a.class_id_id for a in assigns}).count()

    at_risk = [t for t in _attendance_rows(
        students=Student.objects.filter(
            class_id__in={a.class_id_id for a in assigns}),
        courses=[a.course_id for a in assigns])
        if t.has_classes and t.attendance < 75]

    return {
        'latest_notices': Notice.objects.filter(
            audience__in=['All', 'Teachers'])[:3],
        'assigns': assigns,
        'class_count': len(assigns),
        'student_count': student_count,
        'pending_sessions': pending_sessions,
        'pending_sessions_count': AttendanceClass.objects.filter(
            assign__in=assigns, status=0, date__lte=today).count(),
        'pending_marks': pending_marks,
        'at_risk': sorted(at_risk, key=lambda t: t.attendance)[:10],
        'at_risk_count': len(at_risk),
    }


def _admin_dashboard():
    with_classes = [t for t in _attendance_rows() if t.has_classes]
    held = sum(t.total_class for t in with_classes)
    attended = sum(t.att_class for t in with_classes)

    fees = Fee.objects.all()
    outstanding = sum(f.balance for f in fees)

    return {
        'latest_notices': Notice.objects.all()[:3],
        'student_count': Student.objects.count(),
        'teacher_count': Teacher.objects.count(),
        'dept_count': Dept.objects.count(),
        'avg_attendance': round(attended / held * 100, 2) if held else None,
        'at_risk_count': len({t.student.USN for t in with_classes
                              if t.attendance < 75}),
        'fees_outstanding': outstanding,
        'overdue_count': sum(1 for f in fees if f.is_overdue),
        'open_support': SupportRequest.objects.exclude(status='Resolved').count(),
        'recent_activity': AuditLog.objects.all()[:10],
    }


@login_required()
def attendance(request, stud_id):
    stud = get_object_or_404(Student, USN=stud_id)
    courses = Course.objects.filter(assign__class_id=stud.class_id_id).distinct()

    # Backfill in one go rather than one get-or-create per course inside a loop.
    AttendanceTotal.objects.bulk_create(
        [AttendanceTotal(student=stud, course=c) for c in courses],
        ignore_conflicts=True,
    )
    att_list = (AttendanceTotal.objects
                .filter(student=stud, course__in=courses)
                .select_related('course', 'student')
                .with_counts())
    return render(request, 'info/attendance.html', {'att_list': att_list})


@login_required()
def attendance_detail(request, stud_id, course_id):
    stud = get_object_or_404(Student, USN=stud_id)
    cr = get_object_or_404(Course, id=course_id)
    att_list = Attendance.objects.filter(course=cr, student=stud).order_by('date')
    return render(request, 'info/att_detail.html', {'att_list': att_list, 'cr': cr})


# Teacher Views

@login_required
@teacher_required
@owns_teacher_id('teacher_id')
def t_clas(request, teacher_id, choice):
    teacher1 = get_object_or_404(Teacher, id=teacher_id)
    return render(request, 'info/t_clas.html', {'teacher1': teacher1, 'choice': choice})


@login_required()
@teacher_required
@owns_assign('assign_id')
def t_student(request, assign_id):
    ass = get_object_or_404(Assign, id=assign_id)
    students = list(ass.class_id.student_set.all())

    AttendanceTotal.objects.bulk_create(
        [AttendanceTotal(student=s, course=ass.course) for s in students],
        ignore_conflicts=True,
    )
    att_list = (AttendanceTotal.objects
                .filter(student__in=students, course=ass.course)
                .select_related('course', 'student')
                .with_counts())
    return render(request, 'info/t_students.html', {'att_list': att_list})


@login_required()
@teacher_required
@owns_assign('assign_id')
def t_class_date(request, assign_id):
    now = timezone.now()
    ass = get_object_or_404(Assign, id=assign_id)
    att_list = ass.attendanceclass_set.filter(date__lte=now).order_by('-date')
    return render(request, 'info/t_class_date.html', {'att_list': att_list})


@login_required()
@teacher_required
@owns_attendance_class('ass_c_id')
def cancel_class(request, ass_c_id):
    assc = get_object_or_404(AttendanceClass, id=ass_c_id)
    assc.status = CLASS_CANCELLED
    assc.save()
    AuditLog.record(
        actor=request.user, action='attendance.cancelled', target=assc,
        summary='Class cancelled: %s on %s' % (assc.assign.class_id, assc.date))
    return HttpResponseRedirect(reverse('t_class_date', args=(assc.assign_id,)))


@login_required()
@teacher_required
@owns_attendance_class('ass_c_id')
def t_attendance(request, ass_c_id):
    assc = get_object_or_404(AttendanceClass, id=ass_c_id)
    ass = assc.assign
    c = ass.class_id
    context = {
        'ass': ass,
        'c': c,
        'assc': assc,
    }
    return render(request, 'info/t_attendance.html', context)


@login_required()
@teacher_required
@owns_attendance_class('ass_c_id')
def edit_att(request, ass_c_id):
    assc = get_object_or_404(AttendanceClass, id=ass_c_id)
    cr = assc.assign.course
    att_list = Attendance.objects.filter(attendanceclass=assc, course=cr)
    context = {
        'assc': assc,
        'att_list': att_list,
    }
    return render(request, 'info/t_edit_att.html', context)


@login_required()
@teacher_required
@owns_attendance_class('ass_c_id')
@require_POST
def confirm(request, ass_c_id):
    assc = get_object_or_404(AttendanceClass, id=ass_c_id)
    ass = assc.assign
    cr = ass.course
    cl = ass.class_id

    # A student with no radio button in the payload used to raise KeyError and
    # 500 the request half way through the class. Treat a missing value as
    # absent - the form always submits one, so this only catches malformed
    # posts - and record which ones were missing rather than failing silently.
    resubmission = assc.status == 1
    with transaction.atomic():
        previous = {a.student_id: a.status for a in
                    Attendance.objects.filter(attendanceclass=assc)}
        entries = []
        for s in cl.student_set.all():
            present = request.POST.get(s.USN) == 'present'
            Attendance.objects.update_or_create(
                course=cr, student=s, attendanceclass=assc,
                defaults={'status': present, 'date': assc.date},
            )
            was = previous.get(s.USN)
            # On a first submission there is nothing to compare against, so log
            # the batch rather than a change per student.
            if resubmission and was is not None and was != present:
                entries.append(AuditLog(
                    actor=request.user, actor_name=request.user.username,
                    action='attendance.changed', target_type='Attendance',
                    student=s, student_name=s.name,
                    summary='%s on %s for %s' % (
                        'Marked present' if present else 'Marked absent',
                        assc.date, cr.id),
                    changes={'status': {'from': was, 'to': present}},
                ))
        AuditLog.record_many(entries)

        if not resubmission:
            AuditLog.record(
                actor=request.user, action='attendance.marked', target=assc,
                summary='Attendance submitted for %s on %s'
                        % (cl, assc.date))

        # Set once, after every student is written. This used to be assigned
        # while handling the first student, which sent everyone after them down
        # the "already submitted" branch.
        assc.status = 1
        assc.save(update_fields=['status'])

    return HttpResponseRedirect(reverse('t_class_date', args=(ass.id,)))


@login_required()
@teacher_required
def t_attendance_detail(request, stud_id, course_id):
    stud = get_object_or_404(Student, USN=stud_id)
    cr = get_object_or_404(Course, id=course_id)
    assert_teaches(request, cr.id, stud)
    att_list = Attendance.objects.filter(course=cr, student=stud).order_by('date')
    return render(request, 'info/t_att_detail.html', {'att_list': att_list, 'cr': cr})


@login_required()
@teacher_required
@require_POST
def change_att(request, att_id):
    # Was a GET that flipped the record, so it bypassed CSRF entirely and could
    # be fired by anything that could make the browser issue a request. It is a
    # POST now, and restricted to the teacher who takes that course.
    a = get_object_or_404(Attendance, id=att_id)
    assert_teaches(request, a.course_id, a.student)
    was = a.status
    a.status = not a.status
    a.save()
    AuditLog.record(
        actor=request.user, action='attendance.changed', target=a,
        student=a.student,
        summary='%s on %s for %s' % (
            'Marked present' if a.status else 'Marked absent',
            a.date, a.course_id),
        changes={'status': {'from': was, 'to': a.status}},
    )
    return HttpResponseRedirect(reverse('t_attendance_detail', args=(a.student.USN, a.course_id)))


@login_required()
@teacher_required
@owns_assign('assign_id')
def t_extra_class(request, assign_id):
    ass = get_object_or_404(Assign, id=assign_id)
    c = ass.class_id
    context = {
        'ass': ass,
        'c': c,
    }
    return render(request, 'info/t_extra_class.html', context)


@login_required()
@teacher_required
@owns_assign('assign_id')
@require_POST
def e_confirm(request, assign_id):
    ass = get_object_or_404(Assign, id=assign_id)
    cr = ass.course
    cl = ass.class_id

    # The date arrived straight from the form and went into the database
    # unchecked, so a typo or a hand-crafted post created sessions on any date
    # at all - including outside the semester, or a second one for a day that
    # already had a class.
    form = ExtraClassForm(request.POST, assign=ass)
    if not form.is_valid():
        return render(request, 'info/t_extra_class.html',
                      {'ass': ass, 'c': cl, 'form': form})

    session_date = form.cleaned_data['date']
    with transaction.atomic():
        assc = ass.attendanceclass_set.create(status=1, date=session_date)
        for s in cl.student_set.all():
            Attendance.objects.create(
                course=cr, student=s, attendanceclass=assc, date=session_date,
                status=request.POST.get(s.USN) == 'present',
            )

    return HttpResponseRedirect(reverse('t_clas', args=(ass.teacher_id, 1)))


@login_required()
@teacher_required
@owns_assign('assign_id')
def t_report(request, assign_id):
    ass = get_object_or_404(Assign, id=assign_id)
    students = list(ass.class_id.student_set.all())

    # A bare .get() here meant one student without a StudentCourse row took the
    # whole class report down with an uncaught DoesNotExist.
    StudentCourse.objects.bulk_create(
        [StudentCourse(student=s, course=ass.course) for s in students],
        ignore_conflicts=True,
    )
    sc_list = _report_rows(ass, students)

    order = request.GET.get('sort', 'name')
    sc_list = _sort_report(sc_list, order)
    at_risk_only = request.GET.get('risk') == '1'

    at_risk = [sc for sc in sc_list if sc.is_at_risk]
    held = [sc for sc in sc_list if sc.has_marks]

    return render(request, 'info/t_report.html', {
        'assign': ass,
        'sc_list': [sc for sc in sc_list if sc.is_at_risk] if at_risk_only else sc_list,
        'sort': order,
        'sorts': REPORT_SORT_LABELS,
        'at_risk_only': at_risk_only,
        'headcount': len(sc_list),
        'at_risk_count': len(at_risk),
        # Averages over the students who actually have something recorded, so a
        # class that has not sat a test yet does not report an average of zero.
        'avg_cie': (round(sum(sc.get_cie() for sc in held) / len(held), 1)
                    if held else None),
        'avg_attendance': (round(sum(sc.get_attendance() for sc in sc_list) / len(sc_list), 1)
                           if sc_list else None),
        'ineligible_count': sum(1 for sc in sc_list if sc.is_see_eligible is False),
        'cie_max': CIE_MAX,
        'eligibility_cie': SEE_ELIGIBILITY_CIE,
    })


def _report_rows(assign, students):
    """Every student on this class's course, with marks and attendance loaded.

    Both attach_* calls exist to keep this flat: without them each row looks up
    its own attendance and its own submitted-components status, and the
    template asks for each twice.
    """
    # attach_attendance reads AttendanceTotal, and those rows are only
    # backfilled when someone opens the attendance page - so without this the
    # report showed 0% for every student until they each did, and then flagged
    # the whole class as at risk. Same guard the attendance page already has.
    AttendanceTotal.objects.bulk_create(
        [AttendanceTotal(student=s, course=assign.course) for s in students],
        ignore_conflicts=True,
    )

    rows = list(StudentCourse.objects
                .filter(student__in=students, course=assign.course)
                .select_related('student', 'course')
                .prefetch_related('marks_set'))
    StudentCourse.attach_attendance(rows, assign.course)
    StudentCourse.attach_submitted(rows, assign.class_id_id)
    return rows


REPORT_SORTS = {
    'name': lambda sc: sc.student.name,
    'usn': lambda sc: sc.student_id,
    'cie': lambda sc: sc.get_cie(),
    'attendance': lambda sc: sc.get_attendance(),
}

REPORT_SORT_LABELS = (
    ('name', 'Name'),
    ('usn', 'USN'),
    ('cie', 'Lowest CIE'),
    ('attendance', 'Lowest attendance'),
)


def _sort_report(rows, order):
    """Lowest-first on the two numeric columns - the point of sorting a class
    report is to bring the students in trouble to the top."""
    return sorted(rows, key=REPORT_SORTS.get(order, REPORT_SORTS['name']))


@login_required()
@teacher_required
@owns_assign('assign_id')
def t_report_export(request, assign_id):
    """The same report as a spreadsheet, for department records."""
    ass = get_object_or_404(Assign, id=assign_id)
    rows = _sort_report(
        _report_rows(ass, list(ass.class_id.student_set.all())),
        request.GET.get('sort', 'name'))

    wb = Workbook()
    ws = wb.active
    ws.title = 'Class report'
    ws.append(['USN', 'Name', 'Attendance %', 'CIE', 'SEE eligible', 'At risk'])
    for cell in ws[1]:
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill(start_color='4F46E5', end_color='4F46E5',
                                fill_type='solid')

    for sc in rows:
        eligible = sc.is_see_eligible
        ws.append([
            sc.student_id,
            sc.student.name,
            sc.get_attendance(),
            sc.get_cie(),
            # Undecided is its own answer here, not a False.
            'Undecided' if eligible is None else ('Yes' if eligible else 'No'),
            'Yes' if sc.is_at_risk else '',
        ])

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = (
        'attachment; filename="%s_%s_report.xlsx"'
        % (ass.class_id_id, ass.course_id))
    wb.save(response)
    return response


BREAK_COLUMNS = (4, 8)


def _timetable_matrix(slots, cell, blank=''):
    """Lay `slots` out as the 6x12 grid the timetable templates render.

    Column 0 is the day label and columns 4 and 8 are the break and lunch gaps;
    the remaining nine map to time_slots in order.

    This used to call .get() once per cell - 54 queries per page, every miss
    raising DoesNotExist as normal control flow - and caught only DoesNotExist,
    so two courses scheduled against one class in the same slot raised
    MultipleObjectsReturned and 500'd the page for everyone in that class.
    Indexing what a single query returned removes both problems.
    """
    by_slot = {(s.day, s.period): s for s in slots}

    matrix = []
    for day, _ in DAYS_OF_WEEK:
        row = [day]
        period_index = 0
        for column in range(1, 12):
            if column in BREAK_COLUMNS:
                row.append(blank)
                continue
            slot = by_slot.get((day, time_slots[period_index][0]))
            row.append(cell(slot) if slot else blank)
            period_index += 1
        matrix.append(row)
    return matrix


@login_required()
def timetable(request, class_id):
    slots = (AssignTime.objects
             .filter(assign__class_id=class_id)
             .select_related('assign'))
    matrix = _timetable_matrix(slots, cell=lambda s: s.assign.course_id)
    return render(request, 'info/timetable.html', {'matrix': matrix})


@login_required()
@teacher_required
@owns_teacher_id('teacher_id')
def t_timetable(request, teacher_id):
    slots = (AssignTime.objects
             .filter(assign__teacher_id=teacher_id)
             .select_related('assign', 'assign__course', 'assign__class_id'))
    # The template checks `j == True` for an empty cell, which is why the blank
    # here is True rather than '' as in the student view.
    class_matrix = _timetable_matrix(slots, cell=lambda s: s, blank=True)
    return render(request, 'info/t_timetable.html', {'class_matrix': class_matrix})


def _next_weekday(day, today=None):
    """The next date `day` falls on, counting today as the next occurrence.

    A timetable slot is a recurring weekday, but a cancellation belongs to one
    date - so answering "is this teacher free" needs a date to look at.
    Returns None for a day name that is not in DAYS_OF_WEEK, in which case
    callers fall back to the static timetable.
    """
    target = WEEKDAY_INDEX.get(day)
    if target is None:
        return None
    today = today or timezone.localdate()
    return today + timedelta(days=(target - today.weekday()) % 7)


@login_required()
@teacher_required
def free_teachers(request, asst_id):
    """Who across the college could cover this slot.

    The candidate pool used to be Teacher.objects.filter(assign__class_id=...),
    i.e. only teachers already teaching this class - so the page answered a
    much narrower question than its title and could never find an outside
    substitute. It also joined across `assign`, which repeated any teacher
    holding two courses for the class, and then ran one query per candidate to
    decide availability in Python.
    """
    asst = get_object_or_404(
        AssignTime.objects.select_related('assign__class_id', 'assign__course',
                                          'assign__teacher'),
        id=asst_id)

    date = _next_weekday(asst.day)

    # A cancelled session frees its teacher up even though the timetable still
    # shows them as teaching - which is the case a substitute is being looked
    # for in the first place.
    cancelled_assigns = []
    if date is not None:
        cancelled_assigns = list(
            AttendanceClass.objects
            .filter(date=date, status=CLASS_CANCELLED)
            .values_list('assign_id', flat=True))

    busy = (AssignTime.objects
            .filter(day=asst.day, period=asst.period)
            .exclude(assign_id__in=cancelled_assigns)
            .values_list('assign__teacher_id', flat=True))

    # exclude() against the collected ids rather than filtering across the
    # assign join, so a teacher cannot come back twice.
    ft_list = (Teacher.objects
               .exclude(id__in=busy)
               .select_related('dept')
               .order_by('name'))

    return render(request, 'info/free_teachers.html', {
        'ft_list': ft_list,
        'slot': asst,
        'date': date,
    })


# student marks


@login_required()
def marks_list(request, stud_id):
    stud = get_object_or_404(Student, USN=stud_id)
    courses = Course.objects.filter(assign__class_id=stud.class_id_id).distinct()

    # The old fallback here passed type='I' to marks_set.create(), but Marks has
    # no `type` field - it raised TypeError. It only ran when a StudentCourse
    # row was missing, which the signals normally prevent, so the page worked by
    # luck. bulk_create with ignore_conflicts covers the same gap without the
    # per-course round trips.
    StudentCourse.objects.bulk_create(
        [StudentCourse(student=stud, course=c) for c in courses],
        ignore_conflicts=True,
    )
    sc_list = list(StudentCourse.objects
                   .filter(student=stud, course__in=courses)
                   .select_related('course')
                   .prefetch_related('marks_set'))

    # One query for the whole page rather than a status lookup per component.
    StudentCourse.attach_submitted(sc_list, stud.class_id_id)

    # Courses with something actually marked. Filtering on a truthy CIE instead
    # would silently drop a course genuinely sitting at zero - which is exactly
    # the one worth calling out - while keeping one that has simply not started.
    with_cie = [sc for sc in sc_list if sc.has_marks]
    return render(request, 'info/marks_list.html', {
        'sc_list': sc_list,
        'sgpa': sgpa_for(sc_list),
        'cie_max': CIE_MAX,
        'see_max': SEE_MAX,
        'eligibility_cie': SEE_ELIGIBILITY_CIE,
        # Honest label while no result is in: an average CIE is not a GPA.
        'average_cie': (round(sum(sc.get_cie() for sc in with_cie) / len(with_cie), 1)
                        if with_cie else None),
        'best': max(with_cie, key=lambda sc: sc.get_cie(), default=None),
        'weakest': min(with_cie, key=lambda sc: sc.get_cie(), default=None),
    })


# teacher marks


@login_required()
@teacher_required
@owns_assign('assign_id')
def t_marks_list(request, assign_id):
    ass = get_object_or_404(Assign, id=assign_id)
    m_list = MarksClass.objects.filter(assign=ass)
    return render(request, 'info/t_marks_list.html', {'m_list': m_list})


@login_required()
@teacher_required
@owns_marks_class('marks_c_id')
def t_marks_entry(request, marks_c_id):
    mc = get_object_or_404(MarksClass, id=marks_c_id)
    ass = mc.assign
    c = ass.class_id
    return render(request, 'info/t_marks_entry.html',
                  _marks_entry_context(mc, list(c.student_set.all())))


def _marks_entry_context(mc, students, form=None):
    """Build the per-student rows the marks entry template renders.

    Templates can't index a dict by a variable key, so the pairing of student to
    input value and error list is done here rather than in the template.
    """
    rows = []
    for s in students:
        rows.append({
            'student': s,
            'value': form.data.get(s.USN, '') if form else 0,
            'errors': form.errors_for(s) if form else [],
        })
    return {'ass': mc.assign, 'c': mc.assign.class_id, 'mc': mc,
            'rows': rows, 'form': form}


@login_required()
@teacher_required
@owns_marks_class('marks_c_id')
@require_POST
def marks_confirm(request, marks_c_id):
    mc = get_object_or_404(MarksClass, id=marks_c_id)
    ass = mc.assign
    cr = ass.course
    cl = ass.class_id
    students = list(cl.student_set.all())

    # Marks went in as raw POST strings with no bounds check, so a slip of the
    # keyboard stored 85 on a test worth 20 - the field validators never run on
    # a plain .save(). Validate the whole class before writing any of it.
    form = MarksEntryForm(request.POST, students=students,
                          total_marks=mc.total_marks)
    if not form.is_valid():
        return render(request, 'info/t_marks_entry.html',
                      _marks_entry_context(mc, students, form))

    revision = mc.status
    with transaction.atomic():
        entries = []
        for s in students:
            # get_or_create rather than get: a student without a StudentCourse
            # row used to raise DoesNotExist and take down the whole batch.
            sc, _ = StudentCourse.objects.get_or_create(course=cr, student=s)
            scored = form.marks_for(s)
            existing = sc.marks_set.filter(name=mc.name).first()
            was = existing.marks1 if existing else None
            sc.marks_set.update_or_create(name=mc.name,
                                          defaults={'marks1': scored})
            # Overwriting a grade with no record of the old value is the gap
            # people ask about first.
            if revision and was is not None and was != scored:
                entries.append(AuditLog(
                    actor=request.user, actor_name=request.user.username,
                    action='marks.changed', target_type='Marks',
                    student=s, student_name=s.name,
                    summary='%s for %s changed from %s to %s'
                            % (mc.name, cr.id, was, scored),
                    changes={'marks1': {'from': was, 'to': scored}},
                ))
        AuditLog.record_many(entries)

        if not revision:
            AuditLog.record(
                actor=request.user, action='marks.entered', target=mc,
                summary='%s entered for %s (%d students)'
                        % (mc.name, cl, len(students)))

        mc.status = True
        mc.save(update_fields=['status'])

    return HttpResponseRedirect(reverse('t_marks_list', args=(ass.id,)))


@login_required()
@teacher_required
@owns_marks_class('marks_c_id')
def edit_marks(request, marks_c_id):
    mc = get_object_or_404(MarksClass, id=marks_c_id)
    cr = mc.assign.course
    stud_list = mc.assign.class_id.student_set.all()
    m_list = []
    for stud in stud_list:
        sc = StudentCourse.objects.get(course=cr, student=stud)
        m = sc.marks_set.get(name=mc.name)
        m_list.append(m)
    context = {
        'mc': mc,
        'm_list': m_list,
    }
    return render(request, 'info/edit_marks.html', context)


@login_required()
@teacher_required
@owns_assign('assign_id')
def student_marks(request, assign_id):
    ass = Assign.objects.get(id=assign_id)
    sc_list = StudentCourse.objects.filter(student__in=ass.class_id.student_set.all(), course=ass.course)
    return render(request, 'info/t_student_marks.html', {'sc_list': sc_list})


@login_required()
def add_teacher(request):
    if not request.user.is_superuser:
        return redirect("/")

    credentials = None
    if request.method == 'POST':
        form = TeacherForm(request.POST)
        if form.is_valid():
            # Both writes go together: without this, a failure on the second
            # left a usable login account attached to no teacher record.
            with transaction.atomic():
                user, password = form.create_user()
                teacher = form.save(commit=False)
                teacher.user = user
                teacher.save()
            # Shown once, here only - the password is random and not recoverable.
            credentials = {'username': user.username, 'password': password,
                           'name': teacher.name}
            form = TeacherForm()
    else:
        form = TeacherForm()

    return render(request, 'info/add_teacher.html',
                  {'form': form, 'credentials': credentials})


@login_required()
def add_student(request):
    # If the user is not admin, they will be redirected to home
    if not request.user.is_superuser:
        return redirect("/")

    credentials = None
    if request.method == 'POST':
        form = StudentForm(request.POST)
        if form.is_valid():
            # See add_teacher - the two writes must not be able to come apart.
            with transaction.atomic():
                user, password = form.create_user()
                student = form.save(commit=False)
                student.user = user
                student.save()
            credentials = {'username': user.username, 'password': password,
                           'name': student.name}
            form = StudentForm()
    else:
        form = StudentForm()

    return render(request, 'info/add_student.html',
                  {'form': form, 'credentials': credentials})


# ---------------------------------------------------------------------------
# Fees
# ---------------------------------------------------------------------------

@login_required()
def fees(request, stud_id):
    stud = get_object_or_404(Student, USN=stud_id)
    if not (request.user.is_superuser or (request.user.is_student and request.user.student.USN == stud.USN)):
        return redirect('/')

    fee_list = stud.fees.all()
    total_amount = sum(f.amount for f in fee_list)
    total_paid = sum(f.paid_amount for f in fee_list)
    context = {
        'stud': stud,
        'fee_list': fee_list,
        'total_amount': total_amount,
        'total_paid': total_paid,
        'total_balance': total_amount - total_paid,
    }
    return render(request, 'info/fees.html', context)


@login_required()
def fees_export(request, stud_id):
    stud = get_object_or_404(Student, USN=stud_id)
    if not (request.user.is_superuser or (request.user.is_student and request.user.student.USN == stud.USN)):
        return redirect('/')

    wb = Workbook()
    ws = wb.active
    ws.title = 'Fees'
    headers = ['Fee Type', 'Description', 'Amount', 'Paid', 'Balance', 'Status', 'Due Date']
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill(start_color='4F46E5', end_color='4F46E5', fill_type='solid')

    for f in stud.fees.all():
        ws.append([f.fee_type, f.description, float(f.amount), float(f.paid_amount),
                   float(f.balance), f.status, f.due_date.strftime('%Y-%m-%d')])

    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename="%s_fees.xlsx"' % stud.USN
    wb.save(response)
    return response


@login_required()
def t_fees(request):
    if not (request.user.is_superuser or request.user.is_teacher):
        return redirect('/')

    q = request.GET.get('q', '').strip()
    students = Student.objects.all().order_by('class_id_id', 'name')
    if q:
        students = students.filter(name__icontains=q) | students.filter(USN__icontains=q)

    fee_list = Fee.objects.select_related('student').all()
    if q:
        fee_list = fee_list.filter(student__in=students)

    context = {'fee_list': fee_list, 'q': q}
    return render(request, 'info/t_fees.html', context)


@login_required()
def add_fee(request):
    if not (request.user.is_superuser or request.user.is_teacher):
        return redirect('/')

    if request.method == 'POST':
        form = FeeForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('t_fees')
    else:
        form = FeeForm()

    return render(request, 'info/add_fee.html', {'form': form})


@login_required()
def edit_fee(request, fee_id):
    """Record a payment against a fee.

    This used to overwrite paid_amount with a new running total, so staff had to
    do the arithmetic themselves, a mistake was unrecoverable, and nothing
    recorded when the money came in or who took it.
    """
    if not (request.user.is_superuser or request.user.is_teacher):
        return redirect('/')

    fee = get_object_or_404(Fee.objects.select_related('student'), id=fee_id)

    if request.method == 'POST':
        form = FeeTransactionForm(request.POST, fee=fee)
        if form.is_valid():
            with transaction.atomic():
                payment = form.save(commit=False)
                payment.fee = fee
                payment.received_by = request.user
                payment.save()
                fee.recalculate_paid()
                AuditLog.record(
                    actor=request.user, action='fee.payment', target=payment,
                    student=fee.student,
                    summary='%s of %s for %s (%s)'
                            % (payment.receipt_no, payment.amount,
                               fee.fee_type, payment.mode),
                    changes={'paid_amount': {'to': str(fee.paid_amount)}},
                )
            return redirect('edit_fee', fee_id=fee.id)
    else:
        form = FeeTransactionForm(fee=fee,
                                  initial={'amount': fee.balance or None})

    return render(request, 'info/edit_fee.html', {
        'fee': fee,
        'form': form,
        'payments': fee.transactions.select_related('received_by'),
    })


# ---------------------------------------------------------------------------
# Notice board
# ---------------------------------------------------------------------------

@login_required()
def notices(request):
    """The board, with search, filters and pagination.

    Previously every notice for the audience came back in one unpaginated list
    with no way to find anything in it.
    """
    notice_list = Notice.objects.visible_to(request.user).select_related('posted_by')

    query = request.GET.get('q', '').strip()
    if query:
        notice_list = notice_list.filter(
            Q(title__icontains=query) | Q(message__icontains=query))

    category = request.GET.get('category', '')
    if category:
        notice_list = notice_list.filter(category=category)

    period = request.GET.get('period', '')
    if period == 'week':
        notice_list = notice_list.filter(
            created_at__gte=timezone.now() - timedelta(days=7))
    elif period == 'month':
        notice_list = notice_list.filter(
            created_at__gte=timezone.now() - timedelta(days=30))

    page = Paginator(notice_list, 10).get_page(request.GET.get('page'))
    read_ids = set(NoticeRead.objects
                   .filter(user=request.user, notice__in=page.object_list)
                   .values_list('notice_id', flat=True))

    return render(request, 'info/notices.html', {
        'page': page,
        'q': query,
        'category': category,
        'period': period,
        'categories': notice_category_choice,
        'read_ids': read_ids,
        'unread_count': unread_notice_count(request.user),
        'can_post': request.user.is_superuser or request.user.is_teacher,
    })


@login_required()
def notice_detail(request, notice_id):
    notice = get_object_or_404(
        Notice.objects.visible_to(request.user).select_related('posted_by'),
        id=notice_id)

    # Opening it is what counts as reading it.
    NoticeRead.objects.get_or_create(notice=notice, user=request.user)

    return render(request, 'info/notice_detail.html', {
        'notice': notice,
        'can_edit': request.user.is_superuser or notice.posted_by_id == request.user.id,
        'read_count': notice.reads.count(),
    })


@login_required()
def add_notice(request):
    if not (request.user.is_superuser or request.user.is_teacher):
        return redirect('/')

    if request.method == 'POST':
        form = NoticeForm(request.POST, user=request.user)
        if form.is_valid():
            notice = form.save(commit=False)
            notice.posted_by = request.user
            notice.save()
            return redirect('notice_detail', notice_id=notice.id)
    else:
        form = NoticeForm(user=request.user)

    return render(request, 'info/add_notice.html', {'form': form})


@login_required()
def edit_notice(request, notice_id):
    """Neither editing nor deleting existed - a notice, once posted, was
    permanent from the UI."""
    notice = get_object_or_404(Notice, id=notice_id)
    if not (request.user.is_superuser or notice.posted_by_id == request.user.id):
        raise PermissionDenied

    if request.method == 'POST':
        form = NoticeForm(request.POST, instance=notice, user=request.user)
        if form.is_valid():
            form.save()
            return redirect('notice_detail', notice_id=notice.id)
    else:
        form = NoticeForm(instance=notice, user=request.user)

    return render(request, 'info/add_notice.html',
                  {'form': form, 'notice': notice})


@login_required()
@require_POST
def delete_notice(request, notice_id):
    notice = get_object_or_404(Notice, id=notice_id)
    if not (request.user.is_superuser or notice.posted_by_id == request.user.id):
        raise PermissionDenied

    notice.delete()
    messages.success(request, 'Notice deleted.')
    return redirect('notices')


def unread_notice_count(user):
    """Notices the user has not opened, for the topbar badge."""
    if not user.is_authenticated:
        return 0
    return (Notice.objects.visible_to(user)
            .exclude(reads__user=user)
            .count())

class ErpPasswordChangeView(PasswordChangeView):
    """Django's password change, plus clearing the must-change flag.

    Without this the middleware would keep redirecting a user who had just
    picked a new password straight back to this page.
    """
    template_name = 'info/password_change.html'
    success_url = reverse_lazy('password_change_done')

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.request.user.must_change_password:
            self.request.user.must_change_password = False
            self.request.user.save(update_fields=['must_change_password'])
        return response


class ErpLoginView(LoginView):
    """Login with a role selector, Remember Me and the support form alongside."""
    template_name = 'info/login.html'
    authentication_form = ErpLoginForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault('support_form', SupportRequestForm())
        return context

    def form_valid(self, form):
        # Without this every session lasts SESSION_COOKIE_AGE regardless, so the
        # checkbox would be decoration.
        if form.cleaned_data.get('remember_me'):
            self.request.session.set_expiry(REMEMBER_ME_SECONDS)
        else:
            self.request.session.set_expiry(0)  # ends when the browser closes
        return super().form_valid(form)


def support_request(request):
    """Handle the "Contact Administrator" form on the login page.

    Deliberately open to anonymous callers - someone who cannot sign in is
    exactly who needs it - so it is rate-limited per IP and the form carries a
    honeypot.
    """
    if request.method != 'POST':
        return redirect('login')

    form = SupportRequestForm(request.POST)
    if _support_rate_limited(request):
        form.add_error(None, 'Too many messages from here just now. '
                             'Try again in a few minutes.')
    elif form.is_valid():
        support = form.save()
        logger.info('Support request %s from %s (%s)',
                    support.pk, support.name, support.category)
        messages.success(
            request,
            'Thanks - your message is with the administrator. '
            'They will get back to you by email.')
        return redirect('login')

    # Re-render the login page with the modal's errors, so nothing is retyped.
    return ErpLoginView.as_view(extra_context={
        'support_form': form, 'open_support': True})(request)


def _support_rate_limited(request, limit=3, window=900):
    """Allow `limit` submissions per IP per `window` seconds.

    Uses the cache rather than a table - this only needs to make spamming
    inconvenient, and losing the counter on a restart is not a problem.
    """
    ip = (request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
          or request.META.get('REMOTE_ADDR', 'unknown'))
    key = 'support-requests:%s' % ip
    seen = cache.get(key, 0)
    if seen >= limit:
        return True
    cache.set(key, seen + 1, window)
    return False
