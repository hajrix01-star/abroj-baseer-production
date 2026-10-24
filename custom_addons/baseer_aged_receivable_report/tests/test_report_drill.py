from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from odoo.exceptions import AccessError, ValidationError
from odoo import Command
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'reports_unified_drill')
class TestAgedReceivableDrill(TransactionCase):
    def setUp(self):
        super().setUp()
        self.report = self.env['baseer.aged.receivable.report']
        self.filters = {'company_id': self.env.company.id, 'cutoff_date': '2026-10-23'}
        self.snapshot = {
            'currency': SimpleNamespace(rounding=0.01, decimal_places=2),
            'partners': [{'id': 7, 'name': 'Customer'}, {'id': False, 'name': 'Unassigned'}],
            'all_rows': [
                {'id': 11, 'partner_id': 7, 'date': '2026-10-01', 'date_maturity': '',
                 'move_name': 'INV/11', 'bucket': 'not_due', 'credit_age_bucket': '', 'amount': Decimal('100')},
                {'id': 12, 'partner_id': 7, 'date': '2026-10-02', 'date_maturity': '',
                 'move_name': 'CN/12', 'bucket': 'credit', 'credit_age_bucket': 'd1_30', 'amount': Decimal('-20')},
            ],
        }

    def test_signed_summary_credit_magnitude_and_zero_bucket(self):
        with patch.object(type(self.report), '_snapshot', return_value=self.snapshot):
            receivables = self.report._get_drilldown(self.filters, {'kind': 'summary', 'metric': 'receivables'}, 1)
            credits = self.report._get_drilldown(self.filters, {'kind': 'summary', 'metric': 'credits'}, 1)
            zero = self.report._get_drilldown(self.filters, {'kind': 'bucket', 'side': 'receivable', 'bucket': 'over_90'}, 1)
        self.assertEqual(receivables['value'], '100.00')
        self.assertEqual(credits['value'], '20.00')
        self.assertEqual(credits['rows'][0]['cells']['open'], '-20.00')
        self.assertEqual(zero['value'], '0.00')
        self.assertEqual(zero['rows'], [])

    def test_tampered_selector_and_foreign_company_are_denied(self):
        with patch.object(type(self.report), '_snapshot', return_value=self.snapshot):
            with self.assertRaises(ValidationError):
                self.report._get_drilldown(self.filters, {'kind': 'summary', 'metric': []}, 1)
            with self.assertRaises(ValidationError):
                self.report._get_drilldown(self.filters, {'kind': 'bucket', 'side': {}, 'bucket': 'not_due'}, 1)
        with self.assertRaises(AccessError):
            self.report._get_drilldown({**self.filters, 'company_id': self.env.company.id + 999999},
                                       {'kind': 'summary', 'metric': 'net'}, 1)

    def test_central_dispatch_rebuilds_actual_cutoff_and_rechecks_source_membership(self):
        Account = self.env['account.account'].with_company(self.env.company)
        receivable = Account.create({'code': '968801', 'name': 'AR drill', 'account_type': 'asset_receivable',
                                     'reconcile': True, 'company_ids': [Command.set(self.env.company.ids)]})
        income = Account.create({'code': '968802', 'name': 'AR income', 'account_type': 'income',
                                 'company_ids': [Command.set(self.env.company.ids)]})
        bank = Account.create({'code': '968804', 'name': 'AR bank', 'account_type': 'asset_cash',
                               'company_ids': [Command.set(self.env.company.ids)]})
        loan = Account.create({'code': '968803', 'name': 'AR loan', 'account_type': 'asset_receivable',
                               'company_ids': [Command.set(self.env.company.ids)]})
        self.env.company.baseer_loan_account_id = loan
        partner = self.env['res.partner'].create({'name': 'AR drill partner', 'property_account_receivable_id': receivable.id})
        journal = self.env['account.journal'].search([('company_id', '=', self.env.company.id), ('type', '=', 'sale')], limit=1)
        move = self.env['account.move'].create({'move_type': 'out_invoice', 'partner_id': partner.id, 'journal_id': journal.id,
            'date': '2026-10-01', 'invoice_date': '2026-10-01', 'invoice_date_due': '2026-10-01',
            'invoice_line_ids': [Command.create({'name': 'source', 'quantity': 1, 'price_unit': 25, 'account_id': income.id,
                                                  'tax_ids': [Command.clear()]})]})
        move.action_post()
        receivable_line = move.line_ids.filtered(lambda line: line.account_id == receivable)
        general = self.env['account.journal'].search([('company_id', '=', self.env.company.id), ('type', '=', 'general')], limit=1)
        payment = self.env['account.move'].create({'date': '2026-10-20', 'journal_id': general.id, 'move_type': 'entry',
            'line_ids': [Command.create({'name': 'bank', 'account_id': bank.id, 'debit': 10, 'partner_id': partner.id}),
                         Command.create({'name': 'settlement', 'account_id': receivable.id, 'credit': 10, 'partner_id': partner.id})]})
        payment._post(soft=False)
        payment_line = payment.line_ids.filtered(lambda line: line.account_id == receivable)
        (receivable_line + payment_line).reconcile()
        filters = {'company_id': self.env.company.id, 'cutoff_date': '2026-10-23'}
        result = self.env['baseer.report.drill'].get_drilldown('aged_receivable', filters, {'kind': 'summary', 'metric': 'receivables'}, 1)
        self.assertEqual(result['value'], '15.00')
        earlier = self.env['baseer.report.drill'].get_drilldown('aged_receivable', {**filters, 'cutoff_date': '2026-10-15'}, {'kind': 'summary', 'metric': 'receivables'}, 1)
        bucket = self.env['baseer.report.drill'].get_drilldown('aged_receivable', filters, {'kind': 'bucket', 'side': 'receivable', 'bucket': 'd1_30'}, 1)
        partner_detail = self.env['baseer.report.drill'].get_drilldown('aged_receivable', filters, {'kind': 'partner', 'partner_id': partner.id, 'metric': 'receivables'}, 1)
        self.assertEqual(earlier['value'], '25.00')
        self.assertEqual(bucket['value'], partner_detail['value'])
        action = self.env['baseer.report.drill'].open_source('aged_receivable', filters, result['rows'][0]['source'])
        self.assertEqual(action['res_model'], 'account.move.line')
        income_line = move.line_ids.filtered(lambda line: line.account_id == income)
        with self.assertRaises(AccessError):
            self.env['baseer.report.drill'].open_source('aged_receivable', filters, {**result['rows'][0]['source'], 'line_id': income_line.id})
