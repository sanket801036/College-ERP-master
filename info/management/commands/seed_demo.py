"""Populate an empty database with enough data to actually use the app.

A fresh install has no Dept, Course, Class, Assign or AttendanceRange, and the
app is unusable until all of them exist - the admin has to create six kinds of
record, in the right order, before a single page shows anything. Worse, the
attendance signal reads AttendanceRange, so adding a timetable slot first used
to fail outright.

    python manage.py seed_demo
"""
import random
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.crypto import get_random_string

from info.models import (Assign, AssignTime, Attendance, AttendanceClass,
                         AttendanceRange, Class, Course, Dept, Fee, Notice,
                         Student, Teacher)

User = get_user_model()

DEPTS = [('CSE', 'Computer Science'), ('ECE', 'Electronics')]

COURSES = [
    ('CS501', 'Database Management Systems', 'DBMS', 'CSE'),
    ('CS502', 'Operating Systems', 'OS', 'CSE'),
    ('CS503', 'Computer Networks', 'CN', 'CSE'),
    ('EC501', 'Digital Signal Processing', 'DSP', 'ECE'),
]

TEACHERS = [
    ('t101', 'Ravi Shankar', 'CSE'),
    ('t102', 'Meera Nair', 'CSE'),
    ('t103', 'Arun Prasad', 'ECE'),
]

STUDENT_NAMES = [
    'Aarav Patel', 'Bhavna Singh', 'Chirag Gupta', 'Divya Menon',
    'Farhan Qureshi', 'Gauri Deshmukh', 'Harsh Vardhan', 'Ishita Roy',
    'Karan Malhotra', 'Lakshmi Iyer', 'Manav Joshi', 'Neha Kulkarni',
]

SLOTS = [
    ('CS501', 'Monday', '7:30 - 8:30'),
    ('CS501', 'Wednesday', '11:00 - 11:50'),
    ('CS502', 'Tuesday', '8:30 - 9:30'),
    ('CS502', 'Thursday', '2:30 - 3:30'),
    ('CS503', 'Monday', '11:50 - 12:40'),
    ('CS503', 'Friday', '9:30 - 10:30'),
]


class Command(BaseCommand):
    help = 'Create a demo department, class, teachers, students and history.'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true',
                            help='Delete existing demo data first.')

    @transaction.atomic
    def handle(self, *args, **options):
        if options['reset']:
            self.stdout.write('Clearing existing data...')
            for model in (Attendance, AttendanceClass, AssignTime, Assign,
                          Fee, Notice, Student, Teacher, Course, Class, Dept,
                          AttendanceRange):
                model.objects.all().delete()

            # Deleting the Student/Teacher rows leaves their login accounts
            # behind, matching neither role - they can still sign in and land
            # on a dead end. Superusers are kept.
            orphans = (User.objects
                       .filter(student__isnull=True, teacher__isnull=True,
                               is_superuser=False))
            count = orphans.count()
            orphans.delete()
            if count:
                self.stdout.write('  removed %d orphaned login(s)' % count)

        if Student.objects.exists():
            self.stdout.write(self.style.WARNING(
                'Database already has students - pass --reset to start over.'))
            return

        # The semester range has to exist before any AssignTime, because the
        # signal that generates attendance sessions reads it.
        term_start = date.today() - timedelta(days=60)
        AttendanceRange.objects.create(start_date=term_start,
                                       end_date=term_start + timedelta(days=150))

        depts = {d: Dept.objects.create(id=d, name=n) for d, n in DEPTS}
        klass = Class.objects.create(id='CSE-5A', dept=depts['CSE'],
                                     section='A', sem=5)

        courses = {
            cid: Course.objects.create(id=cid, name=name, shortname=short,
                                       dept=depts[dept])
            for cid, name, short, dept in COURSES
        }

        credentials = []
        teachers = {}
        for staff_id, name, dept in TEACHERS:
            user, password = self._make_user(name.split(' ')[0].lower(), staff_id)
            teachers[staff_id] = Teacher.objects.create(
                user=user, id=staff_id, dept=depts[dept], name=name,
                sex='Male', DOB=date(1980, 1, 1))
            credentials.append(('teacher', name, user.username, password))

        assigns = {}
        for course_id, staff_id in [('CS501', 't101'), ('CS502', 't102'),
                                    ('CS503', 't101')]:
            assigns[course_id] = Assign.objects.create(
                class_id=klass, course=courses[course_id],
                teacher=teachers[staff_id])

        students = []
        for i, name in enumerate(STUDENT_NAMES, start=1):
            usn = '1CS22CS%03d' % i
            user, password = self._make_user(name.split(' ')[0].lower(), usn[-3:])
            students.append(Student.objects.create(
                user=user, USN=usn, class_id=klass, name=name,
                sex='Female' if i % 2 == 0 else 'Male',
                DOB=date(2004, (i % 12) + 1, (i % 28) + 1)))
            if i <= 2:
                credentials.append(('student', name, user.username, password))

        for course_id, day, period in SLOTS:
            # Creating these generates the term's AttendanceClass rows.
            AssignTime.objects.create(assign=assigns[course_id], day=day,
                                      period=period)

        self._fill_attendance(students)
        self._fill_marks(assigns, students)
        self._fill_fees(students)
        self._add_notices()

        self.stdout.write(self.style.SUCCESS('\nDemo data created.\n'))
        self.stdout.write('%-9s %-18s %-16s %s' % ('ROLE', 'NAME', 'USERNAME',
                                                   'PASSWORD'))
        for role, name, username, password in credentials:
            self.stdout.write('%-9s %-18s %-16s %s' % (role, name, username,
                                                       password))
        self.stdout.write(
            '\nCreate an admin with: python manage.py createsuperuser\n')

    def _make_user(self, first_name, suffix):
        password = get_random_string(10, 'abcdefghijkmnpqrstuvwxyz23456789')
        username = '%s_%s' % (first_name, suffix)
        user = User.objects.create_user(
            username=username, email='%s@example.edu' % username,
            password=password)
        return user, password

    def _fill_attendance(self, students):
        """Mark every past session, leaving a couple of students short of 75%."""
        today = date.today()
        rows = []
        for session in AttendanceClass.objects.filter(date__lte=today):
            session.status = 1
            for i, student in enumerate(students):
                # The first two students attend ~60% so the low-attendance
                # warnings have something to show.
                chance = 0.6 if i < 2 else 0.9
                rows.append(Attendance(
                    course=session.assign.course, student=student,
                    attendanceclass=session, date=session.date,
                    status=random.random() < chance))
        AttendanceClass.objects.filter(date__lte=today).update(status=1)
        Attendance.objects.bulk_create(rows, batch_size=500)
        self.stdout.write('  attendance: %d records' % len(rows))

    def _fill_marks(self, assigns, students):
        from info.models import MarksClass, StudentCourse

        entered = ['Internal test 1', 'Internal test 2']
        count = 0
        for assign in assigns.values():
            for name in entered:
                for student in students:
                    sc, _ = StudentCourse.objects.get_or_create(
                        student=student, course=assign.course)
                    sc.marks_set.update_or_create(
                        name=name, defaults={'marks1': random.randint(8, 20)})
                    count += 1
            MarksClass.objects.filter(assign=assign, name__in=entered).update(
                status=True)
        self.stdout.write('  marks: %d entries (internals 1-2 only)' % count)

    def _fill_fees(self, students):
        due = date.today() + timedelta(days=14)
        rows = []
        for i, student in enumerate(students):
            rows.append(Fee(student=student, fee_type='Tuition Fee',
                            description='Semester 5 tuition', amount=45000,
                            paid_amount=45000 if i % 3 else 20000, due_date=due))
            rows.append(Fee(student=student, fee_type='Exam Fee',
                            description='Semester 5 examination', amount=2500,
                            paid_amount=0 if i % 4 == 0 else 2500,
                            due_date=due + timedelta(days=30)))
        Fee.objects.bulk_create(rows)
        self.stdout.write('  fees: %d records' % len(rows))

    def _add_notices(self):
        Notice.objects.create(
            title='Semester End Exam timetable released',
            message='The examination schedule for Semester 5 is now available '
                    'on the department noticeboard. Check your seat numbers.',
            audience='Students')
        Notice.objects.create(
            title='Library closed for stocktaking on Saturday',
            message='The central library will remain closed all day Saturday.',
            audience='All')
        Notice.objects.create(
            title='Internal marks entry deadline',
            message='Internal test 3 marks must be entered by the end of the '
                    'month.',
            audience='Teachers')
        self.stdout.write('  notices: 3')
