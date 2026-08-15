from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from info.models import Fee, FeeTransaction
from info.tests import factories as f


class FeeStatusTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.student = f.make_student(f.make_class(dept), username='pupil')

    def _fee(self, amount='10000', paid='0'):
        fee = Fee.objects.create(student=self.student, fee_type='Tuition Fee',
                                 amount=Decimal(amount),
                                 due_date=date(2026, 9, 1))
        if Decimal(paid) > 0:
            FeeTransaction.objects.create(fee=fee, amount=Decimal(paid))
            fee.recalculate_paid()
        return fee

    def test_unpaid(self):
        fee = self._fee()
        self.assertEqual(fee.status, 'Unpaid')
        self.assertEqual(fee.balance, Decimal('10000'))

    def test_partial(self):
        fee = self._fee(paid='4000')
        self.assertEqual(fee.status, 'Partial')
        self.assertEqual(fee.balance, Decimal('6000'))

    def test_paid(self):
        fee = self._fee(paid='10000')
        self.assertEqual(fee.status, 'Paid')
        self.assertEqual(fee.balance, Decimal('0'))

    def test_zero_amount_fee_reads_as_paid(self):
        """A fully waived fee reported "Unpaid" for ever: the paid<=0 check ran
        before the paid>=amount one, so 0 of 0 could never settle."""
        fee = Fee.objects.create(student=self.student, fee_type='Other',
                                 amount=Decimal('0'), due_date=date(2026, 9, 1))

        self.assertEqual(fee.status, 'Paid')

    def test_is_overdue(self):
        past = Fee.objects.create(student=self.student, fee_type='Exam Fee',
                                  amount=Decimal('2500'),
                                  due_date=timezone.localdate() - timedelta(days=1))
        future = Fee.objects.create(student=self.student, fee_type='Exam Fee',
                                    amount=Decimal('2500'),
                                    due_date=timezone.localdate() + timedelta(days=1))

        self.assertTrue(past.is_overdue)
        self.assertFalse(future.is_overdue)

    def test_paid_amount_is_the_sum_of_transactions(self):
        fee = self._fee()
        FeeTransaction.objects.create(fee=fee, amount=Decimal('3000'))
        FeeTransaction.objects.create(fee=fee, amount=Decimal('2500'))

        self.assertEqual(fee.recalculate_paid(), Decimal('5500'))
        self.assertEqual(fee.status, 'Partial')


class RecordPaymentTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.student = f.make_student(f.make_class(dept), username='pupil')
        self.teacher = f.make_teacher(dept, id='t001', username='staff')
        self.fee = Fee.objects.create(student=self.student,
                                      fee_type='Tuition Fee',
                                      amount=Decimal('10000'),
                                      due_date=date(2026, 9, 1))
        self.url = reverse('edit_fee', args=(self.fee.id,))
        self.client.force_login(self.teacher.user)

    def test_records_a_payment_with_who_and_when(self):
        response = self.client.post(self.url, {
            'amount': '4000', 'mode': 'UPI', 'reference': 'TXN123',
            'paid_on': '2026-08-01', 'note': ''})

        self.assertEqual(response.status_code, 302)
        payment = self.fee.transactions.get()
        self.assertEqual(payment.amount, Decimal('4000'))
        self.assertEqual(payment.mode, 'UPI')
        self.assertEqual(payment.received_by, self.teacher.user)
        self.assertEqual(payment.paid_on, date(2026, 8, 1))

        self.fee.refresh_from_db()
        self.assertEqual(self.fee.paid_amount, Decimal('4000'))

    def test_payments_accumulate_rather_than_replace(self):
        """The old form overwrote the running total, so staff did the addition
        themselves and nothing recorded the individual payments."""
        self.client.post(self.url, {'amount': '4000', 'mode': 'Cash',
                                    'paid_on': '2026-08-01', 'reference': '',
                                    'note': ''})
        self.client.post(self.url, {'amount': '2500', 'mode': 'Cash',
                                    'paid_on': '2026-08-05', 'reference': '',
                                    'note': ''})

        self.assertEqual(self.fee.transactions.count(), 2)
        self.fee.refresh_from_db()
        self.assertEqual(self.fee.paid_amount, Decimal('6500'))

    def test_overpayment_is_rejected(self):
        """A fee of 10,000 accepted 99,999, leaving a balance of -89,999 that
        still reported as "Paid"."""
        response = self.client.post(self.url, {
            'amount': '99999', 'mode': 'Cash', 'paid_on': '2026-08-01',
            'reference': '', 'note': ''})

        self.assertEqual(response.status_code, 200)
        self.assertIn('more than the outstanding balance',
                      str(response.context['form'].errors['amount']))
        self.assertEqual(self.fee.transactions.count(), 0)

    def test_negative_payment_is_rejected(self):
        response = self.client.post(self.url, {
            'amount': '-500', 'mode': 'Cash', 'paid_on': '2026-08-01',
            'reference': '', 'note': ''})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.fee.transactions.count(), 0)

    def test_future_dated_payment_is_rejected(self):
        tomorrow = timezone.localdate() + timedelta(days=1)

        response = self.client.post(self.url, {
            'amount': '100', 'mode': 'Cash', 'paid_on': tomorrow.isoformat(),
            'reference': '', 'note': ''})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.fee.transactions.count(), 0)

    def test_history_is_shown(self):
        FeeTransaction.objects.create(fee=self.fee, amount=Decimal('4000'),
                                      mode='Cheque')

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Cheque')
        self.assertContains(response, 'RCP-')

    def test_student_cannot_record_payments(self):
        self.client.force_login(self.student.user)

        response = self.client.post(self.url, {
            'amount': '4000', 'mode': 'Cash', 'paid_on': '2026-08-01',
            'reference': '', 'note': ''})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.fee.transactions.count(), 0)


class AddFeeTests(TestCase):
    def setUp(self):
        dept = f.make_dept()
        self.student = f.make_student(f.make_class(dept), username='pupil')
        self.client.force_login(f.make_admin())

    def _payload(self, **overrides):
        data = {'student': self.student.pk, 'fee_type': 'Exam Fee',
                'description': 'Semester 5', 'amount': '2500',
                'due_date': '2026-09-01'}
        data.update(overrides)
        return data

    def test_creates_a_fee(self):
        response = self.client.post(reverse('add_fee'), self._payload())

        self.assertEqual(response.status_code, 302)
        fee = Fee.objects.get(student=self.student)
        self.assertEqual(fee.amount, Decimal('2500'))
        self.assertEqual(fee.paid_amount, Decimal('0'))

    def test_negative_amount_is_rejected(self):
        response = self.client.post(reverse('add_fee'),
                                    self._payload(amount='-5000'))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Fee.objects.exists())

    def test_unknown_fee_type_is_rejected(self):
        """fee_type was stored straight from POST, so an arbitrary string could
        be saved and the fee then matched no filter anywhere."""
        response = self.client.post(reverse('add_fee'),
                                    self._payload(fee_type='Bribe'))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Fee.objects.exists())

    def test_invalid_date_is_rejected_not_a_500(self):
        response = self.client.post(reverse('add_fee'),
                                    self._payload(due_date='not-a-date'))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Fee.objects.exists())
