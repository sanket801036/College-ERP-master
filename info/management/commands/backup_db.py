"""Dump the database to a file.

Render's free Postgres has no automated backups and a ninety-day lifetime, so
losing it is a matter of when. This uses Django's own serialiser rather than
pg_dump: pg_dump is better in every way except being installed, and it is not
in the Python image the app deploys on.

    python manage.py backup_db
    python manage.py backup_db --output backups/nightly.json.gz

Restore with `python manage.py loaddata <file>` into an empty database.
"""
import gzip
from datetime import datetime
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand

# Rows Django recreates or that belong to a particular deployment. Carrying
# sessions and permissions across would fight the fresh database's own.
EXCLUDE = [
    'contenttypes',
    'auth.permission',
    'sessions.session',
    'admin.logentry',
]


class Command(BaseCommand):
    help = 'Write a compressed JSON dump of the database.'

    def add_arguments(self, parser):
        parser.add_argument('--output', help='Path to write to.')
        parser.add_argument('--no-compress', action='store_true',
                            help='Write plain JSON instead of gzip.')

    def handle(self, *args, **options):
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        default = 'backup-%s.json%s' % (stamp,
                                        '' if options['no_compress'] else '.gz')
        path = Path(options['output'] or default)
        if path.parent != Path('.'):
            path.parent.mkdir(parents=True, exist_ok=True)

        opener = open if options['no_compress'] else gzip.open
        with opener(path, 'wt', encoding='utf-8') as handle:
            call_command('dumpdata', exclude=EXCLUDE, natural_foreign=True,
                         indent=None, stdout=handle)

        size = path.stat().st_size
        self.stdout.write(self.style.SUCCESS(
            'Wrote %s (%.1f KB)' % (path, size / 1024)))
        self.stdout.write(
            'On Render this lands on an ephemeral disk - copy it somewhere '
            'that survives a redeploy.')
