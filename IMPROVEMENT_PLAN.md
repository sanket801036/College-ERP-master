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

## Next steps (PAUSED — awaiting your review)

**Login page (§5)** + **dashboards (§6)** specs are now complete. Before we code anything:
1. Review both — does the flow/layout make sense?
2. Any metrics missing, extra, or should be different?
3. Approve the approach, then we start building code.

Mark up this file with your feedback, then send it back.
