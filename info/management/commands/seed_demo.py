"""Populate an empty database with enough data to actually use the app.

A fresh install has no Dept, Course, Class, Assign or AttendanceRange, and the
app is unusable until all of them exist - the admin has to create six kinds of
record, in the right order, before a single page shows anything. Worse, the
attendance signal reads AttendanceRange, so adding a timetable slot first used
to fail outright.

    python manage.py seed_demo
"""
import io
import random
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.crypto import get_random_string
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from info import notifications, services
from info.models import (
    Assign,
    AssignTime,
    Attendance,
    AttendanceClass,
    AttendanceCorrection,
    AttendanceRange,
    Class,
    Course,
    Dept,
    Fee,
    LeaveRequest,
    MarkQuery,
    Marks,
    MarksClass,
    Notice,
    Notification,
    Student,
    Teacher,
)

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
        parser.add_argument(
            '--demo-logins', action='store_true',
            help='Also create the three published demo accounts (admin, '
                 'teststud, testteach) with their known passwords.')

    @transaction.atomic
    def handle(self, *args, **options):
        if options['reset']:
            self.stdout.write('Clearing existing data...')
            # Children before parents. Most of these would cascade anyway, but
            # Notification hangs off User rather than Student, so a re-seed
            # would otherwise leave the bell counting messages about people who
            # no longer exist.
            for model in (Notification, MarkQuery, AttendanceCorrection,
                          LeaveRequest, Attendance, AttendanceClass,
                          AssignTime, Assign, Fee, Notice, Student, Teacher,
                          Course, Class, Dept, AttendanceRange):
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
        self._publish_marks(assigns)
        self._add_workflows(assigns, teachers, students)

        self.stdout.write(self.style.SUCCESS('\nDemo data created.\n'))
        self.stdout.write('%-9s %-18s %-16s %s' % ('ROLE', 'NAME', 'USERNAME',
                                                   'PASSWORD'))
        for role, name, username, password in credentials:
            self.stdout.write('%-9s %-18s %-16s %s' % (role, name, username,
                                                       password))
        if options['demo_logins']:
            self._demo_logins(students[0], teachers['t101'])
        else:
            self.stdout.write(
                '\nCreate an admin with: python manage.py createsuperuser\n')

    def _demo_logins(self, student, teacher):
        """The three accounts a public demo advertises.

        Deliberately fixed and deliberately weak: they are printed on a
        portfolio page for strangers to try, so the passwords are the point
        rather than an oversight. Everything else this command creates gets a
        random one.

        They attach to people the seed already created rather than making new
        ones, so signing in as the demo student lands on a populated
        timetable, attendance and marks instead of an empty shell.
        """
        accounts = [
            ('admin', 'admin12345', None),
            ('teststud', 'testpass123', student),
            ('testteach', 'testpass123', teacher),
        ]

        for username, password, profile in accounts:
            user = User.objects.filter(username=username).first()
            if user is None:
                user = User(username=username,
                            email='%s@example.edu' % username)
            user.set_password(password)
            # An account handed to a stranger should not be met by the
            # change-your-password screen the moment they sign in.
            user.must_change_password = False
            user.is_superuser = user.is_staff = profile is None
            user.save()

            if profile is not None:
                # The seeded person's own login is replaced rather than left
                # beside this one: two accounts pointing at one student is not
                # a state the app should have to reason about.
                previous = profile.user
                profile.user = user
                profile.save(update_fields=['user'])
                if previous is not None and previous.pk != user.pk:
                    previous.delete()

        self.stdout.write(self.style.SUCCESS('PUBLISHED DEMO LOGINS'))
        for username, password, _ in accounts:
            self.stdout.write('  %-12s %s' % (username, password))
        self.stdout.write(
            '  These are public by design. Do not reuse them anywhere real.')

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
        from info.models import StudentCourse

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

    def _publish_marks(self, assigns):
        """Release the first internal, and tell the class it is out.

        Publication is what a student can see, and it is also what opens the
        seven-day window for questioning a mark - so without this the
        re-evaluation workflow below would have nothing to work on.
        """
        for assign in assigns.values():
            batch = MarksClass.objects.get(assign=assign,
                                           name='Internal test 1')
            batch.publish()
            notifications.announce(notifications.messages_for_batch(batch))
        self.stdout.write('  marks published: internal test 1')

    def _add_workflows(self, assigns, teachers, students):
        """One of each request-and-approve workflow, in both states.

        A demo where every queue is empty shows none of this, so each workflow
        gets one answered case and one still waiting - which is also what the
        teacher's queues need in order to look like queues.
        """
        teacher = teachers['t101']
        course = assigns['CS501'].course

        # Re-evaluation: one accepted, one still open.
        settled = Marks.objects.get(studentcourse__student=students[2],
                                    studentcourse__course=course,
                                    name='Internal test 1')
        query = services.raise_mark_query(
            settled, students[2],
            'Question 4(b) is marked out of 5 on my paper but the scheme says '
            '10. Could you check the total?', students[2].user)
        services.resolve_mark_query(
            query, teacher.user, accept=True,
            response='You are right, the total was added wrong. Corrected.',
            new_mark=min(settled.total_marks, settled.marks1 + 3))
        notifications.announce(notifications.messages_for_query_resolved(query))

        pending = Marks.objects.get(studentcourse__student=students[3],
                                    studentcourse__course=course,
                                    name='Internal test 1')
        waiting = services.raise_mark_query(
            pending, students[3],
            'I answered the last question on the back of the sheet and I do '
            'not think it was seen.', students[3].user)
        notifications.announce(notifications.messages_for_query_raised(waiting))

        # Leave: one approved with a certificate, one waiting.
        #
        # The dates come from a real absence rather than a guess. Picking
        # "three days ago" and hoping produces an approval that excused
        # nothing, which reads as the feature not working - the whole point of
        # approving leave is the sessions it takes out of the percentage.
        absent_on = (Attendance.objects
                     .filter(student=students[0], status=False,
                             is_excused=False,
                             date__gte=date.today() - timedelta(days=12),
                             date__lte=date.today())
                     .order_by('-date')
                     .values_list('date', flat=True).first())
        first_day = absent_on or date.today() - timedelta(days=3)
        approved = services.apply_for_leave(
            students[0], 'Medical', first_day, first_day,
            'Viral fever - certificate from the college doctor attached.',
            students[0].user, document=self._certificate())
        services.approve_leave(approved, teacher.user,
                               'Certificate received. Get well.')
        notifications.announce(notifications.messages_for_leave_decided(approved))

        upcoming = services.apply_for_leave(
            students[1], 'Official duty', date.today() + timedelta(days=2),
            date.today() + timedelta(days=3),
            'Selected for the inter-college hackathon at the city campus.',
            students[1].user)
        notifications.announce(notifications.messages_for_leave_applied(upcoming))

        # Attendance dispute: one accepted, one waiting.
        disputes = 0
        for student, reason, accept in [
            (students[4], 'I was in the lab that morning and signed the '
                          'sheet - I think it was passed round late.', True),
            (students[5], 'I came in after the roll call because the bus was '
                          'diverted. I was there for the whole class.', False),
        ]:
            # The most recent session inside the seven-day window, whatever
            # it says. Waiting for the random marking above to hand us an
            # absence in the right week means the demo sometimes ships with an
            # empty queue, so the absence is arranged rather than hoped for.
            record = (Attendance.objects
                      .filter(student=student, course=course,
                              date__gte=date.today() - timedelta(days=6),
                              date__lte=date.today())
                      .order_by('-date').first())
            if record is None:
                continue
            if record.status or record.is_excused:
                record.status = False
                record.is_excused = False
                record.save(update_fields=['status', 'is_excused'])

            dispute = services.dispute_attendance(record, student, reason,
                                                  student.user)
            disputes += 1
            if accept:
                services.resolve_correction(
                    dispute, teacher.user, accept=True,
                    response='Found your signature on the sheet. Corrected.')
                notifications.announce(
                    notifications.messages_for_dispute_resolved(dispute))
            else:
                notifications.announce(
                    notifications.messages_for_dispute_raised(dispute))

        self.stdout.write('  workflows: 2 mark queries, 2 leave applications, '
                          '%d attendance disputes' % disputes)

    def _certificate(self):
        """A one-line PDF, so the leave application has a real attachment.

        Also the end-to-end proof that object storage is wired up: this is a
        file written through whatever STORAGES points at, and on the deployed
        site it has to survive the next redeploy.
        """
        buffer = io.BytesIO()
        page = canvas.Canvas(buffer, pagesize=A4)
        page.setFont('Helvetica-Bold', 14)
        page.drawString(25 * mm, 260 * mm, 'Medical certificate')
        page.setFont('Helvetica', 11)
        page.drawString(25 * mm, 248 * mm,
                        'This is demonstration data, not a real certificate.')
        page.showPage()
        page.save()
        buffer.seek(0)
        return ContentFile(buffer.read(), name='certificate.pdf')
