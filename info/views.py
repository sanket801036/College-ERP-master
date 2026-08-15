from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponseRedirect, HttpResponse
from .models import Dept, Class, Student, Attendance, Course, Teacher, Assign, AttendanceTotal, time_slots, \
    DAYS_OF_WEEK, AssignTime, AttendanceClass, StudentCourse, Marks, MarksClass, Fee, Notice, fee_type_choice
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.db import transaction
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import PasswordChangeView
from django.views.decorators.http import require_POST
from django.contrib.auth import get_user_model
from info.forms import (StudentForm, TeacherForm, MarksEntryForm,
                        ExtraClassForm, FeeForm, FeeTransactionForm)
from info.decorators import (teacher_required, owns_assign, owns_attendance_class,
                             owns_marks_class, owns_teacher_id, assert_teaches)
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill


User = get_user_model()

# Create your views here.


@login_required
def index(request):
    if request.user.is_teacher:
        latest_notices = Notice.objects.filter(audience__in=['All', 'Teachers'])[:3]
        return render(request, 'info/t_homepage.html', {'latest_notices': latest_notices})
    if request.user.is_student:
        latest_notices = Notice.objects.filter(audience__in=['All', 'Students'])[:3]
        return render(request, 'info/homepage.html', {'latest_notices': latest_notices})
    if request.user.is_superuser:
        latest_notices = Notice.objects.all()[:3]
        context = {
            'latest_notices': latest_notices,
            'student_count': Student.objects.count(),
            'teacher_count': Teacher.objects.count(),
            'dept_count': Dept.objects.count(),
        }
        return render(request, 'info/admin_page.html', context)
    return render(request, 'info/logout.html')


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
    assc.status = 2
    assc.save()
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
    with transaction.atomic():
        for s in cl.student_set.all():
            Attendance.objects.update_or_create(
                course=cr, student=s, attendanceclass=assc,
                defaults={
                    'status': request.POST.get(s.USN) == 'present',
                    'date': assc.date,
                },
            )
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
    a.status = not a.status
    a.save()
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
    sc_list = (StudentCourse.objects
               .filter(student__in=students, course=ass.course)
               .select_related('student', 'course')
               .prefetch_related('marks_set'))
    # Otherwise each row looks up its own attendance, and the template asks for
    # it twice - roughly five queries per student.
    sc_list = StudentCourse.attach_attendance(sc_list, ass.course)
    return render(request, 'info/t_report.html', {'sc_list': sc_list})


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


@login_required()
@teacher_required
def free_teachers(request, asst_id):
    asst = get_object_or_404(AssignTime, id=asst_id)
    ft_list = []
    t_list = Teacher.objects.filter(assign__class_id__id=asst.assign.class_id_id)
    for t in t_list:
        at_list = AssignTime.objects.filter(assign__teacher=t)
        if not any([True if at.period == asst.period and at.day == asst.day else False for at in at_list]):
            ft_list.append(t)

    return render(request, 'info/free_teachers.html', {'ft_list': ft_list})


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
    sc_list = (StudentCourse.objects
               .filter(student=stud, course__in=courses)
               .select_related('course')
               .prefetch_related('marks_set'))

    return render(request, 'info/marks_list.html', {'sc_list': sc_list})


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

    with transaction.atomic():
        for s in students:
            # get_or_create rather than get: a student without a StudentCourse
            # row used to raise DoesNotExist and take down the whole batch.
            sc, _ = StudentCourse.objects.get_or_create(course=cr, student=s)
            sc.marks_set.update_or_create(
                name=mc.name, defaults={'marks1': form.marks_for(s)})
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
    if request.user.is_teacher:
        audiences = ['All', 'Teachers']
    elif request.user.is_student:
        audiences = ['All', 'Students']
    else:
        audiences = ['All', 'Students', 'Teachers']

    notice_list = Notice.objects.filter(audience__in=audiences)
    context = {'notice_list': notice_list}
    return render(request, 'info/notices.html', context)


@login_required()
def add_notice(request):
    if not (request.user.is_superuser or request.user.is_teacher):
        return redirect('/')

    if request.method == 'POST':
        Notice(
            title=request.POST['title'],
            message=request.POST['message'],
            audience=request.POST['audience'],
            posted_by=request.user,
        ).save()
        return redirect('notices')

    return render(request, 'info/add_notice.html')

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
