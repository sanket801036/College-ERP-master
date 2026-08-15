"""Turn each existing paid_amount into an opening transaction.

Before this, paid_amount was the only record that money had been received - no
date, no mode, no idea who took it. There is nothing to recover for historical
rows, so each becomes a single "opening balance" entry carrying the total, dated
to when the fee was raised.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    Fee = apps.get_model('info', 'Fee')
    FeeTransaction = apps.get_model('info', 'FeeTransaction')

    rows = []
    for fee in Fee.objects.filter(paid_amount__gt=0).iterator():
        rows.append(FeeTransaction(
            fee=fee,
            amount=fee.paid_amount,
            mode='Cash',
            note='Opening balance carried over from before payments were '
                 'recorded individually.',
            paid_on=fee.created_at.date() if fee.created_at else fee.due_date,
        ))
    FeeTransaction.objects.bulk_create(rows, batch_size=500)


def backwards(apps, schema_editor):
    # paid_amount is still the stored total, so dropping the transactions loses
    # only the breakdown.
    apps.get_model('info', 'FeeTransaction').objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('info', '0020_alter_fee_amount_feetransaction'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
