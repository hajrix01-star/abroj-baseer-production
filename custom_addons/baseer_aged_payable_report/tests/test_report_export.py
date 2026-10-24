from datetime import date
from decimal import Decimal
import os
from pathlib import Path
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'reports_unified_export')
class TestAgedPayableUnifiedExport(TransactionCase):
    def setUp(self):
        super().setUp()
        self.env['res.lang']._activate_lang('ar_001')
        self.company = self.env.company
        self.report = self.env['baseer.aged.payable.report']
        Account = self.env['account.account'].with_company(self.company)
        def account(code, kind, reconcile=False):
            return Account.create({'code': code, 'name': f'AP export {code}', 'account_type': kind,
                                   'reconcile': reconcile, 'company_ids': [Command.set(self.company.ids)]})
        self.payable = account('957811', 'liability_payable', True)
        self.expense = account('957812', 'expense')
        self.partner = self.env['res.partner'].with_company(self.company).create({
            'name': 'AP export supplier', 'property_account_payable_id': self.payable.id})
        self.journal = self.env['account.journal'].with_company(self.company).search([
            ('company_id', '=', self.company.id), ('type', '=', 'purchase')], limit=1)
        self.assertTrue(self.journal)

    def _invoice(self, amount, move_type='in_invoice'):
        move = self.env['account.move'].with_company(self.company).create({
            'move_type': move_type, 'partner_id': self.partner.id, 'journal_id': self.journal.id,
            'invoice_date': '2025-01-10', 'invoice_date_due': '2025-01-10',
            'invoice_line_ids': [Command.create({'name': 'AP export line', 'quantity': 1,
                                                  'price_unit': amount, 'account_id': self.expense.id})],
        })
        move.action_post()

    def _readonly(self):
        return self.env['res.users'].create({
            'name': 'AP export reader', 'login': 'ap_export_reader', 'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)], 'group_ids': [Command.set([
                self.env.ref('base.group_user').id, self.env.ref('account.group_account_readonly').id])],
        })

    @staticmethod
    def _evidence(name, payload):
        target = os.environ.get('BASEER_EXPORT_EVIDENCE_DIR')
        if target and os.path.isdir(target):
            Path(target, name).write_bytes(payload)

    def test_actual_cutoff_collector_exports_every_historical_line_for_normal_reader(self):
        self._invoice(100)
        self._invoice(20, 'in_refund')
        filters = {'company_id': self.company.id, 'cutoff_date': '2025-01-31', 'page': 1}
        document = self.report._get_export_document(filters)
        detail = next(row for row in document['rows'] if row['kind'] == 'detail')
        self.assertEqual(detail['cells']['open'], Decimal('100.00'))
        self.assertEqual([row['cells']['open'] for row in document['rows'][-3:]],
                         [Decimal('100.00'), Decimal('20.00'), Decimal('80.00')])
        self.assertEqual(self.report.with_user(self._readonly()).with_context(
            allowed_company_ids=self.company.ids,
        )._get_export_document(filters)['rows'][0]['cells']['open'], Decimal('100.00'))
        for lang, suffix in (('en_US', 'en'), ('ar_001', 'ar')):
            for file_format, magic in (('xlsx', b'PK'), ('pdf', b'%PDF-')):
                payload, _mimetype, _name = self.env['baseer.report.export'].with_context(
                    lang=lang,
                )._export('aged_payable', filters, file_format)
                self.assertTrue(payload.startswith(magic))
                self._evidence(f'aged_payable-export-{suffix}.{file_format}', payload)

    def test_full_historical_pdf_projection_keeps_decimal_and_rejects_foreign_company(self):
        report = self.env['baseer.aged.payable.report']
        fixture = {'cutoff_date': '2026-10-23', 'currency_symbol': 'SAR',
                   'summary': {'payables': '12.50', 'counter_balances': '2.00', 'net': '10.50'},
                   'lines': [{'partner_name': 'Supplier', 'date': '2026-10-01',
                              'date_maturity': '', 'move_name': 'BILL/1', 'kind': 'invoice',
                              'bucket': 'not_due', 'open': '12.50'}]}
        filters = {'company_id': self.env.company.id, 'cutoff_date': '2026-10-23', 'page': 1}
        with patch.object(type(report), '_cutoff', return_value=date(2026, 10, 23)), \
                patch.object(type(report), '_page'), \
                patch.object(type(report), '_build_pdf', return_value=fixture):
            document = report._get_export_document(filters)
        self.assertEqual(document['rows'][0]['cells']['open'], Decimal('12.50'))
        self.assertEqual(document['rows'][-1]['cells']['open'], Decimal('10.50'))
        with patch.object(type(report), 'MAX_PDF_LINES', 0), \
                patch.object(type(report), '_cutoff', return_value=date(2026, 10, 23)), \
                patch.object(type(report), '_page'), \
                patch.object(type(report), '_build_pdf', return_value=fixture), \
                self.assertRaises(ValidationError):
            report._get_export_document(filters)
        other = self.env['res.company'].create({'name': 'Aged payable export foreign'})
        with self.assertRaises(AccessError):
            report._get_export_document({**filters, 'company_id': other.id})
