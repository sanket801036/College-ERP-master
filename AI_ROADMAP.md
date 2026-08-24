# College ERP — the AI layer

This is a scope document. It decides **what gets built, in what order, and what
deliberately does not get built.** `IMPROVEMENT_PLAN.md` is the audit of the
records system — what exists, what is broken, what is missing. This is a
different argument: a product direction, layered on top of a system that already
works.

Nothing here is started until it is agreed here.

---

## The problem this layer solves

The ERP is finished as a *record* of what happened. Attendance is counted, marks
are entered and published, fees are tracked, disputes have a queue, and 809 tests
hold it together. A student can open it and learn that their Data Structures CIE
is 22 out of 50 and that they are two classes short of 75%.

And then nothing. The system knows exactly where a student is weak and says
nothing about it. It is a filing cabinet that can do arithmetic.

The layer described here is the part that acts on what the records already know:
answer the question the student actually has, generate practice for the topic
they actually failed, tell somebody before the failure rather than after.

---

## How to read this

Every item carries the same six fields, so the list can be ranked rather than
admired:

| Field | Meaning |
|---|---|
| **Does** | What a person can do afterwards that they could not before |
| **Needs** | New dependencies, new services, new secrets |
| **Effort** | S (a pass) · M (two or three) · L (a project of its own) |
| **Risk** | What breaks, costs money, or embarrasses us in a demo |
| **Reuses** | What already exists in this codebase, named |
| **Tier** | When |

"Reuses" is not a courtesy column. If an item cannot name what it builds on, it
is a rewrite wearing a feature's clothes, and it belongs in a different project.

---

## The one fact that decides the order

**The RAG pipeline built for the chatbot is the same pipeline that generates
quiz questions.**

Ingest → chunk → embed → store → retrieve gets built once and consumed twice: the
chatbot retrieves in order to *answer*, the generator retrieves in order to
*ask*. Same documents, same embeddings, same store, same retrieval code, two
completely different products on top.

That is why RAG goes first, ahead of the quiz that seems like the more obvious
starting point. Build the quiz first and the generator arrives later with nothing
underneath it; build RAG first and the quiz's hardest part is already done.

---

## Standing decisions

| | |
|---|---|
| **Generation** | **Groq** — `https://api.groq.com/openai/v1`, OpenAI-compatible, `gsk_…` key. Free tier |
| **Embeddings** | **Gemini** `text-embedding-004` — free tier. Neither Groq nor xAI has an embeddings endpoint, so generation and embeddings come from different providers |
| **Vector store** | **pgvector on the existing Neon Postgres.** No second database, no hosted vector service, no new bill |
| **Voice** | Browser Web Speech API. No infrastructure, no cost, no upload of anybody's voice |
| **RAG sources** | Teacher-uploaded course material and school policy first; web is a fallback for topics with no material |
| **Secrets** | `GROQ_API_KEY` and `GEMINI_API_KEY` through python-decouple, like every other secret here; `sync: false` in `render.yaml` |
| **Feature flags** | A service is on when its key is present, off and harmless when it is absent — the pattern `USE_S3` already establishes |
| **Quiz points** | Mastery-based: a question pays once, the first time it is answered correctly |
| **Generated content** | Nothing an LLM writes reaches a student without a human approving it |

---

## Already on the books

Four items below are not new ideas — they are already written down in
`IMPROVEMENT_PLAN.md` and blocked on exactly the things this layer adds. Saying
so is the difference between a roadmap and a wish list.

| ID | Where | What it says |
|---|---|---|
| **AT24** | §7.1.x | *"Email the guardian on sustained low attendance — ❌ needs guardian contact fields"* |
| **Tier 3 #17** | §4 | *"Parent/guardian portal — read-only visibility into their child's records"* |
| **AT14** | §7.1.x | *"Streaks — light gamification that costs almost nothing"* |
| **MK15** | §7.2.x | Semester-over-semester SGPA/CGPA history |

---

# Tier 1 — the headline

A voice chatbot grounded in the school's own documents that hands over to a human
when it is unsure. **This tier alone is a complete, demonstrable product.**

### 1 · RAG pipeline

| | |
|---|---|
| **Does** | Turns uploaded PDFs, notes and policy documents into something the system can search by meaning rather than by keyword |
| **Needs** | `pgvector` on Neon; a Gemini key for embeddings; a chunker. No new service |
| **Effort** | M |
| **Risk** | Chunking badly is invisible until answers are subtly wrong. Embedding cost is per-document, not per-question, so it is bounded |
| **Reuses** | B2 object storage (already holds leave certificates and photos), `django-storages`, Neon, the `USE_S3` feature-flag pattern |

Three source kinds, and they are not equally hard:

- **Uploaded documents** — course material, the handbook, exam rules. The normal case.
- **The ERP's own structured rules** — the 75% attendance threshold, `LEAVE_MAX_DAYS`, fee due-date logic, the VTU grade bands. These are *in the code*, not in a document, and they are the questions students actually ask. Rendering them into text the pipeline can index is a small job with a large payoff.
- **Live student data** — "what is *my* attendance". This is **not RAG**; it is a database query the chatbot is allowed to make on behalf of the signed-in student. Keeping these two paths separate is the difference between a chatbot that is right and one that is plausible.

### 2 · Grounded chatbot

| | |
|---|---|
| **Does** | Answers a student's question about the college, their course, or the rules, and shows where the answer came from |
| **Needs** | Item 1, a Groq key, the budget guard (item 14) |
| **Effort** | M |
| **Risk** | Confident invention. An ERP chatbot that guesses a fee deadline is worse than no chatbot |
| **Reuses** | The `services.py` pattern, `owns_student_record`, the existing auth |

**The refusal path is a feature, not a gap.** When retrieval returns nothing
relevant, the answer is "I do not have anything on that — here is who to ask",
with a link to the support-request form that already exists. Every answer carries
a citation the student can open. A chatbot that cannot say "I do not know" cannot
be trusted about the things it does know.

### 3 · Voice assistant

| | |
|---|---|
| **Does** | Ask by speaking, hear the answer read back |
| **Needs** | Nothing. Web Speech API, in the browser |
| **Effort** | S |
| **Risk** | Chrome-only in practice; Safari support is partial. Degrade to typing, do not block on it |
| **Reuses** | The no-CDN, no-library doctrine the charts already follow |

Worth noting for what it is: no audio leaves the browser, no Whisper server, no
per-minute cost. The same TTS should read notices and marks aloud too — that
turns a demo feature into an access feature.

### 4 · Doubt escalation

| | |
|---|---|
| **Does** | When the bot is unsure, or the student says the answer did not help, it opens a ticket to the course teacher |
| **Needs** | Items 2, and a queue |
| **Effort** | S |
| **Risk** | Low |
| **Reuses** | **The `MarkQuery` review-queue shape almost exactly** — a student raises, a teacher sees a queue, resolves with a written response, both sides get a notification. That whole workflow already exists three times over (mark queries, leave, attendance disputes) |

**This is what makes the chatbot a system rather than a toy.** Most portfolio
chatbots answer or fail silently. This one knows the difference and routes the
failure to a person who can fix it — and the queue it routes into is already
built.

---

# Tier 2 — the learning loop

### 5 · Topic tagging

| | |
|---|---|
| **Does** | Makes syllabus units first-class, so a mark, a question and a document chunk can all point at "Unit 3: Trees" |
| **Needs** | Nothing external |
| **Effort** | S |
| **Risk** | Getting the granularity wrong. Too fine and nothing has enough data; too coarse and "you are weak in Data Structures" says nothing |
| **Reuses** | `Course`, `Marks` components, the existing `attach_*` bulk-loader idiom |

**This is the join that makes the layer one product instead of five toys.**
Without it, the quiz cannot target a weakness, the generator cannot be told what
to generate, the study plan has nothing to plan over, and "you are weak in Unit
3" is unsayable. It is the smallest item in Tier 2 and the one everything else
leans on.

### 6 · Quiz, mastery points and badges

| | |
|---|---|
| **Does** | Practice quizzes on your own courses; teacher-assigned quizzes with a window and one attempt; points, streaks and badges |
| **Needs** | Item 5 |
| **Effort** | L |
| **Risk** | Points get farmed; or the engagement layer leaks into the grade book |
| **Reuses** | `Assign` for authority, `MarksClass`'s publish/unpublish shape, `{% meter %}` `{% bar_chart %}` `{% sparkline %}`, `.erp-badge-*`, the `services.py` pattern, the `Notification` idempotency key |

Two rules that are not negotiable:

- **Quiz results never touch `Marks`, CIE, SGPA or a grade.** A test asserts that a
  perfect quiz leaves the marks card byte-identical. The day this feature becomes
  an academic record by accident is the day it has to be removed.
- **A question pays once**, the first time it is answered correctly. Points then
  measure how much you learned, not how long you clicked. A question you got
  *wrong* stays unpaid, so it pays when you finally learn it — the system pays
  for improving.

Closes **AT14**.

### 7 · RAG question generation

| | |
|---|---|
| **Does** | The model writes questions from a retrieved chunk of the actual syllabus, with a citation, into a review queue |
| **Needs** | Items 1, 5, 6, 14 |
| **Effort** | M |
| **Risk** | Wrong answers presented as authoritative; the same prompt run twice doubling the bank |
| **Reuses** | The entire pipeline from item 1 — this is the second consumer that justified building it |

**Nothing generated is served to a student until a human approves it.** The
question bank has an approval gate; generation writes into it unapproved. That
one design decision is what makes an LLM safe to point at a grade-adjacent
feature.

### 8 · Generated-question eval harness

| | |
|---|---|
| **Does** | Automatically rejects bad generated questions before a teacher ever sees them |
| **Needs** | Item 7 |
| **Effort** | S |
| **Risk** | Low. This *reduces* risk |
| **Reuses** | The test suite's conventions |

Checks: exactly one defensible answer · distractors not trivially wrong (no "none
of the above", no answer three times longer than the others) · the answer
actually present in the cited chunk · not a near-duplicate of a question already
in the bank.

Unglamorous, and **the most senior item on this list.** *"How do you know the
LLM's output is any good?"* is the question every interviewer asks about every AI
feature, and almost nobody has an answer that is code.

---

# Tier 3 — growth and people

### 9 · Growth profile + semester history

| | |
|---|---|
| **Does** | One page per student: attendance trend, CIE trend, topic mastery, streak, badges — measured against **their own past** |
| **Needs** | Items 5, 6; semester tagging on `StudentCourse` (**MK15**) |
| **Effort** | M |
| **Risk** | Drifting into a leaderboard. See C3 |
| **Reuses** | `{% attendance_trend %}`, `{% sparkline %}`, `{% bar_chart %}`, `.erp-stat-*`, `sgpa_for()` |

This is the honest form of "an advanced school that focuses on student growth".
The competitive feeling comes from beating your own last month, which is
unbounded and requires nobody else to lose.

Closes **MK15**.

### 10 · Early warning

| | |
|---|---|
| **Does** | Flags a student weeks before they fail, to their teacher and to them |
| **Needs** | Items 5, 6 for the quiz signal; nothing external |
| **Effort** | M |
| **Risk** | False positives that teach everyone to ignore it. Start conservative |
| **Reuses** | `AttendanceTotal`, `StudentCourse.is_at_risk`, `required_see_for()`, the notification gatherer + `send_notifications` command |

**Rules-based first, and possibly for good.** "Attendance below 70% *and* CIE
trending down over two internals *and* no practice in three weeks" is
explainable to the student it is about, defensible to the teacher acting on it,
and testable. A model that says 0.73 is none of those. `is_at_risk` exists today
and reads exactly two numbers; this widens it and gives it somewhere to go.

### 11 · Parent email and parent portal

| | |
|---|---|
| **Does** | Routes the notifications that already exist to a guardian; then a read-only page for them |
| **Needs** | A `parent_email` field. Signed URLs for the portal |
| **Effort** | S for the email, M for the portal |
| **Risk** | Sending a child's academic record to an unverified address. The portal needs a real think about who is allowed to see what |
| **Reuses** | **The whole notification layer.** `Notification`, `Message`, `announce()`, `send_all()`, the email backend, and the four scheduled gatherers already exist — this is a routing change, not a new system |

Closes **AT24** and **Tier 3 #17**. The smallest genuinely-useful item in this
document, and it has been blocked on one missing field the entire time.

---

# Tier 4 — the ambitious two

### 12 · Daily homework with OCR

| | |
|---|---|
| **Does** | Generates homework per student per day, accepts a photo or PDF of the written answer, extracts it, and proposes a mark |
| **Needs** | Items 5, 7; a vision model; storage (already there) |
| **Effort** | L |
| **Risk** | **High.** Handwriting extraction is good; grading free-text handwriting is not solved |
| **Reuses** | B2 storage, the review-queue pattern, the quiz bank |

**Assist, not decide.** Extract the answer, propose a mark *with a reason*, and
put it in the teacher's queue — the same shape as mark queries and leave. Points
are awarded when the teacher confirms, never on the model's unreviewed judgement
of somebody's handwriting. Auto-grading here is how this feature becomes a
complaints generator.

### 13 · Integrity and proctoring

| | |
|---|---|
| **Does** | Records what happened during an assigned quiz and surfaces anything odd to the teacher |
| **Needs** | Item 6. CV needs a machine that can run it — see C1 |
| **Effort** | M for signals, L for CV |
| **Risk** | See C1. This one is worth reading before building |
| **Reuses** | `.erp-badge-*`, the review pattern, `AuditLog` |

Two halves, deliberately separated:

- **Behavioural signals — always on.** Tab switches, paste events, per-question
  timing anomalies, back-navigation, reopened papers. Zero infrastructure, works
  on every deployment, and enough to be useful on its own.
- **Computer vision — behind a flag.** See C1 for where it can actually run.

**Nothing here ever changes a score.** Signals go to a teacher who decides. The
wording rule is: state the fact ("3 tab switches"), never the inference.

---

# Supporting — not optional

### 14 · LLM budget guard

| | |
|---|---|
| **Does** | Per-user and global daily call caps, response caching, and a kill switch |
| **Needs** | Nothing |
| **Effort** | S |
| **Reuses** | The DRF throttle configuration already in `settings.py` |

The demo is public and the key is paid. **This ships with item 2, not after it.**
A stranger clicking the chatbot four hundred times is not a hypothetical.

### 15 · Config and deploy checks

| | |
|---|---|
| **Does** | Makes a half-configured AI feature fail loudly at deploy instead of silently at runtime |
| **Effort** | S |
| **Reuses** | `info/checks.py` — the `@register('deploy')` check that already catches half-configured object storage |

`GROQ_API_KEY` and `GEMINI_API_KEY` via python-decouple, `sync: false` in
`render.yaml`, and a check for
"a generator is named but no key is set". The storage check exists because
exactly that class of bug shipped once already: uploads succeeded, the signed URL
pointed at the wrong host, and nothing errored.

---

## C1 · Where the CV proctoring can actually run

Server-side computer vision is in scope and will be built. On the record so it is
not a surprise later:

**YOLO plus torch is roughly 2 GB resident. The live demo runs on Render's free
tier, which gives 512 MB. It will run locally and it will not run on the current
deployment.**

The options are a paid instance, a separate inference service, or running
detection in the browser. Until one of those is chosen, the split in item 13 is
what keeps the feature honest: behavioural signals work on every deployment, and
CV is an enhancement behind a flag rather than a dependency.

Two more things this needs before it ships anywhere real: **consent** — a student
must be told what is recorded and agree before a camera opens — and **retention**
— how long signals are kept and who can see them. Neither is optional when the
subject is a student.

---

## C2 · What OCR grading can honestly claim

Extraction is a solved problem. *Grading* a handwritten free-text answer is not —
not by classical OCR, and not reliably by a vision model either. A student who
wrote a correct answer in bad handwriting and was marked wrong by a machine has a
legitimate complaint, and the ERP has three review queues precisely because this
project already decided that contested marks need a human.

So: extract, propose, queue. Never auto-award.

---

## C3 · The leaderboard ruling

`IMPROVEMENT_PLAN.md` rejects leaderboards twice, in writing:

> **AT17** — *"show only the aggregate, never a per-student leaderboard. Ranking
> classmates by attendance is a privacy problem, not a feature"*

> **MK8** — *"Own standing only; no leaderboard anywhere … Do **not** build a
> public leaderboard"*

A points-and-badges system in the spirit of a ruthlessly competitive school
points straight at what those forbid. The distinction that resolves it: both
rulings govern **academic records** — attendance and marks are not chosen by the
student, are permanently consequential, and are disclosed by the institution.
Quiz points are none of those things.

But the reason behind the rulings still binds. A points board is a proxy for
effort, and a visible bottom of a board is public shaming of the student with
least time — which correlates with things nobody should be publishing. So:

> **A student may see where they stand. A student may never see where a named
> classmate stands.**

**Allowed** — own points, streak, badges and accuracy; own percentile against an
**anonymous** distribution ("top 20% of your class", with a chart of bands and
counts and no names); the class average as an aggregate; and self-competition,
which is where the growth feeling actually lives. Withheld entirely in a class
with fewer than five active students, because in a six-person class "top 20%" *is*
a name.

**Not built** — any student-facing page showing another student's score, rank or
badges; any cross-class board; points or badges anywhere near the marks card or a
grade.

**Teacher-side** — named rosters stay. A teacher already sees every mark; that is
a register, not a leaderboard.

**Deferred, needs its own decision** — an *opt-in* named class board, default off,
top N only, never a bottom. Because the student opts in, it is disclosure by the
person rather than by the institution, which is a genuinely different question.
Not slipped in with a feature; decided deliberately or not at all.

---

## What this document says no to

Naming these is half the value of the exercise — the question "what did you leave
out, and why?" is the one that separates a plan from a list.

| Not building | Why |
|---|---|
| **Google scraping as the primary question source** | Against its terms, structurally unstable, and no guarantee the content matches the syllabus. Web stays a fallback for topics with no uploaded material |
| **Auto-grading handwriting** | See C2 |
| **Auto-punishing on integrity signals** | See C1 |
| **Any named student-vs-student leaderboard** | See C3 |
| **Fine-tuning a model** | Retrieval over the school's own documents answers the actual question. A fine-tune is expense and mystique, and it cannot cite a source |
| **A second database or a hosted vector service** | pgvector on Neon is already paid for and already backed up |
| **Server-side speech** | The browser does it free, and no student's voice needs to reach our servers |
| **An agent framework** | Two prompts and a retrieval call do not need LangChain. The dependency costs more than it saves at this size |

---

## Honest note on size

Tiers 1-3 are eleven workstreams; Tier 4 adds two more. That is a lot, and the
tiering is what makes it survivable — each tier reuses what the one before it
built rather than starting again, and **each tier is a stopping point that leaves
something whole.**

If time runs short, stop at the end of a tier, not halfway through one.

**Tier 1 + items 5 and 6** is a coherent portfolio on its own: a voice chatbot
grounded in the school's own documents that escalates to a human when unsure,
plus practice quizzes generated from the same pipeline. Everything after that is
upside.

---

## Status

| Tier | Item | State |
|---|---|---|
| 1 | 1 · RAG pipeline | Not started |
| 1 | 2 · Grounded chatbot | Not started |
| 1 | 3 · Voice assistant | Not started |
| 1 | 4 · Doubt escalation | Not started |
| 2 | 5 · Topic tagging | Not started |
| 2 | 6 · Quiz + points + badges | Not started — technical design done |
| 2 | 7 · RAG question generation | Not started |
| 2 | 8 · Eval harness | Not started |
| 3 | 9 · Growth profile + history | Not started |
| 3 | 10 · Early warning | Not started |
| 3 | 11 · Parent email + portal | Not started |
| 4 | 12 · Homework + OCR | Not started |
| 4 | 13 · Integrity + proctoring | Not started |
| — | 14 · Budget guard | Ships with item 2 |
| — | 15 · Config + deploy checks | Ships with item 1 |
