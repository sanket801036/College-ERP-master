"""Read-only endpoints returning the signed-in student's own records.

These were unusable as written. Each view re-derived the user from a Token row
on top of the authentication DRF had already done, so a perfectly valid session
was rejected with 400 "User not authenticated" - and since nothing in the app
ever issued a token, that was every caller. permission_classes already covers
this; request.user is populated by the time the view runs.
"""
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from info.models import (AssignTime, Attendance, AttendanceTotal, Course,
                         Student, StudentCourse)

import apis.serializers as api_ser


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
