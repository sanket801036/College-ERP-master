from rest_framework import serializers

from info.models import Assign, AssignTime, AttendanceTotal, Student, StudentCourse


class StudentSerializer(serializers.ModelSerializer):
    """The student's own profile.

    This used to be `fields = '__all__'`, which returned DOB among everything
    else - the one field worth withholding, given accounts were originally
    issued with a password derived from the birth year.
    """
    dept = serializers.CharField(source='class_id.dept.name', read_only=True)
    semester = serializers.IntegerField(source='class_id.sem', read_only=True)
    section = serializers.CharField(source='class_id.section', read_only=True)

    class Meta:
        model = Student
        fields = ['USN', 'name', 'dept', 'semester', 'section']


class AttendanceSerializer(serializers.ModelSerializer):
    """Attendance for one course.

    The old version serialised AttendanceTotal with `fields = '__all__'`, but
    every useful value on that model is a Python property rather than a column,
    so DRF dropped all of them - the endpoint returned identifiers and nothing
    else. They are declared explicitly here.
    """
    course_id = serializers.CharField(source='course.id', read_only=True)
    course = serializers.CharField(source='course.name', read_only=True)
    attended = serializers.ReadOnlyField(source='att_class')
    held = serializers.ReadOnlyField(source='total_class')
    percentage = serializers.ReadOnlyField(source='attendance')
    classes_to_attend = serializers.ReadOnlyField()
    classes_can_skip = serializers.ReadOnlyField()
    has_classes = serializers.ReadOnlyField()

    class Meta:
        model = AttendanceTotal
        fields = ['course_id', 'course', 'attended', 'held', 'percentage',
                  'classes_to_attend', 'classes_can_skip', 'has_classes']


class MarksSerializer(serializers.ModelSerializer):
    course_id = serializers.CharField(source='course.id', read_only=True)
    course = serializers.CharField(source='course.name', read_only=True)
    cie = serializers.SerializerMethodField()
    marks = serializers.SerializerMethodField()

    class Meta:
        model = StudentCourse
        fields = ['course_id', 'course', 'cie', 'marks']

    def get_cie(self, obj):
        return obj.get_cie()

    def get_marks(self, obj):
        return {m.name: m.marks1 for m in obj.marks_set.all()}


class TimetableSerializer(serializers.ModelSerializer):
    course_id = serializers.CharField(source='assign.course.id', read_only=True)
    course = serializers.CharField(source='assign.course.name', read_only=True)
    teacher = serializers.CharField(source='assign.teacher.name', read_only=True)

    class Meta:
        model = AssignTime
        fields = ['day', 'period', 'course_id', 'course', 'teacher']


class ClassSerializer(serializers.ModelSerializer):
    """One of a teacher's assignments."""
    assign_id = serializers.IntegerField(source='id', read_only=True)
    course_id = serializers.CharField(source='course.id', read_only=True)
    course = serializers.CharField(source='course.name', read_only=True)
    class_id = serializers.CharField(source='class_id.id', read_only=True)
    semester = serializers.IntegerField(source='class_id.sem', read_only=True)
    section = serializers.CharField(source='class_id.section', read_only=True)
    student_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Assign
        fields = ['assign_id', 'course_id', 'course', 'class_id', 'semester',
                  'section', 'student_count']


class ClassStudentSerializer(serializers.Serializer):
    """A student in a class, with their standing in that course.

    Not a ModelSerializer: the values come from an aggregate over Attendance
    rather than from columns on any one model.
    """
    usn = serializers.CharField()
    name = serializers.CharField()
    attended = serializers.IntegerField()
    held = serializers.IntegerField()
    percentage = serializers.FloatField()
    at_risk = serializers.BooleanField()


class AttendanceSubmitSerializer(serializers.Serializer):
    """A submission for one session.

    `present` is the USNs marked present; anybody in the class and not listed
    is recorded absent, which is what the web form does with an unticked box.
    """
    present = serializers.ListField(
        child=serializers.CharField(max_length=100),
        allow_empty=True,
        help_text='USNs of the students present.')

    def __init__(self, *args, roll=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.roll = set(roll or ())

    def validate_present(self, present):
        # A USN from another class is a caller mistake, not somebody to quietly
        # ignore - saying so beats silently recording their whole class absent.
        strangers = sorted(set(present) - self.roll)
        if strangers:
            raise serializers.ValidationError(
                'Not in this class: %s' % ', '.join(strangers))
        return present


class TokenSerializer(serializers.Serializer):
    """What a successful sign-in returns."""
    token = serializers.CharField()
    username = serializers.CharField()
    role = serializers.CharField()


class AttendanceSubmitResultSerializer(serializers.Serializer):
    """What a submission reports back."""
    session_id = serializers.IntegerField()
    date = serializers.DateField()
    first_submission = serializers.BooleanField()
    changed = serializers.IntegerField(
        help_text='Students whose status moved. Zero on a first submission.')
    present = serializers.IntegerField()
    total = serializers.IntegerField()
