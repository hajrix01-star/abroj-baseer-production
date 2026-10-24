from decimal import Decimal
from unittest.mock import patch
from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged
from .test_profit_loss import TestProfitLoss


@tagged('post_install', '-at_install', 'reports_unified_drill')
class TestProfitLossDrill(TransactionCase):
    _entry = TestProfitLoss._entry
    _accountant = TestProfitLoss._accountant

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.report = self.env['baseer.profit.loss.report']
        self.filters = {'company_id': self.company.id, 'date_from': '2044-10-01', 'date_to': '2044-10-31', 'journal_ids': []}
        self.accounts = {}
        for index, kind in enumerate(('asset_cash', 'income', 'expense', 'expense_depreciation'), 1):
            account = self.env['account.account'].create({'code': '9625' + str(index), 'name': 'Drill ' + kind,
                'account_type': kind, 'company_ids': [Command.set(self.company.ids)]})
            self.accounts[kind] = account
        self.balance = self.accounts['asset_cash']
        self.journal = self.env['account.journal'].search([('company_id', '=', self.company.id), ('type', '=', 'general')], limit=1)
        self.sale = self._entry('income', 120, day='2044-10-10')
        self.expense_move = self._entry('expense', 40, day='2044-10-11')
        self._entry('expense_depreciation', 5, day='2044-10-12')
        self.reader = self._accountant()
        self.engine = self.env['baseer.report.drill'].with_user(self.reader)

    def test_every_summary_exact_signed_composition(self):
        report = self.report.with_user(self.reader).get_report(self.filters)
        for row in report['rows']:
            detail = self.engine.get_drilldown('profit_loss', self.filters, {'kind': 'row', 'row_key': row['key'], 'period_key': 'current'})
            self.assertEqual(detail['value'], row['amounts']['current']['amount'])
            self.assertEqual(sum((Decimal(item['cells']['amount'].replace(',', '')) for item in detail['rows']), Decimal('0')),
                             Decimal(detail['value'].replace(',', '')))
        expense = self.engine.get_drilldown('profit_loss', self.filters, {'kind': 'row', 'row_key': 'expense', 'period_key': 'current'})
        self.assertEqual(expense['value'], '45.00')
        self.assertEqual(expense['total_count'], 2)

    def test_account_and_unallocated_channel_provenance(self):
        selector = {'kind': 'account', 'account_id': self.accounts['income'].id, 'period_key': 'current'}
        result = self.engine.get_drilldown('profit_loss', self.filters, selector)
        self.assertEqual(result['value'], '120.00')
        self.assertEqual(self.engine.open_source('profit_loss', self.filters, result['rows'][0]['source'])['res_id'], self.sale.id)
        detail = self.report.with_user(self.reader).get_accounts(self.filters, 'income')
        channel = next(item for item in detail['accounts'] if item['id'] == self.accounts['income'].id)['channels'][0]
        result = self.engine.get_drilldown('profit_loss', self.filters, dict(selector, kind='channel', channel_key=channel['key']))
        self.assertEqual(result['value'], '120.00')
        token = result['rows'][0]['source']
        self.assertEqual(self.engine.open_source('profit_loss', self.filters, token)['res_id'], self.sale.id)
        with self.assertRaises(AccessError):
            self.engine.open_source('profit_loss', self.filters, dict(token, move_id=self.expense_move.id))

    def test_invalid_selectors_company_period_and_zero(self):
        selector = {'kind': 'row', 'row_key': 'net_income', 'period_key': 'current'}
        for invalid in [dict(selector, domain=[]), dict(selector, row_key='missing'), {'kind': 'account', 'account_id': True, 'period_key': 'current'}]:
            with self.assertRaises(ValidationError):
                self.engine.get_drilldown('profit_loss', self.filters, invalid)
        with self.assertRaises(AccessError):
            self.engine.get_drilldown('profit_loss', dict(self.filters, company_id=self.company.id + 999), selector)
        with self.assertRaises(AccessError):
            self.engine.get_drilldown('profit_loss', self.filters, dict(selector, period_key='missing'))
        zero = self.engine.get_drilldown('profit_loss', self.filters, dict(selector, row_key='other_income'))
        self.assertEqual(zero['value'], '0.00')
        self.assertEqual(zero['rows'], [])

    def test_comparison_only_channel_keeps_name_at_zero(self):
        filters = dict(self.filters, comparison={'kind': 'previous_period', 'count': 1, 'order': 'descending'})
        report = self.report.with_user(self.reader)
        channels = {self.accounts['income'].id: {'payment_9': ('Card', Decimal('120'))}}
        # Selected period, then current-period scope, then comparison-period scope.
        with patch.object(type(report), '_revenue_channels', side_effect=[{}, {}, channels]):
            detail = report._get_drilldown(filters, {'kind': 'channel', 'account_id': self.accounts['income'].id,
                'channel_key': 'payment_9', 'period_key': 'current'})
        self.assertIn('Card', detail['title'])
        self.assertEqual(detail['value'], '0.00')
        self.assertEqual(detail['rows'], [])
