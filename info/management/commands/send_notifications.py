"""Send the emails nobody is sitting at a screen to trigger.

    python manage.py send_notifications                 # all four
    python manage.py send_notifications fee attendance  # just these
    python manage.py send_notifications --dry-run       # say what would go

Meant for a scheduler. Render's free tier has no cron, so this is a command
rather than a Celery beat schedule or a bare `while True` - anything that can
run a shell line once a day can run it, including a laptop, a GitHub Actions
schedule, or a paid cron job later, and none of that changes the code.

Running it twice sends nothing twice: see `info/notifications.py` for why.
A `--dry-run` reports the same counts without sending or recording anything.
"""
from django.core.management.base import BaseCommand, CommandError

from info import notifications

KINDS = {
    'fee': 'fee reminders',
    'attendance': 'low-attendance alerts',
    'marks': 'marks-release alerts',
    'notice': 'notice announcements',
}


class Command(BaseCommand):
    help = 'Send fee, attendance, marks and notice emails that are due.'

    def add_arguments(self, parser):
        # No `choices=` here: argparse validates the empty default against
        # them when nargs='*', so passing nothing - the normal case - is
        # rejected as an invalid choice. Checked in handle() instead.
        parser.add_argument(
            'kinds', nargs='*', metavar='KIND',
            help='Which to send: %s. Defaults to all of them.'
                 % ', '.join(sorted(KINDS)))
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would be sent without sending or recording it.')
        parser.add_argument(
            '--window-days', type=int,
            default=notifications.DEFAULT_WINDOW_DAYS,
            help='How far back to look for published marks and notices '
                 '(default %(default)s). Keeps a first run from emailing the '
                 'whole archive.')
        parser.add_argument(
            '--due-soon-days', type=int,
            default=notifications.DEFAULT_DUE_SOON_DAYS,
            help='How long before a fee falls due to start reminding '
                 '(default %(default)s).')

    def handle(self, *args, **options):
        kinds = options['kinds'] or sorted(KINDS)
        unknown = [k for k in kinds if k not in KINDS]
        if unknown:
            raise CommandError('unknown kind(s): %s. Choose from %s.'
                               % (', '.join(unknown), ', '.join(sorted(KINDS))))
        dry_run = options['dry_run']

        gatherers = {
            'fee': lambda: notifications.fee_reminders(
                due_soon_days=options['due_soon_days']),
            'attendance': notifications.attendance_alerts,
            'marks': lambda: notifications.marks_release_alerts(
                window_days=options['window_days']),
            'notice': lambda: notifications.notice_alerts(
                window_days=options['window_days']),
        }

        if dry_run:
            self.stdout.write(self.style.WARNING(
                'Dry run: nothing will be sent and nothing recorded.'))

        total_sent = total_failed = 0
        for kind in kinds:
            messages = gatherers[kind]()
            result = notifications.send_all(messages, dry_run=dry_run)
            total_sent += result.sent
            total_failed += result.failed

            line = ('%s: %d sent, %d already had it, %d failed'
                    % (KINDS[kind], result.sent, result.skipped, result.failed))
            style = self.style.ERROR if result.failed else self.style.SUCCESS
            self.stdout.write(style(line))

        if total_failed:
            # A non-zero exit is how a scheduler notices; a silent failure in a
            # job nobody reads is the same as no job at all.
            raise CommandError('%d message(s) could not be sent' % total_failed)

        self.stdout.write('%d message(s) %s.'
                          % (total_sent, 'would be sent' if dry_run else 'sent'))
