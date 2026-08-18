"""Enrolling an intake from a spreadsheet.

Adding sixty students meant sixty trips through the add-student form.
"""
import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from openpyxl import Workbook

from info.models import Student, Teacher
from info.tests import factories as f

HEADER = ['usn', 'name', 'class', 'sex', 'dob', 'email']


def csv_upload(rows, header=HEADER, name='intake.csv'):
    lines = [','.join(header)] + [','.join(row) for row in rows]
    return SimpleUploadedFile(name, '\n'.join(lines).encode(), 'text/csv')


def xlsx_upload(rows, header=HEADER, name='intake.xlsx'):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(header)
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return SimpleUploadedFile(
        name, buffer.read(),
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


class ImportStudentsTests(TestCase):
    def setUp(self):
        self.dept = f.make_dept()
        self.klass = f.make_class(self.dept)
        self.client.force_login(f.make_admin())
        self.url = reverse('bulk_import')

    def _row(self, usn='1CS22CS001', name='Asha Rao', email='asha@example.edu'):
        return [usn, name, self.klass.pk, 'Female', '2004-05-14', email]

    def _post(self, upload, kind='students'):
        return self.client.post(self.url, {'file': upload, 'kind': kind})

    def test_imports_a_csv(self):
        response = self._post(csv_upload([self._row()]))

        self.assertEqual(response.status_code, 200)
        student = Student.objects.get(USN='1CS22CS001')
        self.assertEqual(student.name, 'Asha Rao')
        self.assertEqual(student.user.email, 'asha@example.edu')

    def test_imports_an_xlsx(self):
        self._post(xlsx_upload([self._row()]))

        self.assertTrue(Student.objects.filter(USN='1CS22CS001').exists())

    def test_every_row_gets_a_login_with_a_one_time_password(self):
        response = self._post(csv_upload([
            self._row(),
            self._row(usn='1CS22CS002', name='Bhavna Singh',
                      email='bhavna@example.edu'),
        ]))

        created = response.context['created']
        self.assertEqual(len(created), 2)
        for person in created:
            user = Student.objects.get(USN=person['key']).user
            self.assertTrue(user.check_password(person['password']))
            self.assertTrue(user.must_change_password)

    def test_a_bad_row_stops_the_whole_file(self):
        """A half-imported intake with no record of which half is worse than a
        rejected file."""
        response = self._post(csv_upload([
            self._row(),
            self._row(usn='1CS22CS002', name='Bhavna', email='not-an-email'),
        ]))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Student.objects.exists())
        self.assertTrue(response.context['errors'])

    def test_errors_are_numbered_as_the_spreadsheet_shows_them(self):
        """Row 2 is the first one under the header - that is what the person
        has open."""
        response = self._post(csv_upload([
            self._row(),
            self._row(usn='1CS22CS002', name='Bhavna', email='nope'),
        ]))

        rows = [row for row, _, _ in response.context['errors']]
        self.assertEqual(rows, [3])

    def test_a_usn_already_in_the_database_is_rejected(self):
        f.make_student(self.klass, usn='1CS22CS001', name='Original',
                       username='original')

        self._post(csv_upload([self._row()]))

        self.assertEqual(Student.objects.get(USN='1CS22CS001').name, 'Original')

    def test_a_usn_repeated_within_the_file_is_rejected(self):
        """Each row passes its own uniqueness check - nothing is in the
        database yet - and then the second would overwrite the first."""
        response = self._post(csv_upload([
            self._row(),
            self._row(name='Someone Else', email='other@example.edu'),
        ]))

        self.assertFalse(Student.objects.exists())
        messages = [message for _, _, message in response.context['errors']]
        self.assertTrue(any('Duplicate of row 2' in m for m in messages))

    def test_an_unknown_class_is_rejected(self):
        row = self._row()
        row[2] = 'NO-SUCH-CLASS'

        self._post(csv_upload([row]))

        self.assertFalse(Student.objects.exists())

    def test_a_missing_column_is_reported_before_any_row_is_read(self):
        response = self._post(csv_upload([['1CS22CS001', 'Asha']],
                                         header=['usn', 'name']))

        self.assertIn('Missing column', response.context['file_error'])
        self.assertNotIn('errors', response.context)

    def test_a_wrong_file_type_is_refused(self):
        upload = SimpleUploadedFile('notes.txt', b'hello', 'text/plain')

        response = self._post(upload)

        self.assertIn('.xlsx or .csv', response.context['file_error'])

    def test_an_empty_file_is_refused(self):
        response = self._post(SimpleUploadedFile('empty.csv', b'', 'text/csv'))

        self.assertIn('empty', response.context['file_error'])

    def test_blank_rows_are_skipped_rather_than_failing(self):
        upload = SimpleUploadedFile(
            'intake.csv',
            (','.join(HEADER) + '\n' + ','.join(self._row()) + '\n\n\n').encode(),
            'text/csv')

        self._post(upload)

        self.assertEqual(Student.objects.count(), 1)

    def test_the_import_is_logged(self):
        from info.models import AuditLog

        self._post(csv_upload([self._row()]))

        entry = AuditLog.objects.get(action='accounts.imported')
        self.assertIn('1 students', entry.summary)


class ImportTeachersTests(TestCase):
    HEADER = ['staff_id', 'name', 'department', 'sex', 'dob', 'email']

    def setUp(self):
        self.dept = f.make_dept()
        self.client.force_login(f.make_admin())
        self.url = reverse('bulk_import')

    def test_imports_teachers(self):
        upload = csv_upload(
            [['t104', 'Ravi Shankar', self.dept.pk, 'Male', '1980-01-01',
              'ravi@example.edu']],
            header=self.HEADER)

        self.client.post(self.url, {'file': upload, 'kind': 'teachers'})

        teacher = Teacher.objects.get(id='t104')
        self.assertEqual(teacher.name, 'Ravi Shankar')
        self.assertEqual(teacher.dept, self.dept)


class ImportAccessTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.klass = f.make_class(dept)
        self.student = f.make_student(self.klass, username='pupil')
        self.teacher = f.make_teacher(dept, id='t001', username='staff')
        self.url = reverse('bulk_import')

    def test_a_student_cannot_open_it(self):
        self.client.force_login(self.student.user)

        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_a_teacher_cannot_open_it(self):
        """Enrolling people is an administrative act."""
        self.client.force_login(self.teacher.user)

        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_an_admin_can(self):
        self.client.force_login(f.make_admin())

        self.assertEqual(self.client.get(self.url).status_code, 200)
