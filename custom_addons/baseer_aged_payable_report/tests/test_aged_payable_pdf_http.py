"""Focused real PDF smoke check in an isolated Odoo HttpCase."""

from datetime import datetime
from io import BytesIO
import os
from pathlib import Path
from unittest.mock import patch

from odoo.tests.common import HttpCase, tagged

from ..models.aged_payable import BaseerAgedPayable


@tagged('post_install', '-at_install', 'ap_pdf_http')
class TestAgedPayablePdfHttp(HttpCase):

    def test_real_multipage_a4_pdf(self):
        currency = self.env.company.currency_id
        buckets = ('not_due', 'd1_30', 'd31_60', 'd61_90', 'over_90')
        lines = [{
            'id': number,
            'partner_id': number,
            'partner_name': f'Supplier {number:03d}',
            'move_name': f'BILL/2041/{number:05d}',
            'date': '2041-01-01',
            'date_maturity': '2041-01-31',
            'kind': 'invoice',
            'bucket': 'd1_30',
            'counter_age_bucket': '',
            'open': '10.00',
        } for number in range(1, 102)]
        report = {
            'cutoff_date': '2041-02-10',
            'currency_symbol': currency.symbol,
            'generated_at': datetime(2041, 2, 10, 12, 0),
            'summary': {
                'payables': '1,010.00', 'counter_balances': '0.00', 'net': '1,010.00',
                'buckets': {key: '1,010.00' if key == 'd1_30' else '0.00'
                            for key in buckets},
                'counter_buckets': {key: '0.00' for key in buckets},
            },
            'lines': lines,
        }
        with patch.object(BaseerAgedPayable, '_build_pdf', return_value=report):
            pdf, mime = self.env['ir.actions.report'].with_context(
                force_report_rendering=True, lang='en_US',
            )._render_qweb_pdf(
                'baseer_aged_payable_report.aged_payable_pdf',
                res_ids=[], data={'cutoff_date': '2041-02-10'},
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
        self.assertIn('Supplier 101', text)
        self.assertIn('1,010.00', text)
        for page in reader.pages:
            self.assertAlmostEqual(float(page.mediabox.width), 842, delta=4)
            self.assertAlmostEqual(float(page.mediabox.height), 595, delta=4)
        output_dir = os.environ.get('BASEER_AP_PDF_ARTIFACT_DIR')
        if output_dir:
            Path(output_dir, 'ap-101.pdf').write_bytes(pdf)
