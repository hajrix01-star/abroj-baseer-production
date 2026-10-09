"""Opt-in real multipage A4 render, with no load against shared QA."""

from datetime import date
from io import BytesIO
import os
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from unittest.mock import patch

from odoo.tests.common import HttpCase, tagged

@tagged('post_install', '-at_install', 'tb_pdf_http')
class TestTrialBalancePdfHttp(HttpCase):
    def test_real_101_account_pdf_is_multipage_a4(self):
        company = self.env.company
        filters = {
            'company_id': company.id,
            'date_from': '2041-03-01',
            'date_to': '2041-03-31',
            'journal_ids': [],
        }
        accounts = {index: SimpleNamespace(
            id=index, code=f'{index:06}', name=f'Account {index}',
            include_initial_balance=True,
        ) for index in range(1, 102)}
        snapshot = (company, date(2041, 3, 1), date(2041, 3, 31),
                    date(2041, 1, 1), [], {}, {}, {}, accounts)
        start = monotonic()
        trial_class = type(self.env['baseer.trial.balance.report'])
        with patch.object(trial_class, '_snapshot', return_value=snapshot), \
                patch.object(trial_class, '_assert_complete_source'):
            pdf, mime = self.env['ir.actions.report'].with_context(
                force_report_rendering=True,
            )._render_qweb_pdf(
                'baseer_trial_balance_report.trial_balance_pdf',
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
        text = ' '.join(page.extract_text() or '' for page in reader.pages)
        self.assertIn('Account 101', text)
        self.assertIn('Total', text)
        for page in reader.pages:
            self.assertAlmostEqual(float(page.mediabox.width), 842, delta=4)
            self.assertAlmostEqual(float(page.mediabox.height), 595, delta=4)
        output_dir = os.environ.get('BASEER_TB_PDF_ARTIFACT_DIR')
        if output_dir:
            Path(output_dir, 'tb-101.pdf').write_bytes(pdf)
        self.assertLess(len(pdf), 20 * 1024 * 1024)
        self.assertLess(monotonic() - start, 60)
