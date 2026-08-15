from django import forms
from django.contrib.auth import get_user_model
from django.utils.crypto import get_random_string

from info.models import Student, Teacher

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
