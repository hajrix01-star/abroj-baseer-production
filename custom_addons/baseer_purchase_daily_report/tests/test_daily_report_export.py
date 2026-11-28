"""PDF and Excel exports of the daily purchases report."""

import io
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from odoo import Command, api
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged
from odoo.tools.misc import file_path

try:
    from openpyxl import load_workbook
except ImportError:  # pragma: no cover - bundled with the local test venv
    load_workbook = None

FORBIDDEN_COMPANY_IDS = {54, 56}
OWL_XML = Path(__file__).resolve().parents[1] / 'static/src/purchase_daily_report.xml'
QWEB_XML = Path(__file__).resolve().parents[1] / 'report/daily_purchases_report.xml'


@tagged('post_install', '-at_install')
class TestDailyPurchaseReportExport(TransactionCase):

    def setUp(self):
        super().setUp()
        for xmlid in (
            'baseer_procurement_requests.group_procurement_accountant',
            'baseer_procurement_requests.group_procurement_manager',
            'account.group_account_manager',
            'base.group_erp_manager',
        ):
            self.env.user.group_ids |= self.env.ref(xmlid)
        self.company = self.env.company
        self.assertNotIn(self.company.id, FORBIDDEN_COMPANY_IDS)
        self.company.currency_id.active = True
        Account = self.env['account.account']
        Journal = self.env['account.journal']
        self.custody_account = Account.create({
            'name': 'Purchase export custody', 'code': 'PDE108', 'account_type': 'asset_current',
            'reconcile': True, 'company_ids': [Command.set(self.company.ids)],
        })
        bank_account = Account.create({
            'name': 'Purchase export bank', 'code': 'PDE101', 'account_type': 'asset_cash',
            'company_ids': [Command.set(self.company.ids)],
        })
        cash_account = Account.create({
            'name': 'Purchase export cash', 'code': 'PDE102', 'account_type': 'asset_cash',
            'company_ids': [Command.set(self.company.ids)],
        })
        self.payable = Account.create({
            'name': 'Purchase export payable', 'code': 'PDE200', 'account_type': 'liability_payable',
            'reconcile': True, 'company_ids': [Command.set(self.company.ids)],
        })
        self.expense = Account.create({
            'name': 'Purchase export expense', 'code': 'PDE600', 'account_type': 'expense',
            'company_ids': [Command.set(self.company.ids)],
        })
        general = Journal.create({
            'name': 'Purchase export entries', 'code': 'PDEG', 'type': 'general', 'company_id': self.company.id,
        })
        self.bank = Journal.create({
            'name': 'Purchase export bank', 'code': 'PDEB', 'type': 'bank',
            'company_id': self.company.id, 'default_account_id': bank_account.id,
        })
        self.cash = Journal.create({
            'name': 'Purchase export cash', 'code': 'PDEX', 'type': 'cash',
            'company_id': self.company.id, 'default_account_id': cash_account.id,
        })
        self.purchase = Journal.create({
            'name': 'Purchase export purchases', 'code': 'PDEP', 'type': 'purchase',
            'company_id': self.company.id, 'default_account_id': self.expense.id,
        })
        self.company.write({
            'baseer_procurement_representative_petty_cash_account_id': self.custody_account.id,
            'baseer_procurement_representative_petty_cash_journal_id': general.id,
            'baseer_procurement_representative_petty_cash_payment_journal_ids': [Command.set([self.bank.id])],
        })
        self.representative = self.env['res.partner'].create({
            'name': 'Purchase export representative', 'company_id': self.company.id,
        })
        self.representative.with_company(self.company).is_purchase_representative = True
        self.custody = Journal.search([
            ('company_id', '=', self.company.id), ('baseer_custody_representative_id', '=', self.representative.id),
        ], limit=1)
        if not self.custody:
            self.custody = Journal.create({
                'name': 'Purchase export representative cash', 'code': 'PDEC', 'type': 'cash',
                'company_id': self.company.id, 'default_account_id': self.custody_account.id,
                'baseer_custody_representative_id': self.representative.id,
            })
        for journal, account in ((self.custody, self.custody_account), (self.bank, bank_account), (self.cash, cash_account)):
            (journal.outbound_payment_method_line_ids | journal.inbound_payment_method_line_ids).write({
                'payment_account_id': account.id,
            })
        self.vendor = self.env['res.partner'].create({'name': 'Purchase export vendor'})
        self.vendor.with_company(self.company).property_account_payable_id = self.payable
        self.owner = self.env['res.users'].sudo().with_context(no_reset_password=True).create({
            'name': 'Purchase export owner', 'login': 'purchase_daily_export_owner',
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'baseer_access_role': 'owner',
        })

    def _report(self, user=None, company=None):
        company = company or self.company
        env = api.Environment(self.env.cr, (user or self.owner).id, {
            'allowed_company_ids': [company.id],
            'lang': self.env.lang,
            'tz': 'Asia/Riyadh',
        })
        return env['baseer.purchase.daily.report'].with_company(company)

    def _bill(self, amount, day, vendor=None):
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice', 'company_id': self.company.id, 'journal_id': self.purchase.id,
            'partner_id': (vendor or self.vendor).id, 'invoice_date': day, 'ref': 'Purchase export',
            'invoice_line_ids': [Command.create({
                'name': 'Goods', 'quantity': 1, 'price_unit': amount,
                'account_id': self.expense.id, 'tax_ids': [Command.clear()],
            })],
        })
        bill.action_post()
        return bill

    def _pay(self, bill, journal, amount=None):
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=bill.ids,
        ).create({
            'journal_id': journal.id, 'payment_date': bill.invoice_date,
            'payment_method_line_id': journal.outbound_payment_method_line_ids[0].id,
        })
        if amount is not None:
            wizard.amount = amount
        return wizard._create_payments().ensure_one()

    def _movements(self):
        Advance = self.env['baseer.procurement.representative.advance']
        rep = self.representative.id
        Advance.submit_funding(False, self.bank.id, rep, '1000.00', str(uuid4()), '2099-11-02')
        second = Advance.submit_funding(False, self.bank.id, rep, '500.00', str(uuid4()), '2099-11-05')
        Advance.submit_funding_reversal(second, 'Duplicate transfer', '2099-11-06', str(uuid4()))
        Advance.submit_aggregate_return(rep, self.bank.id, '50.00', str(uuid4()), '2099-11-07')
        Advance.submit_funding(False, self.bank.id, rep, '25.00', str(uuid4()), '2026-10-20')

    def _seed_period(self):
        self._movements()
        custody_bill = self._bill(300, '2099-11-03')
        self._pay(custody_bill, self.custody)
        mixed = self._bill(200, '2099-11-04')
        self._pay(mixed, self.custody, 120)
        self._pay(mixed, self.cash, 80)
        unpaid = self._bill(100, '2099-11-04')
        bank_bill = self._bill(70, '2099-11-05')
        self._pay(bank_bill, self.bank)
        # Outside the November window — must stay out of the export.
        self._pay(self._bill(999, '2099-12-01'), self.bank)
        return custody_bill, mixed, unpaid, bank_bill

    def test_templates_do_not_call_string_or_number_helpers(self):
        import re
        pattern = re.compile(r'(?<![A-Za-z_])(String|Number)\s*\(')
        for path in (OWL_XML, QWEB_XML):
            text = path.read_text()
            self.assertFalse(pattern.search(text), path)

    def test_export_matches_report_table_and_respects_filters(self):
        custody_bill, mixed, unpaid, bank_bill = self._seed_period()
        report = self._report()
        payload = report.get_days('2099-11-01', '2099-11-30', 'all')
        document = report._export_document('2099-11-01', '2099-11-30', 'all')
        self.assertNotIn(document['company_id'], FORBIDDEN_COMPANY_IDS)
        self.assertEqual(document['company'], self.company.name)
        self.assertEqual(document['date_from'], '2099-11-01')
        self.assertEqual(document['date_to'], '2099-11-30')
        self.assertEqual(document['currency'], self.company.currency_id.name)
        self.assertTrue(document['show_custody'])
        self.assertEqual([column['key'] for column in document['method_columns']], ['bank', 'osama', 'cash', 'unpaid'])
        self.assertEqual([column['key'] for column in document['columns']], [
            'date', 'count', 'bank', 'osama', 'cash', 'unpaid', 'total', 'transfer', 'balance',
        ])
        table = payload['table']
        self.assertEqual([row['date'] for row in document['rows']], [row['date'] for row in table['rows']])
        self.assertEqual([row['kind'] for row in document['rows']], [row['kind'] for row in table['rows']])
        self.assertEqual(document['totals']['total'], 670.0)
        self.assertEqual(document['totals']['count'], 4)
        self.assertEqual(document['totals']['amounts']['bank'], 70.0)
        self.assertEqual(document['totals']['amounts']['osama'], 420.0)
        self.assertEqual(document['totals']['amounts']['cash'], 80.0)
        self.assertEqual(document['totals']['amounts']['unpaid'], 100.0)
        self.assertEqual(document['totals']['transfer'], 950.0)
        self.assertEqual(document['totals']['balance'], 530.0)
        days = {row['date']: row for row in document['rows'] if row['kind'] == 'day'}
        self.assertEqual(days['2099-11-04']['count'], 2)
        self.assertEqual(days['2099-11-04']['amounts']['osama'], 120.0)
        self.assertEqual(days['2099-11-04']['amounts']['cash'], 80.0)
        self.assertEqual(days['2099-11-04']['amounts']['unpaid'], 100.0)
        self.assertIsNone(days['2099-11-04']['amounts']['bank'])
        self.assertEqual(days['2099-11-04']['total'], 300.0)
        transfers = [row for row in document['rows'] if row['kind'] == 'transfer']
        self.assertTrue(transfers)
        self.assertTrue(all(row['count'] is None and row['total'] is None for row in transfers))
        self.assertNotIn('2099-12-01', [row['date'] for row in document['rows']])
        self.assertEqual({bill['total'] for bill in document['bills']}, {300.0, 200.0, 100.0, 70.0})
        self.assertEqual({bill['number'] for bill in document['bills']}, {
            custody_bill.name, mixed.name, unpaid.name, bank_bill.name,
        })
        self.assertTrue(any(item['label'] == 'Company' and item['value'] == self.company.name for item in document['filters']))
        self.assertTrue(any(item['label'] == 'Payment status' and item['value'] == 'All statuses' for item in document['filters']))
        self.assertTrue(file_path('baseer_report_layout/static/fonts/IBMPlexSansArabic-Regular.ttf'))
        self.assertTrue(document['font_regular'].startswith('data:font/truetype;base64,'))
        self.assertGreater(len(document['font_regular']), 1000)

        cash_only = report._export_document('2099-11-01', '2099-11-30', 'all', 'cash')
        self.assertFalse(cash_only['show_custody'])
        self.assertEqual(cash_only['totals']['total'], 200.0)
        self.assertEqual(len(cash_only['bills']), 1)
        self.assertEqual(cash_only['bills'][0]['total'], 200.0)
        self.assertNotIn('transfer', [column['key'] for column in cash_only['columns']])

        unpaid_only = report._export_document('2099-11-01', '2099-11-30', 'not_paid')
        self.assertFalse(unpaid_only['show_custody'])
        self.assertEqual(unpaid_only['totals']['total'], 100.0)
        self.assertEqual(unpaid_only['totals']['count'], 1)
        self.assertEqual(unpaid_only['bills'][0]['total'], 100.0)

        content, filename = report._export_xlsx_bytes('2099-11-01', '2099-11-30', 'all')
        self.assertTrue(content.startswith(b'PK'))
        self.assertIn('2099-11-01', filename)
        self.assertIn('2099-11-30', filename)
        self.assertTrue(filename.endswith('.xlsx'))
        self.assertIsNotNone(load_workbook)
        book = load_workbook(io.BytesIO(content))
        self.assertGreaterEqual(len(book.worksheets), 2)
        sheet = book.worksheets[0]
        self.assertTrue(sheet.freeze_panes)
        self.assertTrue(sheet.auto_filter.ref)
        freeze_row = int(''.join(ch for ch in str(sheet.freeze_panes) if ch.isdigit()) or '0')
        self.assertGreaterEqual(freeze_row, 2)
        texts = []
        money_formats = []
        date_formats = []
        for row in sheet.iter_rows():
            for cell in row:
                if cell.value is not None:
                    texts.append(str(cell.value))
                if cell.number_format and '#,##0.00' in str(cell.number_format):
                    money_formats.append(cell.value)
                if cell.number_format == 'YYYY-MM-DD':
                    date_formats.append(cell.value)
        blob = '\n'.join(texts)
        self.assertIn(self.company.name, blob)
        self.assertIn('Daily purchases', blob)
        self.assertIn('Transferred to custody', blob)
        self.assertIn('Custody balance', blob)
        self.assertNotIn('2099-12-01', blob)
        self.assertTrue(any(value in (Decimal('670'), Decimal('670.00'), 670, 670.0) for value in money_formats), money_formats)
        self.assertTrue(date_formats)
        bills_sheet = book.worksheets[1]
        self.assertTrue(bills_sheet.freeze_panes)
        self.assertTrue(bills_sheet.auto_filter.ref)
        bill_texts = [str(cell.value) for row in bills_sheet.iter_rows() for cell in row if cell.value is not None]
        self.assertIn(mixed.name, bill_texts)
        self.assertIn(self.vendor.display_name, bill_texts)
        self.assertNotIn('999', ''.join(bill_texts))

        action = report.action_export_xlsx('2099-11-01', '2099-11-30', 'all')
        self.assertEqual(action['type'], 'ir.actions.act_url')
        self.assertIn('/web/content/', action['url'])
        self.assertIn('download=true', action['url'])
        attachment_id = int(action['url'].split('/web/content/')[1].split('?')[0])
        attachment = self.env['ir.attachment'].browse(attachment_id)
        self.assertTrue(attachment.exists())
        self.assertTrue(attachment.raw.startswith(b'PK'))

    def test_arabic_pdf_and_excel_use_rtl_and_existing_fonts(self):
        self._seed_period()
        self.env['res.lang'].sudo()._activate_lang('ar_001')
        report = self._report()
        report = report.with_context(lang='ar_001')
        document = report._export_document('2099-11-01', '2099-11-30', 'all')
        self.assertTrue(document['arabic'])
        self.assertIn('المشتريات', document['title'])
        self.assertNotEqual(document['title'], 'Daily purchases')
        self.assertEqual(document['filters'][0]['label'], 'الشركة')
        self.assertEqual(document['filters'][1]['label'], 'الفترة')
        self.assertIn('العهدة', document['columns'][-1]['label'] + document['columns'][-2]['label'])
        content, _filename = report._export_xlsx_bytes('2099-11-01', '2099-11-30', 'all')
        book = load_workbook(io.BytesIO(content))
        sheet = book.active
        self.assertTrue(sheet.sheet_view.rightToLeft)
        values = [cell.value for row in sheet.iter_rows() for cell in row if isinstance(cell.value, str)]
        blob = '\n'.join(values)
        self.assertIn('المشتريات', blob)
        self.assertIn('الشركة', blob)
        self.assertIn('الإجماليات', blob)
        self.assertTrue(any(not value.isascii() for value in values if value), values[:20])
        self.assertTrue(book.worksheets[1].sheet_view.rightToLeft)

        pdf_action = report.action_export_pdf('2099-11-01', '2099-11-30', 'all')
        self.assertEqual(pdf_action['type'], 'ir.actions.report')
        self.assertEqual(pdf_action['report_name'], 'baseer_purchase_daily_report.daily_purchases_pdf')
        self.assertEqual(pdf_action['data']['date_from'], '2099-11-01')
        self.assertEqual(pdf_action['data']['status'], 'all')
        reports = report.env['ir.actions.report'].with_context(force_report_rendering=True)
        html, _type = reports._render_qweb_html(
            'baseer_purchase_daily_report.daily_purchases_pdf',
            [],
            data=pdf_action['data'],
        )
        html_text = html.decode() if isinstance(html, (bytes, bytearray)) else html
        self.assertIn('dir="rtl"', html_text)
        self.assertIn('Baseer Plex Arabic', html_text)
        self.assertIn('data:font/truetype;base64,', html_text)
        self.assertIn('المشتريات', html_text)
        self.assertIn(self.company.name, html_text)
        self.assertIn('670.00', html_text.replace(',', ''))
        self.assertIn('2099-11-04', html_text)
        self.assertIn('العهدة', html_text)
        self.assertIn(self.vendor.display_name, html_text)

    def test_export_actions_require_an_authorised_role(self):
        self._bill(40, '2099-11-03')
        report = self._report()
        other = self.env['res.users'].sudo().with_context(no_reset_password=True).create({
            'name': 'Purchase export reader',
            'login': 'purchase_daily_export_reader',
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
        })
        self.assertNotIn(other.company_id.id, FORBIDDEN_COMPANY_IDS)
        blocked = self._report(user=other)
        with self.assertRaises(AccessError):
            blocked.action_export_xlsx('2099-11-01', '2099-11-30', 'all')
        with self.assertRaises(AccessError):
            blocked.action_export_pdf('2099-11-01', '2099-11-30', 'all')
