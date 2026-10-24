"""Focused synthetic access, value projection and actual native export coverage."""

from datetime import date
from decimal import Decimal
from io import BytesIO
import os
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook
from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'reports_unified_export')
class TestTobaccoUnifiedExport(TransactionCase):
    def setUp(self):
        super().setUp()
        self.env['res.lang']._activate_lang('ar_001')
        self.company = self.env.company
        self.company.currency_id = self.env.ref('base.SAR')
        self.report = self.env['baseer.pos.tobacco.report.wizard']
        self.collector = self.env['report.baseer_pos_tobacco_report.report_pos_tobacco_fees']
        self.filters = {'company_id': self.company.id, 'period': 'month', 'month': 10, 'year': 2099,
                        'date_from': '2099-10-01', 'date_to': '2099-10-31', 'show_products': False, 'page': 1}

    def _user(self, suffix, accounting=True, pos=True):
        groups = [self.env.ref('base.group_user').id]
        if accounting:
            groups.append(self.env.ref('account.group_account_readonly').id)
        if pos:
            groups.append(self.env.ref('point_of_sale.group_pos_user').id)
        return self.env['res.users'].create({
            'name': 'tobacco export ' + suffix, 'login': 'tobacco_unified_export_' + suffix,
            'group_ids': [Command.set(groups)], 'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)], 'lang': 'en_US',
        })

    @staticmethod
    def _mock_data():
        return {'show_products': False,
                'rows': [{'date': '01-10-2099 10:00', 'order': 'POS/1', 'type': 'Sale',
                          'debit': '0.00', 'credit': '2.50', 'running': '2.50'}],
                'exceptions': [{'date': '01-10-2099 10:00', 'order': 'POS/1',
                                'computed_total': '10.00', 'saved_total': '9.00'}],
                'debit_total': '0.00', 'credit_total': '2.50', 'closing': '2.50',
                'labels': {'date': 'Date', 'order': 'Order', 'product': 'Products', 'type': 'Type',
                           'debit': 'Debit', 'credit': 'Credit', 'running': 'Running',
                           'total': 'Total', 'mismatch': 'Mismatch', 'title': 'Tobacco',
                           'computed_total': 'Computed total', 'saved_total': 'Saved total',
                           'from': 'From', 'to': 'To'}, 'from_text': '01-10-2099', 'to_text': '31-10-2099'}

    def test_nonzero_authoritative_projection_and_exceptions(self):
        data = self._mock_data()
        with patch.object(type(self.collector), '_build_report', return_value=data):
            document = self.report._get_export_document(self.filters)
        self.assertEqual(document['rows'][0]['cells']['credit'], Decimal('2.50'))
        self.assertEqual(document['rows'][0]['cells']['debit'], Decimal('0.00'))
        self.assertEqual(document['rows'][1]['cells']['running'], Decimal('2.50'))
        self.assertEqual(document['rows'][-1]['cells']['computed'], Decimal('10.00'))
        self.assertEqual(document['rows'][-1]['cells']['saved'], Decimal('9.00'))
        self.assertIsNone(document['rows'][-1]['cells'].get('credit'))

    def test_real_authorized_collector_and_native_ar_en_files(self):
        user = self._user('reader')
        report = self.report.with_user(user).sudo(False).with_context(allowed_company_ids=self.company.ids)
        # No mocked collector: actual access, country/currency/period validation
        # and source queries execute against an empty future test period.
        company, values = report._hub_wizard_values(self.filters)
        virtual = report.with_company(company).new(values)
        source = self.collector.with_user(user).sudo(False).with_context(allowed_company_ids=self.company.ids)._build_report(virtual)
        document = report._get_export_document(self.filters)
        self.assertEqual(source['rows'], [])
        self.assertEqual(len(document['rows']), 1)
        for key, original in (('debit', 'debit_total'), ('credit', 'credit_total'), ('running', 'closing')):
            self.assertEqual(document['rows'][0]['cells'][key], Decimal(source[original].replace(',', '')))
        exports = self.env['baseer.report.export'].with_user(user).sudo(False).with_context(allowed_company_ids=self.company.ids)
        for lang, suffix in (('en_US', 'en'), ('ar_001', 'ar')):
            localized = report.with_context(lang=lang)._get_export_document(self.filters)
            self.assertTrue(all(not label.endswith(':') for label, _value in localized['metadata']))
            for file_format in ('xlsx', 'pdf'):
                payload, mime, filename = exports.with_context(lang=lang)._export('tobacco', self.filters, file_format)
                self.assertTrue(filename.endswith('.' + file_format))
                if file_format == 'xlsx':
                    self.assertIn('spreadsheetml.sheet', mime)
                    sheet = load_workbook(BytesIO(payload)).active
                    self.assertEqual(sheet.sheet_view.rightToLeft, suffix == 'ar')
                    self.assertTrue(any(cell.value == 0 and cell.data_type == 'n' for row in sheet for cell in row))
                    for row in sheet:
                        for cell in row:
                            self.assertIsNone(cell.hyperlink)
                            self.assertNotEqual(cell.data_type, 'f')
                else:
                    self.assertEqual(mime, 'application/pdf')
                    self.assertTrue(payload.startswith(b'%PDF-'))
                    try:
                        from pypdf import PdfReader
                    except ImportError:
                        from PyPDF2 import PdfReader
                    pages = PdfReader(BytesIO(payload)).pages
                    self.assertTrue(pages)
                    for page in pages:
                        self.assertFalse(any(ref.get_object().get('/Subtype') == '/Link' for ref in page.get('/Annots', [])))
                target = os.environ.get('BASEER_EXPORT_EVIDENCE_DIR')
                if target and os.path.isdir(target):
                    Path(target, f'tobacco-export-{suffix}.{file_format}').write_bytes(payload)

    def test_denied_user_foreign_company_and_malformed_filters(self):
        for suffix, accounting, pos in (('none', False, False), ('account_only', True, False)):
            with self.assertRaises(AccessError):
                self.report.with_user(self._user(suffix, accounting, pos)).sudo(False)._get_export_document(self.filters)
        other = self.env['res.company'].create({'name': 'tobacco unified export foreign'})
        with self.assertRaises(AccessError):
            self.report.with_context(allowed_company_ids=[self.company.id, other.id])._get_export_document({**self.filters, 'company_id': other.id})
        for invalid in ({**self.filters, 'amount': '999.99'}, {**self.filters, 'month': 13},
                        {key: value for key, value in self.filters.items() if key != 'page'}):
            with self.assertRaises(ValidationError):
                self.report._get_export_document(invalid)

    def test_oversized_document_fails_without_truncation(self):
        data = self._mock_data()
        data['rows'] = [data['rows'][0]] * 5001
        with patch.object(type(self.collector), '_build_report', return_value=data), self.assertRaises(ValidationError):
            self.report._get_export_document(self.filters)
