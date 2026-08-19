from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from info.models import Fee, FeeTransaction
from info.tests import factories as f


class Base(TestCase):
    def setUp(self):
        self.dept = f.make_dept()
        self.klass = f.make_class(self.dept)
        self.student = f.make_student(self.klass, usn='1CS001', name='Anita',
                                      username='anita')
        self.teacher = f.make_teacher(self.dept, id='t001', username='owner')
        self.admin = f.make_admin()
        self.fee = Fee.objects.create(
            student=self.student, fee_type='Tuition Fee',
            description='Semester 5', amount=Decimal('30000'),
            due_date=date(2026, 9, 1))

    def pay(self, amount='10000', mode='UPI', reference='UPI-99'):
        payment = FeeTransaction.objects.create(
            fee=self.fee, amount=Decimal(amount), mode=mode,
            reference=reference, paid_on=date(2026, 8, 10),
            received_by=self.admin)
        self.fee.recalculate_paid()
        return payment


class PaymentHistoryTests(Base):
    def test_the_student_page_lists_each_payment(self):
        """The transaction model landed without the page that shows it, so a
        student saw a balance drop with no record of when or how."""
        self.pay()
        self.client.force_login(self.student.user)

        response = self.client.get(reverse('fees', args=(self.student.pk,)))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'RCP-')
        self.assertContains(response, 'UPI-99')

    def test_a_fee_with_no_payments_shows_none(self):
        self.client.force_login(self.student.user)

        response = self.client.get(reverse('fees', args=(self.student.pk,)))

        self.assertNotContains(response, 'RCP-')

    def test_query_count_does_not_grow_with_payments(self):
        self.pay()
        self.client.force_login(self.student.user)
        url = reverse('fees', args=(self.student.pk,))

        # One of these is the topbar badge, which every page carries. It was
        # two until the bell became a notification inbox: counting unread
        # notices first had to work out the reader's role, and counting
        # their own notifications does not.
        with self.assertNumQueries(7):
            self.assertEqual(self.client.get(url).status_code, 200)

        for _ in range(5):
            self.pay(amount='1000')

        with self.assertNumQueries(7):
            self.assertEqual(self.client.get(url).status_code, 200)


class ReceiptTests(Base):
    def url(self, payment):
        return reverse('fee_receipt', args=(payment.id,))

    def test_it_returns_a_pdf_named_for_the_receipt(self):
        payment = self.pay()
        self.client.force_login(self.student.user)

        response = self.client.get(self.url(payment))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn(payment.receipt_no, response['Content-Disposition'])
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_another_student_cannot_download_it(self):
        payment = self.pay()
        other = f.make_student(self.klass, usn='1CS002', name='Bharat',
                               username='bharat')
        self.client.force_login(other.user)

        response = self.client.get(self.url(payment))

        self.assertEqual(response.status_code, 403)

    def test_an_admin_can_download_it(self):
        payment = self.pay()
        self.client.force_login(self.admin)

        self.assertEqual(self.client.get(self.url(payment)).status_code, 200)

    def test_nothing_is_drawn_outside_the_page(self):
        """Same guard as the marks card: content being in the file is not the
        same as content being on the paper."""
        import re

        from reportlab import rl_config
        from reportlab.lib.pagesizes import A4

        payment = self.pay()
        self.client.force_login(self.student.user)

        rl_config.pageCompression = 0
        try:
            body = self.client.get(self.url(payment)).content.decode('latin-1')
        finally:
            rl_config.pageCompression = 1

        drawn = re.findall(r'1 0 0 1 ([\d.]+) ([\d.]+) Tm \((.*?)\)\s*Tj',
                           body, re.S)
        self.assertTrue(drawn)
        for x, y, text in drawn:
            self.assertLessEqual(float(x), A4[0], '%r is off the right' % text)
            self.assertGreaterEqual(float(y), 0, text)

    def test_the_receipt_carries_the_payment_and_the_balance(self):
        import re

        from reportlab import rl_config

        payment = self.pay(amount='12000')
        self.client.force_login(self.student.user)

        rl_config.pageCompression = 0
        try:
            body = self.client.get(self.url(payment)).content.decode('latin-1')
        finally:
            rl_config.pageCompression = 1

        text = ' '.join(re.findall(r'\((.*?)\)\s*Tj', body, re.S))
        self.assertIn('12000', text, 'the amount being certified')
        self.assertIn('18000', text, 'the balance left')
        self.assertIn(payment.receipt_no, text)


class BulkFeeTests(Base):
    def setUp(self):
        super().setUp()
        self.second = f.make_student(self.klass, usn='1CS002', name='Bharat',
                                     username='bharat')
        self.third = f.make_student(self.klass, usn='1CS003', name='Chetan',
                                    username='chetan')
        self.client.force_login(self.admin)

    def payload(self, **overrides):
        data = {
            'class_id': self.klass.pk,
            'fee_type': 'Exam Fee',
            'description': 'Semester 5 exam',
            'amount': '2000',
            'due_date': '2026-10-01',
        }
        data.update(overrides)
        return data

    def post(self, **overrides):
        return self.client.post(reverse('add_class_fee'),
                                self.payload(**overrides), follow=True)

    def test_it_raises_the_fee_for_every_student_in_the_class(self):
        self.post()

        self.assertEqual(Fee.objects.filter(fee_type='Exam Fee').count(), 3)

    def test_running_it_twice_does_not_double_the_class_fees(self):
        """An easy mistake to make and an expensive one to undo."""
        self.post()
        self.post()

        self.assertEqual(Fee.objects.filter(fee_type='Exam Fee').count(), 3)

    def test_it_says_how_many_were_skipped(self):
        self.post()

        response = self.post()

        self.assertContains(response, 'already had this fee')

    def test_a_different_amount_is_a_different_fee(self):
        self.post()
        self.post(amount='2500')

        self.assertEqual(Fee.objects.filter(fee_type='Exam Fee').count(), 6)

    def test_a_zero_amount_is_rejected(self):
        response = self.client.post(reverse('add_class_fee'),
                                    self.payload(amount='0'))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Fee.objects.filter(fee_type='Exam Fee').exists())

    def test_a_student_cannot_raise_fees(self):
        self.client.force_login(self.student.user)

        self.client.post(reverse('add_class_fee'), self.payload())

        self.assertFalse(Fee.objects.filter(fee_type='Exam Fee').exists())

    def test_it_costs_a_fixed_number_of_queries(self):
        """One statement for the whole class, not one per student."""
        with self.assertNumQueries(6):
            self.client.post(reverse('add_class_fee'), self.payload())

        for n in range(4, 12):
            f.make_student(self.klass, usn='1CS0%02d' % n,
                           name='Student %d' % n, username='student%d' % n)

        with self.assertNumQueries(6):
            self.client.post(reverse('add_class_fee'),
                             self.payload(due_date='2026-11-01'))
