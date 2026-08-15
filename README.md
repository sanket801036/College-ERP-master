# College ERP

[![CI](https://github.com/sanket801036/College-ERP-master/actions/workflows/ci.yml/badge.svg)](https://github.com/sanket801036/College-ERP-master/actions/workflows/ci.yml)

A Django college management system covering attendance, marks, timetables, fees
and notices for three roles — students, teachers and administrators.

**Live demo:** https://college-erp-rlyy.onrender.com

Sign-in details for the demo are on the deployment itself. To load the same
data locally, run `python manage.py seed_demo` — it prints the logins it
creates.

The free Render instance sleeps when idle, so the first request can take 30–50
seconds.

---

## What it does

**Students** see attendance per course with the number of classes they still
need to reach 75% (and how many they can afford to miss), internal marks and
CIE totals, their weekly timetable, fee balances with an Excel export, and the
notice board.

**Teachers** mark attendance a session at a time, enter marks for a whole class
in one form, schedule extra classes, cancel sessions, view a combined
attendance-and-CIE report per class, and post notices.

**Administrators** create student and teacher accounts, manage fees, and reach
the full Django admin for departments, courses, classes and teaching
assignments.

## Stack

Django 4.2 LTS · PostgreSQL · Django REST Framework · Bootstrap 4 ·
gunicorn + WhiteNoise on Render

## Running it locally

Requires Python 3.10+ and PostgreSQL.

```bash
git clone https://github.com/sanket801036/College-ERP-master.git
cd College-ERP-master

python -m venv venv
venv\Scripts\activate          # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env           # then edit it with your database details
createdb college_erp

python manage.py migrate
python manage.py seed_demo     # demo data + printed logins
python manage.py createsuperuser
python manage.py runserver
```

`seed_demo` creates a department, a class of twelve students, three teachers, a
timetable, a term of attendance history, marks, fees and notices, and prints the
generated logins. Without it the database is empty and there is nothing to look
at — every page needs a department, course, class, teaching assignment and
semester date range to exist first.

Configuration comes from environment variables (see `.env.example`):
`DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, or a single
`DATABASE_URL`; plus `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS` and `LOG_LEVEL`.

## Tests

```bash
python manage.py test info.tests
```

67 tests covering the attendance and CIE calculations, role and ownership
checks on every teacher view, form validation, timetable clash detection, and
query counts on the list pages.

## Deployment

`render.yaml` is a Render blueprint: it provisions a web service and a managed
Postgres instance, runs `build.sh` (install, `collectstatic`, `migrate`) and
starts gunicorn. Push to `master` and Render redeploys.

---

## Project layout

```
CollegeERP/       settings, root URLs, WSGI
info/             the application
  models.py       Dept, Course, Class, Student, Teacher, Assign, AssignTime,
                  Attendance, AttendanceTotal, StudentCourse, Marks, Fee, Notice
  views.py        all page views
  forms.py        validation for account creation, marks entry, extra classes
  decorators.py   role and ownership guards
  tests/          test suite
apis/             read-only REST endpoints for the student's own records
templates/        error pages (400/403/404/500)
```

Roles are derived rather than stored: `User.is_student` and `User.is_teacher`
check for a linked `Student` or `Teacher` record, and Django's `is_superuser`
covers administrators.

`AttendanceTotal` holds no counts of its own — attendance is computed from the
`Attendance` rows, either per instance or annotated across a whole list by
`with_counts()`.

---

## Engineering notes

This started as an existing project on Django 2.1 with MySQL. Migrating it to
Django 4.2 and PostgreSQL and then working through the behaviour turned up a
number of defects worth writing down, because several were the kind that fail
silently.

### Authorization

Every teacher view carried `@login_required` and nothing else. Signed in as a
student, all of these returned 200:

- whole-class attendance and the class report
- teacher marks lists and the marks entry form

The worst of it was `change_attendance`, which flipped any `Attendance` row by
integer id — a student could walk the ids and turn their own absences into
attendance. It ran on a `GET`, so CSRF never applied and an `<img>` tag was
enough to trigger it.

Fixed with a `teacher_required` role check plus ownership guards
(`owns_assign`, `owns_attendance_class`, `owns_marks_class`, `owns_teacher_id`)
in `info/decorators.py`, so a teacher reaches only their own classes.
`change_attendance` is POST-only and restricted to the teacher who takes the
course. Seventeen views, covered by tests that assert a student is blocked, an
unrelated teacher is blocked, and the owning teacher and superuser are not.

### Silent data loss

`Student.USN` and `Teacher.id` are primary keys, and saving a model instance
with its primary key already set makes Django attempt an `UPDATE`. Submitting
the add-student form with an existing USN therefore overwrote that student's
name, class and date of birth and moved their login to the new account —
no error, success redirect. This was hit accidentally while testing the failure
path, which is how it was found. Both forms now reject duplicates before
saving.

### Wrong answers, no error

- `get_cie()` summed "the first five" rows of `marks_set.all()`, but `Marks` has
  no `Meta.ordering`. If the database returned the Semester End Exam row (out of
  100) inside that window, it was scored as an internal and a real internal was
  dropped. The components are selected by name now.
- Marks were assigned straight from `request.POST` — 85 saved cleanly onto a
  test worth 20, because field validators don't run on a plain `.save()`.
- A course that hadn't met yet rendered as a red **0%** rather than "no classes
  held yet".

### Crashes

- `AttendanceTotal`'s properties re-fetched their related objects **by name**
  (`Student.objects.get(name=self.student)`) despite already holding them. Two
  students sharing a name raised `MultipleObjectsReturned`.
- Two courses could be scheduled against one class in the same period, or a
  teacher into two classes at once. The timetable view's `.get()` then raised
  `MultipleObjectsReturned`, and only `DoesNotExist` was caught, so the page
  500'd for every student in that class. `AssignTime.clean()` rejects both
  clashes now.
- Three views used a bare `.get()` inside a loop, so one missing row took the
  whole page down. One "self-healing" fallback passed a field that doesn't
  exist on the model and raised `TypeError` if it ever ran.
- On a fresh install, the attendance signal read `AttendanceRange` with `.get()`
  — so the first timetable slot an admin added failed outright.

### Query counts

The pages built their data one row at a time. Measured before and after:

| Page | Before | After |
|---|---|---|
| Student attendance | 28 | 9 |
| Student timetable | 57 | 4 |
| Teacher timetable | 57 | 5 |
| Teacher class attendance | 28 | 13 |
| Class report (12 students) | 62 | 15 |

The timetable was the clearest case: it called `.get()` once per cell — 54
queries whether or not anything was scheduled, with every empty slot raising and
swallowing `DoesNotExist` as its normal path.

More important than the totals, the counts no longer grow with the class. There
are tests that add ten students and assert the query count is unchanged.

### Still open

Tracked in [IMPROVEMENT_PLAN.md](IMPROVEMENT_PLAN.md), a page-by-page review of
the whole app with a prioritised backlog. The larger items:

- Fees record a running `paid_amount` rather than a transaction history, so
  there are no receipts and no record of when a payment arrived
- No audit trail on marks or attendance changes
- The REST API rejects session-authenticated users and returns no attendance
  data; it needs fixing or removing
- Email is configured but has no host, which blocks password reset, fee
  reminders and notice notifications
- No CI, no Docker, no media storage for profile photos
