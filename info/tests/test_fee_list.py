from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from info.models import Fee
from info.tests import factories as f


class Base(TestCase):
    def setUp(self):
        self.dept = f.make_dept()
        self.klass = f.make_class(self.dept)
        self.other_class = f.make_class(self.dept, id='CS-3B', section='B')
        self.admin = f.make_admin()
        self.today = timezone.localdate()
        self.client.force_login(self.admin)

    def student(self, usn, name, klass=None):
        return f.make_student(klass or self.klass, usn=usn, name=name,
                              username=usn.lower())

    def fee(self, student, amount='1000', paid='0', due_days=30,
            fee_type='Tuition Fee'):
        record = Fee.objects.create(
            student=student, fee_type=fee_type, amount=Decimal(amount),
            paid_amount=Decimal(paid),
            due_date=self.today + timedelta(days=due_days))
        return record

    def get(self, **params):
        url = reverse('t_fees')
        if params:
            url += '?' + '&'.join('%s=%s' % kv for kv in params.items())
        return self.client.get(url)


class FilterTests(Base):
    def setUp(self):
        super().setUp()
        self.anita = self.student('1CS001', 'Anita')
        self.bharat = self.student('1CS002', 'Bharat')
        self.chetan = self.student('1CS003', 'Chetan', self.other_class)
        self.unpaid = self.fee(self.anita, amount='1000', paid='0')
        self.partial = self.fee(self.bharat, amount='1000', paid='400')
        self.paid = self.fee(self.chetan, amount='1000', paid='1000',
                             fee_type='Exam Fee')
        self.overdue = self.fee(self.anita, amount='500', paid='0',
                                due_days=-10)

    def rows(self, response):
        return list(response.context['page'])

    def test_unpaid_filter(self):
        rows = self.rows(self.get(status='unpaid'))

        self.assertCountEqual(rows, [self.unpaid, self.overdue])

    def test_partial_filter(self):
        self.assertEqual(self.rows(self.get(status='partial')), [self.partial])

    def test_paid_filter(self):
        self.assertEqual(self.rows(self.get(status='paid')), [self.paid])

    def test_overdue_cuts_across_the_status_values(self):
        self.assertEqual(self.rows(self.get(status='overdue')), [self.overdue])

    def test_a_fully_waived_zero_fee_counts_as_paid(self):
        """The status property had this backwards once - a zero fee reported
        unpaid for ever and could never reach paid."""
        waived = self.fee(self.bharat, amount='0', paid='0')

        self.assertIn(waived, self.rows(self.get(status='paid')))
        self.assertNotIn(waived, self.rows(self.get(status='unpaid')))

    def test_filter_by_fee_type(self):
        self.assertEqual(self.rows(self.get(fee_type='Exam Fee')), [self.paid])

    def test_filter_by_class(self):
        rows = self.rows(self.get(class_id=self.other_class.pk))

        self.assertEqual(rows, [self.paid])

    def test_search_by_name_or_usn(self):
        self.assertCountEqual(self.rows(self.get(q='Anita')),
                              [self.unpaid, self.overdue])
        self.assertCountEqual(self.rows(self.get(q='1CS002')), [self.partial])

    def test_filters_combine(self):
        rows = self.rows(self.get(q='Anita', status='overdue'))

        self.assertEqual(rows, [self.overdue])


class TotalsTests(Base):
    def setUp(self):
        super().setUp()
        self.anita = self.student('1CS001', 'Anita')
        self.fee(self.anita, amount='1000', paid='400')
        self.fee(self.anita, amount='500', paid='500')

    def test_totals_are_raised_collected_and_outstanding(self):
        totals = self.get().context['totals']

        self.assertEqual(totals['raised'], Decimal('1500'))
        self.assertEqual(totals['collected'], Decimal('900'))
        self.assertEqual(totals['outstanding'], Decimal('600'))

    def test_totals_follow_the_filters_rather_than_the_page(self):
        """A summary that changed as you paged would be worse than none."""
        totals = self.get(status='paid').context['totals']

        self.assertEqual(totals['raised'], Decimal('500'))
        self.assertEqual(totals['collected'], Decimal('500'))
        self.assertEqual(totals['outstanding'], Decimal('0'))

    def test_totals_on_an_empty_result_are_zero_not_none(self):
        totals = self.get(q='nobody').context['totals']

        self.assertEqual(totals['raised'], Decimal('0'))
        self.assertEqual(totals['outstanding'], Decimal('0'))


class PaginationTests(Base):
    def setUp(self):
        super().setUp()
        anita = self.student('1CS001', 'Anita')
        for _ in range(30):
            self.fee(anita, amount='100')

    def test_the_page_is_capped(self):
        """The view returned every fee record in the institution."""
        page = self.get().context['page']

        self.assertEqual(len(page), 25)
        self.assertEqual(page.paginator.count, 30)

    def test_the_second_page_has_the_rest(self):
        self.assertEqual(len(self.get(page=2).context['page']), 5)

    def test_filters_survive_paging(self):
        response = self.get(page=2, status='unpaid')

        self.assertIn('status=unpaid', response.context['querystring'])
        self.assertNotIn('page=', response.context['querystring'])

    def test_query_count_does_not_grow_with_the_number_of_records(self):
        url = reverse('t_fees')

        with self.assertNumQueries(10):
            self.assertEqual(self.client.get(url).status_code, 200)

        anita = self.student('1CS009', 'Extra')
        for _ in range(40):
            self.fee(anita, amount='100')

        with self.assertNumQueries(10):
            self.assertEqual(self.client.get(url).status_code, 200)


class AccessTests(Base):
    def test_a_student_cannot_open_the_staff_list(self):
        student = self.student('1CS001', 'Anita')
        self.client.force_login(student.user)

        response = self.client.get(reverse('t_fees'))

        self.assertEqual(response.status_code, 302)
