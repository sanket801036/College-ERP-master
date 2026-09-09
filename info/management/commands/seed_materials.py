"""Put something in the corpus, so the assistant has something to answer from.

The rules below are the ones this application already enforces in code - the
75% attendance threshold, the seven-day window on questioning a mark, the CIE
of 20 needed to sit the semester exam. That is deliberate: an assistant whose
answers contradict the software it sits inside is worse than no assistant, and
writing plausible-sounding invented policy into a demo is how that happens.

    python manage.py seed_materials
    python manage.py seed_materials --embed      # also calls the provider
"""
from django.core.management.base import BaseCommand

from info import rag
from info.models import MATERIAL_POLICY, User

DOCUMENTS = [
    ('Attendance', 'Student Handbook', """
Attendance

A student must attend at least 75 percent of the classes held in each course
to be eligible for the semester end examination in that course. The percentage
is counted per course, not across the whole semester, so a shortfall in one
subject cannot be made up by attendance in another.

Approved leave is excluded from the total rather than counted as present. A
leave application that has been approved removes those sessions from both the
classes held and the classes attended, so an approved absence neither helps
nor harms the percentage.

A student who believes a session was marked wrongly may raise an attendance
dispute against that session. The course teacher reviews it and records a
decision with a written reason.
"""),
    ('Marks and grading', 'Student Handbook', """
Marks and grading

Continuous internal evaluation is made up of five components, each out of 20:
three internal tests and two events. The total of 100 is halved to give a CIE
out of 50. The semester end examination is out of 100 and contributes half its
mark, so a final mark is out of 100.

A student needs a CIE of at least 20 out of 50 to be eligible to sit the
semester end examination in that course.

Grades follow the ten point scale. A final of 90 or above is O and carries 10
grade points, 80 is A plus and 9 points, 70 is A and 8, 60 is B plus and 7, 55
is B and 6, 50 is C and 5, 40 is P and 4. Below 40 is F and carries no points.

SGPA is the credit weighted average of the grade points of the courses whose
result has been declared.
"""),
    ('Questioning a mark', 'Student Handbook', """
Questioning a mark

A student who believes an internal mark is wrong may raise a query on that
mark within seven days of the mark being published. Marks that have not been
published cannot be questioned, because they are not yet the student's result.

Only one query may be open on a mark at a time. A student may withdraw their
own query while it is open, which frees the mark to be questioned again.

The course teacher reviews the query and must record a written reason for the
decision, whether the mark changes or stands.
"""),
    ('Leave', 'Student Handbook', """
Leave

A leave application covers a range of dates and must be supported by a reason.
A medical certificate or similar document may be attached; accepted formats
are PDF, JPG and PNG, up to five megabytes.

Leave may be applied for up to fourteen days after the dates in question, and
a single application may not cover more than thirty days.

Approved leave excuses the sessions it covers. Those sessions are removed from
the attendance total rather than being marked present.
"""),
    ('Fees', 'Student Handbook', """
Fees

Fees are recorded per student and per fee type, each with its own due date and
amount. A payment is recorded as a transaction against a fee, and the amount
paid is the sum of those transactions rather than a figure anybody types in.

A fee is unpaid until a payment is recorded, partly paid while the payments
total less than the amount, and paid once they meet it. A fee whose due date
has passed and which is not fully paid is overdue.

A receipt is available for every payment recorded.
"""),
]


class Command(BaseCommand):
    help = 'Seed the college policy documents the assistant answers from.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--embed', action='store_true',
            help='Also embed the passages, which calls the provider and '
                 'counts against its quota.')

    def handle(self, *args, **options):
        actor = User.objects.filter(is_superuser=True).order_by('pk').first()

        added = skipped = 0
        for title, source, text in DOCUMENTS:
            try:
                rag.ingest(text, title=title, actor=actor,
                           kind=MATERIAL_POLICY, source=source, publish=True)
                added += 1
                self.stdout.write('  added   %s' % title)
            except rag.MaterialNotAllowed as exc:
                # Re-running is the normal case, not a failure.
                skipped += 1
                self.stdout.write('  skipped %s (%s)' % (title, exc))

        self.stdout.write(self.style.SUCCESS(
            '%d added, %d already here' % (added, skipped)))

        if options['embed']:
            done = rag.embed_pending()
            self.stdout.write(self.style.SUCCESS(
                'embedded %d passages' % done))
        else:
            pending = rag.MaterialChunk.objects.filter(
                embedding__isnull=True).count()
            if pending:
                self.stdout.write(
                    '%d passages have no vector yet. Run with --embed to '
                    'make them searchable.' % pending)
