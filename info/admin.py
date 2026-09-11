from datetime import datetime, timedelta

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.http import HttpResponseRedirect
from django.urls import path

from .models import (
    AiUsage,
    Assign,
    AssignTime,
    AssistantEscalation,
    Attendance,
    AttendanceClass,
    AttendanceRange,
    AuditLog,
    Class,
    Course,
    CourseMaterial,
    Dept,
    Fee,
    FeeTransaction,
    LoginEvent,
    Marks,
    MaterialChunk,
    Notice,
    Student,
    StudentCourse,
    SupportRequest,
    Teacher,
    User,
)

# Register your models here.

days = {
    'Monday': 1,
    'Tuesday': 2,
    'Wednesday': 3,
    'Thursday': 4,
    'Friday': 5,
    'Saturday': 6,
}


def daterange(start_date, end_date):
    for n in range(int((end_date - start_date).days)):
        yield start_date + timedelta(n)


class ClassInline(admin.TabularInline):
    model = Class
    extra = 0


class DeptAdmin(admin.ModelAdmin):
    inlines = [ClassInline]
    list_display = ('name', 'id')
    search_fields = ('name', 'id')
    ordering = ['name']


class StudentInline(admin.TabularInline):
    model = Student
    extra = 0


class ClassAdmin(admin.ModelAdmin):
    list_display = ('id', 'dept', 'sem', 'section')
    search_fields = ('id', 'dept__name', 'sem', 'section')
    ordering = ['dept__name', 'sem', 'section']
    inlines = [StudentInline]


class CourseAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'dept', 'credits')
    list_editable = ('credits',)
    search_fields = ('id', 'name', 'dept__name')
    ordering = ['dept', 'id']


class AssignTimeInline(admin.TabularInline):
    model = AssignTime
    extra = 0


class AssignAdmin(admin.ModelAdmin):
    inlines = [AssignTimeInline]
    list_display = ('class_id', 'course', 'teacher')
    search_fields = ('class_id__dept__name', 'class_id__id', 'course__name', 'teacher__name', 'course__shortname')
    ordering = ['class_id__dept__name', 'class_id__id', 'course__id']
    raw_id_fields = ['class_id', 'course', 'teacher']


class MarksInline(admin.TabularInline):
    model = Marks
    extra = 0


class StudentCourseAdmin(admin.ModelAdmin):
    inlines = [MarksInline]
    list_display = ('student', 'course',)
    search_fields = ('student__name', 'course__name', 'student__class_id__id', 'student__class_id__dept__name')
    ordering = ('student__class_id__dept__name', 'student__class_id__id', 'student__USN')



@admin.action(description='Deactivate - blocks sign-in, keeps records')
def deactivate(modeladmin, request, queryset):
    # One at a time rather than queryset.update(): the save() override is what
    # disables the login, and update() bypasses it.
    for person in queryset:
        person.is_active = False
        person.save()


@admin.action(description='Reactivate')
def reactivate(modeladmin, request, queryset):
    for person in queryset:
        person.is_active = True
        person.save()


class StudentAdmin(admin.ModelAdmin):
    list_display = ('USN', 'name', 'class_id', 'is_active')
    list_filter = ('is_active', 'class_id')
    search_fields = ('USN', 'name', 'class_id__id', 'class_id__dept__name')
    ordering = ['class_id__dept__name', 'class_id__id', 'USN']
    actions = [deactivate, reactivate]
    fieldsets = (
        ('Identity', {'fields': ('USN', 'name', 'photo')}),
        ('Enrolment', {
            'fields': ('class_id', 'user', 'is_active'),
            'description': 'Clearing is_active blocks sign-in and keeps every '
                           'record; it is not a delete.',
        }),
        ('Personal', {'fields': ('sex', 'DOB', 'phone', 'address')}),
    )


class TeacherAdmin(admin.ModelAdmin):
    list_display = ('name', 'dept', 'is_active')
    list_filter = ('is_active', 'dept')
    search_fields = ('name', 'dept__name')
    ordering = ['dept__name', 'name']
    actions = [deactivate, reactivate]
    fieldsets = (
        ('Identity', {'fields': ('id', 'name', 'photo')}),
        ('Post', {'fields': ('dept', 'user', 'is_active')}),
        ('Personal', {'fields': ('sex', 'DOB', 'phone', 'address')}),
    )


class AttendanceClassAdmin(admin.ModelAdmin):
    list_display = ('assign', 'date', 'status')
    ordering = ['assign', 'date']
    change_list_template = 'admin/attendance/attendance_change_list.html'

    def get_urls(self):
        urls = super().get_urls()
        my_urls = [
            path('reset_attd/', self.reset_attd, name='reset_attd'),
        ]
        return my_urls + urls

    def reset_attd(self, request):

        start_date = datetime.strptime(request.POST['startdate'], '%Y-%m-%d').date()
        end_date = datetime.strptime(request.POST['enddate'], '%Y-%m-%d').date()

        try:
            a = AttendanceRange.objects.all()[:1].get()
            a.start_date = start_date
            a.end_date = end_date
            a.save()
        except AttendanceRange.DoesNotExist:
            a = AttendanceRange(start_date=start_date, end_date=end_date)
            a.save()

        Attendance.objects.all().delete()
        AttendanceClass.objects.all().delete()
        for asst in AssignTime.objects.all():
            for single_date in daterange(start_date, end_date):
                if single_date.isoweekday() == days[asst.day]:
                    try:
                        AttendanceClass.objects.get(date=single_date.strftime("%Y-%m-%d"), assign=asst.assign)
                    except AttendanceClass.DoesNotExist:
                        a = AttendanceClass(date=single_date.strftime("%Y-%m-%d"), assign=asst.assign)
                        a.save()

        self.message_user(request, "Attendance Dates reset successfully!")
        return HttpResponseRedirect("../")


class FeeTransactionInline(admin.TabularInline):
    model = FeeTransaction
    extra = 0
    readonly_fields = ('created_at',)


class FeeAdmin(admin.ModelAdmin):
    inlines = [FeeTransactionInline]
    # paid_amount is derived from the transactions, so editing it here would
    # only be overwritten by the next recalculation.
    readonly_fields = ('paid_amount',)
    list_display = ('student', 'fee_type', 'amount', 'paid_amount', 'status', 'due_date')
    search_fields = ('student__name', 'student__USN', 'fee_type')
    list_filter = ('fee_type', 'due_date')
    ordering = ['-due_date']
    fieldsets = (
        (None, {'fields': ('student', 'fee_type', 'description')}),
        ('Amounts', {
            'fields': ('amount', 'paid_amount', 'due_date'),
            'description': 'paid_amount is the sum of the transactions below '
                           'and is recalculated on save.',
        }),
    )

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        form.instance.recalculate_paid()


class FeeTransactionAdmin(admin.ModelAdmin):
    list_display = ('receipt_no', 'fee', 'amount', 'mode', 'paid_on', 'received_by')
    search_fields = ('fee__student__name', 'fee__student__USN', 'reference')
    list_filter = ('mode', 'paid_on')
    ordering = ['-paid_on']


class SupportRequestAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'name', 'category', 'status', 'email')
    list_filter = ('status', 'category', 'created_at')
    search_fields = ('name', 'email', 'message')
    list_editable = ('status',)
    readonly_fields = ('name', 'email', 'category', 'message', 'created_at',
                       'resolved_at')
    ordering = ['-created_at']


class LoginEventAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'username', 'successful', 'ip', 'device')
    list_filter = ('successful', 'created_at')
    search_fields = ('username', 'ip')
    date_hierarchy = 'created_at'
    ordering = ['-created_at']

    # A record of who signed in is only worth having if it cannot be edited
    # afterwards.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'action', 'actor_name', 'student_name', 'summary')
    list_filter = ('action', 'created_at')
    search_fields = ('summary', 'actor_name', 'student_name')
    date_hierarchy = 'created_at'
    ordering = ['-created_at']

    # Append-only: the point of the log is that it cannot be tidied up after
    # the fact.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class MaterialChunkInline(admin.TabularInline):
    """The passages, read-only.

    They are produced by the chunker and given vectors by the embedder;
    editing one by hand would leave text that no longer matches the vector
    stored beside it, which is a wrong answer with nothing to explain it.
    """
    model = MaterialChunk
    extra = 0
    can_delete = False
    fields = ('index', 'text', 'embedded_at')
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.action(description='Publish - students can be answered from these')
def publish_materials(modeladmin, request, queryset):
    for material in queryset:
        material.publish()


@admin.action(description='Unpublish - take back out of the assistant')
def unpublish_materials(modeladmin, request, queryset):
    for material in queryset:
        material.unpublish()


class CourseMaterialAdmin(admin.ModelAdmin):
    """What the assistant is allowed to answer from.

    Publication is the control that matters here: an unpublished document is
    invisible to every search, so a teacher who uploads the wrong file can
    notice before anybody is answered out of it.
    """
    list_display = ('title', 'kind', 'course', 'chunk_count', 'embedded',
                    'is_published', 'created_at')
    list_filter = ('kind', 'is_published', 'created_at')
    search_fields = ('title', 'source', 'course__name')
    readonly_fields = ('content_hash', 'chunk_count', 'published_at',
                       'created_at', 'updated_at')
    inlines = [MaterialChunkInline]
    actions = [publish_materials, unpublish_materials]
    date_hierarchy = 'created_at'
    fieldsets = (
        (None, {'fields': ('title', 'source', 'file')}),
        ('Who can search it', {
            'fields': ('kind', 'course'),
            'description': 'Course material is searchable only by the classes '
                           'assigned that course. Policy is searchable by '
                           'everybody and must have no course.',
        }),
        ('Publication', {
            'fields': ('is_published', 'published_at'),
            'description': 'Nothing unpublished is ever searched.',
        }),
        ('Derived', {'fields': ('content_hash', 'chunk_count', 'uploaded_by',
                                'created_at', 'updated_at')}),
    )

    @admin.display(description='Embedded', boolean=True)
    def embedded(self, obj):
        """Whether every passage has a vector. Without one it cannot be found."""
        return not obj.chunks.filter(embedding__isnull=True).exists()


class AssistantEscalationAdmin(admin.ModelAdmin):
    """Questions the assistant could not answer.

    Read-only on purpose. Answering one belongs on the teacher's own page,
    which requires a written response and tells the student; doing it here
    would set the status with nobody told and nothing said.

    The value of the list is the pattern rather than the individual row: a run
    of these on one topic is the only honest signal that the material is thin
    there, and it is worth being able to sort and filter for that.
    """
    list_display = ('created_at', 'student', 'course', 'short_question',
                    'status', 'answered_by')
    list_filter = ('status', 'created_at', 'course')
    search_fields = ('question', 'response', 'student__name', 'student__USN')
    date_hierarchy = 'created_at'
    readonly_fields = ('student', 'course', 'question', 'assistant_said',
                       'status', 'response', 'answered_by', 'answered_at',
                       'created_at')

    @admin.display(description='Question')
    def short_question(self, obj):
        return obj.question[:70]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class AiUsageAdmin(admin.ModelAdmin):
    """Calls to a metered provider. A counter, not something to edit."""
    list_display = ('day', 'user', 'kind', 'calls')
    list_filter = ('day', 'kind')
    search_fields = ('user__username',)
    date_hierarchy = 'day'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class ErpUserAdmin(UserAdmin):
    """Stock UserAdmin does not know about the fields this project added.

    `must_change_password` is what ForcePasswordChangeMiddleware redirects on,
    and it was invisible here - so the one screen meant for fixing an account
    could neither see that somebody was stuck behind the change-password wall
    nor let them out of it.
    """

    list_display = UserAdmin.list_display + ('must_change_password',)
    list_filter = UserAdmin.list_filter + ('must_change_password',)
    fieldsets = UserAdmin.fieldsets + (
        ('College ERP', {
            'fields': ('must_change_password',),
            'description': 'While this is set the account is redirected to '
                           'the change-password screen on every request.',
        }),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('College ERP', {'fields': ('must_change_password',)}),
    )


class NoticeAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'audience', 'is_published', 'pinned',
                    'posted_by', 'created_at')
    # There used to be a second `list_filter = ('audience',)` three lines
    # below this one, which simply won - so the category, published and pinned
    # filters had never appeared on the page despite being written down. Ruff's
    # selected rules do not include PIE794, so nothing said a word.
    list_filter = ('category', 'audience', 'is_published', 'pinned')
    search_fields = ('title', 'message')
    date_hierarchy = 'created_at'
    ordering = ['-created_at']
    fieldsets = (
        (None, {'fields': ('title', 'message')}),
        ('Who sees it', {'fields': ('audience', 'category')}),
        ('Publication', {
            'fields': ('is_published', 'published_at', 'pinned', 'expires_at',
                       'posted_by'),
            'description': 'An unpublished notice is visible to nobody, '
                           'whatever its audience.',
        }),
    )


admin.site.register(User, ErpUserAdmin)
admin.site.register(Dept, DeptAdmin)
admin.site.register(Class, ClassAdmin)
admin.site.register(Student, StudentAdmin)
admin.site.register(Course, CourseAdmin)
admin.site.register(Teacher, TeacherAdmin)
admin.site.register(Assign, AssignAdmin)
admin.site.register(StudentCourse, StudentCourseAdmin)
admin.site.register(AttendanceClass, AttendanceClassAdmin)
admin.site.register(Fee, FeeAdmin)
admin.site.register(FeeTransaction, FeeTransactionAdmin)
admin.site.register(AuditLog, AuditLogAdmin)
admin.site.register(SupportRequest, SupportRequestAdmin)
admin.site.register(LoginEvent, LoginEventAdmin)
admin.site.register(Notice, NoticeAdmin)
admin.site.register(CourseMaterial, CourseMaterialAdmin)
admin.site.register(AiUsage, AiUsageAdmin)
admin.site.register(AssistantEscalation, AssistantEscalationAdmin)
