from django.db import models
import math
from decimal import Decimal
from django.db.models.functions import Coalesce
from django.utils.functional import cached_property
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from django.contrib.auth.models import AbstractUser
from django.db.models.signals import post_save, post_delete
from datetime import timedelta

# Create your models here.
sex_choice = (
    ('Male', 'Male'),
    ('Female', 'Female')
)

time_slots = (
    ('7:30 - 8:30', '7:30 - 8:30'),
    ('8:30 - 9:30', '8:30 - 9:30'),
    ('9:30 - 10:30', '9:30 - 10:30'),
    ('11:00 - 11:50', '11:00 - 11:50'),
    ('11:50 - 12:40', '11:50 - 12:40'),
    ('12:40 - 1:30', '12:40 - 1:30'),
    ('2:30 - 3:30', '2:30 - 3:30'),
    ('3:30 - 4:30', '3:30 - 4:30'),
    ('4:30 - 5:30', '4:30 - 5:30'),
)

DAYS_OF_WEEK = (
    ('Monday', 'Monday'),
    ('Tuesday', 'Tuesday'),
    ('Wednesday', 'Wednesday'),
    ('Thursday', 'Thursday'),
    ('Friday', 'Friday'),
    ('Saturday', 'Saturday'),
)

# The three internals in order. A comparison across these is fair - same kind
# of assessment, same ceiling, sequential through the term - which the events
# are not, so a trend is drawn over these alone.
INTERNAL_COMPONENTS = (
    'Internal test 1',
    'Internal test 2',
    'Internal test 3',
)

CIE_COMPONENTS = (
    'Internal test 1',
    'Internal test 2',
    'Internal test 3',
    'Event 1',
    'Event 2',
)

test_name = (
    ('Internal test 1', 'Internal test 1'),
    ('Internal test 2', 'Internal test 2'),
    ('Internal test 3', 'Internal test 3'),
    ('Event 1', 'Event 1'),
    ('Event 2', 'Event 2'),
    ('Semester End Exam', 'Semester End Exam'),
)

SEE_NAME = 'Semester End Exam'

# The marking scheme, stated once. Five CIE components of 20 each, halved to a
# CIE out of 50; the semester-end exam is out of 100 and contributes half its
# mark, so a final is out of 100.
CIE_MAX = 50
SEE_MAX = 100

# VTU's 10-point scale: (minimum final mark, letter, grade points). Ordered
# high to low so the first match wins.
GRADE_BANDS = (
    (90, 'O', 10),
    (80, 'A+', 9),
    (70, 'A', 8),
    (60, 'B+', 7),
    (55, 'B', 6),
    (50, 'C', 5),
    (40, 'P', 4),
    (0, 'F', 0),
)

# 40% of the CIE is needed to sit the semester-end exam.
SEE_ELIGIBILITY_CIE = 20


def grade_for(final_marks):
    """(letter, points) for a final mark out of 100."""
    for floor, letter, points in GRADE_BANDS:
        if final_marks >= floor:
            return letter, points
    return 'F', 0


def required_see_for(cie, floor):
    """SEE mark needed to reach `floor`, given a CIE already banked.

    final = cie + see/2, so see = (floor - cie) * 2. Returns 0 when the band is
    already secured on the CIE alone, and None when it cannot be reached even
    with a perfect paper - which is the honest answer, not a number over 100.
    """
    needed = math.ceil((floor - cie) * 2)
    if needed <= 0:
        return 0
    if needed > SEE_MAX:
        return None
    return needed


def sgpa_for(student_courses):
    """Credit-weighted SGPA over the courses whose result is actually in.

    This is what Course.credits was added for: an unweighted mean would let a
    one-credit lab pull the same weight as a four-credit core paper. Returns
    None while no course has a semester-end mark - a partial SGPA presented as
    a whole one is worse than no number.
    """
    graded = [(sc.grade[1], sc.course.credits)
              for sc in student_courses if sc.grade]
    if not graded:
        return None
    credits = sum(credit for _, credit in graded)
    return round(sum(points * credit for points, credit in graded) / credits, 2)


class User(AbstractUser):
    # Set when an admin creates the account, cleared once the user picks their
    # own password. See info.middleware.ForcePasswordChangeMiddleware.
    must_change_password = models.BooleanField(default=False)

    @property
    def is_student(self):
        if hasattr(self, 'student'):
            return True
        return False

    @property
    def is_teacher(self):
        if hasattr(self, 'teacher'):
            return True
        return False


class Dept(models.Model):
    id = models.CharField(primary_key='True', max_length=100)
    name = models.CharField(max_length=200)

    def __str__(self):
        return self.name


class Course(models.Model):
    dept = models.ForeignKey(Dept, on_delete=models.CASCADE)
    id = models.CharField(primary_key='True', max_length=50)
    name = models.CharField(max_length=50)
    shortname = models.CharField(max_length=50, default='X')
    # Without this a credit-weighted SGPA/CGPA cannot be computed at all - an
    # average of course percentages weights a 1-credit lab the same as a
    # 4-credit core paper. 4 is the common default for a theory course; set it
    # per course in the admin.
    credits = models.PositiveSmallIntegerField(
        default=4, validators=[MinValueValidator(1), MaxValueValidator(10)],
        help_text='Credit weight used for SGPA/CGPA.')

    def __str__(self):
        return self.name


class Class(models.Model):
    # courses = models.ManyToManyField(Course, default=1)
    id = models.CharField(primary_key='True', max_length=100)
    dept = models.ForeignKey(Dept, on_delete=models.CASCADE)
    section = models.CharField(max_length=100)
    sem = models.IntegerField()

    class Meta:
        verbose_name_plural = 'classes'

    def __str__(self):
        return '%s : %d %s' % (self.dept.name, self.sem, self.section)


class Student(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True)
    class_id = models.ForeignKey(Class, on_delete=models.CASCADE, default=1)
    USN = models.CharField(primary_key='True', max_length=100)
    name = models.CharField(max_length=200)
    sex = models.CharField(max_length=50, choices=sex_choice, default='Male')
    DOB = models.DateField(default='1998-01-01')
    # Contact details the person maintains themselves. Kept off the
    # add-student/add-teacher forms deliberately - an admin enrolling somebody
    # has their USN and class, not their phone number.
    phone = models.CharField(max_length=20, blank=True)
    address = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return self.name


class Teacher(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True)
    id = models.CharField(primary_key=True, max_length=100)
    dept = models.ForeignKey(Dept, on_delete=models.CASCADE, default=1)
    name = models.CharField(max_length=100)
    sex = models.CharField(max_length=50, choices=sex_choice, default='Male')
    DOB = models.DateField(default='1980-01-01')
    # Contact details the person maintains themselves. Kept off the
    # add-student/add-teacher forms deliberately - an admin enrolling somebody
    # has their USN and class, not their phone number.
    phone = models.CharField(max_length=20, blank=True)
    address = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return self.name


class Assign(models.Model):
    class_id = models.ForeignKey(Class, on_delete=models.CASCADE)
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE)

    class Meta:
        unique_together = (('course', 'class_id', 'teacher'),)

    def __str__(self):
        cl = Class.objects.get(id=self.class_id_id)
        cr = Course.objects.get(id=self.course_id)
        te = Teacher.objects.get(id=self.teacher_id)
        return '%s : %s : %s' % (te.name, cr.shortname, cl)


class AssignTime(models.Model):
    assign = models.ForeignKey(Assign, on_delete=models.CASCADE)
    period = models.CharField(max_length=50, choices=time_slots, default='11:00 - 11:50')
    day = models.CharField(max_length=15, choices=DAYS_OF_WEEK)

    class Meta:
        # Stops the exact same assignment being scheduled twice in one slot. The
        # two clashes that actually matter - a class with two courses at once,
        # or a teacher in two places at once - span a foreign key and so cannot
        # be expressed as a constraint; clean() checks those.
        unique_together = (('assign', 'day', 'period'),)

    def __str__(self):
        return '%s : %s %s' % (self.assign, self.day, self.period)

    def clean(self):
        """Reject timetable clashes before they reach the database.

        Nothing prevented these, and a class with two courses in one slot made
        the timetable page raise MultipleObjectsReturned for every student in
        that class.
        """
        super().clean()
        if self.assign_id is None:
            return

        others = AssignTime.objects.filter(day=self.day, period=self.period)
        if self.pk:
            others = others.exclude(pk=self.pk)

        clash = others.filter(assign__class_id=self.assign.class_id_id).first()
        if clash:
            raise ValidationError(
                '%s already has %s in this slot.'
                % (self.assign.class_id, clash.assign.course))

        clash = others.filter(assign__teacher=self.assign.teacher_id).first()
        if clash:
            raise ValidationError(
                '%s is already teaching %s in this slot.'
                % (self.assign.teacher, clash.assign.class_id))


# These were bare integers with no choices and no names: 0 not taken, 1 taken,
# 2 cancelled, with 2 documented nowhere at all.
CLASS_PENDING = 0
CLASS_TAKEN = 1
CLASS_CANCELLED = 2

class_status_choice = (
    (CLASS_PENDING, 'Not taken'),
    (CLASS_TAKEN, 'Submitted'),
    (CLASS_CANCELLED, 'Cancelled'),
)


class AttendanceClass(models.Model):
    assign = models.ForeignKey(Assign, on_delete=models.CASCADE)
    date = models.DateField()
    status = models.IntegerField(default=CLASS_PENDING,
                                 choices=class_status_choice)

    class Meta:
        verbose_name = 'Attendance'
        verbose_name_plural = 'Attendance'

    @property
    def is_future(self):
        return self.date > timezone.localdate()

    @property
    def is_today(self):
        return self.date == timezone.localdate()

    @property
    def state(self):
        """One label covering the stored status and where the date sits.

        A scheduled session nobody could have marked yet is not the same thing
        as one the teacher still owes, but the stored status cannot tell them
        apart - both are 0.
        """
        if self.status == CLASS_CANCELLED:
            return 'cancelled'
        if self.status == CLASS_TAKEN:
            return 'submitted'
        return 'future' if self.is_future else 'pending'

    @property
    def is_markable(self):
        """Cancelled sessions and ones that have not happened cannot be marked."""
        return self.status != CLASS_CANCELLED and not self.is_future


class Attendance(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    attendanceclass = models.ForeignKey(AttendanceClass, on_delete=models.CASCADE, default=1)
    date = models.DateField(default='2018-10-23')
    # Was the string 'True'. It round-trips through the database correctly, so
    # this was never data corruption - but an unsaved instance held the literal
    # string, and bool('False') is True, so any check on a fresh object read
    # the opposite of what it said.
    status = models.BooleanField(default=True)

    def __str__(self):
        return '%s : %s' % (self.student.name, self.course.shortname)


ATTENDANCE_THRESHOLD = 0.75


class AttendanceTotalQuerySet(models.QuerySet):
    def with_counts(self):
        """Annotate held/attended counts so a list costs one query, not N.

        Attendance has no foreign key to AttendanceTotal - the two are joined on
        (student, course) - so this correlates on both columns rather than
        following a relation.
        """
        def count_of(**extra):
            return (Attendance.objects
                    .filter(student=models.OuterRef('student'),
                            course=models.OuterRef('course'), **extra)
                    .order_by()
                    .values('student')
                    .annotate(n=models.Count('*'))
                    .values('n')[:1])

        as_int = models.IntegerField()
        return self.annotate(
            _held=Coalesce(models.Subquery(count_of(), output_field=as_int), 0),
            _attended=Coalesce(
                models.Subquery(count_of(status=True), output_field=as_int), 0),
        )


class AttendanceTotal(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    student = models.ForeignKey(Student, on_delete=models.CASCADE)

    objects = AttendanceTotalQuerySet.as_manager()

    class Meta:
        unique_together = (('student', 'course'),)

    @cached_property
    def _counts(self):
        """(held, attended) for this student and course.

        Every property below used to run its own pair of lookups plus a COUNT,
        and looked the records up by *name* - `Student.objects.get(name=...)` -
        even though the related objects were already loaded. Two students
        sharing a name raised MultipleObjectsReturned and 500'd the page.

        Values annotated by with_counts() are used when present, so rendering a
        whole class does not go back to the database per row.
        """
        held = getattr(self, '_held', None)
        if held is not None:
            return held, self._attended

        counts = (Attendance.objects
                  .filter(student_id=self.student_id, course_id=self.course_id)
                  .aggregate(held=models.Count('pk'),
                             attended=models.Count('pk',
                                                   filter=models.Q(status=True))))
        return counts['held'], counts['attended']

    @property
    def att_class(self):
        return self._counts[1]

    @property
    def total_class(self):
        return self._counts[0]

    @property
    def has_classes(self):
        """False before the course has met at all.

        Templates need this to tell "no classes yet" apart from 0%, which
        otherwise renders as an alarming red zero for a course that simply
        hasn't started.
        """
        return self._counts[0] > 0

    @property
    def attendance(self):
        held, attended = self._counts
        if held == 0:
            return 0
        return round(attended / held * 100, 2)

    @property
    def classes_to_attend(self):
        """How many more consecutive classes are needed to reach the threshold.

        Assumes every remaining class is attended.
        """
        held, attended = self._counts
        cta = math.ceil((ATTENDANCE_THRESHOLD * held - attended)
                        / (1 - ATTENDANCE_THRESHOLD))
        return max(cta, 0)

    @property
    def classes_can_skip(self):
        """How many classes can still be missed while staying at the threshold."""
        held, attended = self._counts
        if held == 0:
            return 0
        return max(math.floor(attended / ATTENDANCE_THRESHOLD) - held, 0)


class StudentCourse(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    course = models.ForeignKey(Course, on_delete=models.CASCADE)

    # Populated lazily by get_cie/get_attendance, or in bulk by
    # attach_attendance(), so a class listing does not query per row.
    _cie_cache = None
    _attendance_cache = None
    # Which components the teacher has actually submitted, filled in bulk by
    # attach_submitted(). None means "not loaded", and everything below then
    # falls back to treating a component as submitted - the old behaviour.
    _submitted_cache = None
    # Which components have been *entered*, as opposed to released. On the
    # student page these differ, and telling a student that a test they sat
    # last week was "not yet conducted" is its own small lie.
    _entered_cache = None
    # (rank, class size) for this course, filled by attach_rank().
    _rank_cache = None

    class Meta:
        unique_together = (('student', 'course'),)
        verbose_name_plural = 'Marks'

    def __str__(self):
        return '%s : %s' % (self.student.name, self.course.shortname)

    def get_cie(self):
        """CIE over the components the viewer is allowed to see.

        This has to respect visibility, not just sum everything: on the student
        page a withheld component that still counted towards the total let the
        mark be recovered by subtracting the visible ones, which defeats the
        point of holding results back.
        """
        # Templates reference this twice per row (once to pick a colour, once
        # to print it), so memoise rather than walking the marks each time.
        if self._cie_cache is None:
            scored = {m.name: m.marks1 for m in self.marks_set.all()
                      if self.is_submitted(m.name)}
            self._cie_cache = math.ceil(
                sum(scored.get(name, 0) for name in CIE_COMPONENTS) / 2)
        return self._cie_cache

    def get_attendance(self):
        """Attendance percentage for this student on this course.

        Views rendering a whole class should call attach_attendance() first;
        otherwise this falls back to a query per row.
        """
        if self._attendance_cache is None:
            total = AttendanceTotal.objects.filter(student=self.student,
                                                   course=self.course).first()
            self._attendance_cache = total.attendance if total else 0
        return self._attendance_cache

    @property
    def marks_in_order(self):
        """The six components in the order the marks table's headers list them.

        The template used to iterate marks_set.all() straight into columns
        headed Internals 1-3 / Events / SEE, but Marks has no Meta.ordering, so
        a value could land under the wrong heading.
        """
        scored = {m.name: m for m in self.marks_set.all()}
        return [scored.get(name) for name, _ in test_name]

    def is_submitted(self, name):
        """Is this component's mark visible to whoever is looking?

        marks1 defaults to 0, so a test that has not been sat is indistinguishable
        from one scored zero unless MarksClass is consulted.
        """
        if self._submitted_cache is None:
            return True
        return name in self._submitted_cache

    @property
    def visible_components(self):
        """The component names this row is allowed to show."""
        return self._submitted_cache if self._submitted_cache is not None \
            else set(CIE_COMPONENTS)

    def is_entered(self, name):
        """Has the teacher entered this component, whether or not it is out?"""
        if self._entered_cache is None:
            return self.is_submitted(name)
        return name in self._entered_cache

    def component_rows(self):
        """The five CIE components, each with its mark or a pending flag."""
        scored = {m.name: m for m in self.marks_set.all()}
        rows = []
        for name in CIE_COMPONENTS:
            mark = scored.get(name)
            rows.append({
                'name': name,
                'marks': mark.marks1 if mark else 0,
                'total': mark.total_marks if mark else 20,
                'pending': mark is None or not self.is_submitted(name),
                # Entered but held back. "Not yet conducted" would be wrong for
                # a test the student sat last week.
                'awaiting_release': (not self.is_submitted(name)
                                     and self.is_entered(name)),
                # Still counts as zero towards the CIE, but the page says which
                # of the two it was rather than showing a bare 0.
                'absent': bool(mark and mark.is_absent),
            })
        return rows

    def internal_trend(self):
        """Submitted internals in order, as (label, mark, total).

        Only what has been released - an unsat test plotted at zero reads as a
        collapse in performance rather than a test that has not happened.
        """
        scored = {m.name: m for m in self.marks_set.all()}
        rows = []
        for index, name in enumerate(INTERNAL_COMPONENTS, start=1):
            mark = scored.get(name)
            if mark is None or not self.is_submitted(name):
                continue
            rows.append({'label': 'I%d' % index,
                         'marks': mark.marks1,
                         'total': mark.total_marks})
        return rows

    def get_see(self):
        """The semester-end mark out of 100, or None if it has not been sat."""
        if not self.is_submitted(SEE_NAME):
            return None
        mark = next((m for m in self.marks_set.all() if m.name == SEE_NAME), None)
        return mark.marks1 if mark else None

    @property
    def cie_percent(self):
        """CIE as a percentage, so the meter can read it against a limit."""
        return round(self.get_cie() / CIE_MAX * 100, 1)

    @property
    def is_at_risk(self):
        """Low on both attendance and marks.

        Either alone is common and often recoverable; together they are the
        signal a teacher can act on, which is why the class report highlights
        the combination rather than colouring two columns independently.
        """
        return (self.get_attendance() < ATTENDANCE_THRESHOLD * 100
                and self.get_cie() < SEE_ELIGIBILITY_CIE)

    @property
    def has_marks(self):
        """Has any CIE component been submitted for this course yet?"""
        return any(not row['pending'] for row in self.component_rows())

    @property
    def cie_is_final(self):
        """Are all five CIE components in?

        Until they are, the CIE is a running subtotal and nothing should be
        concluded from it - a course whose tests have not been sat yet sits at
        0 and would otherwise read as a failing one.
        """
        return all(not row['pending'] for row in self.component_rows())

    @property
    def is_see_eligible(self):
        """None while the CIE is still incomplete - not yet decided.

        Returning False there would flag a course that has simply not started
        as one the student has already failed out of.
        """
        if not self.cie_is_final:
            return None
        return self.get_cie() >= SEE_ELIGIBILITY_CIE

    @property
    def final_marks(self):
        """CIE out of 50 plus half the SEE, so a final out of 100."""
        see = self.get_see()
        if see is None:
            return None
        return self.get_cie() + see / 2

    @property
    def grade(self):
        """(letter, points), or None while the semester-end exam is pending."""
        final = self.final_marks
        return grade_for(final) if final is not None else None

    @property
    def reachable_grades(self):
        """What the student still has to score to reach each band.

        The counterpart to the attendance bunk calculator, and the thing a
        marks page is actually opened for. Bands already secured on the CIE
        alone, and bands a perfect paper cannot reach, are both dropped.
        """
        if self.get_see() is not None:
            return []
        cie = self.get_cie()
        out = []
        for floor, letter, points in GRADE_BANDS:
            needed = required_see_for(cie, floor)
            if needed:
                out.append({'letter': letter, 'points': points,
                            'required_see': needed})
        return list(reversed(out))

    @property
    def rank(self):
        """(position, class size) on this course, or None if not computed.

        Each student sees only their own standing. Ranking classmates against
        each other in a list they can all read is a privacy problem rather than
        a feature, so there is deliberately no leaderboard anywhere.
        """
        return self._rank_cache

    @staticmethod
    def attach_rank(student_courses, class_id, visible_components):
        """Fill each row's rank against its own class, in one query.

        Ranked on the same components the student can see. Ranking on the full
        entered set would let a withheld mark move someone's position, which
        leaks the thing publication control exists to hold back.
        """
        rows = list(student_courses)
        if not rows:
            return rows

        courses = {sc.course_id for sc in rows}
        totals = {}
        for mark in (Marks.objects
                     .filter(studentcourse__course__in=courses,
                             studentcourse__student__class_id=class_id,
                             name__in=CIE_COMPONENTS)
                     .select_related('studentcourse')):
            course_id = mark.studentcourse.course_id
            if mark.name not in visible_components.get(course_id, set()):
                continue
            key = (course_id, mark.studentcourse.student_id)
            totals[key] = totals.get(key, 0) + mark.marks1

        by_course = {}
        for (course_id, student_id), total in totals.items():
            by_course.setdefault(course_id, {})[student_id] = total

        for sc in rows:
            scores = by_course.get(sc.course_id)
            if not scores:
                continue
            mine = scores.get(sc.student_id, 0)
            # Standard competition ranking: equal scores share a position.
            position = 1 + sum(1 for other in scores.values() if other > mine)
            sc._rank_cache = (position, len(scores))
        return rows

    @staticmethod
    def attach_submitted(student_courses, class_id, published_only=False):
        """Fill the visible-component cache for a list of rows in one query.

        Entry and publication are different questions. A teacher looking at the
        class report should see what has been entered; a student should see
        what has been released. Pass published_only for the student-facing side.
        """
        rows = list(student_courses)
        visible, entered = {}, {}
        for mc in (MarksClass.objects
                   .filter(assign__class_id=class_id, status=True)
                   .select_related('assign')):
            entered.setdefault(mc.assign.course_id, set()).add(mc.name)
            if mc.is_published or not published_only:
                visible.setdefault(mc.assign.course_id, set()).add(mc.name)

        for sc in rows:
            sc._submitted_cache = visible.get(sc.course_id, set())
            sc._entered_cache = entered.get(sc.course_id, set())
        return rows

    @staticmethod
    def attach_attendance(student_courses, course):
        """Fill the attendance cache for a list of rows in one query."""
        rows = list(student_courses)
        totals = (AttendanceTotal.objects
                  .filter(course=course,
                          student__in=[sc.student_id for sc in rows])
                  .with_counts())
        by_student = {t.student_id: t.attendance for t in totals}
        for sc in rows:
            sc._attendance_cache = by_student.get(sc.student_id, 0)
        return rows


class Marks(models.Model):
    studentcourse = models.ForeignKey(StudentCourse, on_delete=models.CASCADE)
    name = models.CharField(max_length=50, choices=test_name, default='Internal test 1')
    marks1 = models.IntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    # A student who missed a test is not a student who scored zero. The mark
    # still counts as zero towards the CIE - that is how the scheme works - but
    # the record says which of the two it was, and the pages say so too.
    is_absent = models.BooleanField(default=False)

    class Meta:
        unique_together = (('studentcourse', 'name'),)

    @property
    def total_marks(self):
        if self.name == 'Semester End Exam':
            return 100
        return 20


class MarksClass(models.Model):
    assign = models.ForeignKey(Assign, on_delete=models.CASCADE)
    name = models.CharField(max_length=50, choices=test_name, default='Internal test 1')
    # Entered by the teacher.
    status = models.BooleanField(default=False)
    # Released to students. Colleges do not expose a mark the instant it is
    # typed - entry and publication are separate acts, and separating them also
    # gives the teacher room to correct a slip before anyone has seen it.
    is_published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = (('assign', 'name'),)

    def publish(self):
        self.is_published = True
        self.published_at = timezone.now()
        self.save(update_fields=['is_published', 'published_at'])

    def unpublish(self):
        self.is_published = False
        self.published_at = None
        self.save(update_fields=['is_published', 'published_at'])

    @property
    def total_marks(self):
        if self.name == 'Semester End Exam':
            return 100
        return 20


class AttendanceRange(models.Model):
    start_date = models.DateField()
    end_date = models.DateField()


fee_type_choice = (
    ('Tuition Fee', 'Tuition Fee'),
    ('Exam Fee', 'Exam Fee'),
    ('Hostel Fee', 'Hostel Fee'),
    ('Library Fee', 'Library Fee'),
    ('Other', 'Other'),
)


payment_mode_choice = (
    ('Cash', 'Cash'),
    ('UPI', 'UPI'),
    ('Card', 'Card'),
    ('Cheque', 'Cheque'),
    ('Bank transfer', 'Bank transfer'),
)


class FeeQuerySet(models.QuerySet):
    """Status and balance live in the database, not only in Python.

    `Fee.balance` and `Fee.status` are properties, so filtering or totalling by
    them meant pulling every row and looping. That is fine for one student and
    wrong for a staff list covering the whole institution.
    """

    def with_balance(self):
        return self.annotate(
            balance_due=models.F('amount') - models.F('paid_amount'))

    def paid(self):
        # A fully waived fee of zero is paid, not unpaid - the same ordering
        # bug the status property had.
        return self.filter(models.Q(amount__lte=0)
                           | models.Q(paid_amount__gte=models.F('amount')))

    def unpaid(self):
        return self.filter(paid_amount__lte=0).exclude(amount__lte=0)

    def partial(self):
        return (self.filter(paid_amount__gt=0,
                            paid_amount__lt=models.F('amount'))
                .exclude(amount__lte=0))

    def outstanding(self):
        return self.filter(paid_amount__lt=models.F('amount'), amount__gt=0)

    def overdue(self):
        return self.outstanding().filter(due_date__lt=timezone.localdate())

    def totals(self):
        """Raised, collected and outstanding, in one query."""
        zero = Decimal('0')
        summary = self.aggregate(
            raised=Coalesce(models.Sum('amount'), zero),
            collected=Coalesce(models.Sum('paid_amount'), zero))
        summary['outstanding'] = summary['raised'] - summary['collected']
        return summary


class Fee(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='fees')
    fee_type = models.CharField(max_length=50, choices=fee_type_choice, default='Tuition Fee')
    description = models.CharField(max_length=200, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2,
                                 validators=[MinValueValidator(Decimal('0.01'))])
    # Kept as a column so totals can be summed in the database, but it is
    # derived from the transaction rows rather than written to directly -
    # see recalculate_paid(). Editing it in place is what lost the payment
    # history in the first place.
    paid_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    due_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    objects = FeeQuerySet.as_manager()

    class Meta:
        ordering = ['-due_date']

    def __str__(self):
        return '%s : %s' % (self.student.name, self.fee_type)

    def recalculate_paid(self):
        """Re-derive paid_amount from the transactions and save it."""
        total = self.transactions.aggregate(
            total=Coalesce(models.Sum('amount'), Decimal('0')))['total']
        self.paid_amount = total
        self.save(update_fields=['paid_amount'])
        return total

    @property
    def balance(self):
        return self.amount - self.paid_amount

    @property
    def status(self):
        # The zero check came first, so a fully waived fee of 0 reported
        # "Unpaid" for ever and could never reach "Paid".
        if self.amount <= 0:
            return 'Paid'
        if self.paid_amount >= self.amount:
            return 'Paid'
        if self.paid_amount <= 0:
            return 'Unpaid'
        return 'Partial'

    @property
    def is_overdue(self):
        return self.balance > 0 and self.due_date < timezone.localdate()


class FeeTransaction(models.Model):
    """One payment against a fee.

    Fee.paid_amount used to be a single running total that staff overwrote by
    hand, so there was no record of when money arrived, how much came in each
    time, who took it or how it was paid - and two people recording payments at
    once silently lost one of them.
    """
    fee = models.ForeignKey(Fee, on_delete=models.CASCADE,
                            related_name='transactions')
    amount = models.DecimalField(max_digits=10, decimal_places=2,
                                 validators=[MinValueValidator(Decimal('0.01'))])
    mode = models.CharField(max_length=20, choices=payment_mode_choice,
                            default='Cash')
    reference = models.CharField(max_length=100, blank=True,
                                 help_text='UPI reference, cheque number, etc.')
    note = models.CharField(max_length=200, blank=True)
    paid_on = models.DateField(default=timezone.localdate)
    received_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
                                    blank=True, related_name='fee_receipts')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-paid_on', '-id']

    def __str__(self):
        return '%s %s on %s' % (self.receipt_no, self.amount, self.paid_on)

    @property
    def receipt_no(self):
        return 'RCP-%06d' % self.pk if self.pk else ''


notice_audience_choice = (
    ('All', 'All'),
    ('Students', 'Students'),
    ('Teachers', 'Teachers'),
)


notice_category_choice = (
    ('General', 'General'),
    ('Exam', 'Exam'),
    ('Fee', 'Fee'),
    ('Event', 'Event'),
    ('Holiday', 'Holiday'),
    ('Administrative', 'Administrative'),
)


class NoticeQuerySet(models.QuerySet):
    def visible_to(self, user):
        """Published, unexpired notices addressed to this user's role.

        Staff see drafts and expired notices as well, since they are the ones
        who have to manage them.
        """
        if user.is_teacher:
            audiences = ['All', 'Teachers']
        elif user.is_student:
            audiences = ['All', 'Students']
        else:
            audiences = [a for a, _ in notice_audience_choice]

        qs = self.filter(audience__in=audiences)
        if user.is_student:
            qs = qs.filter(is_published=True).exclude(
                expires_at__lt=timezone.localdate())
        return qs


class Notice(models.Model):
    title = models.CharField(max_length=200)
    message = models.TextField(max_length=5000)
    audience = models.CharField(max_length=20, choices=notice_audience_choice, default='All')
    category = models.CharField(max_length=20, choices=notice_category_choice,
                                default='General')
    # Written now, released when ready - marks and notices alike were visible
    # the instant they were typed.
    is_published = models.BooleanField(default=True)
    published_at = models.DateTimeField(null=True, blank=True)
    pinned = models.BooleanField(default=False)
    expires_at = models.DateField(null=True, blank=True,
                                  help_text='Hidden from students after this date.')
    posted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = NoticeQuerySet.as_manager()

    class Meta:
        # Pinned first, then newest. A board that only accumulates is unusable.
        ordering = ['-pinned', '-created_at']

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if self.is_published and self.published_at is None:
            self.published_at = timezone.now()
        elif not self.is_published:
            self.published_at = None
        super().save(*args, **kwargs)

    @property
    def is_expired(self):
        return self.expires_at is not None and self.expires_at < timezone.localdate()

    def is_read_by(self, user):
        return self.reads.filter(user=user).exists()


class NoticeRead(models.Model):
    """Per-user read state.

    A through model rather than a plain ManyToMany, so "read 2 days ago" and
    the author's read count both come for free.
    """
    notice = models.ForeignKey(Notice, on_delete=models.CASCADE,
                               related_name='reads')
    user = models.ForeignKey(User, on_delete=models.CASCADE,
                             related_name='notice_reads')
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = (('notice', 'user'),)


# Triggers


def daterange(start_date, end_date):
    for n in range(int((end_date - start_date).days)):
        yield start_date + timedelta(n)


days = {
    'Monday': 1,
    'Tuesday': 2,
    'Wednesday': 3,
    'Thursday': 4,
    'Friday': 5,
    'Saturday': 6,
}


def create_attendance(sender, instance, **kwargs):
    if not kwargs['created']:
        return

    # The semester date range is set up once by an admin. On a fresh install it
    # doesn't exist yet, and this signal used to raise DoesNotExist and take the
    # whole save with it - so adding the very first timetable slot failed. Skip
    # generation instead; the sessions can be built once a range is configured.
    date_range = AttendanceRange.objects.first()
    if date_range is None:
        return

    weekday = days[instance.day]
    existing = set(
        AttendanceClass.objects.filter(assign=instance.assign).values_list('date', flat=True)
    )
    AttendanceClass.objects.bulk_create([
        AttendanceClass(date=single_date, assign=instance.assign)
        for single_date in daterange(date_range.start_date, date_range.end_date)
        if single_date.isoweekday() == weekday and single_date not in existing
    ])


def create_marks(sender, instance, **kwargs):
    if kwargs['created']:
        if hasattr(instance, 'name'):
            ass_list = instance.class_id.assign_set.all()
            for ass in ass_list:
                try:
                    StudentCourse.objects.get(student=instance, course=ass.course)
                except StudentCourse.DoesNotExist:
                    sc = StudentCourse(student=instance, course=ass.course)
                    sc.save()
                    sc.marks_set.create(name='Internal test 1')
                    sc.marks_set.create(name='Internal test 2')
                    sc.marks_set.create(name='Internal test 3')
                    sc.marks_set.create(name='Event 1')
                    sc.marks_set.create(name='Event 2')
                    sc.marks_set.create(name='Semester End Exam')
        elif hasattr(instance, 'course'):
            stud_list = instance.class_id.student_set.all()
            cr = instance.course
            for s in stud_list:
                try:
                    StudentCourse.objects.get(student=s, course=cr)
                except StudentCourse.DoesNotExist:
                    sc = StudentCourse(student=s, course=cr)
                    sc.save()
                    sc.marks_set.create(name='Internal test 1')
                    sc.marks_set.create(name='Internal test 2')
                    sc.marks_set.create(name='Internal test 3')
                    sc.marks_set.create(name='Event 1')
                    sc.marks_set.create(name='Event 2')
                    sc.marks_set.create(name='Semester End Exam')


def create_marks_class(sender, instance, **kwargs):
    if kwargs['created']:
        for name in test_name:
            try:
                MarksClass.objects.get(assign=instance, name=name[0])
            except MarksClass.DoesNotExist:
                m = MarksClass(assign=instance, name=name[0])
                m.save()


def delete_marks(sender, instance, **kwargs):
    stud_list = instance.class_id.student_set.all()
    StudentCourse.objects.filter(course=instance.course, student__in=stud_list).delete()


post_save.connect(create_marks, sender=Student)
post_save.connect(create_marks, sender=Assign)
post_save.connect(create_marks_class, sender=Assign)
post_save.connect(create_attendance, sender=AssignTime)
post_delete.connect(delete_marks, sender=Assign)


audit_action_choice = (
    ('attendance.marked', 'Attendance marked'),
    ('attendance.changed', 'Attendance changed'),
    ('attendance.cancelled', 'Class cancelled'),
    ('marks.entered', 'Marks entered'),
    ('marks.changed', 'Marks changed'),
    ('marks.published', 'Marks published'),
    ('marks.unpublished', 'Marks withdrawn'),
    ('fee.payment', 'Payment recorded'),
)


class AuditLog(models.Model):
    """Who changed a mark, an attendance record or a fee, when, and from what.

    None of these kept any history. A teacher could flip an attendance record or
    overwrite a mark and nothing recorded the previous value, the person, or the
    time - which for grades and money is the first thing anyone asks about.

    Deliberately append-only and denormalised: `student_name` and `summary` are
    stored rather than joined, so an entry still reads correctly after the row
    it describes has been edited or deleted.
    """
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
                              blank=True, related_name='audit_entries')
    actor_name = models.CharField(max_length=150, blank=True)
    action = models.CharField(max_length=40, choices=audit_action_choice)
    target_type = models.CharField(max_length=40)
    target_id = models.CharField(max_length=100, blank=True)
    student = models.ForeignKey(Student, on_delete=models.SET_NULL, null=True,
                                blank=True, related_name='audit_entries')
    student_name = models.CharField(max_length=200, blank=True)
    summary = models.CharField(max_length=255)
    changes = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['student', '-created_at']),
        ]

    def __str__(self):
        return '%s: %s' % (self.get_action_display(), self.summary)

    @classmethod
    def record(cls, actor, action, target, summary, student=None, changes=None):
        return cls.objects.create(
            actor=actor if actor and actor.is_authenticated else None,
            actor_name=getattr(actor, 'username', '') or '',
            action=action,
            target_type=type(target).__name__ if target is not None else '',
            target_id=str(getattr(target, 'pk', '') or ''),
            student=student,
            student_name=student.name if student else '',
            summary=summary,
            changes=changes or {},
        )

    @classmethod
    def record_many(cls, entries):
        """Bulk variant for batch submissions."""
        return cls.objects.bulk_create(entries)


support_category_choice = (
    ('Login issue', 'Cannot sign in'),
    ('Password reset', 'Forgotten password'),
    ('Account locked', 'Account locked'),
    ('Wrong details', 'My details are wrong'),
    ('Other', 'Something else'),
)

support_status_choice = (
    ('New', 'New'),
    ('In progress', 'In progress'),
    ('Resolved', 'Resolved'),
)


class SupportRequest(models.Model):
    """A message from the login page's "Contact Administrator" link.

    Submitted by people who cannot sign in, so it has to work while logged out -
    which is also why the form carries a honeypot and the view rate-limits.
    """
    name = models.CharField(max_length=150)
    email = models.EmailField()
    category = models.CharField(max_length=40, choices=support_category_choice,
                                default='Login issue')
    message = models.TextField(max_length=2000)
    status = models.CharField(max_length=20, choices=support_status_choice,
                              default='New')
    admin_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return '%s - %s' % (self.name, self.category)

    def save(self, *args, **kwargs):
        if self.status == 'Resolved' and self.resolved_at is None:
            self.resolved_at = timezone.now()
        elif self.status != 'Resolved':
            self.resolved_at = None
        super().save(*args, **kwargs)
