"""Fresh source-based owner PDF and the existing Arabic-safe A4 shell."""

from io import BytesIO
import os
from pathlib import Path
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import HttpCase, tagged

from .test_owner_cash import TestOwnerCash


@tagged('post_install', '-at_install', 'operations_owner_pdf')
class TestOwnerPdf(HttpCase):
    _statement = TestOwnerCash._statement

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.report = self.env['baseer.operations.report']
        self.expense = self.env['account.account'].create({
            'code': '959301', 'name': 'Owner PDF actual expense', 'account_type': 'expense',
            'company_ids': [Command.set(self.company.ids)],
        })
        self.bank = self.env['account.journal'].search([
            ('company_id', '=', self.company.id), ('type', '=', 'bank'),
        ], limit=1)
        self.partner = self.env['res.partner'].create({'name': 'Owner PDF payment partner'})
        self.filters = {'company_id': self.company.id, 'date_from': '2026-06-01',
                        'date_to': '2026-06-30', 'journal_ids': []}
        self._statement('40.00')

    def test_print_rebuilds_source_and_ignores_client_amounts(self):
        action = self.report.action_print_owner(self.filters)
        self.assertEqual(action['report_name'], 'baseer_operations_report.owner_pdf_portrait')
        self._statement('10.00', day='2026-06-19')
        values = self.env['report.baseer_operations_report.owner_pdf_portrait']._get_report_values(
            [], {'filters': self.filters, 'snapshot': {'complete': True, 'cash_total': '999.00'}},
        )
        self.assertEqual(values['periods'][0]['totals'][1]['amount'], '50.00')
        self.assertEqual(values['periods'][0]['totals'][2]['amount'], '-50.00')

    def test_incomplete_company_and_layout_guards(self):
        portrait = self.env['report.baseer_operations_report.owner_pdf_portrait']
        landscape = self.env['report.baseer_operations_report.owner_pdf_landscape']
        for bad in (None, {}, {'filters': []}):
            with self.assertRaises(ValidationError):
                portrait._get_report_values([], bad)
        with self.assertRaises(AccessError):
            portrait._get_report_values([], {'filters': {**self.filters, 'company_id': True}})
        with self.assertRaises(ValidationError):
            landscape._get_report_values([], {'filters': self.filters})
        with patch.object(type(self.report), 'get_owner_snapshot', return_value={'complete': False}):
            with self.assertRaises(AccessError):
                self.report.action_print_owner(self.filters)
            for model in (portrait, landscape):
                with self.assertRaises(AccessError):
                    model._get_report_values([], {'filters': self.filters, 'complete': True})

    def _render_pdf(self, arabic=False, comparison=False):
        filters = dict(self.filters)
        if comparison:
            filters['comparison'] = {'kind': 'previous_period', 'count': 1, 'order': 'descending'}
        language = 'ar_001' if arabic else 'en_US'
        layout = 'landscape' if comparison else 'portrait'
        name = 'baseer_operations_report.owner_pdf_' + layout
        report = self.env['ir.actions.report'].with_context(lang=language, force_report_rendering=True)
        html, _kind = report._render_qweb_html(name, docids=[], data={'filters': filters})
        self.assertIn(('ملخص المبيعات والمدفوعات' if arabic else 'Sales and Payments Summary').encode(), html)
        self.assertIn(b'-40.00', html)
        pdf, kind = report._render_qweb_pdf(name, res_ids=[], data={'filters': filters})
        self.assertEqual(kind, 'pdf')
        self.assertTrue(pdf.startswith(b'%PDF-'))
        # Only the isolated visual-review runner mounts this explicit output.
        if os.environ.get('BASEER_OWNER_PDF_DIR') == '/mnt/owner-pdf-output':
            Path('/mnt/owner-pdf-output', f'owner-{layout}-{language}.pdf').write_bytes(pdf)
        try:
            from pypdf import PdfReader
        except ImportError:
            from PyPDF2 import PdfReader
        pages = PdfReader(BytesIO(pdf)).pages
        self.assertTrue(pages)
        width, height = (842, 595) if comparison else (595, 842)
        for page in pages:
            self.assertAlmostEqual(float(page.mediabox.width), width, delta=4)
            self.assertAlmostEqual(float(page.mediabox.height), height, delta=4)
        self.assertIn('40.00', '\n'.join(page.extract_text() or '' for page in pages))

    def test_real_english_portrait_pdf(self):
        self._render_pdf()

    def test_real_arabic_comparison_pdf(self):
        self._render_pdf(arabic=True, comparison=True)
