import io
import re

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, SetPasswordForm  # noqa: F401
from django.core.files.base import ContentFile
from django.utils import timezone
from django.utils.crypto import get_random_string
from PIL import Image, ImageOps

from info.models import (
    AttendanceRange,
    Class,
    Fee,
    FeeTransaction,
    Notice,
    Student,
    SupportRequest,
    Teacher,
    fee_type_choice,
    notice_audience_choice,
)

User = get_user_model()

# Ambiguous characters (0/O, 1/l/I) left out - these passwords get read off a
# screen and typed by hand.
_PASSWORD_ALPHABET = 'abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789'


def _unique_username(base):
    """Return `base`, or `base_2`, `base_3`... if it is already taken.

    The old code built a username from the first name plus part of the USN and
    saved it blind, so two students with the same first name and matching USN
    tails collided and raised IntegrityError mid-request.
    """
    base = base or 'user'
    candidate = base
    suffix = 2
    while User.objects.filter(username=candidate).exists():
        candidate = '%s_%d' % (base, suffix)
        suffix += 1
    return candidate


class _PersonForm(forms.ModelForm):
    """Shared bits of the add-student and add-teacher forms."""

    email = forms.EmailField(
        required=True,
        help_text='Used for password resets and notifications.',
    )

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if not name:
            raise forms.ValidationError('Enter a name.')
        return name

    def build_username(self):
        raise NotImplementedError

    def create_user(self):
        """Create the login account and return it with its one-time password.

        The password used to be `firstname_birthyear`, which is derivable from
        anything printed on a college ID card. It is random now, which means the
        admin has to be shown it once at creation - see the add_* templates.

        Callers must run this inside a transaction together with the form save,
        so a failure part-way cannot leave an orphaned account behind.
        """
        password = get_random_string(10, _PASSWORD_ALPHABET)
        user = User.objects.create_user(
            username=_unique_username(self.build_username()),
            email=self.cleaned_data['email'],
            password=password,
            # The admin reads this off the screen and hands it over, so it is
            # only good until the user signs in once.
            must_change_password=True,
        )
        return user, password


class StudentForm(_PersonForm):
    class Meta:
        model = Student
        fields = ['USN', 'name', 'class_id', 'sex', 'DOB']
        labels = {'USN': 'USN', 'class_id': 'Class', 'DOB': 'Date of birth'}
        widgets = {'DOB': forms.DateInput(attrs={'type': 'date'})}

    def clean_USN(self):
        # USN is the primary key. Saving a Student whose PK already exists
        # UPDATES that row instead of failing, which silently overwrote the
        # existing student's record and reassigned their login. Reject it here.
        usn = self.cleaned_data['USN'].strip().upper()
        if Student.objects.filter(USN=usn).exists():
            raise forms.ValidationError('A student with this USN already exists.')
        return usn

    def build_username(self):
        first = self.cleaned_data['name'].split(' ')[0].lower()
        return '%s_%s' % (first, self.cleaned_data['USN'][-3:].lower())


class TeacherForm(_PersonForm):
    class Meta:
        model = Teacher
        fields = ['id', 'name', 'dept', 'sex', 'DOB']
        labels = {'id': 'Staff ID', 'dept': 'Department', 'DOB': 'Date of birth'}
        widgets = {'DOB': forms.DateInput(attrs={'type': 'date'})}

    def clean_id(self):
        # Same primary-key overwrite hazard as StudentForm.clean_USN.
        staff_id = self.cleaned_data['id'].strip().lower()
        if Teacher.objects.filter(id=staff_id).exists():
            raise forms.ValidationError('A teacher with this ID already exists.')
        return staff_id

    def build_username(self):
        first = self.cleaned_data['name'].split(' ')[0].lower()
        return '%s_%s' % (first, self.cleaned_data['id'])


class MarksEntryForm(forms.Form):
    """Validates a whole class's marks before any of them are written.

    The entry template posts one field per student, keyed by USN, so the fields
    are built at runtime rather than declared.
    """

    #: Prefix for the per-student "did not sit this test" checkbox.
    ABSENT_PREFIX = 'absent_'

    def __init__(self, data=None, students=None, total_marks=20, **kwargs):
        super().__init__(data, **kwargs)
        self.students = students or []
        self.total_marks = total_marks
        for student in self.students:
            self.fields[student.USN] = forms.IntegerField(
                label=student.name,
                required=False,
                min_value=0,
                max_value=total_marks,
                error_messages={
                    'max_value': 'Maximum for this test is %d.' % total_marks,
                    'min_value': 'Marks cannot be negative.',
                    'invalid': 'Enter a whole number.',
                },
            )
            self.fields[self.absent_field(student)] = forms.BooleanField(
                required=False)

    @classmethod
    def absent_field(cls, student):
        return cls.ABSENT_PREFIX + student.USN

    def clean(self):
        """A blank is not a zero.

        The mark field is optional so that "absent" can be submitted without
        one, which means the blank case has to be rejected here instead - a
        student left empty is one the teacher has not got to yet, and saving
        them as having scored nothing is the bug this whole field exists to
        avoid.
        """
        cleaned = super().clean()
        for student in self.students:
            if cleaned.get(self.absent_field(student)):
                continue
            if self.errors.get(student.USN):
                continue
            if cleaned.get(student.USN) is None:
                self.add_error(student.USN,
                               'Enter a mark, or mark the student absent.')
        return cleaned

    def marks_for(self, student):
        """(marks, is_absent). An absentee scores zero towards the CIE - that
        is how the scheme works - but the record says which it was."""
        if self.cleaned_data.get(self.absent_field(student)):
            return 0, True
        return self.cleaned_data[student.USN], False

    def errors_for(self, student):
        return self.errors.get(student.USN, [])


class ExtraClassForm(forms.Form):
    """Checks the date of an ad-hoc session before it is created."""

    date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date'}),
        error_messages={'required': 'Pick a date.',
                        'invalid': 'Enter a valid date.'},
    )

    def __init__(self, data=None, assign=None, **kwargs):
        super().__init__(data, **kwargs)
        self.assign = assign

    def clean_date(self):
        value = self.cleaned_data['date']

        date_range = AttendanceRange.objects.first()
        if date_range and not (date_range.start_date <= value <= date_range.end_date):
            raise forms.ValidationError(
                'Pick a date inside the current term (%s to %s).'
                % (date_range.start_date, date_range.end_date))

        if self.assign and self.assign.attendanceclass_set.filter(date=value).exists():
            raise forms.ValidationError(
                'This class already has a session on that date.')

        return value


class FeeForm(forms.ModelForm):
    """Raising a fee.

    Everything here used to come straight off request.POST: fee_type was never
    checked against the choices, so an arbitrary string could be stored and the
    fee then vanished from every audience filter, and a bad amount or date threw
    an unhandled exception.
    """

    class Meta:
        model = Fee
        fields = ['student', 'fee_type', 'description', 'amount', 'due_date']
        widgets = {'due_date': forms.DateInput(attrs={'type': 'date'})}

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if amount <= 0:
            raise forms.ValidationError('Amount must be greater than zero.')
        return amount


class BulkFeeForm(forms.Form):
    """Raise one fee against every student in a class.

    Adding a semester exam fee to a sixty-student intake meant sixty identical
    form submissions, which is the most obviously missing staff action in the
    module.
    """

    class_id = forms.ModelChoiceField(queryset=None, label='Class')
    fee_type = forms.ChoiceField(choices=fee_type_choice)
    description = forms.CharField(max_length=200, required=False)
    amount = forms.DecimalField(max_digits=10, decimal_places=2)
    due_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['class_id'].queryset = Class.objects.all()

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if amount <= 0:
            raise forms.ValidationError('Amount must be greater than zero.')
        return amount

    def students(self):
        return self.cleaned_data['class_id'].student_set.all()

    def existing(self):
        """Students who already have this exact fee.

        Running the same bulk assignment twice is an easy mistake, and silently
        doubling a class's fees is an expensive one - so these are skipped and
        reported rather than duplicated.
        """
        return set(Fee.objects
                   .filter(student__in=self.students(),
                           fee_type=self.cleaned_data['fee_type'],
                           amount=self.cleaned_data['amount'],
                           due_date=self.cleaned_data['due_date'])
                   .values_list('student_id', flat=True))

    def build(self):
        """(fees to create, number skipped as already raised)."""
        already = self.existing()
        fees = [
            Fee(student=student,
                fee_type=self.cleaned_data['fee_type'],
                description=self.cleaned_data['description'],
                amount=self.cleaned_data['amount'],
                due_date=self.cleaned_data['due_date'])
            for student in self.students() if student.pk not in already
        ]
        return fees, len(already)


class FeeTransactionForm(forms.ModelForm):
    """Recording a payment against a fee.

    This replaces editing the running total by hand, which meant staff did the
    arithmetic themselves, nothing recorded when or how the money arrived, and
    two people recording payments at once silently lost one of them.
    """

    class Meta:
        model = FeeTransaction
        fields = ['amount', 'mode', 'reference', 'paid_on', 'note']
        widgets = {'paid_on': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, *args, fee=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fee = fee
        if fee is not None:
            self.fields['amount'].widget.attrs.update(
                {'max': fee.balance, 'step': '0.01'})

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if amount <= 0:
            raise forms.ValidationError('Payment must be greater than zero.')
        # A fee of 10,000 accepted a paid_amount of 99,999 before this, leaving
        # a balance of -89,999 reported as "Paid".
        if self.fee is not None and amount > self.fee.balance:
            raise forms.ValidationError(
                'That is more than the outstanding balance of %s.'
                % self.fee.balance)
        return amount

    def clean_paid_on(self):
        paid_on = self.cleaned_data['paid_on']
        if paid_on > timezone.localdate():
            raise forms.ValidationError('Payment date cannot be in the future.')
        return paid_on


ROLE_CHOICES = (
    ('student', 'Student'),
    ('teacher', 'Faculty'),
    ('admin', 'Admin'),
)


class ErpLoginForm(AuthenticationForm):
    """Login with a role selector and a Remember Me box.

    The role is checked rather than decorative: signing in as a student from the
    Admin tab says so, instead of silently landing on the student dashboard and
    leaving the person wondering what happened.
    """

    role = forms.ChoiceField(choices=ROLE_CHOICES, initial='student',
                             widget=forms.RadioSelect)
    remember_me = forms.BooleanField(required=False, initial=False,
                                     label='Remember me')

    error_messages = dict(AuthenticationForm.error_messages, **{
        'wrong_role': 'That account is not registered as %(role)s. '
                      'Pick the right tab and try again.',
    })

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)

        role = self.cleaned_data.get('role') or self.data.get('role')
        actual = ('admin' if user.is_superuser
                  else 'teacher' if user.is_teacher
                  else 'student' if user.is_student
                  else None)
        if role and actual != role:
            raise forms.ValidationError(
                self.error_messages['wrong_role'],
                code='wrong_role',
                params={'role': dict(ROLE_CHOICES)[role]},
            )


class SupportRequestForm(forms.ModelForm):
    """The form behind "Facing issues? Contact Administrator".

    Reachable without signing in - that is the whole point of it - so it needs a
    honeypot and rate limiting rather than trusting the caller.
    """

    # Bots fill every field they find; people never see this one.
    website = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = SupportRequest
        fields = ['name', 'email', 'category', 'message']
        widgets = {'message': forms.Textarea(attrs={'rows': 4})}

    def clean_website(self):
        if self.cleaned_data.get('website'):
            raise forms.ValidationError('Sorry, that looked automated.')
        return ''

    def clean_message(self):
        message = self.cleaned_data['message'].strip()
        if len(message) < 10:
            raise forms.ValidationError('Tell us a bit more about the problem.')
        return message


class NoticeForm(forms.ModelForm):
    """Posting or editing a notice.

    title, message and audience previously came straight off request.POST, so a
    missing field was a 500 and audience was never checked against the choices -
    an arbitrary string could be stored, after which the notice matched no
    audience filter and was invisible to everyone.
    """

    class Meta:
        model = Notice
        fields = ['title', 'message', 'audience', 'category', 'pinned',
                  'is_published', 'expires_at']
        widgets = {
            'message': forms.Textarea(attrs={'rows': 6}),
            'expires_at': forms.DateInput(attrs={'type': 'date'}),
        }
        labels = {
            'is_published': 'Publish now (uncheck to save as a draft)',
            'pinned': 'Pin to the top of the board',
            'expires_at': 'Hide after (optional)',
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        # Addressing the whole institution, staff included, is an
        # administrator's call rather than any teacher's.
        if user is not None and not user.is_superuser:
            self.fields['audience'].choices = [
                c for c in notice_audience_choice if c[0] != 'Teachers']
            self.fields['pinned'].disabled = True

    def clean_title(self):
        title = self.cleaned_data['title'].strip()
        if len(title) < 5:
            raise forms.ValidationError('Give the notice a clearer title.')
        return title

    def clean_expires_at(self):
        expires_at = self.cleaned_data.get('expires_at')
        if expires_at and expires_at < timezone.localdate():
            raise forms.ValidationError('That date has already passed.')
        return expires_at


def shrink_photo(uploaded, size=None):
    """Square-crop and downscale an upload, returning it as JPEG.

    A phone photograph is several megabytes and thousands of pixels wide, and
    it would be served at that size on every row of a class roster. Cropping to
    a square is done here rather than with CSS so the stored file is the one
    that gets used.
    """
    size = size or settings.PROFILE_PHOTO_SIZE
    image = Image.open(uploaded)
    # Photographs from phones carry an orientation tag that most things honour
    # and PIL does not, so an upright picture would be stored on its side.
    image = ImageOps.exif_transpose(image)
    # Flatten transparency onto white; JPEG has no alpha channel.
    if image.mode in ('RGBA', 'LA', 'P'):
        image = image.convert('RGBA')
        backdrop = Image.new('RGB', image.size, (255, 255, 255))
        backdrop.paste(image, mask=image.split()[-1])
        image = backdrop
    else:
        image = image.convert('RGB')

    image = ImageOps.fit(image, (size, size), Image.LANCZOS)

    buffer = io.BytesIO()
    image.save(buffer, format='JPEG', quality=85, optimize=True)
    buffer.seek(0)
    return ContentFile(buffer.read(), name='photo.jpg')


class ProfileForm(forms.Form):
    """The contact details a person maintains about themselves.

    Deliberately not a ModelForm over Student/Teacher: those two share no base
    class, and the fields worth exposing are the same handful either way. USN,
    class, department and date of birth stay out - changing those is an
    administrative act, not a profile edit.
    """
    email = forms.EmailField(
        required=True,
        help_text='Where password resets and notifications are sent.')
    phone = forms.CharField(required=False, max_length=20)
    address = forms.CharField(required=False, max_length=255,
                              widget=forms.Textarea(attrs={'rows': 2}))
    photo = forms.ImageField(
        required=False,
        help_text='Optional. Cropped to a square and resized on upload.')
    remove_photo = forms.BooleanField(required=False, label='Remove my photo')

    def __init__(self, *args, profile=None, user=None, **kwargs):
        self.profile = profile
        self.user = user
        if profile is not None and 'initial' not in kwargs:
            kwargs['initial'] = {'email': user.email,
                                 'phone': profile.phone,
                                 'address': profile.address}
        super().__init__(*args, **kwargs)

    def clean_phone(self):
        phone = self.cleaned_data['phone'].strip()
        if phone and not re.fullmatch(r'[0-9+()\s-]{6,20}', phone):
            raise forms.ValidationError(
                'Use digits, spaces and + ( ) - only.')
        return phone

    def clean_photo(self):
        photo = self.cleaned_data.get('photo')
        # Checked before opening it: the resize would otherwise have to load an
        # arbitrarily large file into memory to find out it was too big.
        if photo and photo.size > settings.PROFILE_PHOTO_MAX_BYTES:
            raise forms.ValidationError(
                'That image is %.1f MB; the limit is %.0f MB.'
                % (photo.size / 1024 / 1024,
                   settings.PROFILE_PHOTO_MAX_BYTES / 1024 / 1024))
        return photo

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        clash = User.objects.filter(email__iexact=email)
        if self.user is not None:
            clash = clash.exclude(pk=self.user.pk)
        if clash.exists():
            raise forms.ValidationError('Another account already uses that address.')
        return email

    def save(self):
        self.profile.phone = self.cleaned_data['phone']
        self.profile.address = self.cleaned_data['address'].strip()

        fields = ['phone', 'address']
        if self.cleaned_data.get('remove_photo'):
            self.profile.photo.delete(save=False)
            self.profile.photo = None
            fields.append('photo')
        elif self.cleaned_data.get('photo'):
            # Replacing rather than accumulating: the old file is of no use
            # once a new one is chosen.
            self.profile.photo.delete(save=False)
            self.profile.photo = shrink_photo(self.cleaned_data['photo'])
            fields.append('photo')

        self.profile.save(update_fields=fields)
        self.user.email = self.cleaned_data['email']
        self.user.save(update_fields=['email'])
        return self.profile


class PasswordResetRequestForm(forms.Form):
    """Step one: who are you.

    Takes either a username or an email because people remember one or the
    other, and an ERP username like `asha_001` is not what anybody memorises.
    """
    identifier = forms.CharField(
        label='Username or email',
        max_length=254,
        widget=forms.TextInput(attrs={'autofocus': True}))

    def find_user(self):
        """The matching account, or None.

        Deliberately returns None rather than raising: the view must respond
        the same way either way, or the form becomes a way to discover which
        usernames exist.
        """
        value = self.cleaned_data['identifier'].strip()
        return (User.objects.filter(username__iexact=value).first()
                or User.objects.filter(email__iexact=value).first())


class PasswordResetVerifyForm(forms.Form):
    """Step two: the code from the email."""
    code = forms.CharField(
        label='6-digit code',
        min_length=6, max_length=6,
        widget=forms.TextInput(attrs={'autofocus': True, 'inputmode': 'numeric',
                                      'autocomplete': 'one-time-code'}),
        error_messages={'min_length': 'The code is six digits.',
                        'max_length': 'The code is six digits.'})

    def clean_code(self):
        code = self.cleaned_data['code'].strip()
        if not code.isdigit():
            raise forms.ValidationError('The code is six digits.')
        return code


class MarkQueryForm(forms.Form):
    """What the student says when they think a mark is wrong."""
    reason = forms.CharField(
        label='What do you think is wrong?',
        min_length=15, max_length=1000,
        widget=forms.Textarea(attrs={
            'rows': 4,
            'placeholder': 'For example: question 3b was marked out of 5 but '
                           'the paper says 10.'}),
        error_messages={
            'min_length': 'Say a little more - the teacher has to be able to '
                          'check what you mean.'})

    def clean_reason(self):
        return self.cleaned_data['reason'].strip()


class MarkQueryReviewForm(forms.Form):
    """The teacher's answer, and the corrected mark if there is one."""
    decision = forms.ChoiceField(
        choices=(('accept', 'Correct the mark'), ('reject', 'Mark stands')),
        widget=forms.RadioSelect)
    new_mark = forms.IntegerField(
        label='Corrected mark', required=False, min_value=0)
    response = forms.CharField(
        label='What should the student be told?',
        max_length=1000, required=False,
        widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, *args, total_marks=20, **kwargs):
        super().__init__(*args, **kwargs)
        self.total_marks = total_marks
        self.fields['new_mark'].max_value = total_marks
        self.fields['new_mark'].widget.attrs.update({'max': total_marks,
                                                     'min': 0})
        self.fields['new_mark'].help_text = 'Out of %d.' % total_marks

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('decision') != 'accept':
            # A rejection carries no number; keeping one would put a figure in
            # the record that was never applied.
            cleaned['new_mark'] = None
            if not cleaned.get('response'):
                self.add_error('response',
                               'Say why the mark stands - "rejected" on its '
                               'own is not an answer the student can use.')
            return cleaned

        mark = cleaned.get('new_mark')
        if mark is None:
            self.add_error('new_mark', 'Enter the corrected mark.')
        elif mark > self.total_marks:
            self.add_error('new_mark',
                           'This component is out of %d.' % self.total_marks)
        return cleaned
