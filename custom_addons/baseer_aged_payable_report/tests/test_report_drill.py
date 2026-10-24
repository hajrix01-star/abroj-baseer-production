from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from odoo.exceptions import AccessError, ValidationError
from odoo import Command
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'reports_unified_drill')
class TestAgedPayableDrill(TransactionCase):
    def setUp(self):
        super().setUp()
        self.report = self.env['baseer.aged.payable.report']
        self.filters = {'company_id': self.env.company.id, 'cutoff_date': '2026-10-23'}
        self.snapshot = {
            'currency': SimpleNamespace(rounding=0.01, decimal_places=2),
            'partners': [{'id': 8, 'name': 'Supplier'}],
            'all_rows': [
                {'id': 21, 'partner_id': 8, 'date': '2026-10-01', 'date_maturity': '',
                 'move_name': 'BILL/21', 'bucket': 'not_due', 'counter_age_bucket': '', 'amount': Decimal('75')},
                {'id': 22, 'partner_id': 8, 'date': '2026-10-02', 'date_maturity': '',
                 'move_name': 'DB/22', 'bucket': 'counter', 'counter_age_bucket': 'd1_30', 'amount': Decimal('-5')},
            ],
        }

    def test_signed_counter_magnitude_and_zero_bucket(self):
        with patch.object(type(self.report), '_snapshot', return_value=self.snapshot):
            counters = self.report._get_drilldown(self.filters, {'kind': 'summary', 'metric': 'counter_balances'}, 1)
            zero = self.report._get_drilldown(self.filters, {'kind': 'bucket', 'side': 'payable', 'bucket': 'over_90'}, 1)
        self.assertEqual(counters['value'], '5.00')
        self.assertEqual(counters['rows'][0]['cells']['open'], '-5.00')
        self.assertEqual(zero['rows'], [])

    def test_tampered_selector_and_foreign_company_are_denied(self):
        with patch.object(type(self.report), '_snapshot', return_value=self.snapshot):
            with self.assertRaises(ValidationError):
                self.report._get_drilldown(self.filters, {'kind': 'summary', 'metric': []}, 1)
            with self.assertRaises(ValidationError):
                self.report._get_drilldown(self.filters, {'kind': 'bucket', 'side': 'counter', 'bucket': []}, 1)
        with self.assertRaises(AccessError):
            self.report._get_drilldown({**self.filters, 'company_id': self.env.company.id + 999999},
                                       {'kind': 'summary', 'metric': 'net'}, 1)

    def test_central_dispatch_rebuilds_actual_cutoff_and_rechecks_source_membership(self):
        Account = self.env['account.account'].with_company(self.env.company)
        payable = Account.create({'code': '968901', 'name': 'AP drill', 'account_type': 'liability_payable',
                                  'reconcile': True, 'company_ids': [Command.set(self.env.company.ids)]})
        expense = Account.create({'code': '968902', 'name': 'AP expense', 'account_type': 'expense',
                                  'company_ids': [Command.set(self.env.company.ids)]})
        bank = Account.create({'code': '968903', 'name': 'AP bank', 'account_type': 'asset_cash',
                               'company_ids': [Command.set(self.env.company.ids)]})
        partner = self.env['res.partner'].create({'name': 'AP drill partner', 'property_account_payable_id': payable.id})
        journal = self.env['account.journal'].search([('company_id', '=', self.env.company.id), ('type', '=', 'purchase')], limit=1)
        move = self.env['account.move'].create({'move_type': 'in_invoice', 'partner_id': partner.id, 'journal_id': journal.id,
            'date': '2026-10-01', 'invoice_date': '2026-10-01', 'invoice_date_due': '2026-10-01',
            'invoice_line_ids': [Command.create({'name': 'source', 'quantity': 1, 'price_unit': 15, 'account_id': expense.id,
                                                  'tax_ids': [Command.clear()]})]})
        move.action_post()
        payable_line = move.line_ids.filtered(lambda line: line.account_id == payable)
        general = self.env['account.journal'].search([('company_id', '=', self.env.company.id), ('type', '=', 'general')], limit=1)
        payment = self.env['account.move'].create({'date': '2026-10-20', 'journal_id': general.id, 'move_type': 'entry',
            'line_ids': [Command.create({'name': 'settlement', 'account_id': payable.id, 'debit': 5, 'partner_id': partner.id}),
                         Command.create({'name': 'bank', 'account_id': bank.id, 'credit': 5, 'partner_id': partner.id})]})
        payment._post(soft=False)
        payment_line = payment.line_ids.filtered(lambda line: line.account_id == payable)
        (payable_line + payment_line).reconcile()
        filters = {'company_id': self.env.company.id, 'cutoff_date': '2026-10-23'}
        result = self.env['baseer.report.drill'].get_drilldown('aged_payable', filters, {'kind': 'summary', 'metric': 'payables'}, 1)
        self.assertEqual(result['value'], '10.00')
        earlier = self.env['baseer.report.drill'].get_drilldown('aged_payable', {**filters, 'cutoff_date': '2026-10-15'}, {'kind': 'summary', 'metric': 'payables'}, 1)
        bucket = self.env['baseer.report.drill'].get_drilldown('aged_payable', filters, {'kind': 'bucket', 'side': 'payable', 'bucket': 'd1_30'}, 1)
        partner_detail = self.env['baseer.report.drill'].get_drilldown('aged_payable', filters, {'kind': 'partner', 'partner_id': partner.id, 'metric': 'payables'}, 1)
        self.assertEqual(earlier['value'], '15.00')
        self.assertEqual(bucket['value'], partner_detail['value'])
        action = self.env['baseer.report.drill'].open_source('aged_payable', filters, result['rows'][0]['source'])
        self.assertEqual(action['res_model'], 'account.move.line')
        self.assertEqual(action['views'], [[False, 'list'], [False, 'form']])
        expense_line = move.line_ids.filtered(lambda line: line.account_id == expense)
        with self.assertRaises(AccessError):
            self.env['baseer.report.drill'].open_source('aged_payable', filters, {**result['rows'][0]['source'], 'line_id': expense_line.id})
