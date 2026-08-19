"""Role and ownership guards for the teacher-facing views.

Every view in this project used to carry @login_required and nothing else, so
any authenticated account - including a student's - could read and modify other
people's attendance and marks. These decorators put a role check and an
ownership check in one place instead of repeating them per view.
"""
from functools import wraps

from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404

from info.models import Assign, AttendanceClass, MarksClass, Student


def teacher_required(view):
    """Allow teachers and superusers only."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not (request.user.is_teacher or request.user.is_superuser):
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapper


def _assert_owns(request, assign):
    """Superusers see everything; a teacher only their own assignments."""
    if request.user.is_superuser:
        return
    if assign.teacher_id != request.user.teacher.id:
        raise PermissionDenied


def owns_assign(arg='assign_id'):
    """Guard views addressed by an Assign id."""
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            _assert_owns(request, get_object_or_404(Assign, id=kwargs[arg]))
            return view(request, *args, **kwargs)
        return wrapper
    return decorator


def owns_attendance_class(arg='ass_c_id'):
    """Guard views addressed by an AttendanceClass id."""
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            assc = get_object_or_404(AttendanceClass, id=kwargs[arg])
            _assert_owns(request, assc.assign)
            return view(request, *args, **kwargs)
        return wrapper
    return decorator


def owns_marks_class(arg='marks_c_id'):
    """Guard views addressed by a MarksClass id."""
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            mc = get_object_or_404(MarksClass, id=kwargs[arg])
            _assert_owns(request, mc.assign)
            return view(request, *args, **kwargs)
        return wrapper
    return decorator


def assert_teaches(request, course_id, student):
    """Raise unless the caller teaches `course_id` to `student`'s class.

    Used by the views addressed by a student/course pair or by an Attendance
    row, where there is no Assign in the URL to check against.
    """
    if request.user.is_superuser:
        return
    teaches = Assign.objects.filter(
        teacher=request.user.teacher,
        course_id=course_id,
        class_id=student.class_id_id,
    ).exists()
    if not teaches:
        raise PermissionDenied


def owns_teacher_id(arg='teacher_id'):
    """Guard views addressed by a Teacher id - you only get your own."""
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_superuser:
                if str(kwargs[arg]) != str(request.user.teacher.id):
                    raise PermissionDenied
            return view(request, *args, **kwargs)
        return wrapper
    return decorator


def owns_student_record(arg='stud_id'):
    """Guard the student-facing pages that name a student in the URL.

    These read as personal pages, but the USN comes from the path, so without
    this any signed-in account could read a classmate's attendance or marks by
    editing the address bar. Teachers of that student's class keep access -
    they are looking at the same numbers from the other side - and superusers
    see everything.

    Written to compare identifiers rather than fetch the student: the common
    case is somebody reading their own page, and that must not cost the pages
    an extra query on top of the one the view already makes.
    """
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            usn = kwargs[arg]
            user = request.user

            if user.is_superuser:
                pass
            elif user.is_student:
                if user.student.USN != usn:
                    raise PermissionDenied
            elif user.is_teacher:
                class_id = (Student.objects.filter(USN=usn)
                            .values_list('class_id_id', flat=True).first())
                if class_id is None:
                    raise Http404('No such student.')
                if not Assign.objects.filter(teacher=user.teacher,
                                             class_id=class_id).exists():
                    raise PermissionDenied
            else:
                raise PermissionDenied

            return view(request, *args, **kwargs)
        return wrapper
    return decorator
