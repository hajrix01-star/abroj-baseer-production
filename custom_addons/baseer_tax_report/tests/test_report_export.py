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
class TestVatUnifiedExport(TransactionCase):
    def setUp(self):
        super().setUp()
        self.env['res.lang']._activate_lang('ar_001')
        self.company = self.env.company
        self.company.account_fiscal_country_id = self.env.ref('base.sa')
        self.report = self.env['baseer.tax.report.wizard']
        self.filters = {'company_id': self.company.id, 'period_type': 'quarter', 'year': 2099,
                        'month': '1', 'quarter': '4', 'display_mode': 'simple', 'journal_ids': []}

    def _user(self, suffix, accounting=True, pos=True):
        groups = [self.env.ref('base.group_user').id]
        if accounting:
            groups.append(self.env.ref('account.group_account_readonly').id)
        return self.env['res.users'].create({
            'name': 'vat export ' + suffix, 'login': 'vat_unified_export_' + suffix,
            'group_ids': [Command.set(groups)], 'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)], 'lang': 'en_US',
        })

    @staticmethod
    def _mock_data():
        return {'rows': [
            {'number': str(number), 'name': f'Box {number}', 'base': Decimal(number), 'tax': Decimal(number) / 10}
            for number in range(1, 17)
        ], 'exception': {'amount': Decimal('2.00'), 'other_amount': Decimal('-1.00')},
            'date_from': date(2099, 10, 1), 'date_to': date(2099, 12, 31), 'journal_names': ''}

    def test_nonzero_authoritative_projection_and_exceptions(self):
        data = self._mock_data()
        with patch.object(type(self.report), '_build_report', return_value=data):
            document = self.report._get_export_document(self.filters)
        self.assertEqual([row['cells'].get('box') for row in document['rows'][:16]], [str(n) for n in range(1, 17)])
        for row, original in zip(document['rows'][:16], data['rows']):
            self.assertEqual(row['cells']['base'], original['base'])
            self.assertEqual(row['cells']['tax'], original['tax'])
        self.assertEqual(document['rows'][-2]['cells']['base'], Decimal('2.00'))
        self.assertEqual(document['rows'][-1]['cells']['base'], Decimal('-1.00'))

    def test_real_authorized_collector_and_native_ar_en_files(self):
        user = self._user('reader')
        report = self.report.with_user(user).sudo(False).with_context(allowed_company_ids=self.company.ids)
        # No mocked collector: actual access, country/currency/period validation
        # and source queries execute against an empty future test period.
        source = report._hub_wizard(self.filters)._build_report()
        document = report._get_export_document(self.filters)
        self.assertEqual(len(source['rows']), 16)
        self.assertEqual(len(document['rows']), 18)
        for actual, original in zip(document['rows'], source['rows']):
            self.assertEqual(actual['cells'].get('base'), original['base'])
            self.assertEqual(actual['cells'].get('tax'), original['tax'])
        exports = self.env['baseer.report.export'].with_user(user).sudo(False).with_context(allowed_company_ids=self.company.ids)
        for lang, suffix in (('en_US', 'en'), ('ar_001', 'ar')):
            localized = report.with_context(lang=lang)._get_export_document(self.filters)
            self.assertEqual(localized['title'], 'تقرير ضريبة القيمة المضافة' if suffix == 'ar' else 'Saudi VAT Report')
            self.assertEqual(localized['columns'][0]['label'], 'الخانة' if suffix == 'ar' else 'Box')
            for file_format in ('xlsx', 'pdf'):
                payload, mime, filename = exports.with_context(lang=lang)._export('vat', self.filters, file_format)
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
                    Path(target, f'vat-export-{suffix}.{file_format}').write_bytes(payload)

    def test_denied_user_foreign_company_and_malformed_filters(self):
        with self.assertRaises(AccessError):
            self.report.with_user(self._user('denied', accounting=False)).sudo(False)._get_export_document(self.filters)
        other = self.env['res.company'].create({'name': 'vat unified export foreign'})
        with self.assertRaises(AccessError):
            self.report.with_context(allowed_company_ids=[self.company.id, other.id])._get_export_document({**self.filters, 'company_id': other.id})
        for invalid in ({**self.filters, 'amount': '999.99'}, {**self.filters, 'month': 1},
                        {key: value for key, value in self.filters.items() if key != 'quarter'}):
            with self.assertRaises(ValidationError):
                self.report._get_export_document(invalid)

    def test_oversized_document_fails_without_truncation(self):
        data = self._mock_data()
        data['rows'] = [data['rows'][0]] * 5001
        with patch.object(type(self.report), '_build_report', return_value=data), self.assertRaises(ValidationError):
            self.report._get_export_document(self.filters)
