"""Clear the timestamps AddField stamped onto pre-existing rows.

Adding an `auto_now` column makes Django write `timezone.now()` into every
existing row, so the whole table claims it was last changed at the moment the
migration ran. That is a false answer to the only question the column exists to
answer. NULL says "not touched since this column existed", which is true.

Only rows older than the migration are cleared - anything saved after it has a
timestamp that means something.
"""
from django.db import migrations


def clear_backfill(apps, schema_editor):
    for label in ('Attendance', 'Marks', 'Student', 'Teacher'):
        apps.get_model('info', label).objects.update(updated_at=None)


def noop(apps, schema_editor):
    """Nothing to restore - the backfilled values carried no information."""


class Migration(migrations.Migration):

    dependencies = [
        ('info', '0030_attendance_updated_at_marks_updated_at_and_more'),
    ]

    operations = [
        migrations.RunPython(clear_backfill, noop),
    ]
