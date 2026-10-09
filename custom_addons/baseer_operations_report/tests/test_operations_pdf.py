"""Guard the incomplete source and smoke-test its A4 PDF adapters."""

from io import BytesIO
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import HttpCase, TransactionCase, tagged

from ..models.operations import BaseerOperationsReport


@tagged('post_install', '-at_install')
class TestOperationsPdfGuard(TransactionCase):

    def setUp(self):
        super().setUp()
        self.filters = {
            'company_id': self.env.company.id,
            'date_from': '2041-06-01', 'date_to': '2041-06-30',
            'journal_ids': [],
        }

    def test_direct_invocation_denies_incomplete_source_and_bad_scope(self):
        portrait = self.env['report.baseer_operations_report.operations_pdf_portrait']
        landscape = self.env['report.baseer_operations_report.operations_pdf_landscape']
        for data in (None, {}, {'filters': []}):
            with self.assertRaises(ValidationError):
                portrait._get_report_values([], data)
        with self.assertRaises(ValidationError):
            portrait._get_report_values([1], {'filters': self.filters})
        for invalid_id in (True, 0, self.env.company.id + 100000):
            with self.assertRaises(AccessError):
                portrait._get_report_values([], {
                    'filters': {**self.filters, 'company_id': invalid_id},
                })
        with patch.object(BaseerOperationsReport, 'get_source_snapshot',
                          return_value={'complete': False}) as source:
            for adapter in (portrait, landscape):
                with self.assertRaises(AccessError):
                    adapter._get_report_values([], {'filters': self.filters})
            self.assertEqual(source.call_count, 2)
            with self.assertRaises(AccessError):
                self.env['ir.actions.report']._render_qweb_html(
                    'baseer_operations_report.operations_pdf_portrait',
                    docids=[], data={'filters': self.filters},
                )

    def test_both_a4_formats_registered_without_a_user_menu(self):
        portrait = self.env.ref('baseer_operations_report.action_operations_pdf_portrait')
        landscape = self.env.ref('baseer_operations_report.action_operations_pdf_landscape')
        self.assertEqual(portrait.paperformat_id.format, 'A4')
        self.assertEqual(portrait.paperformat_id.orientation, 'Portrait')
        self.assertEqual(landscape.paperformat_id.format, 'A4')
        self.assertEqual(landscape.paperformat_id.orientation, 'Landscape')
        self.assertFalse(portrait.binding_model_id)
        self.assertFalse(landscape.binding_model_id)


@tagged('post_install', '-at_install', 'operations_pdf_http')
class TestOperationsPdfHttp(HttpCase):
    """One real posted receipt, not a fabricated financial snapshot."""

    def setUp(self):
        super().setUp()
        company = self.env.company
        self.env.user.lang = 'en_US'
        receivable = self.env['account.account'].with_company(company).create({
            'code': '959201', 'name': 'Gross PDF receivable',
            'account_type': 'asset_receivable', 'reconcile': True,
            'company_ids': [Command.set(company.ids)],
        })
        income = self.env['account.account'].with_company(company).create({
            'code': '959202', 'name': 'Gross PDF income',
            'account_type': 'income',
            'company_ids': [Command.set(company.ids)],
        })
        vat_account = self.env['account.account'].with_company(company).create({
            'code': '959203', 'name': 'Gross PDF VAT',
            'account_type': 'liability_current',
            'company_ids': [Command.set(company.ids)],
        })
        partner = self.env['res.partner'].with_company(company).create({
            'name': 'Gross PDF customer',
            'property_account_receivable_id': receivable.id,
        })
        journal = self.env['account.journal'].with_company(company).create({
            'name': 'Gross PDF sales', 'code': 'GOPDF',
            'type': 'sale', 'company_id': company.id,
        })
        tax = self.env['account.tax'].with_company(company).create({
            'name': 'Gross PDF VAT 15%', 'amount_type': 'percent',
            'amount': 15, 'type_tax_use': 'sale', 'company_id': company.id,
        })
        tax.invoice_repartition_line_ids.filtered(
            lambda line: line.repartition_type == 'tax',
        ).write({'account_id': vat_account.id})
        receipt = self.env['account.move'].with_company(company).create({
            'move_type': 'out_receipt', 'partner_id': partner.id,
            'journal_id': journal.id, 'invoice_date': '2041-06-10',
            'invoice_line_ids': [Command.create({
                'name': 'Gross PDF receipt', 'quantity': 1,
                'price_unit': 100, 'account_id': income.id,
                'tax_ids': [Command.set(tax.ids)],
            })],
        })
        receipt.action_post()
        self.assertEqual(receipt.amount_total, 115)
        self.filters = {
            'company_id': company.id,
            'date_from': '2041-06-01', 'date_to': '2041-06-30',
            'journal_ids': [],
        }

    def _render(self, report_name, landscape=False):
        filters = dict(self.filters)
        if landscape:
            filters['comparison'] = {
                'kind': 'previous_period', 'count': 1,
                'order': 'descending',
            }
        snapshot = self.env['baseer.operations.report']._build_source_snapshot(filters)
        self.assertTrue(snapshot['coverage_complete'])
        self.assertFalse(snapshot['complete'])
        self.assertEqual(snapshot['periods'][0]['rows'][0]['amount'], '115.00')
        # The production source remains blocked. Only this isolated test lets
        # the real source payload through the PDF adapter to exercise wkhtmltopdf.
        snapshot['complete'] = True
        with patch.object(BaseerOperationsReport, 'get_source_snapshot',
                          return_value=snapshot):
            pdf, mime = self.env['ir.actions.report'].with_context(
                force_report_rendering=True,
            )._render_qweb_pdf(
                report_name, res_ids=[], data={'filters': filters},
            )
        self.assertEqual(mime, 'pdf')
        self.assertTrue(pdf.startswith(b'%PDF-'))
        try:
            from pypdf import PdfReader
        except ImportError:
            from PyPDF2 import PdfReader
        pages = PdfReader(BytesIO(pdf)).pages
        self.assertEqual(len(pages), 1)
        page = pages[0]
        text = page.extract_text() or ''
        self.assertIn('115.00', text)
        self.assertIn('Net operations', text)
        self.assertIn('2041-06-01', text)
        width, height = ((842, 595) if landscape else (595, 842))
        self.assertAlmostEqual(float(page.mediabox.width), width, delta=4)
        self.assertAlmostEqual(float(page.mediabox.height), height, delta=4)

    def test_portrait_real_receipt_is_a4(self):
        self._render('baseer_operations_report.operations_pdf_portrait')

    def test_landscape_comparison_real_receipt_is_a4(self):
        self._render('baseer_operations_report.operations_pdf_landscape', True)
