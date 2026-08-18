"""Read-only endpoints returning the signed-in student's own records.

These were unusable as written. Each view re-derived the user from a Token row
on top of the authentication DRF had already done, so a perfectly valid session
was rejected with 400 "User not authenticated" - and since nothing in the app
ever issued a token, that was every caller. permission_classes already covers
this; request.user is populated by the time the view runs.
"""
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

import apis.serializers as api_ser
from info.models import (
    ATTENDANCE_THRESHOLD,
    Assign,
    AssignTime,
    Attendance,
    AttendanceClass,
    AttendanceTotal,
    Course,
    Student,
    StudentCourse,
    Teacher,
)
from info.services import SessionNotMarkable, submit_attendance


class StudentAPIView(APIView):
    """Base for the endpoints scoped to the caller's own student record."""
    permission_classes = [IsAuthenticated]

    def get_student(self, request):
        # 404 rather than the old catch-all 400: a teacher or admin calling
        # these has no student record, which is a missing resource, not a
        # failed login.
        return get_object_or_404(Student, user=request.user)


class DetailView(StudentAPIView):
    """The caller's own profile."""

    def get(self, request):
        student = self.get_student(request)
        serializer = api_ser.StudentSerializer(student,
                                               context={'request': request})
        return Response({'data': serializer.data})


class AttendanceView(StudentAPIView):
    """Attendance totals per course."""

    def get(self, request):
        student = self.get_student(request)
        courses = Course.objects.filter(
            assign__class_id=student.class_id_id).distinct()

        # The old version created missing AttendanceTotal rows inside the GET
        # handler. A read should not write - and AttendanceTotal stores nothing
        # of its own anyway, the counts all come from Attendance - so the
        # totals are assembled in memory from a single grouped query instead.
        counts = (Attendance.objects
                  .filter(student=student, course__in=courses)
                  .values('course')
                  .annotate(held=Count('pk'),
                            attended=Count('pk', filter=Q(status=True))))
        by_course = {row['course']: row for row in counts}

        totals = []
        for course in courses:
            total = AttendanceTotal(student=student, course=course)
            row = by_course.get(course.id, {})
            total._held = row.get('held', 0)
            total._attended = row.get('attended', 0)
            totals.append(total)

        serializer = api_ser.AttendanceSerializer(
            totals, many=True, context={'request': request})
        return Response({'data': serializer.data})


class MarksView(StudentAPIView):
    """Marks and CIE per course."""

    def get(self, request):
        student = self.get_student(request)
        courses = Course.objects.filter(
            assign__class_id=student.class_id_id).distinct()

        # A bare .get() here meant a student missing one StudentCourse row got
        # an opaque 400 for the whole endpoint.
        records = (StudentCourse.objects
                   .filter(student=student, course__in=courses)
                   .select_related('course')
                   .prefetch_related('marks_set'))
        serializer = api_ser.MarksSerializer(records, many=True,
                                             context={'request': request})
        return Response({'data': serializer.data})


class TimetableView(StudentAPIView):
    """The caller's class timetable."""

    def get(self, request):
        student = self.get_student(request)
        slots = (AssignTime.objects
                 .filter(assign__class_id=student.class_id_id)
                 .select_related('assign__course', 'assign__teacher'))
        serializer = api_ser.TimetableSerializer(
            slots, many=True, context={'request': request})
        # This returned its payload under the key "user_marks", copied from the
        # marks view. Every endpoint uses "data" now.
        return Response({'data': serializer.data})


class TeacherAPIView(APIView):
    """Base for the endpoints scoped to the caller's own teaching load.

    The web views got role and ownership guards; the API was still
    student-only, so there was nothing here to guard.
    """
    permission_classes = [IsAuthenticated]

    def get_teacher(self, request):
        if request.user.is_superuser:
            return None  # sees everything
        return get_object_or_404(Teacher, user=request.user)

    def assignments(self, request):
        teacher = self.get_teacher(request)
        qs = Assign.objects.select_related('course', 'class_id')
        return qs if teacher is None else qs.filter(teacher=teacher)


@extend_schema(
    summary="The caller's classes",
    description='Assignments the signed-in teacher takes, with student counts. '
                'Superusers see every assignment.',
    responses=api_ser.ClassSerializer,
)
class TeacherClassesView(TeacherAPIView):
    def get(self, request):
        assigns = self.assignments(request).annotate(
            student_count=Count('class_id__student', distinct=True))
        serializer = api_ser.ClassSerializer(assigns, many=True,
                                             context={'request': request})
        return Response({'data': serializer.data})


@extend_schema(
    summary='Students in one class, with attendance standing',
    description='Restricted to an assignment the caller teaches.',
    responses=api_ser.ClassStudentSerializer,
)
class ClassStudentsView(TeacherAPIView):
    def get(self, request, assign_id):
        assign = get_object_or_404(self.assignments(request), id=assign_id)

        students = list(assign.class_id.student_set.all().order_by('USN'))
        counts = (Attendance.objects
                  .filter(course=assign.course, student__in=students)
                  .values('student')
                  .annotate(held=Count('pk'),
                            attended=Count('pk', filter=Q(status=True))))
        by_student = {row['student']: row for row in counts}

        rows = []
        for student in students:
            row = by_student.get(student.USN, {})
            held = row.get('held', 0)
            attended = row.get('attended', 0)
            percentage = round(attended / held * 100, 2) if held else 0
            rows.append({
                'usn': student.USN,
                'name': student.name,
                'attended': attended,
                'held': held,
                'percentage': percentage,
                # Below the exam-eligibility line, and only meaningful once the
                # course has actually met.
                'at_risk': held > 0 and percentage < ATTENDANCE_THRESHOLD * 100,
            })

        serializer = api_ser.ClassStudentSerializer(rows, many=True)
        return Response({'data': serializer.data})


@extend_schema(
    summary='Exchange a username and password for a token',
    description='Nothing in the application issued tokens, so the only way to '
                'authenticate was a session cookie or a token created by hand '
                'in the shell.',
    request=None,
    responses=api_ser.TokenSerializer,
)
class ObtainTokenView(ObtainAuthToken):
    # The one endpoint that must be reachable while signed out.
    permission_classes = [AllowAny]
    throttle_scope = 'login'

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data,
                                           context={'request': request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        token, _ = Token.objects.get_or_create(user=user)

        role = ('admin' if user.is_superuser
                else 'teacher' if user.is_teacher
                else 'student' if user.is_student
                else 'none')
        return Response({'data': {'token': token.key,
                                  'username': user.username,
                                  'role': role}})


@extend_schema(
    summary='Submit attendance for a session',
    description='Marks every student in the class: those listed present, the '
                'rest absent. Re-submitting a session updates it and records '
                'what changed.',
    request=api_ser.AttendanceSubmitSerializer,
    responses=api_ser.AttendanceSubmitResultSerializer,
)
class SubmitAttendanceView(TeacherAPIView):
    def post(self, request, session_id):
        # Scoped through assignments(), so a teacher can only mark a session of
        # their own class - the same rule the web view enforces.
        session = get_object_or_404(
            AttendanceClass.objects.filter(assign__in=self.assignments(request)),
            id=session_id)

        roll = [s.USN for s in session.assign.class_id.student_set.all()]
        serializer = api_ser.AttendanceSubmitSerializer(data=request.data,
                                                        roll=roll)
        serializer.is_valid(raise_exception=True)

        try:
            # Shared with the web view rather than reimplemented: an API with
            # its own copy of these rules is a way around them.
            created, changed = submit_attendance(
                session, serializer.validated_data['present'], request.user)
        except SessionNotMarkable as exc:
            return Response({'detail': str(exc)},
                            status=status.HTTP_409_CONFLICT)

        return Response({'data': {
            'session_id': session.id,
            'date': session.date,
            'first_submission': created,
            'changed': changed,
            'present': len(serializer.validated_data['present']),
            'total': len(roll),
        }})
