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

**Students** open on their standing: overall attendance, which courses are
below the 75% exam threshold and how many consecutive classes would fix each,
which have headroom and how many can still be missed, and outstanding fees with
the next due date. Behind that: attendance per course and per session, internal
marks with CIE totals, the weekly timetable, fee history with an Excel export,
and the notice board.

**Teachers** get a work queue rather than a menu — sessions whose attendance was
never submitted, marks batches not yet entered, and the students under 75% in
their own classes, each linking to the page that clears it. They mark attendance
a session at a time, enter marks for a whole class in one validated form,
schedule extra classes, cancel sessions, and view a combined
attendance-and-CIE report per class.

**Administrators** create student and teacher accounts (which issue a one-time
password shown once), record fee payments, and see average attendance, students
at risk, outstanding fees and a feed of who changed what. The full Django admin
covers departments, courses, classes and teaching assignments.

Every change to attendance, marks and fees is recorded — who made it, when, and
what the value was before.

## Stack

Django 4.2 LTS · PostgreSQL · Django REST Framework · Bootstrap 4 ·
gunicorn + WhiteNoise on Render

## Running it locally

### With Docker

```bash
git clone https://github.com/sanket801036/College-ERP-master.git
cd College-ERP-master
docker compose up
```

That brings up Postgres, migrates, seeds a demo database and serves the app on
http://localhost:8000 - the seed step prints the logins it creates.

### Without Docker

Requires Python 3.10+ and a local PostgreSQL.

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

## Tests and linting

```bash
python manage.py test info.tests
ruff check .
```

438 tests covering the attendance, CIE, grade and fee calculations, role and
ownership checks on every teacher view, form validation, timetable clash
detection, the audit trail, the charts, the API, and query counts on the list
pages. Both run in CI on every push.

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
                  Attendance, AttendanceTotal, StudentCourse, Marks, Fee,
                  FeeTransaction, Notice, AuditLog
  views.py        all page views
  forms.py        validation for account creation, marks entry, extra classes,
                  fees and payments
  decorators.py   role and ownership guards
  middleware.py   forces a password change on accounts issued by an admin
  reports.py      PDF marks cards and fee receipts
  templatetags/   inline SVG chart tags - no chart library, no CDN
  management/     seed_demo, which builds a usable demo database
  tests/          test suite
apis/             REST endpoints, documented at /api/docs/
templates/        error pages (400/403/404/500)
Dockerfile        image; docker-compose.yml brings it up with Postgres
```

Roles are derived rather than stored: `User.is_student` and `User.is_teacher`
check for a linked `Student` or `Teacher` record, and Django's `is_superuser`
covers administrators.

`AttendanceTotal` holds no counts of its own — attendance is computed from the
`Attendance` rows, either per instance or annotated across a whole list by
`with_counts()`. The dashboards and the API skip it entirely and aggregate
`Attendance` directly, so they do not depend on rows that are only backfilled
when someone opens the attendance page.

`Fee.paid_amount` works the same way: it stays a column so totals can be summed
in the database, but it is derived from `FeeTransaction` rows rather than
written to.

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
- A fee of 10,000 accepted a payment of 99,999, leaving a balance of −89,999
  that still reported as "Paid". Negative amounts saved cleanly too.
- `Fee.status` checked `paid <= 0` before `paid >= amount`, so a fully waived
  fee of 0 reported "Unpaid" for ever and could never settle.
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

### No history

Fees kept a single `paid_amount` that staff overwrote by hand, so nothing
recorded when money arrived, how much came in each time, who took it or how it
was paid — and two people recording payments at once silently lost one of them,
since it was a read-modify-write with no locking. `FeeTransaction` holds one row
per payment; `paid_amount` is derived from it.

Marks and attendance had the same gap: a value could be changed with no record
of the previous one, the person or the time. One append-only `AuditLog` covers
all three, storing names alongside the foreign keys so entries still read
correctly after an account is deleted. It is add/change/delete-disabled in the
admin — a log that can be tidied up afterwards is not one.

### An API that had never been called

All four endpoints returned 400 "User not authenticated" to every caller: each
view re-derived the user from a `Token` row on top of DRF's own authentication,
and nothing in the app ever issued a token. Once that was removed, the rest
followed — `/api/attendance/` returned no attendance at all (the serializer used
`fields = '__all__'` on a model whose values are properties, so DRF dropped
every one), `/api/timetable/` returned its payload under the key `user_marks`,
the attendance handler wrote rows during a `GET`, and every view ended in
`except Exception: return Response(str(e), status=400)`, handing internal error
text to the caller.

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

- Email has no SMTP host configured, which blocks password reset by OTP, fee
  reminders and notice notifications
- No OpenAPI/Swagger documentation for the API, and no write endpoints
- The notice board has no search, filtering, draft/publish workflow or read
  tracking
- No charts — attendance trend, marks distribution, fee collection
- No Docker, no linting config, and no media storage for profile photos
  (Render's filesystem is ephemeral, so that needs S3 or similar rather than
  just a settings change)
