"""Server-only contract tests for the private owner-summary snapshot."""

from decimal import Decimal, localcontext
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged

from . import test_owner_cash


@tagged('post_install', '-at_install', 'operations_owner_report')
class TestOperationsOwnerReport(TransactionCase):
    # Reuse the real posted-statement fixture builder without inheriting its suite.
    _statement = test_owner_cash.TestOwnerCash._statement

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.report = self.env['baseer.operations.report']
        self.expense = self.env['account.account'].with_company(self.company).create({
            'code': '959201',
            'name': 'Owner snapshot operating expense',
            'account_type': 'expense',
            'company_ids': [Command.set(self.company.ids)],
        })
        self.bank = self.env['account.journal'].with_company(self.company).search([
            ('company_id', '=', self.company.id), ('type', '=', 'bank'),
        ], limit=1)
        self.assertTrue(self.bank and self.bank.default_account_id)
        self.partner = self.env['res.partner'].with_company(self.company).create({
            'name': 'Owner snapshot statement partner',
        })
        self.filters = {
            'company_id': self.company.id,
            'date_from': '2026-06-01',
            'date_to': '2026-06-30',
            'journal_ids': [],
        }

    @staticmethod
    def _keys(value):
        if isinstance(value, dict):
            yield from value
            for item in value.values():
                yield from TestOperationsOwnerReport._keys(item)
        elif isinstance(value, list):
            for item in value:
                yield from TestOperationsOwnerReport._keys(item)

    @staticmethod
    def _amounts(period):
        return {row['key']: row['amount'] for row in period['totals']}

    def test_actual_posted_cash_snapshot_is_fresh_and_never_exposes_source_ids(self):
        self._statement('40.00')
        first = self.report.get_owner_snapshot(self.filters)
        self.assertTrue(first['complete'])
        self.assertEqual(first['source_basis'], 'recorded_sales_headers_and_posted_cash')
        first_period = first['periods'][0]
        self.assertEqual(self._amounts(first_period), {
            'incoming_total': '0.00', 'cash_total': '40.00', 'difference': '-40.00',
        })
        self.assertEqual(sum((Decimal(row['amount'].replace(',', ''))
                              for row in first_period['outflows']), Decimal('0.00')),
                         Decimal('40.00'))
        self.assertFalse(first_period['has_unclassified_outflows'])
        self.assertFalse({'source_id', 'line_id', 'payment_line_id', 'move_id'}
                         .intersection(set(self._keys(first))))

        self._statement('10.00', day='2026-06-19')
        second = self.report.get_owner_snapshot(self.filters)
        self.assertEqual(self._amounts(second['periods'][0])['cash_total'], '50.00')
        self.assertEqual(self._amounts(second['periods'][0])['difference'], '-50.00')

    def test_incomplete_adapter_hides_amounts_for_every_period(self):
        periods = [
            {'key': 'a', 'date_from': '2026-06-01', 'date_to': '2026-06-30',
             'label': 'June', 'display_label': 'June 2026'},
            {'key': 'b', 'date_from': '2026-07-01', 'date_to': '2026-07-31',
             'label': 'July', 'display_label': 'July 2026'},
        ]
        with patch.object(type(self.report), '_scope', return_value=(
                self.company, [], periods, {'kind': 'month'}, {'kind': 'none'})), \
                patch.object(type(self.report), '_owner_sales', return_value=[]), \
                patch.object(type(self.report), '_owner_cash', return_value={
                    'events': [], 'liquidity_totals': {}, 'excluded': {'unsupported': 1},
                    'coverage_complete': False,
                }):
            snapshot = self.report.get_owner_snapshot(self.filters)
        self.assertFalse(snapshot['complete'])
        self.assertFalse(snapshot['coverage_complete'])
        for period in snapshot['periods']:
            self.assertFalse(period['coverage_complete'])
            for hidden in ('totals', 'channels', 'outflows', 'has_unclassified_outflows'):
                self.assertNotIn(hidden, period)

    def test_active_company_and_context_selected_company_are_rejected_server_side(self):
        other = self.env['res.company'].create({'name': 'Owner snapshot other company'})
        with self.assertRaises(AccessError):
            self.report.get_owner_snapshot({**self.filters, 'company_id': other.id})
        with self.assertRaises(AccessError):
            self.report.with_context(
                allowed_company_ids=other.ids,
            ).get_owner_snapshot(self.filters)

    def test_labels_percentages_western_digits_and_low_precision_grouping(self):
        summary = {
            'incoming_total': Decimal('1234.50'),
            'cash_total': Decimal('20.00'),
            'difference': Decimal('1214.50'),
            'channels': [{
                'key': 'card', 'name': 'Card', 'amount': Decimal('1234.50'),
                'percentage': Decimal('100.00'),
            }],
            'outflow_buckets': [{
                'key': 'operating_account:7', 'classification': 'operating_account',
                'name': 'Utilities account', 'account_id': 7, 'amount': Decimal('20.00'),
                'count': 1,
            }],
            'has_unclassified_outflows': False,
        }
        english = self.report.with_context(lang='en_US')._owner_display(summary, self.company)
        arabic = self.report.with_context(lang='ar_001')._owner_display(summary, self.company)
        self.assertEqual(english['totals'][0]['label'], 'Sales')
        self.assertEqual(arabic['totals'][0]['label'], 'المبيعات')
        self.assertEqual(english['channels'][0]['amount'], '1,234.50')
        self.assertEqual(english['channels'][0]['percentage'], '100.00%')
        self.assertRegex(english['channels'][0]['amount'], r'^[0-9,.]+$')

        huge = Decimal('999999999999999999.99')
        precise = {
            'incoming_total': Decimal('0.00'), 'cash_total': huge, 'difference': -huge,
            'channels': [],
            'outflow_buckets': [
                {'key': 'operating_account:11', 'classification': 'operating_account',
                 'name': 'A', 'account_id': 11, 'amount': Decimal('999999999999999999.98'),
                 'count': 1},
                {'key': 'operating_account:12', 'classification': 'operating_account',
                 'name': 'B', 'account_id': 12, 'amount': Decimal('0.01'), 'count': 1},
            ],
            'has_unclassified_outflows': False,
        }
        with localcontext() as context:
            context.prec = 4
            displayed = self.report._owner_display(precise, self.company)
        self.assertEqual(displayed['outflows'][0]['amount'], '999,999,999,999,999,999.99')

