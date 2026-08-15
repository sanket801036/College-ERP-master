from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.utils.crypto import get_random_string

from django.utils import timezone

from info.models import (AttendanceRange, Fee, FeeTransaction, Notice,
                         SupportRequest, Student, Teacher,
                         notice_audience_choice)

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

    def __init__(self, data=None, students=None, total_marks=20, **kwargs):
        super().__init__(data, **kwargs)
        self.students = students or []
        self.total_marks = total_marks
        for student in self.students:
            self.fields[student.USN] = forms.IntegerField(
                label=student.name,
                min_value=0,
                max_value=total_marks,
                error_messages={
                    'max_value': 'Maximum for this test is %d.' % total_marks,
                    'min_value': 'Marks cannot be negative.',
                    'required': 'Enter a mark.',
                    'invalid': 'Enter a whole number.',
                },
            )

    def marks_for(self, student):
        return self.cleaned_data[student.USN]

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
