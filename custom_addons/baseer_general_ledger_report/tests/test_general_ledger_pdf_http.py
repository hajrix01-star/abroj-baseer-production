"""Isolated, opt-in real wkhtmltopdf multipage smoke check.

Run with ``--test-tags=/baseer_general_ledger_report:TestGeneralLedgerPdfHttp``
under HttpCase so the report's asset callback has a live HTTP server.
Scope: PDF bypasses 100-row screen paging; QWeb cannot catch broken second
pages; the owner's small-company usage gives no reason for a 5,000-row load.
"""

from datetime import date
from io import BytesIO
import os
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from unittest.mock import patch

from odoo.tests.common import HttpCase, tagged

from ..models.general_ledger import BaseerGeneralLedger


@tagged('post_install', '-at_install', 'gl_pdf_http')
class TestGeneralLedgerPdfHttp(HttpCase):
    def _render(self, account_count):
        company = self.env.company
        filters = {
            'company_id': company.id,
            'date_from': '2041-03-01',
            'date_to': '2041-03-31',
            'journal_ids': [],
        }
        accounts = {
            index: SimpleNamespace(
                id=index,
                code=f'{index:06}',
                name=f'Account {index}',
                include_initial_balance=True,
            ) for index in range(1, account_count + 1)
        }
        # The fake account set exercises the real aggregation/HTML/PDF path
        # without manufacturing accounting records in this throwaway DB.
        snapshot = (company, date(2041, 3, 1), date(2041, 3, 31),
                    date(2041, 1, 1), [], {}, {}, {}, accounts)
        start = monotonic()
        with patch.object(BaseerGeneralLedger, '_snapshot', return_value=snapshot), \
                patch.object(BaseerGeneralLedger, '_assert_complete_source'):
            pdf, mime = self.env['ir.actions.report'].with_context(
                force_report_rendering=True,
            )._render_qweb_pdf(
                'baseer_general_ledger_report.general_ledger_pdf',
                res_ids=[], data={'filters': filters},
            )
        elapsed = monotonic() - start
        self.assertEqual(mime, 'pdf')
        self.assertTrue(pdf.startswith(b'%PDF-'))
        try:
            from pypdf import PdfReader
        except ImportError:  # The pinned image may expose the legacy package.
            from PyPDF2 import PdfReader
        reader = PdfReader(BytesIO(pdf))
        self.assertGreaterEqual(len(reader.pages), 2)
        page_text = [page.extract_text() or '' for page in reader.pages]
        text = ' '.join(page_text)
        self.assertIn(f'Account {account_count}', text)
        self.assertIn('Total General Ledger', text)
        self.assertTrue(all('Page' in value for value in page_text))
        for page in reader.pages:
            self.assertAlmostEqual(float(page.mediabox.width), 842, delta=4)
            self.assertAlmostEqual(float(page.mediabox.height), 595, delta=4)
        output_dir = os.environ.get('BASEER_GL_PDF_ARTIFACT_DIR')
        if output_dir:
            Path(output_dir, f'gl-{account_count}.pdf').write_bytes(pdf)
        return elapsed, len(pdf)

    def test_real_101_account_pdf_is_multipage_a4(self):
        elapsed, byte_count = self._render(101)
        self.assertLess(byte_count, 20 * 1024 * 1024)
        self.assertLess(elapsed, 60)
