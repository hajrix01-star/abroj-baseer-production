"""Narrow posted sales-receipt and fail-closed census evidence."""

from collections import Counter
from datetime import date
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.baseer_profit_loss_report.models.profit_loss import SECTION_KEYS
from ..models.operations import BaseerOperationsReport


@tagged('post_install', '-at_install')
class TestOperationsSalesCensus(TransactionCase):

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.company.partner_id.tz = 'UTC'
        self.report = self.env['baseer.operations.report']
        self.receivable = self._account('959101', 'asset_receivable', True)
        self.income = self._account('959102', 'income')
        self.tax_account = self._account('959103', 'liability_current')
        self.partner = self.env['res.partner'].with_company(self.company).create({
            'name': 'Gross operations receipt customer',
            'property_account_receivable_id': self.receivable.id,
        })
        self.journal = self.env['account.journal'].with_company(self.company).create({
            'name': 'Gross operations receipt sales', 'code': 'GOR',
            'type': 'sale', 'company_id': self.company.id,
        })
        self.tax = self.env['account.tax'].with_company(self.company).create({
            'name': 'Gross operations receipt VAT', 'amount_type': 'percent',
            'amount': 15, 'type_tax_use': 'sale', 'company_id': self.company.id,
        })
        self.tax.invoice_repartition_line_ids.filtered(
            lambda line: line.repartition_type == 'tax',
        ).write({'account_id': self.tax_account.id})

    def _account(self, code, kind, reconcile=False):
        return self.env['account.account'].with_company(self.company).create({
            'code': code, 'name': 'Gross operations ' + code,
            'account_type': kind, 'reconcile': reconcile,
            'company_ids': [Command.set(self.company.ids)],
        })

    def _receipt(self, invoice_date, post=True):
        receipt = self.env['account.move'].with_company(self.company).create({
            'move_type': 'out_receipt', 'partner_id': self.partner.id,
            'journal_id': self.journal.id, 'invoice_date': invoice_date,
            'invoice_line_ids': [Command.create({
                'name': 'VAT-inclusive receipt', 'quantity': 1,
                'price_unit': 100, 'account_id': self.income.id,
                'tax_ids': [Command.set(self.tax.ids)],
            })],
        })
        if post:
            receipt.action_post()
        return receipt

    def _snapshot(self, start, end, company_id=None):
        return self.report._build_source_snapshot({
            'company_id': company_id or self.company.id,
            'date_from': start, 'date_to': end, 'journal_ids': [],
        })

    def test_posted_receipt_counts_115_on_issue_day_only(self):
        receipt = self._receipt('2041-06-10')
        self._receipt('2041-06-12', post=False)
        june = self._snapshot('2041-06-01', '2041-06-30')
        july = self._snapshot('2041-07-01', '2041-07-31')
        income = next(row for row in june['periods'][0]['rows']
                      if row['key'] == 'income')
        self.assertEqual(income['amount'], '115.00')
        self.assertEqual(june['periods'][0]['excluded']['census_sales_documents'], 1)
        self.assertTrue(june['coverage_complete'])
        self.assertFalse(june['complete'])
        self.assertEqual(next(row for row in july['periods'][0]['rows']
                              if row['key'] == 'income')['amount'], '0.00')
        account = june['periods'][0]['accounts']['income'][0]
        detail = self.report._build_account_events(
            {'company_id': self.company.id, 'date_from': '2041-06-01',
             'date_to': '2041-06-30', 'journal_ids': []},
            'income', self.income.id, june['periods'][0]['key'],
            account['fingerprint'],
        )
        self.assertEqual(detail['total_count'], 1)
        self.assertEqual(detail['events'][0]['source_id'], receipt.id)
        self.assertEqual(detail['events'][0]['date'], '2041-06-10')

    def test_coverage_is_closed_for_unknown_or_unproven_sources(self):
        self.assertTrue(self.report._coverage_complete(Counter({
            'linked_pos_invoice': 1, 'proven_internal_transfer': 2,
            'unconfirmed_payment_link': 1, 'census_sales_documents': 1,
        })))
        for key in ('unproven_liquidity_outflow',
                    'unproven_foreign_sales_document',
                    'unsupported_new_source'):
            self.assertFalse(self.report._coverage_complete(Counter({key: 1})))

    def test_public_report_and_details_hide_unproven_amounts(self):
        self._receipt('2041-06-10')
        filters = {'company_id': self.company.id,
                   'date_from': '2041-06-01', 'date_to': '2041-06-30',
                   'journal_ids': []}
        proven = self.report.get_source_snapshot(filters)
        self.assertTrue(proven['complete'])
        self.assertEqual(next(row for row in proven['periods'][0]['rows']
                              if row['key'] == 'income')['amount'], '115.00')
        account = proven['periods'][0]['accounts']['income'][0]
        self.assertEqual(self.report.get_account_events(
            filters, 'income', self.income.id, proven['periods'][0]['key'],
            account['fingerprint'],
        )['total_count'], 1)
        with patch.object(BaseerOperationsReport, '_coverage_complete',
                          return_value=False):
            hidden = self.report.get_source_snapshot(filters)
            self.assertFalse(hidden['complete'])
            self.assertNotIn('rows', hidden['periods'][0])
            self.assertNotIn('accounts', hidden['periods'][0])
            with self.assertRaises(AccessError):
                self.report.get_account_events(
                    filters, 'income', self.income.id,
                    proven['periods'][0]['key'], account['fingerprint'],
                )
            with self.assertRaises(AccessError):
                self.env['report.baseer_operations_report.operations_pdf_portrait']._get_report_values(
                    [], {'filters': filters},
                )

    def test_census_rejects_a_posted_receipt_without_its_counted_event(self):
        self._receipt('2041-06-10')
        start, end = date(2041, 6, 1), date(2041, 6, 30)
        moves = self.report._invoice_records(self.company, start, end, [])
        with self.assertRaises(AccessError):
            self.report._sales_census(
                self.company, start, end, [], moves,
                self.env['pos.order'].browse(),
                {key: {} for key in SECTION_KEYS}, Counter(),
            )

    def test_active_company_scope_cannot_be_overridden(self):
        other = self.env['res.company'].create({
            'name': 'Gross operations unrelated sales company',
        })
        with self.assertRaises(AccessError):
            self._snapshot('2041-06-01', '2041-06-30', other.id)
