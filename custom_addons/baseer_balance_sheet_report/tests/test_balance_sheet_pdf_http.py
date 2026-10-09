"""Opt-in real A4 multipage rendering without a shared-environment load."""

from datetime import date
from io import BytesIO
import os
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from unittest.mock import patch

from odoo.tests.common import HttpCase, tagged


@tagged('post_install', '-at_install', 'bs_pdf_http')
class TestBalanceSheetPdfHttp(HttpCase):
    def test_real_101_account_pdf_is_multipage_a4(self):
        company = self.env.company
        filters = {'company_id': company.id, 'date_from': '2041-03-01',
                   'date_to': '2041-03-31', 'journal_ids': []}
        accounts = {index: SimpleNamespace(
            id=index, code=f'{index:06}', name=f'Account {index}',
            account_type='asset_cash', include_initial_balance=True,
        ) for index in range(1, 102)}
        snapshot = (company, date(2041, 3, 1), date(2041, 3, 31),
                    date(2041, 1, 1), [], {}, {}, {}, accounts)
        model_class = type(self.env['baseer.balance.sheet.report'])
        start = monotonic()
        with patch.object(model_class, '_snapshot', return_value=snapshot), \
                patch.object(model_class, '_assert_complete_source'):
            pdf, mime = self.env['ir.actions.report'].with_context(
                force_report_rendering=True,
            )._render_qweb_pdf(
                'baseer_balance_sheet_report.balance_sheet_pdf',
                res_ids=[], data={'filters': filters},
            )
        self.assertEqual(mime, 'pdf')
        self.assertTrue(pdf.startswith(b'%PDF-'))
        try:
            from pypdf import PdfReader
        except ImportError:
            from PyPDF2 import PdfReader
        reader = PdfReader(BytesIO(pdf))
        self.assertGreaterEqual(len(reader.pages), 2)
        page_text = [page.extract_text() or '' for page in reader.pages]
        self.assertIn('Account 101', ' '.join(page_text))
        self.assertIn('Total Assets', ' '.join(page_text))
        self.assertTrue(all('Page' in text for text in page_text))
        for page in reader.pages:
            self.assertAlmostEqual(float(page.mediabox.width), 595, delta=4)
            self.assertAlmostEqual(float(page.mediabox.height), 842, delta=4)
        output_dir = os.environ.get('BASEER_BS_PDF_ARTIFACT_DIR')
        if output_dir:
            Path(output_dir, 'bs-101.pdf').write_bytes(pdf)
        self.assertLess(len(pdf), 20 * 1024 * 1024)
        self.assertLess(monotonic() - start, 60)
