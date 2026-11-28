"""PDF and Excel exports of the daily sales and customers report."""

import io
from datetime import timedelta
from decimal import Decimal
from odoo import Command, fields
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged
from odoo.tools.misc import file_path

try:
    from openpyxl import load_workbook
except ImportError:  # pragma: no cover - bundled with the local test venv
    load_workbook = None

FORBIDDEN_COMPANY_IDS = {54, 56}


@tagged('post_install', '-at_install')
class TestDailyReportExport(TransactionCase):

    def _onboard(self, name):
        company = self.env['res.company'].create({'name': name})
        self.assertNotIn(company.id, FORBIDDEN_COMPANY_IDS)
        self.env.user.sudo().write({'company_ids': [Command.link(company.id)]})
        self.assertEqual(company.currency_id.name, 'SAR')
        wizard_action = company.action_baseer_open_onboarding()
        wizard = self.env[wizard_action['res_model']].browse(wizard_action['res_id'])
        wizard.write({'sales_mode': 'summary', 'setup_summary_jahez': True})
        wizard.action_apply_selected()
        scoped = self.env['baseer.pos.summary'].with_context(
            allowed_company_ids=[company.id],
        ).with_company(company)
        config = scoped.env['pos.config'].search([
            ('company_id', '=', company.id), ('baseer_summary_only', '=', True),
        ], limit=1)
        self.assertTrue(config, 'Onboarding must create a summary POS')
        method = config.payment_method_ids[:1]
        self.assertTrue(method)
        return company, scoped, config, method

    def _approve(self, scoped, company, config, method, day, amount, customers=1, period='all'):
        summary = scoped.create({
            'company_id': company.id,
            'config_id': config.id,
            'business_date': day,
            'period_scope': period,
            'day_schedule': 'all',
            'customer_count': customers,
            'allocation_ids': [Command.create({
                'payment_method_id': method.id,
                'amount': amount,
            })],
        })
        summary.action_approve()
        self.assertEqual(summary.state, 'approved')
        return summary

    def _report(self, company, date_from, date_to, lang=None):
        env = self.env(context=dict(self.env.context, lang=lang or self.env.lang, allowed_company_ids=company.ids, tz='Asia/Riyadh'))
        return env['baseer.pos.daily.report'].with_company(company).create({
            'company_id': company.id,
            'date_from': date_from,
            'date_to': date_to,
        })

    def test_export_respects_date_and_company_filters_and_includes_totals(self):
        company, scoped, config, method = self._onboard('Daily sales export cafe')
        other, other_scoped, other_config, other_method = self._onboard('Daily sales export other')
        today = fields.Date.context_today(scoped)
        day_one = today - timedelta(days=3)
        day_two = today - timedelta(days=2)
        day_three = today - timedelta(days=1)
        self._approve(scoped, company, config, method, day_one, 115, customers=2)
        self._approve(scoped, company, config, method, day_three, 230, customers=4)
        self._approve(other_scoped, other, other_config, other_method, day_one, 999, customers=9)
        # A day after the requested period must stay out of the file.
        self._approve(scoped, company, config, method, today, 50, customers=1)

        report = self._report(company, day_one, day_three)
        self.assertFalse(report.generated)
        document = report._export_document()
        self.assertTrue(report.generated)
        self.assertEqual(document['company'], company.name)
        self.assertEqual(document['date_from'], day_one.isoformat())
        self.assertEqual(document['date_to'], day_three.isoformat())
        self.assertEqual(document['currency'], 'SAR')
        self.assertEqual([row['date'] for row in document['lines']], [
            day_one.isoformat(), day_two.isoformat(), day_three.isoformat(),
        ])
        self.assertNotIn(today.isoformat(), [row['date'] for row in document['lines']])
        self.assertEqual(document['lines'][0]['sales'], 115.0)
        self.assertEqual(document['lines'][0]['customers'], 2)
        self.assertEqual(document['lines'][0]['status'], 'complete')
        self.assertFalse(document['lines'][1]['has_sales'])
        self.assertEqual(document['lines'][1]['status'], 'missing')
        self.assertEqual(document['lines'][2]['sales'], 230.0)
        self.assertEqual(document['totals']['sales'], 345.0)
        self.assertEqual(document['totals']['customers'], 6)
        self.assertEqual(document['totals']['count'], 3)
        self.assertEqual(report.recorded_sales, 345.0)
        self.assertEqual(report.operating_days, 2)
        # The other company's 999 sale is never mixed in.
        self.assertTrue(all(row['sales'] != 999 for row in document['lines'] if row['has_sales']))
        self.assertNotIn(other.name, [item['value'] for item in document['filters']])
        self.assertTrue(any(item['label'] == 'Company' and item['value'] == company.name for item in document['filters']))
        self.assertTrue(file_path('baseer_report_layout/static/fonts/IBMPlexSansArabic-Regular.ttf'))
        self.assertTrue(document['font_regular'].startswith('data:font/truetype;base64,'))
        self.assertGreater(len(document['font_regular']), 1000)

        content, filename = report._export_xlsx_bytes()
        self.assertTrue(content.startswith(b'PK'))
        self.assertIn(day_one.isoformat(), filename)
        self.assertIn(day_three.isoformat(), filename)
        self.assertTrue(filename.endswith('.xlsx'))
        self.assertIsNotNone(load_workbook)
        book = load_workbook(io.BytesIO(content))
        sheet = book.active
        self.assertTrue(sheet.freeze_panes)
        self.assertTrue(sheet.auto_filter.ref)
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
        self.assertIn(company.name, blob)
        self.assertIn('Daily sales and customers', blob)
        self.assertNotIn(other.name, blob)
        self.assertIn('345', ''.join(ch for ch in blob if ch.isdigit() or ch in '.,'))
        self.assertTrue(any(value == Decimal('345') or value == 345 or value == 345.0 for value in money_formats))
        self.assertTrue(date_formats)
        # Totals row is the last numeric sales/customers pair.
        self.assertEqual(sheet.auto_filter.ref.split(':')[0][1:], str(_header_row(sheet)))
        freeze_row = int(''.join(ch for ch in sheet.freeze_panes if ch.isdigit()) or '0')
        self.assertGreaterEqual(freeze_row, 2)

        action = report.action_export_xlsx()
        self.assertEqual(action['type'], 'ir.actions.act_url')
        self.assertIn('/web/content/', action['url'])
        self.assertIn('download=true', action['url'])
        attachment_id = int(action['url'].split('/web/content/')[1].split('?')[0])
        attachment = self.env['ir.attachment'].browse(attachment_id)
        self.assertTrue(attachment.exists())
        self.assertEqual(attachment.res_model, report._name)
        self.assertEqual(attachment.res_id, report.id)
        self.assertTrue(attachment.raw.startswith(b'PK'))

    def test_arabic_pdf_and_excel_use_rtl_and_existing_fonts(self):
        company, scoped, config, method = self._onboard('مقهى تصدير المبيعات')
        today = fields.Date.context_today(scoped)
        day = today - timedelta(days=1)
        self._approve(scoped, company, config, method, day, 115, customers=2)
        self.env['res.lang'].sudo()._activate_lang('ar_001')
        report = self._report(company, day, day, lang='ar_001')
        document = report._export_document()
        self.assertTrue(document['arabic'])
        self.assertIn('المبيعات', document['title'])
        self.assertNotEqual(document['title'], 'Daily sales and customers')
        self.assertIn(company.name, document['company'])
        content, _filename = report._export_xlsx_bytes()
        book = load_workbook(io.BytesIO(content))
        sheet = book.active
        self.assertTrue(sheet.sheet_view.rightToLeft)
        values = [cell.value for row in sheet.iter_rows() for cell in row if isinstance(cell.value, str)]
        blob = '\n'.join(values)
        self.assertIn('المبيعات', blob)
        self.assertTrue(any(not value.isascii() for value in values if value), values[:20])
        self.assertEqual(document['filters'][0]['label'], 'الشركة')
        self.assertEqual(document['filters'][1]['label'], 'الفترة')
        self.assertIn('الفترة', blob)
        self.assertIn('الشركة', blob)
        self.assertIn('الإجماليات', blob)

        pdf_action = report.action_export_pdf()
        self.assertEqual(pdf_action['type'], 'ir.actions.report')
        self.assertEqual(pdf_action['report_name'], 'baseer_pos_summary.daily_sales_pdf')
        reports = report.env['ir.actions.report'].with_context(force_report_rendering=True)
        html, _type = reports._render_qweb_html(
            'baseer_pos_summary.daily_sales_pdf', report.ids,
        )
        html_text = html.decode() if isinstance(html, (bytes, bytearray)) else html
        self.assertIn('dir="rtl"', html_text)
        self.assertIn('Baseer Plex Arabic', html_text)
        self.assertIn('data:font/truetype;base64,', html_text)
        self.assertIn('المبيعات', html_text)
        self.assertIn(company.name, html_text)
        self.assertIn('115.00', html_text.replace(',', ''))
        self.assertIn(day.isoformat(), html_text)

        # wkhtmltopdf is exercised from the local preview server, not here:
        # a single-threaded --stop-after-init process deadlocks when the
        # report engine's footer layout requests CSS from the same worker.

    def test_export_actions_require_the_report_creator(self):
        company, scoped, config, method = self._onboard('Daily sales export access')
        day = fields.Date.context_today(scoped) - timedelta(days=1)
        self._approve(scoped, company, config, method, day, 115)
        report = self._report(company, day, day)
        report.action_generate()
        other = self.env['res.users'].create({
            'name': 'Daily sales export reader',
            'login': 'daily_sales_export_reader',
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('point_of_sale.group_pos_user').id,
            ])],
            'company_id': company.id,
            'company_ids': [Command.set(company.ids)],
        })
        with self.assertRaises(AccessError):
            report.with_user(other).with_company(company).action_export_xlsx()
        with self.assertRaises(AccessError):
            report.with_user(other).with_company(company).action_export_pdf()


def _header_row(sheet):
    for index, row in enumerate(sheet.iter_rows(min_col=1, max_col=1), start=1):
        value = row[0].value
        if value in ('Date', 'التاريخ'):
            return index
    raise AssertionError('Could not find the Excel table header')
