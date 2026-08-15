# College ERP — Current State & Interview-Readiness Roadmap

This is a working document, not final. Section 1-2 describe what exists today (so we're on the same page about the baseline). Section 3 lists concrete flaws. Section 4 is a prioritized list of what to add/fix. Edit this file directly with comments/strikethroughs/priorities, then we turn the agreed items into an implementation plan and start writing code.

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
| B2 | **Attendance trend chart** | Line/bar chart of attendance % per course, or week over week | ✅ `Attendance.date` | M |
| B3 | **Subject-wise attendance donut** | Small ring per course, red under 75% — scannable in one glance | ✅ | S |
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
| C6 | **Marks distribution histogram** | Grade spread per test — shows whether a paper was too hard/easy | ✅ | M |
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
| E3 | **Chart library** | Chart.js via CDN, or inline SVG to stay dependency-free. Needed by B2, C4, C6, D1, D2, D7 | ✅ | S |
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
| AT12 | **Attendance trend chart** | Running cumulative % across the semester — shows whether the student is recovering or sliding | ✅ |
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
| MK1 | **GPA / performance card** | Overall score card at the top. See MK14 first — a *true* GPA needs course credits, which the schema doesn't have. Until then this should be an honestly-labelled "Average Score", not a fake "3.8/4.0 GPA" | ⚠️ |
| MK2 | **Per-course accordion** | Replace the 8-column table (unreadable on a phone) with one expandable card per course: CIE total, component breakdown, SEE status | ✅ |
| MK3 | **CIE progress bar** | "CIE: 38 / 50" with a bar — instantly more readable than six loose numbers | ✅ `get_cie()` |
| MK4 | **Pending vs. zero distinction** | **Correctness issue.** `marks1` defaults to `0`, so a test that hasn't happened yet displays as **0** — identical to actually scoring zero. `MarksClass.status` already records whether the teacher submitted that batch, but the student page never consults it. Must render "Not yet conducted" instead of `0` | ✅ (`MarksClass.status` exists, just unused here) |
| MK5 | **Expected / required-marks calculator** | The counterpart to the attendance bunk calculator: *"You have CIE 38/50. You need **44/100** in the SEE to reach an A grade."* Solve the grade formula backwards for the SEE mark. This is the feature students actually want from a marks page | ✅ |
| MK6 | **Letter grade + grade points** | Compute final = CIE + SEE/2 (out of 100), then map to a grade band. Show provisional grade while the SEE is pending | ✅ |
| MK7 | **SEE eligibility flag** | Most colleges require a minimum CIE to sit the final exam. Flag any course where CIE is below the cut-off | ✅ (threshold configurable) |
| MK8 | **Class rank / percentile** | "Rank 12 of 45" for the student's *own* position — standard in Indian colleges and privacy-safe, since each student sees only their own rank. Do **not** build a public leaderboard | ✅ |
| MK9 | **Weakest/strongest subject callout** | "Strongest: DBMS (46/50) · Needs work: OS (21/50)" | ✅ |
| MK10 | **Print / PDF report card** | `reportlab` is installed and still completely unused. A proper marks card with the college header is a very demo-able artifact | ✅ |

#### Phase B — Analysis & insight

| # | Feature | Detail | Data ready? |
|---|---|---|---|
| MK11 | **Performance trend across internals** | Line chart of Internal 1 → 2 → 3 per course — shows improvement or decline over the semester | ✅ |
| MK12 | **Radar/bar chart across subjects** | All courses on one chart, so relative strengths are visible at a glance | ✅ |
| MK13 | **Comparison against class average** | "You: 38 · Class average: 31" per component. Aggregate only — never a per-classmate breakdown | ✅ |
| MK14 | **Credits & true CGPA** | `Course` has **no `credits` field**, so a genuine credit-weighted GPA is not computable today. Either add `credits` to `Course` (small migration, unlocks real CGPA + SGPA) or keep it an unweighted average and label it as such. Recommend adding the field — CGPA is what a college ERP is expected to produce | ⚠️ `Course.credits` |
| MK15 | **Semester-over-semester history** | SGPA per semester and cumulative CGPA over time | ⚠️ needs semester tagging on `StudentCourse` |
| MK16 | **Attendance ↔ marks correlation** | `StudentCourse.get_attendance()` already exists alongside `get_cie()` — plotting the two together across courses is a genuinely interesting insight and costs one scatter chart | ✅ |
| MK17 | **Grade distribution for a course** | Where the student sits in the class histogram | ✅ |

#### Phase C — Workflow (new models)

| # | Feature | Detail | Data ready? |
|---|---|---|---|
| MK18 | **Re-evaluation request** | Student disputes a mark → teacher/admin reviews → mark updated with full audit trail. Same shape as the attendance-correction workflow (AT20) and can share its state machine and permission logic | ❌ `MarkRevaluationRequest` |
| MK19 | **Marks audit log** | Today `marks_confirm` and `edit_marks` overwrite `marks1` in place with no record of the previous value, who changed it, or when. For grades specifically, that is the kind of gap an interviewer will press on | ❌ audit model |
| MK20 | **Result publication control** | Teacher enters marks, but students only see them once results are formally published — colleges never expose marks the instant they're typed | ⚠️ `MarksClass.is_published` |
| MK21 | **Marks release notification** | Email/in-app alert when a batch is published (reuses the SMTP work from §5.1) | ⚠️ |

#### Phase D — Technical fixes this module needs (all verified against the running app)

| # | Issue | Detail |
|---|---|---|
| MK22 | **Crash bug: `marks_list` passes a field that doesn't exist** | `info/views.py` calls `sc.marks_set.create(type='I', name='Internal test 1')` (six times), but the `Marks` model has only `studentcourse`, `name`, `marks1` — there is **no `type` field**. Verified in a shell: this raises `TypeError: Marks() got unexpected keyword arguments: 'type'`. It sits in the `except StudentCourse.DoesNotExist` fallback branch, which normally doesn't fire because the `create_marks` signal pre-creates the rows — so the page works today purely by luck. Any student whose `StudentCourse` row is missing (bulk import, a deleted row, data restored without signals) gets a hard 500. The identical block in `apis/views.py` has the same problem |
| MK23 | **`get_cie()` depends on unordered query results** | `get_cie()` does `marks_list = self.marks_set.all()` then `sum(m[:5])` — "the first five" — but `Marks.Meta` has **no `ordering`** (verified: `Marks._meta.ordering == []`). Unordered SQL results have no guaranteed order; Postgres is free to return rows in any sequence, and updated rows commonly move. If the SEE row (out of 100) lands in the first five, CIE silently absorbs it and drops an internal — a wrong grade with no error anywhere. It happens to be correct today only because insertion order matches. Fix: select the five components **by name**, never by position |
| MK24 | **The marks table has the same positional assumption** | `marks_list.html` renders `{% for m in sc.marks_set.all %}` straight into columns headed Internals 1/2/3, Event 1/2, SEE — so the same unordered queryset can place values under the wrong headings. The template should look each component up by name |
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

## Next steps (PAUSED — awaiting your review)

**Login (§5)**, **Dashboards (§6)**, **Feature Ideas (§6.5)** and **Page Specs (§7)** are now complete. Before we code:

1. **Review §7** — which page designs do you like? Any changes?
2. **Confirm build order** — ready to start with Login page, then Dashboards, then Pages?
3. **Two open decisions from §5:**
   - Role selector: cosmetic (just show "Student | Faculty | Admin" tabs, don't enforce) or real (validate role matches after login)?
   - Forgot Password / OTP: include now (needs SMTP setup, can use Gmail App Password) or defer to later?

Mark up the file with feedback, send it back, and we start coding. **No more planning—only code from here on.**
