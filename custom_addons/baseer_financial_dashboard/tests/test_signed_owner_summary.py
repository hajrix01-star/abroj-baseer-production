"""Pure arithmetic regression tests; source evidence is tested separately."""

from decimal import Decimal
from unittest import TestCase

from odoo.addons.baseer_financial_dashboard.models.signed_owner_summary import build_signed_owner_summary


class TestSignedOwnerSummary(TestCase):
    def setUp(self):
        self.payment = {
            'company_id': 3, 'direction': 'outgoing', 'source_model': 'account.payment',
            'source_id': 40, 'line_model': 'account.move.line', 'line_id': 80,
            'payment_line_id': 81, 'amount': Decimal('1707.75'),
            'classification': 'unconfirmed_bill_classification',
        }
        self.sale = {
            'company_id': 3, 'direction': 'incoming', 'source_model': 'account.move',
            'source_id': 70, 'line_model': 'account.move.line', 'line_id': 90,
            'amount': Decimal('2000.00'),
            'channels': [('card', 'Card', Decimal('2000.00'))],
        }
        self.refund = {
            'company_id': 3, 'direction': 'outgoing', 'source_model': 'account.move',
            'source_id': 44, 'line_model': 'account.move.line', 'line_id': 82,
            'payment_line_id': 82, 'amount': Decimal('-1707.75'),
            'classification': 'unconfirmed_bill_classification',
            'reversal_move_id': 44, 'original_move_id': 41,
            'original_payment_line_id': 81, 'original_amount': Decimal('1707.75'),
            'original_classification': 'unconfirmed_bill_classification',
        }

    def calculate(self, events=None, positive=None, reversals=None, negative=None):
        return build_signed_owner_summary(
            [self.sale, self.payment] if events is None else events,
            {81: Decimal('1707.75')} if positive is None else positive,
            [self.refund] if reversals is None else reversals,
            {82: Decimal('-1707.75')} if negative is None else negative,
            company_id=3,
        )

    def test_same_period_reversal_nets_cash_without_changing_sales(self):
        result = self.calculate()
        self.assertEqual(result['incoming_total'], Decimal('2000.00'))
        self.assertEqual(result['cash_total'], Decimal('0.00'))
        self.assertEqual(result['difference'], Decimal('2000.00'))
        self.assertEqual(result['channels'][0]['amount'], Decimal('2000.00'))
        self.assertEqual(result['outflow_buckets'][0]['amount'], Decimal('0.00'))
        self.assertEqual(result['cash_event_count'], 2)

    def test_reversal_in_a_later_period_can_have_negative_net_payments(self):
        result = self.calculate(events=[self.sale], positive={})
        self.assertEqual(result['incoming_total'], Decimal('2000.00'))
        self.assertEqual(result['cash_total'], Decimal('-1707.75'))
        self.assertEqual(result['difference'], Decimal('3707.75'))
        self.assertEqual(result['outflow_buckets'][0]['amount'], Decimal('-1707.75'))

    def test_payment_period_without_reversal_stays_positive(self):
        result = self.calculate(reversals=[], negative={})
        self.assertEqual(result['cash_total'], Decimal('1707.75'))
        self.assertEqual(result['difference'], Decimal('292.25'))

    def test_reject_company_float_partial_and_different_original(self):
        for changed in (
            {'company_id': 2}, {'amount': -1707.75}, {'original_amount': Decimal('1707.74')},
            {'amount': Decimal('-1707.7')}, {'original_payment_line_id': 82},
            {'source_model': 'account.payment'}, {'source_id': 45},
            {'classification': 'purchase'}, {'channels': [('card', 'Card', Decimal('1.00'))]},
        ):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.calculate(reversals=[{**self.refund, **changed}])

    def test_reject_reused_witness_unmatched_witness_and_duplicate_reversal(self):
        invalid = (
            ([self.refund, self.refund], {82: Decimal('-1707.75')}),
            ([self.refund], {82: Decimal('-1707.75'), 83: Decimal('-1.00')}),
            ([{**self.refund, 'line_id': 81, 'payment_line_id': 81,
               'original_payment_line_id': 88}], {81: Decimal('-1707.75')}),
        )
        for reversals, witnesses in invalid:
            with self.subTest(reversals=reversals), self.assertRaises(ValueError):
                self.calculate(reversals=reversals, negative=witnesses)

    def test_reject_cross_linked_reversal_chain(self):
        other = {**self.refund, 'line_id': 83, 'payment_line_id': 83,
                 'source_id': 45, 'reversal_move_id': 45,
                 'original_move_id': 44, 'original_payment_line_id': 82}
        with self.assertRaises(ValueError):
            self.calculate(reversals=[self.refund, other],
                           negative={82: Decimal('-1707.75'), 83: Decimal('-1707.75')})

    def test_reject_single_pass_event_iterator(self):
        with self.assertRaises(ValueError):
            self.calculate(events=iter([self.sale, self.payment]))

    def test_reject_when_original_payment_is_confirmed(self):
        original = {**self.payment, 'classification': 'operating_account',
                    'account_id': 99, 'account_name': 'Confirmed expense'}
        with self.assertRaises(ValueError):
            self.calculate(events=[self.sale, original])

    def test_later_period_requires_explicit_original_classification(self):
        missing = dict(self.refund)
        del missing['original_classification']
        for refund in (missing, {**self.refund, 'original_classification': 'purchase'}):
            with self.subTest(refund=refund), self.assertRaises(ValueError):
                self.calculate(events=[self.sale], positive={}, reversals=[refund])
