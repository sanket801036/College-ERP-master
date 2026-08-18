# College ERP — Current State & Interview-Readiness Roadmap

This is a working document, not final. Section 1-2 describe what exists today (so we're on the same page about the baseline). Section 3 lists concrete flaws. Section 4 is a prioritized list of what to add/fix. Edit this file directly with comments/strikethroughs/priorities, then we turn the agreed items into an implementation plan and start writing code.

---

## ✅ Build log — what has been fixed so far

Fourteen passes of work. The rest of this document still describes the app as it
was found, so anything listed here as closed has already changed in the code.

| # | Work | Items closed | Tests |
|---|---|---|---|
| 1 | Fresh-install crash: the attendance signal read `AttendanceRange` with `.get()`, so the first timetable slot an admin added failed | MD1, part of MD5 | 3 |
| 2 | Add-student/add-teacher rewritten onto ModelForms | AC1, AC2, AC3, AC4, AC5, AC7, AC9, AC11 | 9 |
| 3 | Role and ownership guards across 17 teacher views | TA-S1, TA-S2, TA-S3, TA-S4, TA-S5, TA-S6, TM17, RP9, CS2, TT16 | 11 |
| 4 | Transactions and validation on every submit path | TA-C1, TA-C2, TA-C3, TM19, TM20, TM21, MK25, TA18 | 15 |
| 5 | `AttendanceTotal` rewritten: primary-key lookups, one aggregate, annotations | AT26, AT27, AT6, AT1, MK23, RP10, RP11 | 13 |
| 6 | Timetable clash prevention and grid rebuilt from one query | TT11, TT12, TT13, TT15 | 8 |
| 7 | Logging configuration and custom 400/403/404/500 pages | CF2, ER1, ER2, ER3 | 3 |
| 8 | README, `seed_demo` management command, two more N+1s | IN2, IN7, MK22, MK24, MK4 (partial) | 5 |
| 9 | GitHub Actions CI | IN3 | — |
| 10 | Fee payments recorded as transactions, with validation | FE1–FE6, FE18, FE24–FE27, FE29 (part) | 17 |
| 11 | REST API rewritten | API1–API3, API5–API10 | 10 |
| 12 | Password change, forced reset on issued accounts, timezone | AC10, AC14, CF4 | 10 |
| 13 | Audit trail across attendance, marks and fees | TA-S7, MK19, FE29, D6 | 10 |
| 14 | Dashboards rebuilt around standing and pending work | AT1, B1, B5, B10, C1, C2, C3, D3, MK4 | 16 |
| 15 | Login page rebuilt, plus the support-request queue | §5 items 2, 4, 5, 6, 7, 8; §5.2 (`SupportRequest`), D5 | 15 |
| 16 | Notice board built out | NB1–NB7, NB9, NB10, NB12, NB13, NB16, NB18, NB19 | 28 |
| 17 | Free-teacher finder made to actually find free teachers; `Course.credits` | FT7, FT8, FT9, FT10, MK14 (field only) | 13 |
| 18 | Charts: an inline-SVG/CSS toolkit, attendance meters and the trend line | E3, B3, B2, AT12, part of AT4, part of QA1 | 27 |
| 19 | Marks page rebuilt on VTU's 10-point scale | MK1, MK2, MK3, MK4, MK5, MK6, MK7, MK9, MK14 | 30 |
| 20 | Class report: summary header, at-risk flagging, sort, export, print | RP1, RP2, RP3, RP4, RP8 | 14 |
| 21 | Attendance entry made usable daily; real session states | TA1, TA2, TA3, TA4, TA5, TA7, TA8, TA-C4, TA-C6 | 20 |
| 22 | Marks entry given the same treatment; edit and entry unified | TM1, TM2, TM3, TM4, TM8, TM9, TM10, rest of TM19 | 14 |
| 23 | Absent is not zero; results are published rather than leaked on entry | TM5, MK20, TM15, MD2 | 22 |
| 24 | Class rank and the PDF marks card | MK8, MK10 | 14 |
| 25 | Fee receipts, payment history and bulk assignment; messages finally shown | FE3, FE10, FE14, rest of FE2 | 15 |
| 26 | Fee list: filters, pagination and a collection summary computed in the database | FE15, FE16 (part), FE17, FE30 | 17 |
| 27 | Class marks page rebuilt: statistics, distribution chart, at-risk rows | TM11, TM12, TM13, C6, TM18, rest of MK24 | 22 |

**382 tests**, from zero.

### The grading rules, decided

Nothing in the codebase defined these; they were a policy choice, not a code
one, and everything on the marks page follows from them.

- **Final** = CIE (out of 50) + SEE / 2, so a final out of 100
- **Scale**: VTU's 10-point — O 90+ (10), A+ 80 (9), A 70 (8), B+ 60 (7),
  B 55 (6), C 50 (5), P 40 (4), F below (0)
- **SEE eligibility**: a CIE of at least 20/50, i.e. 40%
- **SGPA** = Σ(grade points × credits) / Σ(credits), over the courses whose
  result is actually in

They live in `info/models.py` as `GRADE_BANDS`, `SEE_ELIGIBILITY_CIE` and
`sgpa_for()`. Changing the scale is a one-place edit.

### Query counts, measured before and after

| Page | Before | After |
|---|---|---|
| Student attendance | 28 | 9 |
| Student timetable | 57 | 4 |
| Teacher timetable | 57 | 5 |
| Teacher class attendance | 28 | 13 |
| Student marks (3 courses) | 18 | 10 |
| Class report (12 students) | 62 | 15 |

The counts also no longer grow with class size; there are tests that add ten
students and assert the query count is unchanged.

### Page-by-page status

The first fourteen passes went almost entirely into correctness - crashes, data
loss, authorization, query counts - plus the dashboards. Passes 15-18 then took
the two untouched pages (login, notice board), fixed the free-teacher finder and
started the chart work. Every module has now had a correctness pass; what
remains is features, and several pages still have their **bugs** fixed but not
their **features**.

| Page | State | What is left |
|---|---|---|
| **Login** (§5) | 🟢 rebuilt, reset built | §5.1 landed once SMTP credentials arrived: "Forgot password?" now goes to a three-screen OTP reset (identify → verify → choose), and every security rule the spec listed is enforced and tested. Not built: the visible countdown and the "Resend code" button, and the optional admin two-factor the spec floats at the end |
| **Notice board** (§7.5) | 🟢 built out | NB8 (attachments, blocked on CF1), NB11 (scheduled publishing), NB14 (per-class/department targeting), NB15+NB20 (rich text — never ship without sanitisation), NB17 (email on publish, blocked on CF3), NB22 (should a teacher be able to address the whole institution?) |
| **Free-teacher finder** (§7.8.2) | 🟢 finds free teachers | FT1 (still only reachable from the teacher timetable), FT3 (why each teacher is free), FT4 (department filter), FT5 (teaching load), FT6 (request-a-substitute workflow) |
| **Marks - student** (§7.2) | 🟢 rebuilt | Accordion, CIE meter, letter grades, required-marks calculator, SEE eligibility and a real credit-weighted SGPA landed in pass 19 on VTU's 10-point scale; class rank (MK8) and the PDF marks card (MK10) in pass 24; publication control (MK20) in pass 23. Pass 30 added the cross-subject comparison (MK12) and a per-course internals sparkline (MK11). Still open: MK16 (attendance/marks correlation), semester history (MK15, needs semester tagging) and MK18 (re-evaluation workflow) |
| **Attendance - student** (§7.1) | 🟢 summary page done, charts landed | Summary carries a meter per course (B3) and the detail page a running trend (B2/AT12). Note AT4 is only *part* done — the zone-coloured progress bar landed, but inside the existing table rather than as the per-course cards the spec describes. Still open on the detail page: calendar heatmap (AT9), month grouping (AT10), filters (AT11), day-of-week insight (AT13), streaks (AT14), export (AT16). Phase D workflows (correction requests, leave, exemptions, alerts) all unbuilt |
| **Attendance - teacher** (§7.3) | 🟢 secured, entry rebuilt | Pass 21 landed one-click marking from the dashboard, mark-all-present, a live counter, keyboard entry, roster search, the unsaved-changes guard, and real session states; TA-C4 and TA-C6 are closed. Still open: TA6 (photos, blocked on CF1), TA9/TA10 (bulk import, offline drafts), TA12-TA17 (class analytics and export), TA19-TA21 (cancel reason, reschedule, substitutes) |
| **Marks entry - teacher** (§7.7) | 🟢 secured, validated, entry rebuilt | Pass 22 landed the max-marks hint, live inline validation, keyboard entry, running statistics, the previous component alongside, sorting and the unsaved-changes guard, and folded the separate edit template into this one. Still open: TM5 (absent-vs-zero, needs a flag on `Marks`), TM6 (draft save), TM7 (bulk import), TM11-TM14 (post-entry statistics and export), TM15 (publication control), TM16 (re-evaluation queue), TM24 (confirmation screen) |
| **Timetable** (§7.4) | 🟢 correctness done | Presentation untouched: no mobile "today" view, "right now" indicator, day highlighting, labelled free slots, room field, or `.ics` export |
| **Class report** (§7.8.1) | 🟢 rebuilt | Summary header, at-risk flagging, sorting, Excel export and a print stylesheet all landed in pass 20. Still open: RP5 (per-component breakdown), RP6 (SEE eligibility column), RP7 (compare sections), RP12 (pagination — deliberately skipped, see below) |
| **Fees** (§7.6) | 🟢 ledger, receipts, bulk assignment, list rebuilt | Pass 25 added PDF receipts, the payment history the transaction model never got a page for, and raising a fee for a whole class; pass 26 made the staff list usable at volume (FE17). Still open: FE11/FE12 (payment instructions, mock gateway), FE16 (collection dashboard), FE19-FE23 (waivers, instalments, late fees, reminders, year tagging). **FE31 still stands and needs a decision** - see below |
| **Dashboards** (§6) | 🟢 rebuilt, charts landed | Pass 29 added attendance-by-class, fee collection and students-by-department for admins, and a class comparison for teachers. Still open: today's-schedule strip (A1), dark mode (A3), global search (A2), breadcrumbs (A5). A4 is done - the topbar carries an unread count |
| **Accounts** (§7.9) | 🟢 creation, passwords, profile and directory | Pass 31 added self-service contact details (AC15) and a searchable student/teacher directory (AC20). Still open: photo upload (AC16, blocked on CF1), bulk import (AC8), edit/deactivate (AC21) and soft delete (AC22) |
| **API** (§7.10) | 🟢 done | Swagger/ReDoc, `/api/v1/` versioning, pagination, throttling and teacher endpoints in pass 28; a token-issuing sign-in and attendance writes in pass 34; marks entry in pass 37. Both write paths share their rules with the web forms rather than reimplementing them |

**What stands out now:** every module has had its correctness pass. What is
left is either a feature build, or blocked on a piece of configuration nobody
has credentials for yet.

### Still open, highest value first

1. **CF1** — the remaining config blocker. **CF3 is closed**: SMTP is configured
   from env vars, falling back to the console backend when `EMAIL_HOST` is
   unset, and the OTP reset flow (§5.1) is built on it. What email still has to
   pay for is the *scheduled* sends — fee reminders (FE22), notice notifications
   (NB17), attendance alerts (AT23) and marks-release alerts (MK21) — which need
   somewhere to run periodically, not just a mail host. Media storage is
   unconfigured *and* Render's disk is ephemeral, so profile photos (AC16),
   notice attachments (NB8) and roster photos (TA6) need S3/Cloudinary, not just
   a settings change. AC4 is done — accounts now collect an email address
2. **API — nothing outstanding.** API13-API20 are all done: Swagger/ReDoc,
   teacher endpoints, attendance and marks writes, a token-issuing sign-in, a
   consistent envelope, pagination, throttling and `/api/v1/` versioning
3. **§6.5 Phase 2, the rest of the charts** — E3 is done (pass 18): an inline
   SVG/CSS toolkit in `info/templatetags/charts.py`, no chart library and no CDN.
   Built on it so far: B3 (per-course meters), B2 (attendance trend) and, in
   pass 27, C6 (marks distribution) on the class marks page, and in pass 29
   C4 (the teacher's own classes compared) and D1/D2/D7 (attendance by class,
   fee collection and outstanding by type, students by department), and in pass
   30 MK11/MK12 (per-course internals sparkline, subjects compared). **The
   chart work is done** - every chart the roadmap called for is drawn
4. **AC16, AC21, AC22** — profile photo (blocked on CF1), edit/deactivate an
   account, and soft delete. AC15 and AC20 are done - pass 31 added a profile
   page and a searchable directory, and the commented-out `student_search` URL
   is gone
6. **Infrastructure is done.** IN1-IN8 are all closed - pass 39 added
   `pip-audit` to CI and a `backup_db` command, and upgraded off Django 4.2,
   which had gone end-of-life carrying two dozen known CVEs
7. **The model layer is done.** MD1-MD8 are all closed - pass 38 bulk-loaded
   the mark-seeding signals and moved the primary-key guard from the form onto
   the models, so every path is covered rather than the add-student page alone
8. **TA9, TA16, TA12–TA14** — bulk attendance import, class export, and the
   teacher-side attendance analytics. The entry flow is done; the reporting
   around it is not

---

---

## 1. Current State — Page by Page

### Public / Auth
| Page | URL | What happens |
|---|---|---|
| Login | `/accounts/login/` | Django's built-in `AuthenticationForm`, username + password, no "forgot password" link |
| Logout | `/accounts/logout/` | Confirmation screen, link back to login |

### Student role
| Page | URL | What happens |
|---|---|---|
| Home | `/` | Cards: Attendance, Marks, Timetable, Fees + latest 3 notices |
| Attendance summary | `/student/<usn>/attendance/` | Per-course table: classes attended / total / % / classes still needed to hit 75% |
| Attendance detail | `/student/<usn>/<course>/attendance/` | Session-by-session present/absent list for one course |
| Marks | `/student/<usn>/marks_list/` | Internal test 1-3, Event 1-2, Semester End Exam marks per course |
| Timetable | `/student/<class>/timetable/` | Weekly grid (day × period) built from a hand-coded 6×12 matrix |
| Fees | `/student/<usn>/fees/` | Fee records, totals, Excel export button |
| Notices | `/notices/` | Notices tagged "All" or "Students" |

### Teacher role
| Page | URL | What happens |
|---|---|---|
| Home | `/` | Cards: Attendance, Marks, Timetable, Reports, Fees + latest notices |
| Class list | `/teacher/<id>/<choice>/Classes/` | `choice` picks context: 1=attendance, 2=marks, 3=reports |
| Attendance: student summary | `/teacher/<assign_id>/Students/attendance/` | Attendance % for every student in a class |
| Attendance: session list | `/teacher/<assign_id>/ClassDates/` | Past sessions for a class, with cancel option |
| Attendance: mark session | `/teacher/<ass_c_id>/attendance/` → `/confirm/` | Present/absent form per student, submitted in one POST |
| Attendance: edit | `/teacher/<ass_c_id>/Edit_att/` | Re-open a submitted session |
| Attendance: per-student detail | `/teacher/<usn>/<course>/attendance/` | Same as student's detail view, teacher-facing |
| Attendance: toggle one record | `/teacher/<att_id>/change_attendance/` | Flips present↔absent for a single entry |
| Extra class | `/teacher/<assign_id>/Extra_class/` → `/confirm/` | Ad hoc session outside the regular timetable |
| Report | `/teacher/<assign_id>/Report/` | CIE + attendance % for every student in the class |
| Timetable | `/teacher/<id>/t_timetable/` | Teacher's own weekly schedule |
| Free teachers | `/teacher/<asst_id>/Free_teachers/` | Who else is free in a given slot |
| Marks: category list | `/teacher/<assign_id>/marks_list/` | Internal 1-3 / Event 1-2 / SEE, each with entered/not-entered status |
| Marks: student list | `/teacher/<assign_id>/Students/Marks/` | Students in the class for a chosen category |
| Marks: entry | `/teacher/<marks_c_id>/marks_entry/` → `/confirm/` | Bulk marks entry form, one POST for the whole class |
| Marks: edit | `/teacher/<marks_c_id>/Edit_marks/` | Re-open a submitted marks batch |
| Fees | `/fees/`, `/fees/add/`, `/fees/<id>/edit/` | List + search by name/USN, add a fee record, update paid amount |
| Notices | `/notices/`, `/notices/add/` | View + post (audience: All/Students/Teachers) |

### Admin role
| Page | URL | What happens |
|---|---|---|
| Dashboard | `/` | Student/teacher/department counts, shortcuts to add-student, add-teacher, fees, notices, Django admin |
| Add student | `/add-student/` | Creates `User` + `Student`; username = `firstname_last3ofUSN`, password = `firstname_YYYY(dob)` |
| Add teacher | `/add-teacher/` | Same pattern: username = `firstname_id`, password = `firstname_YYYY(dob)` |
| Django admin | `/admin/` | Full CRUD on every model (Dept, Course, Class, Assign, AttendanceRange reset tool, Fee, Notice, etc.) |
| Fees / Notices | same URLs as teacher | Admin shares the teacher-facing fee/notice views |

### REST API (`apis` app) — exists but effectively unused
| Endpoint | Method | Notes |
|---|---|---|
| `/api/details/` | GET | Logged-in student's own profile |
| `/api/attendance/` | GET | Logged-in student's own attendance totals |
| `/api/marks/` | GET | Logged-in student's own marks |
| `/api/timetable/` | GET | Logged-in student's own timetable |

All four are **student-only, read-only**, token-authenticated (via djoser, wired at `/info/api/auth/`) — but nothing in the actual UI issues or consumes a token, so this API layer isn't reachable from anywhere in the product today. No teacher/admin endpoints, no write endpoints.

---

## 2. Architecture Snapshot

- **Backend**: Django 4.2 (upgraded this session from 2.1.2), server-rendered templates (Bootstrap 4 + a custom `theme.css` overlay), Django REST Framework present but barely used (see above)
- **Database**: PostgreSQL (migrated this session from hardcoded MySQL)
- **Models** (`info/models.py`): `User`, `Dept`, `Course`, `Class`, `Student`, `Teacher`, `Assign`, `AssignTime`, `AttendanceClass`, `Attendance`, `AttendanceTotal`, `StudentCourse`, `Marks`, `MarksClass`, `AttendanceRange`, `Fee`, `Notice`
- **Auth**: Django session auth; role is *inferred* per-request via `hasattr(user, 'student')` / `hasattr(user, 'teacher')` / `is_superuser` — no Django Groups or permission classes in use
- **Deployment**: Render (gunicorn + whitenoise + managed Postgres via `render.yaml` blueprint), live demo running

---

## 3. Flaws — why this currently reads as a beginner project

### Security
- Auto-generated passwords follow a guessable pattern (`firstname_last3USN`, `firstname_YYYYdob`) — no forced reset on first login, no "forgot password" flow at all
- Views parse `request.POST['field']` directly with no Django Forms/ModelForms — no validation, a missing field throws an unhandled `KeyError` (500, not a friendly error)
- `apis/views.py` catches broad `except Exception` and returns the raw exception message to the client — leaks internals
- No rate limiting on login or API endpoints
- Role checks are copy-pasted per view (`if not request.user.is_superuser: redirect(...)`) instead of a shared decorator — easy to miss on a new view

### Code quality
- `from info.models import *` wildcard imports in `apis/`
- **Zero automated tests** anywhere — no unit tests, no integration tests, no test factories
- No type hints, no linting/formatting config (black/isort/ruff), no pre-commit hooks
- Signals (`create_marks`, `create_attendance`) loop row-by-row instead of bulk operations — N+1 queries, will get slow with real data
- Timetable is a hand-built 6×12 matrix with magic numbers (indices 4 and 8 skipped for breaks) — fragile
- No API documentation (no Swagger/OpenAPI)

### Missing features a real/"advanced" ERP would have
- No bulk import (CSV/Excel upload to add many students/teachers at once) — a natural fit since `openpyxl`/`pandas` are already dependencies
- No file/photo uploads (student photo, ID documents)
- `Fee.paid_amount` is a single running total, not a transaction history — no receipts, no partial-payment log
- No analytics/charts (attendance trend, pass/fail distribution, department stats) — only raw numbers today
- No email notifications (fee due, new notice, low-attendance warning)
- No search or pagination on any list — student directory, notices, fee list will all break at real data volume
- No PDF generation (report cards, hall tickets) — `reportlab` is a dependency but unused
- No timetable clash detection (a teacher can be double-booked)
- No parent/guardian portal
- No leave-application / attendance-correction request workflow
- No audit trail on who changed a mark/attendance entry, or when
- No self-service profile edit or password change for students/teachers
- No dark mode toggle (the CSS variables in `theme.css` are already dark-mode-ready, just not wired to a switch)
- No custom 404/500 error pages
- No Docker/docker-compose, no CI (GitHub Actions), no README

---

## 4. Proposed Roadmap

### Tier 1 — table stakes for "interview ready"
1. Automated tests (pytest-django) covering models, views, and the API — with coverage reporting
2. Replace raw `request.POST` parsing with Django Forms/ModelForms — real validation + error messages
3. Django Groups/permissions + one shared `role_required` decorator instead of repeated inline checks
4. GitHub Actions CI — lint + test on every push/PR
5. Dockerfile + docker-compose (web + Postgres) — one-command local setup
6. README (setup, architecture, screenshots) — currently doesn't exist
7. `drf-spectacular` — live Swagger/OpenAPI docs for the existing API

### Tier 2 — feature depth that shows product thinking
8. Bulk import: upload Excel/CSV of students or teachers, validate row-by-row, show errors, commit in bulk
9. Analytics dashboard: attendance trend chart, class-wise pass/fail, department stats
10. Fee transactions as their own model (one `Fee` → many `FeeTransaction` rows) instead of a single running total
11. Email notifications (fee due, new notice, low attendance) — async via Celery
12. PDF report card / hall ticket generation (`reportlab` already installed, unused)
13. Self-service: change password, edit contact info, upload profile photo
14. Search + pagination on every list view

### Tier 3 — stretch / "wow factor" for a senior-level interview
15. Timetable clash detection + a "suggest a free slot" helper
16. Audit log on Marks/Attendance/Fee changes (who, what, when)
17. Parent/guardian portal — read-only visibility into their child's records
18. Leave-application workflow (student requests → teacher approves/rejects)
19. Real-time notice push via Django Channels/WebSockets
20. Full REST API parity for teacher/admin actions (today it's student-only, read-only) — enough to build a separate mobile/SPA client on top

---

## 5. Login Page Redesign Spec (in discussion)

Working through the login page first, before anything else, since it's the first thing anyone (interviewer included) sees.

| # | Element | Spec | Current state | Notes / dependencies |
|---|---|---|---|---|
| 1 | Logo & Title | Keep as-is | ✅ Done (graduation-cap icon + "College ERP") | — |
| 2 | Role selector | Small dropdown or tabs above username: **Student \| Faculty \| Admin** — signals multi-role system at a glance | ❌ Doesn't exist | Backend already auto-detects role after login (`is_student`/`is_teacher`/`is_superuser`), so this can start as a **cosmetic/UX signal only** — doesn't have to change what's submitted. Open question: should picking "Admin" and logging in as a student show an error ("this account isn't an admin"), or just silently redirect to the right dashboard like today? Recommend the former — better error messaging, minor view change |
| 3 | Username field | Keep as-is | ✅ Done | — |
| 4 | Password field + eye icon | Show/hide toggle at the end of the password field | ❌ Not present | Pure frontend (a few lines of JS toggling `type="password"` ↔ `type="text"`), no backend change |
| 5 | Remember Me + Forgot Password | Same line below password: checkbox left, link right | ❌ Neither exists | **Remember Me** needs real session-expiry logic (`SESSION_EXPIRE_AT_BROWSER_CLOSE` / custom `SESSION_COOKIE_AGE` toggled on login) — not just a checkbox. **Forgot Password** needs an actual password-reset flow (Django has `PasswordResetView` built in, but it requires an email backend — none is configured yet). Ties into the "self-service" item already in Tier 2 (#13) |
| 6 | Login button | Keep as-is, align width to match the other fields | ✅ Exists, ⚠️ alignment tweak needed | Pure CSS |
| 7 | Error message area | Hidden by default; shows "Invalid Username or Password" in red on failed login | ⚠️ Partially done — a basic error banner exists already from the earlier redesign, needs to match this exact style/placement | Mostly CSS/copy polish |
| 8 | Footer link | "Facing issues? Contact Administrator" — small, light text at the very bottom | ❌ Not present | See §5.2 below for what clicking it should do |

**Items that are pure UI/CSS** (safe to build immediately, no design decisions pending): password eye-icon toggle, button alignment, error message styling, footer link.

**Items that need a decision before building**: role-selector behavior (cosmetic vs. enforced), Remember Me session semantics, Forgot Password / OTP email delivery (§5.1), Contact Administrator behavior (§5.2).

---

### 5.1 Email OTP — Forgot Password flow

🟢 **Built.** `PasswordResetOTP` plus `/accounts/reset/`, `/accounts/reset/verify/`
and `/accounts/reset/set/`, covered by 18 tests in
`info/tests/test_password_reset.py`. Every rule in the security list below is
enforced, and the tests are written against the rules rather than the
implementation: an unknown identifier is checked to produce the same status,
the same redirect and the same wording as a real one. Two things in this spec
were deliberately not built — the countdown, because a timer that disagrees
with the server by a few seconds is worse than none, and "Resend code", which
is the same thing as asking again and is already rate limited. Mail failures
are logged and swallowed, since an error page would tell the caller they had
guessed a real account.

Replaces the "email a reset link" approach with a 6-digit code, which is the pattern most Indian college/banking portals use and reads as more modern in a demo.

**Proposed flow**
1. User clicks **Forgot Password?** on the login page
2. **Screen 1 — Identify**: enter registered username or email → submit
3. System generates a 6-digit OTP, stores it hashed with an expiry, emails it to the account's registered address
   - Always show the same "If that account exists, a code has been sent" message whether or not the account exists — otherwise the page becomes a way to discover valid usernames
4. **Screen 2 — Verify**: enter the 6-digit code (with a visible countdown + "Resend code" button that unlocks after ~60s)
5. **Screen 3 — Reset**: on valid OTP, allow setting a new password (Django's password validators already enforce strength), then auto-redirect to login with a success message

**New model** — `PasswordResetOTP`:
| Field | Purpose |
|---|---|
| `user` | FK to `User` |
| `code_hash` | **Hashed**, never the plain 6 digits — same reason passwords aren't stored raw |
| `created_at` | For expiry math |
| `expires_at` | Recommend **10 minutes** |
| `attempts` | Lock after 5 wrong tries, forces a fresh code |
| `used_at` | Null until consumed; a code works exactly once |

**Security rules to build in (these are what an interviewer will actually probe):**
- OTP is single-use and expires (10 min)
- Max 5 verification attempts per code, then invalidate
- Rate-limit OTP *requests* (e.g. max 3 per account per 15 min) so the endpoint can't be used to spam someone's inbox
- Invalidate any outstanding OTPs when a new one is issued, and when the password is successfully changed
- Never reveal whether a username/email exists (uniform response + uniform timing)
- Log OTP issue/verify events for the audit trail (ties into Tier 3 #16)

**Infra dependency**: needs a real SMTP setup. Recommend Gmail SMTP with an App Password for the demo (free, ~5 min setup), credentials read from env vars — never committed. For local development use Django's console email backend so codes print to the terminal and no real mail is sent.

**Also worth reusing this OTP infrastructure for**: optional two-factor login for the Admin role — a strong talking point, and a small addition once the OTP model exists.

---

### 5.2 "Contact Administrator" — what happens on click

Four options, cheapest to most impressive:

| Option | Behavior | Effort | Verdict |
|---|---|---|---|
| A. `mailto:` link | Opens the user's mail client | Trivial | ❌ Weakest — breaks on machines with no mail client configured, and an interviewer sees zero engineering |
| B. Static info panel | Modal showing admin email + phone + office hours | Low | ⚠️ Fine, but still just static text |
| C. **Support-request form** | Modal/page: name, email, category (Login issue / Password reset / Account locked / Other), message → saved to DB **and** emailed to admin | Medium | ✅ **Recommended** — real feature, real model, works without a mail client |
| D. Full ticketing system | C + ticket IDs, status tracking, admin reply thread | High | Nice, but overkill for a login-page link. Consider later as its own module |

**Recommended: Option C**, with these details:
- Opens as a **modal on the login page** — user never loses their place
- Reachable **without being logged in** (the whole point is that they can't log in) — so it needs CSRF protection and rate limiting to avoid becoming a spam relay
- Include a simple honeypot field or captcha to block bots
- **New model** `SupportRequest`: `name`, `email`, `category`, `message`, `created_at`, `status` (New / In Progress / Resolved), `resolved_at`, `admin_notes`
- Surfaces in Django admin with a filter on status, so the admin has a real queue to work
- Show a count badge of unresolved requests on the admin dashboard
- Send a confirmation email to the requester ("we've received your request") plus a notification to the admin

**Open question for you**: should the support form also be reachable from *inside* the app once logged in (e.g. a "Help" item in the sidebar)? That would make it a general-purpose helpdesk rather than a login-page-only escape hatch. Recommend yes — same model, one extra link, and it makes the feature look deliberate rather than bolted onto the login screen.

---

## 6. Home / Dashboard Pages (Post-Login, Role-Specific)

After successful login, each role sees their own dashboard. Currently they exist but are minimal. Let's redesign them to be the "welcome center" — at a glance, students/teachers/admins see their key metrics, quick actions, and announcements.

### 6.1 Student Home (`/`)

**Current state:**
- 4 feature cards (Attendance, Marks, Timetable, Fees) + latest 3 notices
- No stats, no profile completeness indicator, no quick-access sidebar

**Proposed redesign:**

**Top section: Welcome + Quick Stats**
```
╔════════════════════════════════════════════════════╗
║  Welcome, Aarav Patel!                             ║
║  Computer Science · Semester 5 (VTU)              ║
║                                                    ║
║  [Attendance: 87%]  [GPA: 3.8]  [Fees: ₹2500 due] ║
╚════════════════════════════════════════════════════╝
```
- Pull real data from `Student.class_id`, `AttendanceTotal` averages, `Fee` balance, grades
- Use color-coded badges: green (healthy), orange (warning), red (urgent)
  - Attendance <75% → red
  - Fees due > 0 → red
  - GPA based on marks

**Middle section: Quick Action Cards (2x2 grid on desktop, stack on mobile)**
| Card | Icon | Action | Goes to |
|---|---|---|---|
| Attendance | 📋 | View my attendance % | `/student/<usn>/attendance/` |
| Marks | 📊 | Check marks | `/student/<usn>/marks_list/` |
| Timetable | 🕐 | My class schedule | `/student/<class>/timetable/` |
| Fees | 💳 | Pay fees | `/student/<usn>/fees/` |

Each card shows a small metric inline (e.g., "Attended 87 / 100 classes").

**Bottom section: Latest Notices (Inbox-style)**
- Notices tagged "All" or "Students"
- Show 5 most recent, each with: title, date, snippet (truncated to 100 chars), "Read more" link
- A "View all" button goes to `/notices/`
- Empty state: "No new notices"

**New data to fetch for this page:**
- Student's current attendance % (query `AttendanceTotal`)
- Latest semester exam marks (query `Marks`, filter by category="SEE" or recent)
- Fee balance (query `Fee`, sum unpaid amounts)
- Fee due date (next unpaid fee's `due_date`)
- Notices for this role

---

### 6.2 Teacher Home (`/`)

**Current state:**
- Same 4 feature cards (Attendance, Marks, Timetable, Reports) + notices
- No info about which classes they teach, no workload snapshot

**Proposed redesign:**

**Top section: Welcome + Workload Snapshot**
```
╔════════════════════════════════════════════════════╗
║  Welcome, Dr. Ravi Shankar!                        ║
║  Electronics & Communication Department            ║
║                                                    ║
║  [Classes: 3]  [Students: 87]  [Pending Marks: 2] ║
╚════════════════════════════════════════════════════╝
```
- `Classes`: count of `Assign` records for this teacher
- `Students`: sum of student count across assigned classes
- `Pending Marks`: count of `MarksClass` records with `is_submitted=False`

**Middle section: This Semester's Classes (Table or Cards)**
| Class | Students | Next Session | Pending marks? |
|---|---|---|---|
| CS5A | 45 | 15 Aug, 2:15 PM | ❌ No |
| CS5B | 42 | 15 Aug, 3:15 PM | ⚠️ Yes |
| ... | | | |

- Each row links to the attendance/marks entry page for that class
- Red highlight on rows with pending marks → visual "to-do"

**Bottom section: Latest Notices + Announcements**
- Same as student (notices filtered for "All" or "Teachers")

**New data to fetch:**
- Classes assigned to this teacher (query `Assign`)
- Student count per class (query `Assign.class_id.student_set.count()`)
- Next scheduled session for each class (query `AttendanceClass`, order by `date` ASC, filter by future)
- Pending marks batches (query `MarksClass`, filter by `is_submitted=False`)

---

### 6.3 Admin Home (`/`)

**Current state:**
- Counts (students, teachers, departments)
- Quick links to Django admin, add-student, add-teacher

**Proposed redesign:**

**Top section: System Overview**
```
╔════════════════════════════════════════════════════╗
║  College ERP Dashboard                             ║
║  System is healthy • Last updated 2 mins ago       ║
║                                                    ║
║  [Students: 450]  [Teachers: 28]  [Depts: 4]      ║
║  [Pending notices: 2]  [Fee issues: 12]           ║
╚════════════════════════════════════════════════════╝
```

**Middle section: At-a-Glance Metrics (4-column grid)**
| Metric | Value | Trend |
|---|---|---|
| Avg Attendance | 82% | ↑ 3% (vs. last month) |
| Students at risk (attendance <75%) | 47 | ↑ 5 |
| Fees pending | ₹85,000 | ↑ ₹15,000 |
| Courses offered | 24 | — |

**Middle-lower section: Admin Tasks (Pinned to-do list)**
- [ ] Add student (quick-link form)
- [ ] Add teacher (quick-link form)
- [ ] Review support requests (shows unresolved count)
- [ ] Manage notices (shows draft vs. published)
- [ ] Fee collection report (drill-down to see by department/class)

**Bottom section: Recent Activity Log**
- Last 10 actions system-wide: who logged in, who added a student, who submitted marks, etc. (ties into audit trail from Tier 3)
- Each line: timestamp, actor (teacher/admin name), action, target (class/student/course)

**New data to fetch:**
- Student/teacher/department counts (straightforward queries)
- Average attendance across all students
- Students with attendance <75% (query filter)
- Total fees due (sum of `Fee.balance`)
- Support requests unresolved (count `SupportRequest` where `status != "Resolved"`)
- Recent activity/audit log (if implemented; otherwise placeholder)

---

### 6.4 Mobile Responsiveness & Accessibility

All three dashboards should:
- Stack to single column on phones (<640px)
- Use readable font sizes (base 16px, scale up for headings)
- Have sufficient color contrast (WCAG AA minimum)
- Be keyboard-navigable (tab order, focus outlines)
- Use semantic HTML (`<main>`, `<section>`, `<article>`)

---

### 6.5 Additional Dashboard Feature Ideas

Brainstormed against the actual models in `info/models.py`. The **Data ready?** column matters — ✅ means it can be built today with zero schema changes, ⚠️ means a small addition, ❌ means it needs a new model. Build the ✅ ones first: maximum visible impact, minimum risk.

#### A. Universal (all three roles)

| # | Feature | What it does | Data ready? | Effort |
|---|---|---|---|---|
| A1 | **Today's schedule strip** | "Right now: DBMS, 11:00–11:50, Room 302 · Next: OS at 12:40" — the single most-used thing on any college portal | ✅ `AssignTime.day` + `.period` | S |
| A2 | **Global search (Ctrl+K)** | One search box → students, courses, notices, classes. Command-palette style | ✅ | M |
| A3 | **Dark mode toggle** | `theme.css` is already CSS-variable driven — just needs a dark palette + a toggle that persists to localStorage | ✅ | S |
| A4 | **Notification bell with unread count** | Badge on the topbar bell for notices published since the user's last visit | ⚠️ needs a `last_seen_notices_at` timestamp per user | S |
| A5 | **Breadcrumbs** | The base template already has a commented-out breadcrumb block — revive it, driven per page | ✅ | S |
| A6 | **Skeleton loaders / empty states** | Every list currently renders blank when empty. Real empty states ("No notices yet") read far more finished | ✅ | S |
| A7 | **Academic calendar widget** | Mini month view marking holidays, exam dates, fee deadlines | ⚠️ needs an `AcademicEvent` model | M |

#### B. Student dashboard

| # | Feature | What it does | Data ready? | Effort |
|---|---|---|---|---|
| B1 | **"Classes you must attend" alert** | `AttendanceTotal.classes_to_attend` **already computes this** — "Attend 4 more DBMS classes to reach 75%". Surfacing it as a dashboard alert is nearly free and is the single most useful number to a real student | ✅ already a model property | **S — do this first** |
| ~~B2~~ | **Attendance trend chart** | ✅ Done (pass 18) — see AT12 | ✅ `Attendance.date` | M |
| ~~B3~~ | **Subject-wise attendance ~~donut~~ meter** | ✅ **Done (pass 18), as a meter rather than a ring.** A two-slice donut is a pie of two slices, and the reader's actual question is "am I above the line" — which a track with the 75% mark drawn on it answers directly and a ring does not. Green ≥75, amber 65–74, red below, each with an icon and a word so the state never rests on colour alone | ✅ | S |
| B4 | **CIE / marks progress card** | `StudentCourse.get_cie()` already exists — show CIE per subject with a progress bar out of 50 | ✅ | S |
| B5 | **Fee due countdown** | "Tuition Fee ₹12,000 due in 6 days" with an urgency color ramp; goes red once overdue | ✅ `Fee.due_date` + `.balance` | S |
| B6 | **Exam countdown** | "Semester End Exam in 12 days" | ⚠️ needs an exam-date field or `AcademicEvent` | S |
| B7 | **Class rank / percentile** | "You're in the top 20% of CS5A" — computed from CIE across the class | ✅ computable | M |
| B8 | **Personal timetable "today only" view** | Full weekly grid is noisy on a phone; a today-only column is what students actually open | ✅ | S |
| B9 | **Downloadable report card (PDF)** | `reportlab` is already an installed dependency and completely unused today | ✅ | M |
| B10 | **Low-attendance warning banner** | Persistent red banner across all pages while any course sits under 75% | ✅ | S |

#### C. Teacher dashboard

| # | Feature | What it does | Data ready? | Effort |
|---|---|---|---|---|
| C1 | **"Attendance not taken" to-do list** | `AttendanceClass.status` is `0` until a session is submitted — so "3 sessions pending" is directly queryable. Turns the dashboard into an action list instead of a menu | ✅ | **S — do this first** |
| C2 | **Pending marks entry list** | Same idea via `MarksClass.status` — "Internal Test 2 not entered for CS5B" | ✅ | S |
| C3 | **At-risk student list** | Students under 75% across this teacher's classes, so they can intervene early | ✅ | M |
| C4 | **Class performance comparison** | Average CIE per class as a bar chart — CS5A vs CS5B at a glance | ✅ | M |
| C5 | **One-click "Take attendance for today"** | Detect today's session from `AssignTime` and deep-link straight into the marking form — saves 4 clicks every single day | ✅ | S |
| ~~C6~~ | **Marks distribution histogram** ✅ (pass 27) | Grade spread per test — shows whether a paper was too hard/easy | ✅ | M |
| C7 | **Free-slot finder** | The `free_teachers` view already exists but is buried — surface "you're free 3rd period today" | ✅ | S |
| C8 | **Bulk-message a class** | Post a notice scoped to one class rather than all students | ⚠️ `Notice.audience` needs a class-level option | M |
| C9 | **Export class report to Excel** | `openpyxl` is already wired up for fees — reuse the same pattern for attendance/marks | ✅ | S |

#### D. Admin dashboard

| # | Feature | What it does | Data ready? | Effort |
|---|---|---|---|---|
| D1 | **Department-wise attendance heatmap** | Which departments/semesters are struggling | ✅ | M |
| D2 | **Fee collection chart** | Collected vs. outstanding, split by department or fee type | ✅ | M |
| D3 | **Defaulters list** | Students with an overdue balance, sortable by amount, exportable | ✅ `Fee.due_date` + `.balance` | S |
| D4 | **Teacher workload distribution** | Classes/hours per teacher — instantly exposes uneven load | ✅ `Assign` + `AssignTime` counts | M |
| D5 | **Support request queue** | Unresolved count + inline resolve action (pairs with §5.2) | ❌ needs `SupportRequest` | M |
| D6 | **Recent activity feed** | Who logged in, who submitted marks, who added a student | ❌ needs an audit model | M |
| D7 | **Enrollment trend** | Students per department per semester over time | ✅ | M |
| D8 | **System health strip** | DB status, last backup, total records, storage used — small touch, reads very "production" | ✅ | S |
| D9 | **Quick-add shortcuts** | Add student / teacher / notice inline from the dashboard, no page change | ✅ | S |
| D10 | **Timetable clash detector** | Flag teachers double-booked in the same period (`AssignTime` uniqueness isn't enforced today — this is a real latent bug worth demoing) | ✅ | M |

#### E. Cross-cutting technical polish

| # | Feature | Why it matters in an interview | Data ready? | Effort |
|---|---|---|---|---|
| E1 | **Fix N+1 queries on dashboards** | `AttendanceTotal.attendance` fires 2 queries **per course per student**. A dashboard aggregating this is dozens of queries. Fix with `annotate()`/`aggregate()`. Being able to say "I profiled it, found N+1, cut 60 queries to 3" is a genuinely strong interview answer | ✅ | M |
| E2 | **Cache expensive dashboard stats** | Django's cache framework, 5-minute TTL on admin aggregates | ✅ | S |
| ~~E3~~ | **Chart library** | ✅ **Done (pass 18).** Went with inline SVG + CSS over Chart.js on a CDN: the pages are server-rendered, static files go out through whitenoise, and a CDN script is one more thing to fail offline or behind a college proxy — it would also put the numbers out of reach of the print stylesheet. `info/templatetags/charts.py` computes geometry in Python; `attendance_meter` and `attendance_trend` are the two forms so far. Zero new dependencies | ✅ | S |
| E4 | **`django-debug-toolbar` in dev** | Makes the N+1 work above visible and demonstrable | ✅ | S |
| E5 | **Auto-refresh dashboard stats** | Poll (or WebSocket) so numbers update without a reload | ✅ | M |

#### Suggested build order

**Phase 1 — high impact, zero schema change** (these alone transform the dashboards):
B1 (classes-to-attend alert) → C1 (attendance not taken) → C2 (pending marks) → B5 (fee countdown) → A1 (today's schedule) → D3 (defaulters)

**Phase 2 — charts** (one library unlocks all of them):
E3 → B2/B3 (attendance charts) → C4/C6 (class performance) → D1/D2 (admin analytics)

**Phase 3 — needs new models:**
D5 (support queue, from §5.2) → D6 (activity feed) → A4 (notification badge) → A7 (academic calendar)

**Throughout:** E1 (N+1 fixes) — every new aggregate makes this worse, so it's better done alongside Phase 1 than bolted on later.

---

---

## 7. Key Feature Pages — Next to Redesign

After **Login** and **Dashboards**, the core pages that students/teachers use daily. These exist but are minimal tables with no interactivity or visual polish.

### Page Redesign Priority

| # | Page | URL | Current state | Why it matters | Redesign notes |
|---|---|---|---|---|---|
| 1️⃣ | **Attendance (Student)** | `/student/<usn>/attendance/` | Plain table: course name, attended/total classes, %, classes-to-attend | Checked every single day; this % determines eligibility to sit exams. Visual progress is crucial. | §7.1 |
| 2️⃣ | **Marks (Student)** | `/student/<usn>/marks_list/` | Table of 8 columns (internal 1-3, events 1-2, SEE, CIE); no progress indicators | Academically important; desktop-only layout breaks on mobile | §7.2 |
| 3️⃣ | **Attendance (Teacher)** | `/teacher/<assign_id>/Students/attendance/` | Attendance % for each student in a class; link to submit new session | Teacher's daily workhorse; needs one-click path to "take attendance now" | §7.3 |
| 4️⃣ | **Timetable (Student)** | `/student/<class>/timetable/` | Hard-coded 6×12 grid (magic-number breaks); unreadable on phones | Every student checks timetable multiple times per day — must be phone-friendly | §7.4 |
| 5️⃣ | **Notices** | `/notices/` | Bulleted list; no search, filter, or bookmark | Information noise for students; admin has no draft/publish workflow | §7.5 |

### 7.1 Attendance Page Redesign (Student)

**Current state:**
- Single table: Course | Attended | Total | % | Classes to Attend
- Red/green row coloring for under/over 75%, but no context or guidance
- No way to drill into individual sessions

**Proposed redesign:**

**Top card: Attendance Summary & Health**
```
┌─────────────────────────────────────────────┐
│  Attendance Overview                        │
│  Your attendance averaged across all        │
│  courses. Stay above 75% to sit exams.     │
│                                             │
│  [████████░░] 83% (Average across courses) │
│                                             │
│  🟢 Healthy  |  🟠 At Risk (3)  |  🔴 Alert  │
└─────────────────────────────────────────────┘
```
- Donut or progress bar showing weighted average
- Badge counts for courses in each risk zone
- Click badge → scroll to that section

**Middle: Course-wise Cards (instead of table)**
```
┌──────────────────────────────┐
│ Database Management Systems  │
│ DBMS102                      │
│                              │
│ Attended: 87 / 100           │
│ [████████░░] 87%             │
│                              │
│ 🟢 Safe (attend ≥1 more)    │
│                              │
│ [View Session History]       │
│ [Link to marks for this course]
└──────────────────────────────┘
```

Per course:
- Course name + code
- Attended / total (absolute numbers are more concrete than % alone)
- Visual progress bar (colored by risk)
- Status badge + guidance: "Safe" / "Attend 4 more" / "At Risk — only X classes left"
- CTA links: "See each session →" (drill detail) + link to that course's marks

**Visual hierarchy:**
- Green (≥75%): optimistic tone, "You're safe"
- Amber (65-74%): warning, "Attend X more" (use `AttendanceTotal.classes_to_attend` property)
- Red (<65%): urgent, "High risk"

**Mobile:** Stack cards vertically; remove absolute numbers if screen is tiny (<320px), just show % + badge

**Bottom: Notice strip**
- "Attendance is locked after exam date" or similar college rule

**Data needed:**
- All `AttendanceTotal` records for this student (already have)
- Overall average (use Django `aggregate(Avg('attendance'))` on annotated query)
- `classes_to_attend` for each course (already a model property)

---

### 7.1.x Attendance Module — Full Feature Set

This is the deep dive for the attendance module specifically. Grouped by build phase. **Data ready?** ✅ = buildable today with no schema change, ⚠️ = small addition, ❌ = needs a new model.

#### Phase A — Core page (student-facing, no schema change)

| # | Feature | Detail | Data ready? |
|---|---|---|---|
| AT1 | **Bunk calculator / "Safe skips"** | The inverse of `classes_to_attend`: *"You can skip 3 more DBMS classes and still stay above 75%."* Formula: `floor(attended/0.75) - total`. This is the single most-wanted feature in every Indian college attendance app, and it's a two-line calculation on data we already have. Show it prominently, right next to the "attend X more" number | ✅ |
| AT2 | **Overall attendance donut** | Weighted average across courses (total attended ÷ total held — **not** the mean of percentages, which over-weights courses with few sessions) | ✅ |
| AT3 | **Risk-zone badges** | Counts per zone: 🟢 Safe (≥75%) · 🟠 At Risk (65–74%) · 🔴 Critical (<65%). Clicking a badge filters the cards below | ✅ |
| AT4 | **Per-course progress cards** | Replace the table: course name + code, `attended / total`, progress bar colored by zone, and the AT1/`classes_to_attend` guidance line | ✅ |
| AT5 | **Projected end-of-semester %** | `AttendanceRange` holds the semester start/end dates, and `AttendanceClass` holds every scheduled session — so remaining sessions are directly countable. *"If you attend everything from here: 81% · If you skip everything: 62%"* — turns a static number into a forecast | ✅ |
| AT6 | **"No classes yet" empty state** | Today `AttendanceTotal.attendance` returns `0` when `total_class == 0`, so a course that hasn't met yet renders as an alarming red **0%**. It must read "No classes held yet" instead — this is a correctness bug, not just cosmetics | ✅ |
| AT7 | **Sort & filter** | Sort by lowest % / course name / most missed; filter to "at risk only" | ✅ |
| AT8 | **Print-friendly view** | `@media print` stylesheet — parents/offices genuinely ask for a printout | ✅ |

#### Phase B — Detail page (`/student/<usn>/<course>/attendance/`)

Currently a flat, unpaginated list of every session with a green/red cell. Everything below is buildable on existing data.

| # | Feature | Detail | Data ready? |
|---|---|---|---|
| AT9 | **Calendar heatmap** | GitHub-contributions-style month grid — green = present, red = absent, grey = no class. Absence *patterns* become visible instantly in a way a list never shows | ✅ `Attendance.date` + `.status` |
| AT10 | **Month grouping + collapse** | Group sessions under month headers with a per-month mini-summary ("August: 14/16 — 88%") | ✅ |
| AT11 | **Filters** | Absent-only, date range, month picker | ✅ |
| ~~AT12~~ | **Attendance trend chart** | ✅ **Done (pass 18).** Running cumulative % across the semester, with the 75% rule drawn on it, above the session table on the detail page. Fewer than two sessions renders nothing — one point is a dot, not a trend | ✅ |
| AT13 | **Day-of-week insight** | *"You've missed 60% of your Monday classes"* — a genuine behavioural insight, one `annotate` over `date__week_day` | ✅ |
| AT14 | **Streaks** | "Current streak: 7 present · Longest: 15" — light gamification that costs almost nothing | ✅ |
| AT15 | **Period/time context** | Show which period each session was (`AssignTime.period`), so "I always miss the 7:30 slot" becomes visible | ✅ |
| AT16 | **Export to Excel / PDF** | `openpyxl` is already wired for fees and `reportlab` is installed but entirely unused — reuse both here | ✅ |

#### Phase C — Comparative & social (still no schema change)

| # | Feature | Detail | Data ready? |
|---|---|---|---|
| AT17 | **Class average comparison** | "You: 83% · Class average: 76%" — needs care: show only the aggregate, never a per-student leaderboard. Ranking classmates by attendance is a privacy problem, not a feature | ✅ |
| AT18 | **Course difficulty signal** | If a course's class-wide attendance is far below the rest, flag it for the admin dashboard — schedule or teaching problem, not a student problem | ✅ |
| AT19 | **Personal best / semester comparison** | This semester vs. last, once historical data exists | ⚠️ needs semester tagging on attendance |

#### Phase D — Workflow features (need new models — the "senior engineer" tier)

| # | Feature | Detail | Data ready? |
|---|---|---|---|
| AT20 | **Attendance correction request** | Student disputes a wrongly-marked absence → teacher approves/rejects → record updates with a full audit trail. Right now `change_attendance` lets a teacher silently flip any record with no record of who changed what or why. This single feature demonstrates workflow design, state machines, permissions, and auditability all at once — the strongest interview item in this whole module | ❌ `AttendanceCorrectionRequest` |
| AT21 | **Leave application** | Apply in advance (medical/event), attach a document, teacher approves → sessions marked as excused rather than absent. Requires a third state beyond present/absent | ❌ `LeaveApplication` + a status field on `Attendance` |
| AT22 | **Medical/OD exemption** | Excused sessions excluded from the 75% denominator — how real colleges actually work | ❌ |
| AT23 | **Low-attendance alerts** | Email/in-app warning when a course drops below 75%, and a weekly digest. Reuses the SMTP setup from the OTP work in §5.1 | ⚠️ needs an alert-log model to avoid re-sending |
| AT24 | **Parent notification** | Email the guardian on sustained low attendance | ❌ needs guardian contact fields (ties to the parent portal, Tier 3 #17) |
| AT25 | **Attendance freeze date** | After a cut-off, records lock and only an admin can amend — with the amendment logged | ⚠️ |

#### Phase E — Technical fixes this module needs (measured, not guessed)

| # | Issue | Detail |
|---|---|---|
| AT26 | **N+1 queries — measured at 28 queries for a single course** | I instrumented the real page: `/student/<usn>/attendance/` fires **28 SQL queries for a student with one course**. The breakdown: ~9 fixed (session/auth/student/assign lookups) + **~19 per course**. Each of `att_class`, `total_class`, `attendance`, `classes_to_attend` re-runs its own `Student.objects.get()` + `Course.objects.get()` + `COUNT(*)`, and `attendance` is evaluated **twice** by the template (once in the `{% if %}`, once for display). A realistic 6-course student therefore loads **~120 queries for one page**. Fix: a single `annotate(Count(...), Sum(...))` aggregate, plus caching the computed values on the instance. Cutting 120 queries to 3 is a concrete, measurable result — exactly the kind of thing worth being able to talk through in an interview |
| AT27 | **Latent bug: model properties look records up by `name`, not primary key** | `AttendanceTotal.att_class`/`total_class`/`attendance`/`classes_to_attend` all do `Student.objects.get(name=self.student)` and `Course.objects.get(name=self.course)` — they already hold the related object but re-fetch it **by name**. Two students sharing a name (certain in any real college) raises `MultipleObjectsReturned` → a hard 500 on the attendance page. There are currently no duplicate names in the local DB, which is exactly why this hasn't surfaced yet. Fix: use `self.student` / `self.course` directly — it's also strictly faster |
| AT28 | **`classes_to_attend` formula needs explaining in the UI** | `ceil((0.75×total − attended) / 0.25)` assumes every future class is attended. Correct, but opaque — the UI should state the assumption ("assuming you attend all remaining classes") rather than presenting a bare number |
| AT29 | **No pagination on the detail page** | A full semester renders every session in one table. Fine at demo scale, breaks at real scale — paginate or group by month (AT10) |
| AT30 | **No tests on any of this logic** | The percentage, `classes_to_attend`, and bunk-calculator maths are pure functions over model data — the easiest, highest-value place to add the first real unit tests, including the boundary cases (0 classes held, exactly 75%, all absent) |

#### Recommended order for this module

1. **AT27** (name-lookup bug) and **AT6** (0% vs "no classes") — genuine correctness bugs, fix before building UI on top of them
2. **AT26** (N+1) — do it while rewriting the query anyway, and capture before/after query counts as evidence
3. **AT1–AT5, AT7** — the redesigned page: bunk calculator, donut, zone badges, course cards, projection
4. **AT9–AT16** — the detail page: heatmap, trend, insights, export
5. **AT30** — unit tests for the attendance maths (do this alongside 1–3, not after)
6. **AT20/AT21** — correction-request and leave workflows, the standout feature of this module
7. **AT23** — alerts, once SMTP exists from §5.1

---

### 7.2 Marks Page Redesign (Student)

**Current state:**
- Table: 8 columns wide (internal 1-3, events 1-2, SEE, but missing CIE/total)
- Impossible to scan on a phone
- No GPA, no "passing" indicator, no subject ranking

**Proposed redesign:**

**Top card: Overall Performance**
```
┌────────────────────────────────────┐
│ GPA                                │
│ 3.8 / 4.0                          │
│ [████████░] 95% (Excellent)        │
│                                    │
│ Top performer in CS5A              │
└────────────────────────────────────┘
```
- Compute GPA from all CIE scores (use `StudentCourse.get_cie()`)
- Quick descriptor: Excellent/Good/Average/Below Average
- "Top X%" or "Class rank" if available

**Middle: Course-wise accordion or tabs**
```
Tab: Database Management Systems (DBMS102)

┌──────────────────────────────────────────┐
│ Continuous Internal Evaluation (CIE): 45 │
│ Internal Test 1:  17 / 20                │
│ Internal Test 2:  18 / 20                │
│ Internal Test 3:  10 / 20  ⚠️ Low       │
│ Event 1:         0 / 20   (Pending)     │
│ Event 2:         0 / 20   (Pending)     │
│                                          │
│ Semester End Exam (SEE):  Pending       │
│ Passing cut-off: 40 / 100               │
│                                          │
│ Expected Grade: B+ (if SEE = 60+)       │
└──────────────────────────────────────────┘
```

Per course:
- Show CIE total (sum of internal marks entered so far)
- Sub-bullets for each component (Internals, Events, SEE) with status
- Highlight low internals in amber (e.g., "<50% of internal possible")
- If SEE is locked: show expected grade range based on CIE
- If SEE is entered: show final grade + GPA impact

**Visual polish:**
- Icons: ✅ Submitted, ⏳ Pending, ⚠️ Low
- Responsive: on mobile, stack to one course per scroll

**Data needed:**
- `StudentCourse.get_cie()` for each subject (already exists)
- `Marks` records grouped by test name
- Grade logic (if not exists in models, compute: ≥40 pass, 40-50 D, 50-60 C, 60-75 B, 75-90 A, 90-100 A+)

---

### 7.2.x Marks Module — Full Feature Set

Same treatment as the attendance module. **Data ready?** ✅ = buildable today, ⚠️ = small schema addition, ❌ = new model.

**Marking scheme as it exists in code** (worth stating explicitly, since every feature below depends on it):
- 5 CIE components — Internal Test 1/2/3 and Event 1/2 — each out of **20** (`Marks.total_marks`)
- `StudentCourse.get_cie()` = `ceil(sum of those 5 / 2)` → **CIE is out of 50**
- Semester End Exam (SEE) out of **100**
- Nothing in the codebase computes a final mark, a letter grade, or a GPA today — that logic has to be written from scratch

#### Phase A — Core page (student-facing)

| # | Feature | Detail | Data ready? |
|---|---|---|---|
| ~~MK1~~ | **GPA / performance card** ✅ (pass 19) | Overall score card at the top. See MK14 first — a *true* GPA needs course credits, which the schema doesn't have. Until then this should be an honestly-labelled "Average Score", not a fake "3.8/4.0 GPA" | ⚠️ |
| ~~MK2~~ | **Per-course accordion** ✅ (pass 19) | Replace the 8-column table (unreadable on a phone) with one expandable card per course: CIE total, component breakdown, SEE status | ✅ |
| ~~MK3~~ | **CIE progress bar** ✅ (pass 19), as a meter against the 40% eligibility line | "CIE: 38 / 50" with a bar — instantly more readable than six loose numbers | ✅ `get_cie()` |
| MK4 | **Pending vs. zero distinction** | **Correctness issue.** `marks1` defaults to `0`, so a test that hasn't happened yet displays as **0** — identical to actually scoring zero. `MarksClass.status` already records whether the teacher submitted that batch, but the student page never consults it. Must render "Not yet conducted" instead of `0` | ✅ (`MarksClass.status` exists, just unused here) |
| ~~MK5~~ | **Expected / required-marks calculator** ✅ (pass 19) | The counterpart to the attendance bunk calculator: *"You have CIE 38/50. You need **44/100** in the SEE to reach an A grade."* Solve the grade formula backwards for the SEE mark. This is the feature students actually want from a marks page | ✅ |
| ~~MK6~~ | **Letter grade + grade points** ✅ (pass 19), VTU 10-point | Compute final = CIE + SEE/2 (out of 100), then map to a grade band. Show provisional grade while the SEE is pending | ✅ |
| ~~MK7~~ | **SEE eligibility flag** ✅ (pass 19), CIE 20/50. Undecided rather than False while components are outstanding — flagging a course that has not started as already failed was the bug the first render caught | Most colleges require a minimum CIE to sit the final exam. Flag any course where CIE is below the cut-off | ✅ (threshold configurable) |
| ~~MK8~~ | **Class rank / percentile** ✅ (pass 24). Ranked on the *published* components only - ranking on the entered set would let a withheld mark move someone's position, which leaks exactly what publication holds back. Own standing only; no leaderboard anywhere | "Rank 12 of 45" for the student's *own* position — standard in Indian colleges and privacy-safe, since each student sees only their own rank. Do **not** build a public leaderboard | ✅ |
| ~~MK9~~ | **Weakest/strongest subject callout** ✅ (pass 19) | "Strongest: DBMS (46/50) · Needs work: OS (21/50)" | ✅ |
| ~~MK10~~ | **PDF marks card** ✅ (pass 24). `info/reports.py`, built from the same rows the marks page renders so paper and screen cannot disagree. `reportlab` finally does something | `reportlab` is installed and still completely unused. A proper marks card with the college header is a very demo-able artifact | ✅ |

#### Phase B — Analysis & insight

| # | Feature | Detail | Data ready? |
|---|---|---|---|
| MK11 | **Performance trend across internals** | Line chart of Internal 1 → 2 → 3 per course — shows improvement or decline over the semester | ✅ |
| MK12 | **Radar/bar chart across subjects** | All courses on one chart, so relative strengths are visible at a glance | ✅ |
| MK13 | **Comparison against class average** | "You: 38 · Class average: 31" per component. Aggregate only — never a per-classmate breakdown | ✅ |
| ~~MK14~~ | **Credits & true CGPA** | ✅ **Done (passes 17 and 18-19).** `Course.credits` is a `PositiveSmallIntegerField`, default 4, bounded 1–10, editable inline in the admin list, and `sgpa_for()` computes a credit-weighted SGPA from it on VTU's 10-point scale. It deliberately returns None rather than a partial figure while no course has a result — a fabricated "3.8 / 4.0" was the thing to avoid. Semester-over-semester CGPA (MK15) still needs semester tagging on `StudentCourse` | ✅ |
| MK15 | **Semester-over-semester history** | SGPA per semester and cumulative CGPA over time | ⚠️ needs semester tagging on `StudentCourse` |
| MK16 | **Attendance ↔ marks correlation** | `StudentCourse.get_attendance()` already exists alongside `get_cie()` — plotting the two together across courses is a genuinely interesting insight and costs one scatter chart | ✅ |
| MK17 | **Grade distribution for a course** | Where the student sits in the class histogram | ✅ |

#### Phase C — Workflow (new models)

| # | Feature | Detail | Data ready? |
|---|---|---|---|
| MK18 | **Re-evaluation request** | Student disputes a mark → teacher/admin reviews → mark updated with full audit trail. Same shape as the attendance-correction workflow (AT20) and can share its state machine and permission logic | ❌ `MarkRevaluationRequest` |
| MK19 | **Marks audit log** | Today `marks_confirm` and `edit_marks` overwrite `marks1` in place with no record of the previous value, who changed it, or when. For grades specifically, that is the kind of gap an interviewer will press on | ❌ audit model |
| ~~MK20~~ | **Result publication control** ✅ **Done (pass 23).** `MarksClass.is_published` + `published_at`. The student page reads the published set, the teacher's class report reads the entered set | Teacher enters marks, but students only see them once results are formally published — colleges never expose marks the instant they're typed | ⚠️ `MarksClass.is_published` |
| MK21 | **Marks release notification** | Email/in-app alert when a batch is published (reuses the SMTP work from §5.1) | ⚠️ |

#### Phase D — Technical fixes this module needs (all verified against the running app)

| # | Issue | Detail |
|---|---|---|
| MK22 | **Crash bug: `marks_list` passes a field that doesn't exist** | `info/views.py` calls `sc.marks_set.create(type='I', name='Internal test 1')` (six times), but the `Marks` model has only `studentcourse`, `name`, `marks1` — there is **no `type` field**. Verified in a shell: this raises `TypeError: Marks() got unexpected keyword arguments: 'type'`. It sits in the `except StudentCourse.DoesNotExist` fallback branch, which normally doesn't fire because the `create_marks` signal pre-creates the rows — so the page works today purely by luck. Any student whose `StudentCourse` row is missing (bulk import, a deleted row, data restored without signals) gets a hard 500. The identical block in `apis/views.py` has the same problem |
| MK23 | **`get_cie()` depends on unordered query results** | `get_cie()` does `marks_list = self.marks_set.all()` then `sum(m[:5])` — "the first five" — but `Marks.Meta` has **no `ordering`** (verified: `Marks._meta.ordering == []`). Unordered SQL results have no guaranteed order; Postgres is free to return rows in any sequence, and updated rows commonly move. If the SEE row (out of 100) lands in the first five, CIE silently absorbs it and drops an internal — a wrong grade with no error anywhere. It happens to be correct today only because insertion order matches. Fix: select the five components **by name**, never by position |
| ~~MK24~~ | **The marks table has the same positional assumption** ✅ **Now fully fixed.** `marks_in_order` was added for the student's own page in pass 5; the teacher's class roster kept iterating `marks_set.all()` straight into fixed headings until pass 27, with the same risk of a value landing under the wrong test | `marks_list.html` renders `{% for m in sc.marks_set.all %}` straight into columns headed Internals 1/2/3, Event 1/2, SEE — so the same unordered queryset can place values under the wrong headings. The template should look each component up by name |
| MK25 | **No validation on marks entry** | `marks_confirm` does `mark = request.POST[s.USN]` and assigns it directly to `m.marks1`. Verified: a value of **85 saves cleanly onto an internal test worth 20**. Django field validators only run via `full_clean()`, which a bare `.save()` skips, so `MaxValueValidator(100)` never executes either. Non-numeric input raises an unhandled `ValueError`, and a missing form field raises `KeyError` → 500. This is the clearest case in the whole project for switching to a `ModelForm`/formset with `clean_marks1()` bounded by `total_marks` |
| MK26 | **N+1 on the marks page** | Measured: **10 queries for a single course** (~4 fixed + ~6 per course), so a 6-course student issues roughly 40. Much lighter than the attendance page's ~120, but the same root cause — `sc.marks_set.all()` per course plus `get_cie()` per course. Fix with `prefetch_related('marks_set')` and a single aggregate |
| MK27 | **No tests for grade logic** | CIE, grade banding, and the required-SEE calculator are pure functions — ideal first unit tests, including boundaries (all components pending, exactly at a grade cut-off, SEE absent) |

#### Recommended order for this module

1. **MK22, MK23, MK24, MK25** — four real bugs (one crash, two silent-wrong-grade, one data-integrity). Grades are the highest-stakes data in the system; fix these before layering UI on top
2. **MK4** — pending vs. zero, the same class of correctness bug as AT6 in attendance
3. **MK26** — N+1, while the queries are being rewritten anyway
4. **MK2, MK3, MK5, MK6, MK7** — the redesigned page: accordion, CIE bars, required-marks calculator, grades
5. **MK14** — add `Course.credits`, which unlocks a real CGPA instead of a placeholder
6. **MK27** — unit tests alongside steps 1–4, not after
7. **MK11, MK12, MK16** — charts (shares the chart library with the attendance module)
8. **MK18, MK19, MK20** — re-evaluation workflow, audit log, publication control

**Note on ordering across modules:** MK18/MK19 (re-evaluation + audit) and AT20/AT21 (attendance correction + leave) are the same underlying pattern — a request/approve state machine with an audit trail. Build one generic workflow once and apply it to both, rather than writing it twice.

---

### 7.3 Attendance Marking Page (Teacher)

**Current state:**
- `/teacher/<assign_id>/ClassDates/` lists past sessions
- Click to enter attendance (bulk form per session)
- Two POST steps: mark → confirm → submit

**Proposed redesign:**

**Top card: Class & Session Selection**
```
┌────────────────────────────────────┐
│ CS5A · Database Management Systems │
│ 45 students                        │
│                                    │
│ Sessions this week:                │
│ [Mon Aug 15, 11:00] ✅ Submitted  │
│ [Wed Aug 17, 11:00] ⏳ Pending   │ ← Today
│ [Fri Aug 19, 11:00] 🔒 Future    │
│                                    │
│ [Take attendance for today] CTA   │
└────────────────────────────────────┘
```

**Middle: Attendance Marking Form**
- One-click to mark all present, then uncheck absences (faster than checking 45 boxes)
- Vertical list (not a grid) to save space
```
[ Aarav Patel      ] ✓ Present
[ Bhavna Singh     ] ✓ Present
[ Chirag Gupta     ] ☐ Absent
[...]
```
- Keyboard shortcuts: S = select all, U = unselect all, P = mark present this row, A = mark absent this row
- Show count: "23 / 45 present"

**Bottom: Confirm & Submit**
- Show summary ("Marked 23 present, 22 absent")
- Option to review before submit
- Submit button; on success → "Session recorded. Next session: Fri Aug 19"

**Data needed:**
- `Assign` for this class
- `AttendanceClass` records for this class (past, current, future)
- `Attendance` records for the chosen session
- Real-time count as form updates

---

### 7.3.x Teacher Attendance Module — Full Feature Set

⚠️ **Read the security block (Phase D) first.** This module has the most serious defects in the project — they are authorization holes, not cosmetic issues, and they should be fixed before any UI work here.

#### Phase A — Marking flow (the daily workhorse)

| # | Feature | Detail | Data ready? |
|---|---|---|---|
| ~~TA1~~ | **"Take attendance for today" one-click** ✅ (pass 21), on the dashboard and at the top of the session list | Today's session is derivable from `AssignTime.day` + `AttendanceClass.date`. Right now the teacher navigates Classes → class → ClassDates → pick date → form: four clicks, every day, for something that is unambiguous. Put one button on the dashboard | ✅ |
| ~~TA2~~ | **Mark-all-present default** ✅ (pass 21), plus explicit all-present / all-absent buttons | Typical attendance is 80–95% present, so defaulting everyone to present and unchecking the few absentees is far less work than ticking 45 boxes | ✅ |
| ~~TA3~~ | **Live present/absent counter** ✅ (pass 21) | "38 / 45 present" updating as boxes toggle, so the teacher can sanity-check against a head count before submitting | ✅ |
| ~~TA4~~ | **Keyboard-first entry** ✅ (pass 21). Arrow keys move the cursor, P and A set the row and advance | Arrow keys to move down the roster, space to toggle, `A` = all present, `N` = all absent. A teacher marking 45 students daily will use this every time | ✅ |
| ~~TA5~~ | **Search / filter within the roster** ✅ (pass 21), by name or USN | Jump to a student by name or USN in a large class | ✅ |
| TA6 | **Student photos on the roster** | Makes marking far faster and less error-prone for a teacher who doesn't know every name | ❌ needs a photo field (Tier 2 #13) |
| ~~TA7~~ | **Explicit session states** ✅ (pass 21). Pending / Submitted / Cancelled / Scheduled, with Scheduled derived from the date since the stored status cannot tell a session nobody could have marked yet from one the teacher owes | `AttendanceClass.status` uses bare integers — `0` not taken, `1` taken, `2` cancelled — with no `choices` and no constants. Surface these as real labels: ⏳ Pending · ✅ Submitted · 🚫 Cancelled · 🔒 Future | ✅ |
| ~~TA8~~ | **Unsaved-changes guard** ✅ (pass 21) | Warn before navigating away mid-marking — losing a 45-student roster to a stray click is an easy and infuriating failure | ✅ |
| TA9 | **Bulk-import attendance** | Upload a CSV/XLSX roster for a session; `openpyxl` is already a dependency | ✅ |
| TA10 | **Offline-tolerant entry** | Draft state in `localStorage` so a dropped connection mid-marking doesn't lose the work | ✅ |

#### Phase B — Teacher's class overview

| # | Feature | Detail | Data ready? |
|---|---|---|---|
| TA11 | **Pending-sessions to-do list** | `AttendanceClass.status == 0` with a past date is exactly "attendance you still owe". Turns the dashboard from a menu into a work queue | ✅ |
| TA12 | **At-risk student list** | Students below 75% in this teacher's classes, so intervention happens before it's too late | ✅ |
| TA13 | **Class attendance trend** | Session-by-session attendance rate — reveals which days/periods students skip | ✅ |
| TA14 | **Per-session drill-down** | Who was absent on a given date, exportable | ✅ |
| TA15 | **Compare sections** | CS5A vs CS5B attendance for the same course | ✅ |
| TA16 | **Export class attendance** | Excel/PDF for department records — reuse the fees export pattern | ✅ |
| TA17 | **Consecutive-absence flag** | "Rahul has missed 5 in a row" — a stronger early-warning signal than a percentage, which moves slowly | ✅ |

#### Phase C — Scheduling

| # | Feature | Detail | Data ready? |
|---|---|---|---|
| TA18 | **Extra class with validation** | `e_confirm` currently accepts whatever `date` is posted. Needs: date inside the semester (`AttendanceRange` already stores the bounds), not a duplicate of an existing session, and a sane rule about future dates | ✅ |
| TA19 | **Cancel with a reason** | `cancel_class` sets `status = 2` and records nothing else — no reason, no who, no when | ⚠️ |
| TA20 | **Reschedule** | Move a session instead of cancel-and-recreate | ⚠️ |
| TA21 | **Substitute teacher** | Assign a stand-in who can mark attendance for that session only — pairs with the existing (currently buried) free-teachers finder | ❌ |

#### Phase D — 🔴 Security: missing authorization (fix before anything else)

**Every view in this module is protected by `@login_required()` and nothing else.** There is no check that the caller is a teacher, and no check that the caller owns the class being modified.

I verified this against the running app, logged in as the **student** account `teststud` (`is_teacher=False`, `is_superuser=False`):

| Endpoint | URL tested | Result |
|---|---|---|
| `t_student` — whole class's attendance | `/teacher/1/Students/attendance/` | **HTTP 200 — allowed** |
| `t_class_date` — session list | `/teacher/1/ClassDates/` | **HTTP 200 — allowed** |
| `t_report` — full class report (marks + attendance) | `/teacher/1/Report/` | **HTTP 200 — allowed** |
| `t_marks_list` | `/teacher/1/marks_list/` | **HTTP 200 — allowed** |

So a student can already read every classmate's marks and attendance. The write endpoints share the identical decorator set and have the same absence of checks (established by reading the code — the local DB has no `AttendanceClass`/`Attendance` rows to exercise them against):

| # | Issue | Detail |
|---|---|---|
| TA-S1 | **No role check on any teacher view** | Verified above. Fix: a `@teacher_required` decorator (ties to Tier 1 #3) |
| TA-S2 | **No ownership check** | Even a legitimate teacher can open and modify *another* teacher's class by changing the ID in the URL. Every view must assert `assign.teacher == request.user.teacher` |
| TA-S3 | **`change_att` — IDOR on a single record** | `change_att(request, att_id)` does `get_object_or_404(Attendance, id=att_id)` then `a.status = not a.status; a.save()`, with `@login_required()` as the only guard. Any authenticated user can flip **any** attendance record in the database by guessing a sequential integer ID — including a student flipping their own absences to present. This is the single most serious defect in the project |
| TA-S4 | **`change_att` mutates on GET** | A state change behind a `GET` bypasses CSRF protection entirely and can be triggered by a page merely embedding `<img src="/teacher/42/change_attendance/">`. Must be `POST` |
| TA-S5 | **`confirm` / `e_confirm` accept any authenticated POST** | A non-teacher could submit an entire class's attendance, or create a fabricated extra-class session |
| TA-S6 | **`cancel_class` unprotected** | Any authenticated user can cancel any scheduled session |
| TA-S7 | **No audit trail on any of it** | Attendance can be altered with no record of who changed what, when, or why — the same gap as MK19 for marks. Once TA-S1–S3 are fixed, an audit log is what makes the fix *demonstrable* |

**Why this matters in an interview:** finding, explaining, and fixing an IDOR in your own project is a much stronger story than never having had one. Worth writing up in the README as a "security review" section, with the before/after.

#### Phase E — Correctness & performance

| # | Issue | Detail |
|---|---|---|
| TA-C1 | **No transaction around `confirm()`** | The view loops over students saving `Attendance` rows one at a time. If it raises partway — and `request.POST[s.USN]` raises `KeyError` whenever a checkbox is missing — half the class is saved, `assc.status` may already be flipped to `1`, and the session looks submitted when it isn't. Wrap in `@transaction.atomic` |
| TA-C2 | **`assc.status = 1` is set inside the loop** | It's assigned while processing the *first* student, so every student after that takes the `if assc.status == 1` branch and runs an `Attendance.objects.get()` that always misses before falling back to create. Wasted query per student, and it entangles loop state with session state. Set it once, after the loop |
| TA-C3 | **Unvalidated POST access throughout** | `request.POST[s.USN]` (KeyError → 500) and `request.POST['date']` in `e_confirm` (arbitrary/invalid date accepted). Same root cause as MK25 — no forms anywhere |
| ~~TA-C4~~ | **Magic numbers for session status** ✅ **Fixed (pass 21).** CLASS_PENDING / CLASS_TAKEN / CLASS_CANCELLED, with choices on the field | `0/1/2` with no `choices` and no named constants; `2` (cancelled) is documented nowhere |
| TA-C5 | **Severe N+1 — measured** | `/teacher/<id>/Students/attendance/` fired **28 queries for a class containing a single student**. The per-student cost is the same expensive `AttendanceTotal` property chain described in AT26 (~19–24 queries each), so a realistic 45-student class is on the order of **900+ queries for one page load**. This is the worst hot spot found anywhere in the project. Fixing AT26 and AT27 fixes this page too — they share the root cause |
| ~~TA-C6~~ | **`t_class_date` shows only past sessions** ✅ **Fixed (pass 21).** Upcoming sessions render as locked rather than being hidden | Filtered `date__lte=now`, so a teacher cannot see or prepare for upcoming sessions. TA1 depends on changing this |

#### Recommended order for this module

1. **TA-S1, TA-S2, TA-S3, TA-S4** — the authorization holes. Nothing else in this module should ship first; a student being able to edit their own attendance invalidates the entire feature
2. **TA-C1, TA-C2, TA-C3** — transaction, loop-state bug, and forms/validation
3. **TA-C5** — the N+1, shared with AT26/AT27 in the attendance module
4. **TA-S7** — audit log, which makes the security fixes provable
5. **TA1, TA2, TA3, TA4, TA7, TA11** — the actual UX work: one-click marking, all-present default, live counter, keyboard entry, session states, pending queue
6. **TA12, TA13, TA16, TA17** — analytics and export
7. **TA18–TA21** — scheduling improvements

**Shared work across modules:** TA-S1/TA-S2 (role + ownership decorators) fix the marks views in the same pass — `t_marks_list`, `marks_confirm` and `edit_marks` have exactly the same exposure. Do it once, apply everywhere.

---

### 7.4 Timetable Page Redesign (Student)

**Current state:**
- Hard-coded 6×12 grid with magic-number breaks (indices 4, 8)
- Not responsive; unreadable on phones

**Proposed redesign:**

**Desktop (≥768px): Weekly Grid (keep current)**
```
       Monday    Tuesday   Wednesday  ...
7:30 | DBMS    | OS      | CN       | ...
8:30 | DBMS    | —       | CN       | ...
9:30 | —       | OS      | —        | ...
BREAK
11:00| CN      | DBMS    | OS       | ...
11:50| CN      | DBMS    | —        | ...
12:40| —       | —       | DBMS     | ...
LUNCH
2:30 | —       | CN      | —        | ...
...
```

**Mobile (<768px): Today's Schedule (different view)**
```
Today: Wednesday, Aug 17

┌──────────────────────────────┐
│ Right now: 11:00 – 11:50    │
│ Computer Networks (CN101)    │
│ Room 302 · Lab              │
│ [30 min remaining]           │
└──────────────────────────────┘

Next:
┌──────────────────────────────┐
│ 12:40 – 1:30 (Lunch)        │
└──────────────────────────────┘

┌──────────────────────────────┐
│ 2:30 – 3:30                  │
│ Database Management (DBMS)  │
│ Room 201                     │
└──────────────────────────────┘

[← Prev day] [Week view] [Next day →]
```

**Tablet (768-1024px): Day view (split design)**
- Left: day selector (Mon | Tue | Wed...)
- Right: today's full timetable

**Data needed:**
- `AssignTime` records for this student's class
- Current day/time (for "right now" indicator)
- Course room info (if available; else say "TBD")

---

### 7.4.x Timetable Module — Full Feature Set

**How it works today:** `timetable()` builds a 6×12 matrix — column 0 is the day label, columns 4 and 8 are blank break columns, and the remaining 9 columns map to the 9 entries in `time_slots`. The counter `t` is deliberately not incremented on skipped columns, so the mapping does line up. It works, but it's held together by magic numbers.

#### Phase A — Responsive views

| # | Feature | Detail | Data ready? |
|---|---|---|---|
| TT1 | **Mobile "today" view** | Below 768px the 12-column grid is unusable. Show today's sessions as a vertical list instead — this is what a student actually opens between classes | ✅ |
| TT2 | **"Right now" indicator** | Highlight the current period and show "22 min remaining", plus "Next: OS at 12:40". Needs only the current time compared against `time_slots` | ✅ |
| TT3 | **Tablet day-selector** | Mon–Sat pills across the top, selected day's schedule below | ✅ |
| TT4 | **Today's column highlighted on desktop** | Keep the weekly grid, tint the current day and current period | ✅ |
| TT5 | **Free-period gaps shown explicitly** | Empty slots currently render as blank cells that read as a rendering fault. Label them "Free" | ✅ |
| TT6 | **Show more than a course code** | The student grid stores only `a.assign.course_id`, so the cell shows a bare code like `CS502`. Show course name + teacher on hover/tap — both are one join away via `assign` | ✅ |
| TT7 | **Room / location** | There is no room field anywhere in the schema. Genuinely useful, needs a small migration | ❌ `Assign.room` or `AssignTime.room` |
| TT8 | **Export / subscribe** | Download as PDF, or emit an `.ics` feed so the timetable lands in the student's phone calendar. The `.ics` option is a small amount of code for a disproportionately impressive result | ✅ |
| TT9 | **Next-class notification** | Browser/push reminder 10 minutes before each session | ⚠️ |
| TT10 | **Week navigation** | Previous/next week, so extra classes and cancellations are visible in context | ⚠️ needs merging `AttendanceClass` dates into the view |

#### Phase B — Correctness & performance

| # | Issue | Detail |
|---|---|---|
| TT11 | **57 queries to render an empty timetable — measured** | The view calls `asst.get(period=..., day=...)` inside a 6×9 nested loop — **54 individual queries**, one per cell, plus overhead. I measured **57 queries on a class with zero `AssignTime` rows**: every cell misses, raises `DoesNotExist`, and is swallowed. Exception-driven control flow as the normal path. Fix: fetch all `AssignTime` rows for the class in **one** query and index them by `(day, period)` in a dict. 57 → 2 |
| TT12 | **Unhandled `MultipleObjectsReturned` → 500** | `AssignTime` has **no uniqueness constraint** (verified: `unique_together == []`, `constraints == []`), so nothing stops two courses being scheduled for the same class, day and period. When that happens `asst.get()` raises `MultipleObjectsReturned` — and the `except` clause catches only `DoesNotExist`. The exception propagates and the timetable page **500s for every student in that class**, with no clue as to why. This is the concrete failure behind the "timetable clash detection" item in Tier 3 (#15), and it's a data-integrity bug, not just a missing feature. Fix: add `unique_together = (('assign', 'day', 'period'),)` plus a clash check at assignment time |
| TT13 | **Teacher timetable has the same two bugs** | `t_timetable()` is the same loop with the same `.get()` and the same narrow `except`. A double-booked teacher — which nothing prevents — 500s their own timetable page |
| TT14 | **Hard-coded 12 columns and break positions** | `range(12)` with `j == 4` and `j == 8` skipped assumes exactly 9 periods and exactly 2 breaks in fixed positions. Adding a period or moving a break silently misaligns every cell. Derive the layout from `time_slots` instead of hard-coding it |
| TT15 | **`t_timetable` initialises its matrix to `True`** | `[[True for i in range(12)] ...]` — free slots render as the literal string `True` unless the template guards against it, where the student version uses `''`. Two implementations of the same grid that don't agree |
| TT16 | **No ownership check** | `timetable(request, class_id)` is `@login_required()` only, so any authenticated user can view any class's timetable by editing the URL. Low severity — timetables aren't confidential — but it's the same missing-authorization pattern as TA-S1/TA-S2 and should be fixed in the same pass |

#### Recommended order

1. **TT12** — add the uniqueness constraint and catch the exception; a 500 on a core page is the priority
2. **TT11** — one query instead of 54, while rewriting the loop anyway
3. **TT14, TT15** — derive the grid from `time_slots`, unify the student and teacher implementations
4. **TT1, TT2, TT4, TT5** — the responsive work: mobile today-view, "right now", highlighting, free slots
5. **TT6, TT8** — richer cells and the `.ics` export
6. **TT7** — room field, if a migration is acceptable

---

### 7.5.x Notice Board Module — Full Feature Set

**Current state:** `Notice` has exactly six fields — `id`, `title`, `message`, `audience`, `posted_by`, `created_at` (verified). The list view filters by audience and returns **every** matching notice, unpaginated. Everything the redesign proposes is genuinely new.

**Worth noting:** `add_notice` *does* check `is_superuser or is_teacher` before allowing a post — one of the few views in the project with a real role check. Keep that pattern and apply it elsewhere.

#### Phase A — Reading experience (student/teacher)

| # | Feature | Detail | Data ready? |
|---|---|---|---|
| NB1 | **Search** | Free-text over title and body — `icontains` to start; Postgres full-text search if it needs to scale | ✅ |
| NB2 | **Date filters** | This week / This month / All | ✅ `created_at` |
| NB3 | **Pagination** | The view currently returns every notice for the audience with no limit. Fine at 1 notice, breaks at 500 | ✅ |
| NB4 | **Unread badge + mark-as-read** | Per-user read state. A `readers` M2M is the simple version; a through-model with `read_at` is barely more work and gives you "read 2 days ago" and read counts | ❌ `NoticeRead` (or `readers` M2M) |
| NB5 | **Category tags** | Exam / Fee / Event / Administrative / Holiday, with colour coding and filtering | ⚠️ `Notice.category` |
| NB6 | **Pinned notices** | Important announcements stick to the top regardless of date | ⚠️ `Notice.pinned` |
| NB7 | **Snippet + detail page** | Truncate to ~120 characters in the list, full text on its own page. There is no per-notice URL today — every notice is dumped in full into one list | ✅ |
| NB8 | **Attachments** | PDFs, circulars, exam schedules — what a real college notice board is mostly made of | ❌ needs `FileField` + media storage |
| NB9 | **Empty state** | "No notices yet" instead of a blank page | ✅ |

#### Phase B — Authoring (teacher/admin)

| # | Feature | Detail | Data ready? |
|---|---|---|---|
| NB10 | **Draft / publish workflow** | Write now, publish later. Students only see published notices | ⚠️ `is_draft` + `published_at` |
| NB11 | **Scheduled publishing** | Set a future `publish_at`; a periodic task (or a filter on read) makes it live | ⚠️ |
| NB12 | **Expiry** | Auto-hide after a date — a notice board that only accumulates becomes unusable | ⚠️ `expires_at` |
| NB13 | **Edit / delete** | Neither exists today. A notice, once posted, is permanent from the UI | ✅ views only |
| NB14 | **Narrower targeting** | Audience is only All / Students / Teachers. Real use needs per-class, per-department, per-semester targeting | ⚠️ |
| NB15 | **Rich text** | Bold, lists, links — a plain `TextField` renders as one undifferentiated block. Must sanitise on output; do not trust stored HTML | ⚠️ |
| NB16 | **Read receipts for the author** | "Seen by 342 of 450" — falls out of NB4 for free | ❌ (with NB4) |
| NB17 | **Email/push on publish** | Notify the target audience; reuses the SMTP setup from §5.1 | ⚠️ |

#### Phase C — Correctness & security

| # | Issue | Detail |
|---|---|---|
| NB18 | **Unvalidated POST in `add_notice`** | `request.POST['title'] / ['message'] / ['audience']` are read directly — a missing field raises `KeyError` → 500, and `audience` is never checked against `notice_audience_choice`, so an arbitrary string can be stored and the notice becomes invisible to every audience filter. Same root cause as MK25 and TA-C3: use a `ModelForm` |
| NB19 | **No length limit on message** | `TextField` with no cap; a paste-bomb becomes everyone's homepage |
| NB20 | **XSS risk once rich text lands (NB15)** | Django auto-escapes today, so this is safe **only while notices remain plain text**. The moment `|safe` or a rich-text editor is introduced without sanitisation (bleach or equivalent), any teacher account can inject script into every student's page. Worth stating explicitly in the spec so it isn't discovered the hard way |
| NB21 | **No ordering guarantee on the list** | `Notice.Meta.ordering = ['-created_at']` is set, so this one is actually fine — noted here only because the same assumption is broken in `Marks` (MK23) |
| NB22 | **Teachers can post to "All"** | Any teacher can address the entire institution, including all staff. Probably should be admin-only, or at least flagged | ✅ policy decision |

#### Recommended order

1. **NB18** — validation, alongside the forms work in the other modules
2. **NB3, NB7, NB9** — pagination, detail page, empty state: all pure view/template work
3. **NB1, NB2** — search and date filters
4. **NB5, NB6, NB10** — one migration adds `category`, `pinned`, `is_draft`, `published_at` together
5. **NB4, NB16** — read tracking and read receipts (one model, two features)
6. **NB13, NB12** — edit/delete and expiry
7. **NB15 + NB20 together** — never ship rich text without sanitisation in the same change
8. **NB8, NB17** — attachments and notifications

---

### 7.5 Notice Board Redesign

**Current state:**
- Chronological list of notices; no filter, search, or draft/publish workflow

**Proposed redesign:**

**Student view:**
```
[Search notices...] [🔔 3 unread]

┌──────────────────────────────────────┐
│ Exam schedule released              │
│ 🟢 Aug 16, 2:30 PM                  │
│ Read 40 sec ago · Mark as read ✓    │
│                                      │
│ The Semester End Exam schedule has  │
│ been released. [Read full notice →] │
└──────────────────────────────────────┘

┌──────────────────────────────────────┐
│ Library closure on Aug 19            │
│ 🟡 Aug 15, 10:00 AM                 │
│ Read 2 days ago                      │
│                                      │
│ The library will be closed on Aug   │
│ 19 for maintenance. [More...] └─────┘
```

**Features:**
- Unread badge on topbar
- Search by title/content
- Filter by date (This week / This month / All)
- Mark as read (toggle per notice)
- Category tags: "Exam", "Administrative", "Event"
- Bookmark/save for later

**Admin view:**
```
[+ New Notice]

Drafts (3)
┌──────────────────────────────┐
│ Fee payment deadline          │
│ [Edit] [Preview] [Publish]   │
│ Due date for Spring semester │
└──────────────────────────────┘

Published (15)
┌──────────────────────────────┐
│ Exam schedule released       │
│ [Edit] [Unpublish] [Delete]  │
│ Published 2 hrs ago          │
│ Readers: 342                 │
└──────────────────────────────┘
```

**New fields on Notice model:**
- `is_draft` (Boolean, default True) — only admins see drafts
- `is_published` (Boolean) — flip to publish
- `published_at` (DateTimeField, nullable)
- `pinned` (Boolean) — stick to top
- `readers` (FK to User, ManyToMany, auto-populate on "viewed")

---

### 7.6.x Fees Module — Full Feature Set (gap G1)

**Current state.** `Fee` has eight fields — `id`, `student`, `fee_type`, `description`, `amount`, `paid_amount`, `due_date`, `created_at` (verified) — plus `balance` and `status` properties. Five views: student list + Excel export, staff list with search, add, and edit (which only edits `paid_amount`).

**The central design problem:** `paid_amount` is a single running total that gets **overwritten** on every payment. There is no record of when money arrived, how much came in each time, who recorded it, or how it was paid. Everything below in Phase A follows from fixing that one thing.

**Credit where due:** unlike the teacher attendance views, the fees views *do* carry real authorization — `fees`/`fees_export` allow only the owning student or a superuser, and `t_fees`/`add_fee`/`edit_fee` require teacher or superuser. `t_fees` also already uses `select_related`, so its list is 6 queries, not N+1. This module is the best-behaved in the project; the gaps are product and validation, not access control.

#### Phase A — Payment history (the foundation)

| # | Feature | Detail | Data ready? |
|---|---|---|---|
| FE1 | **`FeeTransaction` model** | One `Fee` → many transactions: `amount`, `paid_on`, `mode`, `reference`, `received_by`, `note`, `receipt_no`. `Fee.paid_amount` becomes a derived `Sum` instead of a stored value that gets clobbered. This single change unlocks FE2–FE6 and fixes FE18 | ❌ new model |
| ~~FE2~~ | **Payment history on the student page** ✅ **Now actually done (pass 25).** FE1 landed the model in pass 10 and this was recorded as closed with it, but the student page never rendered any of it - a balance could drop with no record of when or how | "₹5,000 on 12 Aug via UPI · ₹5,000 on 3 Sep via cash" — currently impossible to display because the data was never kept | ❌ (with FE1) |
| ~~FE3~~ | **Receipts** ✅ (pass 25). Sequential receipt number, downloadable PDF | Sequential receipt number per payment, downloadable PDF with college header. `reportlab` is installed and still unused — this is its most natural use in the whole project | ❌ (with FE1) |
| FE4 | **Payment mode** | Cash / UPI / Card / Cheque / Bank transfer, plus a reference number for reconciliation | ❌ (with FE1) |
| FE5 | **Who recorded it** | `received_by` FK to `User` — accountability for cash handling, and the audit trail an interviewer will ask about | ❌ (with FE1) |
| FE6 | **Reversal / correction** | Wrong entry gets a compensating reversal transaction, never a silent edit — how financial records are actually kept | ❌ (with FE1) |

#### Phase B — Student-facing

| # | Feature | Detail | Data ready? |
|---|---|---|---|
| FE7 | **Due countdown + urgency** | "Tuition Fee ₹12,000 — due in 6 days" ramping to red once overdue. Same component as B5 on the dashboard | ✅ `due_date` |
| FE8 | **Overdue banner** | Persistent warning while anything is past due | ✅ |
| FE9 | **Fee summary by type** | Tuition / Exam / Hostel / Library totals rather than one flat list | ✅ |
| ~~FE10~~ | **Download receipt** ✅ (pass 25) | Per payment (needs FE1/FE3) | ❌ |
| FE11 | **Payment instructions panel** | Bank details, UPI QR, office hours — what a student actually needs next after seeing a balance | ⚠️ config |
| FE12 | **Online payment (mock gateway)** | A simulated Razorpay/Stripe checkout flow: order creation, callback handling, idempotent confirmation, failure paths. Clearly labelled as a demo — **no real credentials, no real money**. Payment-flow correctness (idempotency, webhook replay, partial failure) is a strong senior-level talking point | ❌ |
| FE13 | **Better Excel export** | Existing export is decent — add totals row, date of export, and the transaction history once FE1 lands | ✅ |

#### Phase C — Staff / admin

| # | Feature | Detail | Data ready? |
|---|---|---|---|
| ~~FE14~~ | **Bulk fee assignment** ✅ (pass 25). One statement for the class, and re-running the same assignment skips students who already have it rather than doubling their fees | Assign "Semester 5 Exam Fee ₹2,000" to an entire class or department in one action, rather than adding it student by student. This is the most obviously missing staff feature | ✅ views only |
| ~~FE15~~ | **Defaulters report** ✅ (pass 26). The overdue filter on the staff list, which cuts across the three status values rather than being one of them | Overdue + balance > 0, sorted by amount, filterable by class/department, exportable. Same as D3 on the admin dashboard | ✅ |
| 🟠 FE16 | **Collection dashboard** | Raised / collected / outstanding / overdue now head the staff list, and they follow the filters rather than the page. Still missing the breakdown by department and the trend over time | Collected vs. outstanding, by department, class and fee type, with a trend over time | ✅ |
| ~~FE17~~ | **Pagination + filters on `/fees/`** ✅ (pass 26). Status, fee type and class, all applied in the database - `status` and `balance` are properties, so filtering by them used to mean loading every row and looping | The staff list currently returns **every fee record in the institution** unpaginated. The query itself is efficient (6 queries thanks to `select_related`) — the problem is page size, not query count. Add pagination plus filters for status, class, fee type and date range | ✅ |
| FE18 | **Record-payment form instead of edit-total** | Today "recording a payment" means overwriting `paid_amount` with a new total, so staff must do the arithmetic themselves and any mistake is unrecoverable. Replace with "add a payment of ₹X" | ❌ (with FE1) |
| FE19 | **Waivers, scholarships, discounts** | A concession is not a payment and shouldn't be recorded as one — it needs its own type so reporting can separate "collected" from "waived" | ❌ |
| FE20 | **Installment plans** | Split a fee into scheduled instalments with their own due dates | ❌ |
| FE21 | **Late fee / penalty rules** | Auto-add a penalty after the due date, with a configurable rule | ❌ |
| FE22 | **Payment reminders** | Email N days before due and on overdue; reuses the SMTP work from §5.1 | ⚠️ |
| FE23 | **Academic year / semester tagging** | Fees currently accumulate forever with no period. Without this, "outstanding" grows across a student's whole degree and no year-wise report is possible | ⚠️ `Fee.academic_year` / `semester` |

#### Phase D — Validation & correctness (all verified by running the code)

| # | Issue | Detail |
|---|---|---|
| FE24 | **Overpayment accepted silently** | Verified: a fee of **₹10,000 accepted a `paid_amount` of ₹99,999**, producing `balance = -₹89,999` with status **"Paid"**. `edit_fee` writes `request.POST['paid_amount']` straight onto the model with no bound check, so a typo in the payments desk becomes a negative balance in the ledger |
| FE25 | **Negative amounts accepted** | Verified: `amount = -5000` saves cleanly — a fee that owes negative money. Likewise `paid_amount = -500` saved against a ₹1,000 fee gives `balance = ₹1,500`, i.e. a balance larger than the fee itself. Neither field has a `MinValueValidator`, and raw `.save()` skips validators anyway (same root cause as MK25) |
| FE26 | **Zero-amount fee is permanently "Unpaid"** | The `status` property checks `paid_amount <= 0` **before** `paid_amount >= amount`, so a fully-waived ₹0 fee reports "Unpaid" forever and can never reach "Paid". Verified. Reorder the checks and handle the zero case explicitly |
| FE27 | **No validation on `add_fee`** | `fee_type` is never checked against `fee_type_choice`, so an arbitrary string can be stored; `amount` and `due_date` are raw strings from POST, so bad input raises an unhandled exception → 500. A `ModelForm` fixes all of it — the same fix already needed in MK25, TA-C3 and NB18 |
| FE28 | **Lost update on concurrent payments** | `edit_fee` does read-modify-write on `paid_amount` with no locking. Two staff recording payments for the same student at the same time: last write wins, one payment vanishes. FE1 removes this class of bug entirely, since transactions are inserts rather than overwrites |
| FE29 | **No audit trail** | Nothing records who created a fee or who changed `paid_amount`. For money, that's the gap a reviewer will go straight to — and it's the same gap as MK19 (marks) and TA-S7 (attendance) |
| ~~FE30~~ | **Totals computed in Python** ✅ **Fixed on the staff list (pass 26)**, via `FeeQuerySet.totals()`. The per-student page still sums a handful of rows in Python, which is fine at that size | `fees()` does `sum(f.amount for f in fee_list)` over the queryset instead of `aggregate(Sum(...))`. Harmless at demo scale, wrong habit at real scale |
| FE31 | **Teacher can list fees but not open one** | `t_fees` allows teachers, but `fees(stud_id)` allows only the student or a superuser — so a teacher sees fee rows in the list and gets redirected to `/` when clicking through. Decide the policy and make the two views agree |
| FE32 | **No tests** | Balance/status logic plus the transaction sum are pure functions over model data — ideal first unit tests, including the boundaries proven broken above (overpayment, zero amount, negative values) |

#### Recommended order

1. **FE24–FE27** — validation and the status-logic bug. This is money; wrong numbers here are worse than a missing feature
2. **FE1** — introduce `FeeTransaction` and make `paid_amount` derived. This is the structural change everything else depends on, and it retires FE28 as a side effect
3. **FE18, FE2, FE5** — record-a-payment form, visible history, accountability
4. **FE3, FE10** — receipts (finally puts `reportlab` to work)
5. **FE14, FE17, FE15** — bulk assignment, pagination/filters, defaulters report
6. **FE7, FE8, FE9** — the student-facing polish
7. **FE16, FE22, FE23** — collection dashboard, reminders, year tagging
8. **FE12** — mock payment gateway, once the ledger underneath it is trustworthy
9. **FE19–FE21** — waivers, instalments, penalties

**Cross-module note:** FE1's transaction-log pattern is the same shape as the audit models needed for MK19 (marks) and TA-S7 (attendance). Design the audit/ledger approach once and reuse it across all three.

---

### 7.7.x Teacher Marks Entry Module — Full Feature Set (gap G2)

**Current state.** Five views: `t_marks_list` (which of the six test categories are entered), `t_marks_entry` (blank entry form), `marks_confirm` (the POST handler), `edit_marks` (re-open a submitted batch), `student_marks` (class roster with CIE + attendance).

This module shares the marks *data* problems already documented in §7.2.x (MK22–MK25) and the *authorization* problems already documented in §7.3.x (TA-S1, TA-S2). Listed here is what is specific to the entry flow.

#### Phase A — Entry UX

| # | Feature | Detail | Data ready? |
|---|---|---|---|
| ~~TM1~~ | **Show max marks in the form** ✅ (pass 22) | `Marks.total_marks` already knows the ceiling (20 for internals, 100 for SEE) but the entry form never shows it. Display "/20" beside each input and set `max` on the field | ✅ |
| ~~TM2~~ | **Inline validation while typing** ✅ (pass 22). Statistics are computed over valid marks only - counting an out-of-range typo gave "Average 30.5" on a test worth 20, hiding the very outlier they exist to expose | Flag out-of-range values before submit, rather than silently storing 85/20 (MK25) | ✅ |
| ~~TM3~~ | **Keyboard-first entry** ✅ (pass 22). Enter and the arrow keys move between students | Enter/↓ moves to the next student, so a teacher can type 45 marks without touching the mouse. Same rationale as TA4 in attendance | ✅ |
| ~~TM4~~ | **Live progress + statistics** ✅ (pass 22) | "38 of 45 entered · avg 14.2 · range 6–20" while typing, so an outlier is caught at entry time | ✅ |
| ~~TM5~~ | **Absent / not-appeared marker** ✅ (pass 23). `Marks.is_absent`. An absentee still scores zero towards the CIE - that is how the scheme works - but the record and both pages say which of the two it was | A student who missed the test is not a student who scored 0. Needs a distinct state, exactly like MK4 on the student side | ⚠️ needs a flag on `Marks` |
| TM6 | **Save draft** | Marks entry for a large class is currently all-or-nothing in one POST. Allow partial saves | ⚠️ |
| TM7 | **Bulk import from Excel** | Upload a marks sheet; `openpyxl` already in use for fees export | ✅ |
| ~~TM8~~ | **Unsaved-changes guard** ✅ (pass 22) | Warn before navigating away mid-entry | ✅ |
| ~~TM9~~ | **Sort roster by USN or name** ✅ (pass 22) | Fixed order today; teachers often work from a printed list in a different order | ✅ |
| ~~TM10~~ | **Show previous test's marks alongside** ✅ (pass 22) | Context while entering Internal 2 — helps spot a transposed row immediately | ✅ |

#### Phase B — Post-entry

| # | Feature | Detail | Data ready? |
|---|---|---|---|
| ~~TM11~~ | **Class statistics after submit** ✅ (pass 27). Average, median, range, headcount marked | Average, median, pass count, distribution — `student_marks` shows CIE and attendance per student but no aggregate at all | ✅ |
| ~~TM12~~ | **Marks distribution histogram** ✅ (pass 27), in CIE bands | Tells the teacher whether the paper was too hard or too easy (same as C6) | ✅ |
| ~~TM13~~ | **Highlight at-risk students** ✅ (pass 27), on the same low-marks-*and*-low-attendance rule the class report uses | Low CIE + low attendance together — `StudentCourse` already exposes `get_cie()` and `get_attendance()` side by side | ✅ |
| TM14 | **Export marks sheet** | Excel/PDF for department records | ✅ |
| ~~TM15~~ | **Publication control** ✅ (pass 23). Publish / withdraw from the batch list, both audit-logged | Enter now, release to students later (MK20) | ⚠️ `MarksClass.is_published` |
| TM16 | **Re-evaluation queue** | Teacher-side view of student disputes (MK18) | ❌ |

#### Phase C — Correctness & security (verified against the running app)

| # | Issue | Detail |
|---|---|---|
| TM17 | **All four entry endpoints open to students** | Verified, logged in as the `teststud` student account: `t_marks_list`, `student_marks`, `t_marks_entry` and `edit_marks` all returned **HTTP 200**. So a student can read the whole class's marks and open the marks-entry form. The POST handler `marks_confirm` carries the identical `@login_required()`-only guard, which means **a student can submit marks for an entire class**. Same root cause and same fix as TA-S1/TA-S2 — a `@teacher_required` decorator plus an ownership assertion. Do all of these in one pass |
| ~~TM18~~ | **`student_marks` returns 500 instead of 404** ✅ **Fixed (pass 27).** Recorded as a one-line fix in the module's recommended order and then not done for twenty-three passes | Verified: `Assign.objects.get(id=assign_id)` with an unknown id raises an uncaught `Assign.DoesNotExist` and the request 500s. Every neighbouring view uses `get_object_or_404`; this one doesn't. One-line fix |
| ~~TM19~~ | **Unguarded `StudentCourse.objects.get()` in both `marks_confirm` and `edit_marks`** ✅ **Now fully fixed.** `marks_confirm` was covered in pass 4, but `edit_marks` kept its bare `StudentCourse.objects.get()` *and* `marks_set.get()` until pass 22 - either one raising DoesNotExist took the page down for the whole class. Both are gone; the view now loads existing marks in one query and tolerates rows that are missing | Neither wraps the lookup in `try/except`, so any student missing a `StudentCourse` row 500s the entire batch — the same crash path as G3 (`t_report`). Note this is *also* the branch that MK22's `type='I'` bug lives in, so the "self-healing" fallback in `marks_list` would itself crash. Two independent faults on the same path |
| TM20 | **No transaction around `marks_confirm`** | The view loops over students saving one `Marks` row at a time, then flips `mc.status = True`. A `KeyError` from `request.POST[s.USN]` partway through leaves half the class saved. Unlike the attendance equivalent (TA-C2), the status flag *is* correctly set after the loop — so a partial failure leaves marks saved but the batch still flagged unsubmitted, which is the safer of the two failure modes but still wrong. Wrap in `@transaction.atomic` |
| TM21 | **No validation of the submitted value** | `m.marks1 = request.POST[s.USN]` assigns a raw string with no bounds check — this is MK25, restated here because this is the view that does it. `ModelForm`/formset with `clean()` bounded by `total_marks` |
| TM22 | **No audit trail on overwrite** | `edit_marks` → `marks_confirm` overwrites `marks1` in place; the previous value, the editor, and the timestamp are all lost (MK19). For grades this is the gap most worth closing |
| TM23 | **N+1 across the flow — measured** | `student_marks` 9 queries for a **one-student** class; `edit_marks` 11; `t_marks_list` 5. Each does per-student `StudentCourse.objects.get()` + `marks_set.get()`, so a 45-student class runs roughly **90–100 queries** per page. Not as severe as the attendance pages (TA-C5, ~900) but the same fix applies: one query with `select_related`/`prefetch_related` |
| TM24 | **No confirmation summary before commit** | The flow is named `marks_confirm` but nothing is actually confirmed — the POST writes immediately. Show a review screen (or at minimum a summary of what will change when editing an existing batch) |

#### Recommended order

1. **TM17** — authorization. A student being able to submit their own class's marks is the most serious defect in this module, and the fix is shared with §7.3
2. **TM18, TM19** — two crash paths, both one-line fixes
3. **TM20, TM21** — transaction and validation (`ModelForm`), shared with FE27/NB18/TA-C3
4. **TM22** — audit trail on grade changes
5. **TM1, TM2, TM3, TM4** — the entry UX that makes the page pleasant to use daily
6. **TM23** — N+1, while the queries are being rewritten
7. **TM11, TM12, TM13** — post-entry statistics
8. **TM5, TM15, TM7** — absent marker, publication control, bulk import

---

### 7.8.x Class Report & Free-Teacher Finder (gaps G3, G4)

Two small pages, grouped because each is a single view with a handful of real defects — the quickest wins in the backlog.

---

#### 7.8.1 Class Report — `t_report` (G3)

**Current state.** One view, one table: every student in a class with their CIE (`get_cie()`) and attendance (`get_attendance()`). It's the closest thing the project has to a consolidated academic record, and it's also one of the most fragile pages.

**Features**

| # | Feature | Detail | Data ready? |
|---|---|---|---|
| ~~RP1~~ | **Class summary header** ✅ (pass 20) | Class average CIE, average attendance, pass/fail counts, headcount — the page shows per-student rows but no aggregate at all | ✅ |
| ~~RP2~~ | **At-risk highlighting** ✅ (pass 20). Fires on the combination, and deliberately *does* fire on an incomplete CIE - it is an early warning, unlike the per-student standing, which withholds a verdict until every component is in | Flag rows where CIE is low **and** attendance is under 75% — the combination is the real signal, and both values are already on the row | ✅ |
| ~~RP3~~ | **Sort & filter** ✅ (pass 20). Numeric sorts run lowest-first: the point of sorting a class report is to bring the students in trouble to the top | By CIE, by attendance, by name; filter to at-risk only | ✅ |
| ~~RP4~~ | **Export to Excel** ✅ (pass 20), reusing the fees export pattern. PDF still open | Department records genuinely need this; reuse the fees export pattern | ✅ |
| RP5 | **Per-component breakdown** | Show the internals behind the CIE, not just the total | ✅ |
| RP6 | **SEE eligibility column** | Whether each student meets the CIE cut-off to sit the final (pairs with MK7) | ✅ |
| RP7 | **Comparison across sections** | Same course in CS5A vs CS5B | ✅ |
| ~~RP8~~ | **Print stylesheet** ✅ (pass 20). Row tints and badges carry print-color-adjust, or the at-risk marking vanishes on paper | This is a page people actually print | ✅ |

**Defects (verified)**

| # | Issue | Detail |
|---|---|---|
| RP9 | **Open to students** | Verified: the `teststud` student account gets **HTTP 200** on `/teacher/<id>/Report/` — so any student can read the whole class's marks and attendance. Same fix as TA-S1/TM17 |
| RP10 | **Uncaught `DoesNotExist` → 500** | Verified by deleting one `StudentCourse` row: the page raised an **uncaught `StudentCourse.DoesNotExist`** and 500'd (row restored afterwards). The loop does a bare `StudentCourse.objects.get(...)` per student with no `try/except`, unlike `marks_list` which guards it. Any student missing that row takes down the report for the entire class |
| RP11 | **N+1 — measured at 26 queries for one student** | The row template pulls `get_cie()` (which walks `marks_set`) and `get_attendance()` (which runs the expensive `AttendanceTotal` property chain from AT26). A 45-student class is on the order of **1,000 queries**. Fixing AT26/AT27 fixes most of this page too |
| RP12 | **No pagination** | ⚪ **Deliberately skipped (pass 20).** A class is bounded at roughly sixty students, unlike the institution-wide fee list that FE17 paginates - and paginating would work against the export and print stylesheet added alongside, both of which exist to hand over the whole class at once |

---

#### 7.8.2 Free-Teacher Finder — `free_teachers` (G4)

**Current state.** Given an `AssignTime` slot, list teachers who are free in that day+period. Useful for arranging a substitute — but currently unreachable from anywhere in the UI except a deep link, and the logic doesn't do quite what the page title claims.

**Features**

| # | Feature | Detail | Data ready? |
|---|---|---|---|
| FT1 | **Surface it in the UI** | The view exists and works but nothing links to it prominently. It belongs next to "cancel class" and on the teacher dashboard (C7) | ✅ |
| FT2 | **Widen the search scope** | See FT7 — today it only considers teachers already assigned to *this class*, which is not what "free teachers" means | ✅ |
| FT3 | **Show why each teacher is free** | "Free — no class scheduled" vs "Free — class cancelled today" | ✅ |
| FT4 | **Filter by department** | A substitute usually needs to be from the same department | ✅ |
| FT5 | **Show current teaching load** | Prefer the teacher with the lightest week, rather than the first name in the list | ✅ |
| FT6 | **Request-a-substitute action** | Turn the list into an action: notify the chosen teacher and record the arrangement (pairs with TA21) | ❌ |

**Defects**

| # | Issue | Detail |
|---|---|---|
| ~~FT7~~ | ~~**The page doesn't find "free teachers"**~~ | ✅ **Fixed (pass 17).** `Teacher.objects.filter(assign__class_id__id=...)` restricted the candidate pool to teachers **already teaching this class**, so the page answered a much narrower question than its title and could never find an outside substitute. The pool is now every teacher in the college, minus those the timetable shows as busy in that day+period |
| ~~FT8~~ | ~~**Duplicate rows — no `.distinct()`**~~ | ✅ **Fixed (pass 17).** Filtering `Teacher` across the `assign` join returned one row per matching `Assign`, so a teacher taking two courses for the same class appeared twice. The query is now an `exclude()` against collected teacher ids, so there is no join to fan out — `.distinct()` is unnecessary rather than merely added. Covered by a test |
| ~~FT9~~ | ~~**N+1 in the availability check**~~ | ✅ **Fixed (pass 17).** The loop ran `AssignTime.objects.filter(assign__teacher=t)` per candidate and compared day/period **in Python**. Availability is now two queries regardless of headcount; a test adds ten teachers and asserts the count is unchanged |
| ~~FT10~~ | ~~**Cancelled classes ignored**~~ | ✅ **Fixed (pass 17).** A teacher whose session was cancelled (`AttendanceClass.status == 2`) counted as busy because availability came from the static timetable only. A slot is a recurring weekday and a cancellation belongs to one date, so `_next_weekday()` resolves the slot to its coming date and cancellations on that date free their teacher |
| ~~FT11~~ | ~~**No authorization check**~~ | ✅ Fixed in pass 3 — `@teacher_required` |

**Recommended order for both pages**

1. ~~**RP10, RP9**~~ — ✅ done, passes 3 and 8
2. ~~**FT7, FT8**~~ — ✅ done, pass 17
3. ~~**RP11, FT9**~~ — ✅ done (RP11 fell out of the AT26/AT27 fix; FT9 in pass 17)
4. **RP1, RP2, RP4** — summary header, at-risk highlighting, export ← **next here**
5. **FT1, FT4, FT5** — surface the finder and make its output useful. The page is
   still reachable only from a cell in the teacher timetable, and now that the
   pool is college-wide, a department filter (FT4) and teaching load (FT5) are
   what make a long list decidable
6. ~~**FT10**~~ — ✅ done, pass 17. **FT6** (substitute-request workflow) still open

---

### 7.9.x Account Lifecycle — Add Student / Add Teacher / Self-Service (gaps G5, G10)

Covers `add_student`, `add_teacher`, and the profile/self-service pages that don't exist yet.

#### 🔴 The headline bug: adding a duplicate USN silently overwrites an existing student

`Student.USN` and `Teacher.id` are both **primary keys**. When a model instance is saved with its primary key already set, Django attempts an `UPDATE` before falling back to `INSERT`. So:

```python
Student(user=user, USN=usn, class_id=..., name=..., sex=..., DOB=...).save()
```

If `usn` already belongs to an existing student, this does **not** raise `IntegrityError` — it **overwrites that student's record in place**: name, class, sex, date of birth, and the `user` foreign key all get replaced. The consequences:

- The original student's record is destroyed, with no error and no warning — the admin sees a success redirect
- Their account link is reassigned to the newly created `User`, so **they are locked out of their own account**
- Their old `User` row is left orphaned
- `Student.user` is `on_delete=CASCADE`, so if anyone later deletes that orphaned `User`, the student record, plus their `StudentCourse`, `Marks` and `Fee` rows, are all cascade-deleted

**This was observed directly, not theorised** — it was triggered accidentally while probing the failure path of `add_student` on the dev database, which destroyed the test student's record and its dependent rows (since restored). `add_teacher` has the identical shape via `Teacher.id`.

**Fix:** use `Student.objects.create(...)`, or check `Student.objects.filter(USN=usn).exists()` first and reject the submission with a form error, or set `force_insert=True`. A `ModelForm` with a `unique` check on the primary key handles it properly.

#### Phase A — Fixing account creation

| # | Issue | Detail |
|---|---|---|
| AC1 | **Duplicate PK silently overwrites** | As above. The single most destructive defect found in the project |
| AC2 | **No transaction around the two saves** | `User.objects.create_user()` runs, then `Student(...).save()`. If the second fails, the `User` row persists as an orphan — an account that can log in, has a working password, matches no role, and lands on the logout template. Retrying the same form then fails on the duplicate username. Wrap both in `@transaction.atomic` |
| AC3 | **Username collisions unhandled** | The username is `firstname + '_' + USN[-3:]` for students and `firstname + '_' + id` for teachers. Two students named Rahul whose USNs end in the same three digits collide → `IntegrityError` → 500 (and, thanks to AC2, an orphaned `User`). In any real intake this is a matter of when, not if |
| AC4 | **No email is collected — this blocks §5.1 entirely** | `create_user()` is called with only `username` and `password`. Verified on the dev database: **2 of 3 accounts have an empty email**, and neither student nor teacher creation ever asks for one. The OTP password-reset flow in §5.1, the fee reminders in FE22, and the notice notifications in NB17 all have nowhere to send mail. **Collecting an email address is a prerequisite for those features, not an optional extra** |
| AC5 | **Fragile name parsing** | `name.split(" ")[0]` breaks on a single-word name, a leading space, or an empty string — the last of which produces a username like `_001` |
| AC6 | **Date parsing assumes ISO format** | `dob.replace("-","")[:4]` relies on the browser sending `YYYY-MM-DD`. Correct for `<input type="date">`, but silently produces a nonsense password for any other input path |
| AC7 | **No validation anywhere** | Raw `request.POST[...]` throughout — missing field → `KeyError` → 500. Same root cause as MK25, TA-C3, NB18, FE27. `ModelForm` is the shared fix |
| AC8 | **No bulk import** | Adding a 60-student intake means 60 manual form submissions. `openpyxl`/`pandas` are already dependencies (Tier 1 #8) |

#### Phase B — Credential security

| # | Issue | Detail |
|---|---|---|
| AC9 | **Both halves of the credential are derived from public data** | Username = first name + last 3 digits of USN. Password = first name + birth year. Every input is printed on a college ID card. Anyone who knows a classmate's name, USN and birth year can log in as them — no brute force required. Verified against the dev record: `Test Student`, USN `1CS20CS001`, DOB `2000-01-01` yields username `test_001`, password `test_2000` |
| AC10 | **No forced password change on first login** | The generated password is permanent unless an admin intervenes. Fix: a `must_change_password` flag set at creation, and middleware that redirects to the change-password page until it's cleared |
| AC11 | **Password is never shown to the admin** | The admin creating the account has no way to see or print the generated credential to hand over — they'd have to re-derive it from the documented formula. Show it once, at creation, then never again |
| AC12 | **No password strength enforcement on the generated value** | `create_user` bypasses `AUTH_PASSWORD_VALIDATORS`, so `test_2000` is accepted even though it would fail Django's own similarity/common-password checks if entered through a form |
| AC13 | **`DetailSerializer` exposes every Student field** | `fields = '__all__'` on the student API serializer returns `DOB` and everything else. Combined with a birth-year-derived password scheme, that is exactly the wrong field to expose. Use an explicit field list |

#### Phase C — Self-service (G10 — none of this exists today)

| # | Feature | Detail | Data ready? |
|---|---|---|---|
| AC14 | **Change password** | Django's `PasswordChangeView` is built in and unused. The single most conspicuous omission — currently no user can ever change their own password | ✅ |
| AC15 | **Profile page** | View own details; edit contact fields (phone, address, email) while keeping USN/class admin-only | ⚠️ needs contact fields |
| AC16 | **Profile photo upload** | Also feeds TA6 (photos on the attendance roster) | ❌ `ImageField` + media config |
| AC17 | **Email address management** | Add/verify an email — the prerequisite for AC4 on existing accounts | ⚠️ |
| AC18 | **Session management** | "Signed in on 2 devices", with the ability to sign out elsewhere | ✅ |
| AC19 | **Login history** | Last login time and location — a cheap, credible security feature | ⚠️ |

#### Phase D — Admin-side improvements

| # | Feature | Detail | Data ready? |
|---|---|---|---|
| AC20 | **Student/teacher directory with search** | There is a commented-out `student_search` URL in `info/urls.py` and no directory page anywhere (gap G11). Search by name, USN, class, department | ✅ |
| AC21 | **Edit / deactivate an account** | Neither exists. Records can only be created, never corrected — except via Django admin, and except via the accidental-overwrite path in AC1 |
| AC22 | **Soft delete / alumni status** | Deleting a `User` cascades away the student, their marks, attendance and fees. Graduating students need deactivation, not deletion |
| AC23 | **Bulk credential export** | Generate a printable slip per student for distributing initial logins (pairs with AC10/AC11) |
| AC24 | **Audit log on account changes** | Who created or modified an account, and when — the same audit pattern as FE29/MK19/TA-S7 |

#### Recommended order

1. **AC1** — the silent-overwrite bug. Data loss with no error message outranks everything else in this document
2. **AC2, AC3** — transaction and username collisions (AC2 also prevents the orphan accounts that AC3 currently creates)
3. **AC4** — collect an email address. §5.1's OTP flow, FE22 and NB17 are all blocked until this exists
4. **AC9, AC10, AC11** — stop deriving passwords from public data; force a change on first login; show the credential once at creation
5. **AC14** — change-password page (Django provides it; this is mostly wiring)
6. **AC7** — `ModelForm` validation, shared with every other module
7. **AC13** — tighten the API serializer
8. **AC8, AC20, AC21, AC22** — bulk import, directory, edit/deactivate, soft delete

---

### 7.10.x REST API (gap G7)

**Current state.** Four read-only, student-only endpoints in the `apis` app: `/api/details/`, `/api/attendance/`, `/api/marks/`, `/api/timetable/`. DRF is configured with `IsAuthenticated` plus Token and Session authentication. djoser is wired at `/info/api/auth/`.

#### 🔴 The API does not work as shipped

Verified by calling all four endpoints:

| Auth method | Result |
|---|---|
| Logged-in **session** user (a real student) | **HTTP 400 — `{"message": "User not authenticated"}` on all four endpoints** |
| Explicit **token** in the `Authorization` header | HTTP 200, data returned |
| No authentication at all | HTTP 401 (correct) |

The cause: every view hand-rolls its own auth check on top of DRF's:

```python
us = Token.objects.filter(user=request.user)
if us:
    user = User.objects.filter(auth_token=us[0]).first()
    ...
else:
    return Response({'message': 'User not authenticated'}, status=400)
```

DRF has **already authenticated the request** by the time the view runs — `request.user` is populated. Re-deriving the user from a `Token` row means any correctly authenticated session user without a token row is rejected. And because **nothing in the application ever issues a token** (verified: 0 rows in the token table), the API returns 400 for every user until someone creates a token by hand in the shell or Django admin. As shipped, all four endpoints are unreachable.

**Fix:** delete the token lookup entirely and use `request.user.student`. That one change fixes the auth bug, removes 3 queries per request, and deletes most of the body of each view.

#### Phase A — Correctness

| # | Issue | Detail |
|---|---|---|
| API1 | **Hand-rolled auth rejects valid sessions** | As above. `permission_classes = [IsAuthenticated]` is already doing the job |
| API2 | **`/api/attendance/` returns no attendance data** | Verified response: `{"user_attendance": [{"id": 2, "course": "CS101", "student": "1CS20CS001"}]}`. `AttendanceSerializer` uses `fields = '__all__'` on `AttendanceTotal`, but every useful value — `attendance`, `att_class`, `total_class`, `classes_to_attend` — is a **Python property**, not a model field, so DRF omits them all. The endpoint returns identifiers and nothing else. Fix: declare them as `SerializerMethodField`s or explicit read-only fields |
| API3 | **`/api/timetable/` returns its data under the key `user_marks`** | Verified: `{"user_marks": []}` from the timetable endpoint. Copy-paste from `MarksView`. Any client written against this has to read timetable data out of a field called `user_marks` |
| API4 | **A GET endpoint writes to the database** | `AttendanceView` creates missing `AttendanceTotal` rows inside a GET handler. A read request should not mutate state — it breaks caching assumptions and makes the endpoint non-idempotent |
| API5 | **Raw exception text returned to clients** | Every view ends with `except Exception as e: return Response(str(e), status=400)`, so internal errors — including database messages — are handed to the caller. Also flattens genuine 404/500 conditions into 400 |
| API6 | **Wrong status codes** | "Not authenticated" returns **400**; it should be 401. A missing student profile should be 404, not 400 |
| API7 | **Same unguarded `StudentCourse.objects.get()`** | `MarksView` repeats the crash path from TM19/RP10 — a missing row raises, and is then swallowed by API5 into an opaque 400 |
| API8 | **`fields = '__all__'` leaks personal data** | `/api/details/` returns `DOB` (verified). Given that passwords are derived from the birth year (AC9), this is precisely the field that should not be exposed. Same issue as AC13 |
| API9 | **Dead imports** | `chain`, `mixins`, `generics`, `PageNumberPagination`, `post_save`, `get_object_or_404`, `Sum`, `Count`, `settings`, `render` are all imported and unused. `PageNumberPagination` in particular signals pagination that was never implemented |
| API10 | **Wildcard import** | `from info.models import *` (noted in §3) |
| API11 | **No pagination** | Every endpoint returns a complete list |
| API12 | **No tests** | Zero coverage — and the endpoints are pure request/response functions, the easiest thing in the project to test |

#### Phase B — What the API should become

The strategic question is **expand or remove**. Recommendation: **expand, but deliberately** — a documented API is a strong portfolio item, and a half-built one is a liability.

| # | Feature | Detail |
|---|---|---|
| API13 | **OpenAPI/Swagger docs** | `drf-spectacular` gives a live, browsable schema (Tier 1 #7). This is what makes an API demonstrable in an interview rather than something you have to describe |
| API14 | **Teacher and admin endpoints** | Currently student-only. Attendance marking, marks entry, class lists — the same authorization model as the web views (TA-S1/TA-S2) applies |
| API15 | **Write endpoints** | POST attendance, PATCH marks — with the same validation layer as the forms work |
| API16 | **Proper token lifecycle** | Nothing issues tokens today. Either expose a login endpoint that returns one (djoser is already installed for exactly this) or move to JWT with refresh |
| API17 | **Consistent envelope** | Responses currently vary: `{"data": ...}`, `{"user_attendance": ...}`, `{"user_marks": ...}` — including on the timetable endpoint. Pick one shape |
| API18 | **Rate limiting** | DRF throttling, especially once write endpoints exist |
| API19 | **Versioning** | `/api/v1/` before anything consumes it |
| API20 | **Filtering & pagination** | Date ranges on attendance, course filters on marks |

#### Recommended order

1. **API1** — the auth bug. Nothing else matters while every endpoint returns 400
2. **API2, API3** — the attendance endpoint returning no data, and the timetable key. Both are "this API has clearly never been called" bugs
3. **API5, API6, API7** — error handling and status codes
4. **API8, API10, API9** — serializer field lists, wildcard import, dead imports
5. **API13** — Swagger docs, which immediately makes the rest demonstrable
6. **API16** — token issuance, so the API is reachable without shell access
7. **API12** — tests
8. **API14, API15, API17–API20** — expansion, only once the base is sound

---

### 7.11.x Remaining Small Gaps (G6, G8, G9, G12)

#### 7.11.1 Class & session navigation — `t_clas` (G6)

| # | Issue / feature | Detail |
|---|---|---|
| CS1 | **Magic-number `choice` parameter** | `/teacher/<id>/<choice>/Classes/` uses a bare integer to decide context: `1` = attendance, `2` = marks, `3` = reports. Unlabelled, undocumented, and validated nowhere — `/teacher/1/7/Classes/` renders a page with no meaningful mode. Use named URLs (`/classes/attendance/`) or a slug |
| CS2 | **No authorization** | Same `@login_required()`-only pattern; a teacher can view any other teacher's class list by changing the ID |
| CS3 | **No class context** | The list shows classes but not student counts, pending attendance, or pending marks — all of which are one query away and would turn it into a useful landing page (pairs with TA11/C1) |

#### 7.11.2 Django admin (G8)

The admin is currently the **only** way to manage `Dept`, `Course`, `Class`, `Assign`, `AssignTime` and `AttendanceRange` — i.e. all of the setup data that the rest of the app depends on.

| # | Feature | Detail |
|---|---|---|
| AD1 | **Clash validation on `Assign`/`AssignTime`** | The uniqueness constraint from TT12 should be enforced here, with a friendly admin error rather than a 500 on the student timetable |
| AD2 | **Inlines** | Edit `AssignTime` rows inline on `Assign`; `Marks` inline on `StudentCourse` |
| AD3 | **List filters and search** | On department, class, semester — the model registrations are currently minimal |
| AD4 | **Guard the `AttendanceRange` reset** | Changing the semester date range triggers attendance regeneration through the signals. That's a destructive operation reachable from a plain admin form with no warning |
| AD5 | **Read-only audit fields** | Once audit models exist (FE29/MK19/TA-S7), surface them read-only |
| AD6 | **Restrict staff access** | Any `is_staff` user reaches the full admin; scope it with permissions |

#### 7.11.3 Error pages (G9)

| # | Feature | Detail |
|---|---|---|
| ER1 | **Custom 404 / 500 / 403 templates** | With `DEBUG=False` in production (which is the case on Render), users currently get Django's bare default pages. Given how many 500s this document has catalogued, these will be seen |
| ER2 | **Error logging** | No logging configuration at all — production 500s vanish silently. Add `LOGGING` with a console handler at minimum; Sentry if you want the polished version |
| ER3 | **Friendly permission-denied page** | Every unauthorized access currently `redirect('/')` with no explanation, so a legitimate user hitting a page they can't access just bounces to the dashboard with no idea why |

#### 7.11.4 Logout page (G12)

| # | Feature | Detail |
|---|---|---|
| LO1 | **Styling** | The one screen still on the old unstyled template — it doesn't use the login page's design language |
| LO2 | **`index` falls through to `logout.html`** | In `index()`, a user who is neither student, teacher nor superuser renders the logout template. That's the orphan-account case from AC2, and the result is a confusing dead end rather than an explanatory message |
| LO3 | **Logout should be POST** | `/accounts/logout` as a GET link is CSRF-triggerable; Django 4.1+ prefers POST, and Django 5 requires it |

---

## 8. Coverage Audit — what still has no spec

Every view in `info/views.py` (33 total), checked against what this document actually specs out.

### ✅ Specced in detail

| Module | Views covered | Section |
|---|---|---|
| Login / auth | `login`, `logout` | §5, §5.1, §5.2 |
| Dashboards | `index` (all three roles) | §6, §6.5 |
| Attendance — student | `attendance`, `attendance_detail` | §7.1.x (AT1–AT30) |
| Marks — student | `marks_list` | §7.2.x (MK1–MK27) |
| Attendance — teacher | `t_student`, `t_class_date`, `t_attendance`, `confirm`, `edit_att`, `change_att`, `cancel_class`, `t_attendance_detail`, `t_extra_class`, `e_confirm` | §7.3.x (TA1–TA21) |
| Timetable | `timetable`, `t_timetable` | §7.4.x (TT1–TT16) |
| Notice board | `notices`, `add_notice` | §7.5.x (NB1–NB22) |
| Fees | `fees`, `fees_export`, `t_fees`, `add_fee`, `edit_fee` | §7.6.x (FE1–FE32) |
| Marks entry — teacher | `t_marks_list`, `t_marks_entry`, `marks_confirm`, `edit_marks`, `student_marks` | §7.7.x (TM1–TM24) |
| Class report | `t_report` | §7.8.1 (RP1–RP12) |
| Free-teacher finder | `free_teachers` | §7.8.2 (FT1–FT11) |
| Account lifecycle | `add_student`, `add_teacher`, + self-service (new) | §7.9.x (AC1–AC24) |
| REST API | `apis/` — 4 endpoints | §7.10.x (API1–API20) |
| Class navigation, admin, error pages, logout | `t_clas`, `/admin/`, 404/500, `logout` | §7.11.x (CS/AD/ER/LO) |

### ❌ Not yet specced — remaining gaps

| # | Module | Views | Why it matters |
|---|---|---|---|
| ~~G1~~ | ~~Fees~~ | — | ✅ **Now specced — see §7.6.x (FE1–FE32)** |
| ~~G2~~ | ~~Marks entry — teacher side~~ | — | ✅ **Now specced — see §7.7.x (TM1–TM24)** |
| ~~G3~~ | ~~Class report~~ | — | ✅ **Now specced — see §7.8.1 (RP1–RP12)** |
| ~~G4~~ | ~~Free-teacher finder~~ | — | ✅ **Now specced — see §7.8.2 (FT1–FT11)** |
| ~~G5~~ | ~~Add student / add teacher~~ | — | ✅ **Now specced — see §7.9.x (AC1–AC24)** |
| ~~G6~~ | ~~Class & session management~~ | — | ✅ **Now specced — see §7.11.1 (CS1–CS3) — scheduling parts in §7.3.x TA18–TA21** |
| ~~G7~~ | ~~REST API~~ | — | ✅ **Now specced — see §7.10.x (API1–API20)** |
| ~~G8~~ | ~~Django admin~~ | — | ✅ **Now specced — see §7.11.2 (AD1–AD6)** |
| ~~G9~~ | ~~Error pages~~ | — | ✅ **Now specced — see §7.11.3 (ER1–ER3)** |
| ~~G10~~ | ~~Profile / self-service~~ | — | ✅ **Now specced — see §7.9.x, Phase C** |
| ~~G11~~ | ~~Student directory / search~~ | — | ✅ **Now specced — see §7.9.x, AC20** |
| ~~G12~~ | ~~Logout~~ | — | ✅ **Now specced — see §7.11.4 (LO1–LO3)** |

### Suggested order for filling the gaps

1. ~~G1 (Fees)~~ — ✅ done, §7.6.x
2. ~~G2 (Teacher marks entry)~~ — ✅ done, §7.7.x
3. ~~G3, G4~~ — ✅ done, §7.8.x
4. ~~G5, G10, G11~~ — ✅ done, §7.9.x
5. ~~G7 (API)~~ — ✅ done, §7.10.x (recommendation: **expand deliberately**, don't remove)
6. ~~G6, G8, G9, G12~~ — ✅ done, §7.11.x

**All 12 gaps are now specced.** The document covers every view in the project.

---

## 9. Cross-Cutting Concerns — not tied to any page

§5–§7 cover every view in the project. This section covers what's left: model-layer, configuration, and project-infrastructure issues that don't belong to a single page and therefore never came up in the page-by-page pass.

### 9.1 Model layer

| # | Issue | Detail |
|---|---|---|
| MD1 | **A fresh deployment breaks on the first timetable entry** | The `create_attendance` signal opens with `AttendanceRange.objects.all()[:1].get()`. Verified: with no `AttendanceRange` row, saving an `AssignTime` raises **`AttendanceRange.DoesNotExist`**. A newly-deployed instance has an empty database and no such row, so the very first setup step an admin performs — adding a timetable slot — fails with an error that names a model they've never heard of. Needs either a data migration seeding a default range, a guard in the signal, or a documented setup order |
| ~~MD2~~ | **`BooleanField` defaults are strings** ✅ **Fixed (pass 23).** Both are real booleans now | `Attendance.status = BooleanField(default='True')` and `MarksClass.status = BooleanField(default='False')`. Verified round-trip: the value **is** stored and read back correctly as a real boolean, so this is not data corruption. But an unsaved instance holds the literal string — `bool('False') is True` — so `if mc.status:` on a fresh, unsaved object returns the opposite of what's intended. A latent trap rather than an active bug; fix the defaults to `True`/`False` |
| MD3 | **Stale hardcoded defaults** | `Attendance.date` defaults to `'2018-10-23'`, `Student.DOB` to `'1998-01-01'`, `Teacher.DOB` to `'1980-01-01'`. Any record created without an explicit value silently gets 2018 data. Dates should have no default, or use `timezone.now` |
| MD4 | **`Student.class_id` defaults to `1`** | A default foreign key to whatever `Class` has primary key `1` — and `Class.id` is a `CharField`, so `1` is unlikely to exist at all. Remove the default |
| MD5 | **Signals create rows one at a time** | `create_marks` issues six `marks_set.create()` calls per student per course; `create_attendance` loops every date in the semester calling `.get()` then `.save()`. Adding one `Assign` to a 60-student class triggers hundreds of individual inserts. Use `bulk_create` |
| MD6 | **`on_delete=CASCADE` everywhere** | Deleting a `User` destroys the linked `Student`, and with it their `StudentCourse`, `Marks`, `Attendance` and `Fee` rows. **This was observed directly during the audit** — a cascade from a single user deletion removed a student's entire academic record. Academic and financial history should use `PROTECT` or soft deletion (AC22) |
| MD7 | **No `updated_at` on any model** | Only `Fee` and `Notice` carry `created_at`. Nothing records when a record last changed — which is half of what the audit trails in FE29/MK19/TA-S7 need |
| MD8 | **`CharField` primary keys on `Dept`, `Course`, `Class`** | Same class of hazard as AC1. Django admin uses a `ModelForm` and validates uniqueness, so the admin path is safe — but any programmatic creation carries the same silent-overwrite risk |

### 9.2 Configuration

| # | Issue | Detail |
|---|---|---|
| CF1 | **Media files are not configured** | `MEDIA_ROOT` is `''` and `MEDIA_URL` is `'/'` (verified). Profile photos (AC16) and notice attachments (NB8) have nowhere to go. **And Render's filesystem is ephemeral**, so even once configured, uploads vanish on every redeploy — this needs S3, Cloudinary or similar, not just a settings change. Worth knowing before promising either feature |
| CF2 | **No logging configuration** | `LOGGING` is empty (verified). With `DEBUG=False` in production, unhandled exceptions produce a 500 page and **no record anywhere**. Given how many 500 paths this document catalogues, this should be near the top of the list. Console handler at minimum |
| CF3 | **Email backend points at a non-existent SMTP server** | `EMAIL_BACKEND` is the SMTP backend with no host configured, and `DEFAULT_FROM_EMAIL` is still `webmaster@localhost` (verified). Every mail-dependent feature — OTP (§5.1), fee reminders (FE22), notice notifications (NB17) — will fail at send time. Use the console backend in development and configure real SMTP via environment variables for production |
| CF4 | **`TIME_ZONE` is UTC** | `USE_TZ=True` with `TIME_ZONE='UTC'` (verified). For a college in India this means attendance dates, session times and fee due dates all display in UTC — a 7:30 AM class straddles a date boundary. Set `Asia/Kolkata` |
| CF5 | **`DEFAULT_AUTO_FIELD` is `AutoField`** | 32-bit integer primary keys. Django's current default is `BigAutoField`; not urgent at this scale, but it's a one-line change that avoids a painful migration later |
| CF6 | **`LocMemCache`** | Per-process, in-memory cache. It works, but it isn't shared across gunicorn workers, so the dashboard caching in E2 would behave inconsistently. Redis when caching actually matters |

### 9.3 Project infrastructure — none of this exists

Verified absent from the repository: `.github/`, `Dockerfile`, `docker-compose.yml`, `README.md`, `pytest.ini`, `pyproject.toml`, `.pre-commit-config.yaml`, and any `tests/` directory.

| # | Item | Detail |
|---|---|---|
| IN1 | **No tests at all** | Zero test files. Everything this document identifies as a bug is currently unprotected against regression. Start with the pure functions — attendance percentages, `classes_to_attend`, CIE, fee balance/status — then view-level auth tests, which would have caught TA-S3, TM17 and RP9 |
| IN2 | **No README** | The repository has no setup instructions, no architecture notes, no screenshots. For a portfolio project this is the single highest-leverage missing file — it's what a reviewer opens first |
| IN3 | **No CI** | No GitHub Actions. Lint + test on push is a short workflow file and it's visible on every commit |
| IN4 | **No Docker** | `docker-compose` with web + Postgres turns setup into one command; right now a new contributor must install and configure Postgres by hand |
| IN5 | **No linting or formatting config** | No ruff/black/isort, no pre-commit. Formatting in `views.py` is already inconsistent (trailing whitespace, mixed quoting) |
| IN6 | **No dependency scanning** | `requirements.txt` is pinned, which is good, but nothing checks for known CVEs. `pip-audit` in CI is a two-line addition |
| IN7 | **No seed data / fixtures** | Directly connected to MD1: a fresh deploy has no `Dept`, `Course`, `Class` or `AttendanceRange`, so the app cannot be meaningfully demonstrated until someone hand-creates all of it through the admin. A `loaddata` fixture or a management command would make the deployed demo self-setting-up |
| IN8 | **No database backups** | Render's free Postgres tier has a 90-day lifetime and no automated backups. A periodic `pg_dump` to somewhere durable is worth scripting before the demo has data worth keeping |

### 9.4 Quality attributes barely touched

| # | Area | Detail |
|---|---|---|
| QA1 | **Accessibility** | 🟠 **Partly addressed (pass 18).** The attendance cells no longer rely on colour alone: every meter ships an icon and a word (Safe / At risk / Critical) beside the number, and each chart sits above the table it summarises. The badge tints were also re-stepped — `--erp-success`/`--erp-warning` sat at ~3.0:1 and ~2.9:1 as text on their own tints, so status words now use new `-ink` tokens measured at 4.5:1+. Still unassessed: keyboard order and focus outlines outside the dashboards, and §6.4's other targets on every non-specced page |
| QA2 | **Mobile responsiveness beyond the specced pages** | Every table view (marks, fees, reports, session lists) overflows on a phone |
| QA3 | **No type hints** | Nothing is annotated; `mypy` would find real issues in the view layer |
| QA4 | **Internationalisation** | `LANGUAGE_CODE='en-us'`, no `gettext` usage. Probably out of scope, but worth an explicit decision rather than an accident |
| QA5 | **No performance budget** | This document has measured pages at 28, 57 and ~900+ queries. Once fixed, a `django-debug-toolbar` check or an assertion on query counts in tests keeps them fixed |

### Where these fit in the build order

- **MD1 + IN7** are a deployment blocker for anyone cloning the repo — arguably the first thing to fix, since nothing else can be demonstrated on a fresh instance
- **CF2** (logging) should land before any bug-fixing work, so failures are visible while fixing them
- **CF3** (email) gates §5.1, FE22 and NB17 — same dependency as AC4
- **CF1** (media) gates AC16 and NB8, and needs external storage, not just settings
- **IN1** (tests) should grow alongside each fix rather than as a separate phase
- **IN2** (README) is the cheapest high-visibility improvement in the entire document

---

## Navigation & Sequencing

**Recommended build order for pages:**
1. **Login redesign** (§5) — highest visibility, table-stakes
2. **Dashboard redesign** (§6) — done just after login, students/teachers see it instantly
3. **Attendance page** (§7.1) — most-used feature, high impact
4. **Marks page** (§7.2) — academically critical, makes the app "smart"
5. **Timetable** (§7.4) — mobile experience matters, simpler than attendance
6. **Notice board** (§7.5) — lower priority but completes the core UX
7. **Teacher attendance flow** (§7.3) — backend-heavy, does later

---

## Next steps

Seventeen passes in. The planning phase is closed and the two §5 decisions have
been settled in code:

- **Role selector** — built as **enforced**, not cosmetic. Signing in as a
  student from the Admin tab is rejected with "That account is not registered
  as Admin" rather than silently redirecting (`ErpLoginForm`, `info/forms.py`)
- **Forgot Password / OTP** — **deferred**, because CF3 blocks it. The link
  opens a modal pointing at the support form instead of dead-ending

### Three decisions still needed — each one blocks work that is otherwise ready

1. **Who may see a student's fees (FE31)** — `t_fees` lets any teacher list
   every fee record in the institution, but `fees(stud_id)` allows only the
   student or an administrator, so a teacher sees rows and gets bounced on
   clicking one. The two views have to agree. Recommendation: make fees
   admin-only. Collection is an accounts function, a subject teacher has no
   need for a student's payment history, and it closes the wider exposure of
   the whole institution's ledger to every teacher account. The alternative -
   opening `fees(stud_id)` to teachers - is a one-line change if the college
   works the other way
2. **SMTP credentials (CF3)** — a Gmail App Password is enough. This single
   decision unblocks §5.1 (OTP reset), FE22, NB17, AT23 and MK21
3. **Media storage (CF1)** — S3, Cloudinary or drop photos/attachments from
   scope. Render's disk is ephemeral, so "just configure `MEDIA_ROOT`" is not an
   option. Blocks AC16, NB8, TA6

The grade scale is no longer among them: VTU's 10-point scale and a 40% CIE
eligibility rule were adopted in pass 19 (see "The grading rules, decided").

### Ready to build with no decision outstanding

E3 is done, so the chart work is now just drawing. `{% meter %}`,
`{% attendance_trend %}` and `{% bar_chart %}` are in
`info/templatetags/charts.py`, and the next charts reuse the same
geometry-in-Python, SVG-in-template shape.

1. **C4** — comparing sections of the same course. The distribution chart and
   `{% bar_chart %}` from pass 27 are the pieces; what is missing is the view
   that puts two classes side by side
2. **D1, D2, D7** — the admin analytics strip. `FeeQuerySet.totals()` from
   pass 26 is most of what a collection chart needs
3. **MK18 / TM16 / AT20** — the request-and-approve workflows (re-evaluation,
   attendance correction, leave). All the same state machine, so §7.2.x's note
   applies: build it once and apply it three times, rather than three times

**Two things to know before adding pages.**

*PDF layout is not visible in the text.* The marks card's first version
accumulated column widths and drew three of its five columns at x = 872, 1323
and 1828pt on a 595pt page. Every string was in the file and readable by any
text extractor; none of them were on the paper. `test_report_card.py` now
asserts every drawn point sits inside the page — check coordinates, not just
content.

*Django's `{# #}` comment is single-line only.* A multi-line one is not a comment — the text renders into the
page, and inside an `<svg>` it does so invisibly. Three had accumulated before
pass 18 caught one that landed outside an SVG; `test_charts.py` now fails the
build on any multi-line `{# #}` in the template tree.
