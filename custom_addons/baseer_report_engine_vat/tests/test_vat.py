import base64
import io

from openpyxl import load_workbook

from odoo import Command
from odoo.addons.baseer_report_engine.tests.common import EngineCase
from odoo.service.model import call_kw
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class VatReportCase(EngineCase):
    def test_return_and_rpc(self):
        company = self._company('VAT test')
        company.account_fiscal_country_id = self.env.ref('base.sa')
        journal = self._journal(company, 'VAT')
        receivable = self._account(company, '121001', 'asset_current')
        sales = self._account(company, '411001', 'income')
        tax = self._account(company, '211001', 'liability_current')
        tags = self.env['account.account.tag']
        base_tag = tags._get_tax_tags('-1(B)', company.account_fiscal_country_id.id)
        tax_tag = tags._get_tax_tags('-1(T)', company.account_fiscal_country_id.id)
        move = self.env['account.move'].with_company(company).create({
            'company_id': company.id, 'date': '2041-02-01', 'journal_id': journal.id,
            'line_ids': [
                Command.create({'name': 'Receivable', 'account_id': receivable.id, 'debit': 115}),
                Command.create({'name': 'Sales', 'account_id': sales.id, 'credit': 100, 'tax_tag_ids': [Command.set(base_tag.ids)]}),
                Command.create({'name': 'VAT', 'account_id': tax.id, 'credit': 15, 'tax_tag_ids': [Command.set(tax_tag.ids)]}),
            ],
        })
        move.action_post()
        engine = self._engine(company)
        options = self._options()
        call = lambda method, args: call_kw(engine, method, args, {'context': engine.env.context})
        payload = call('get_report', ['saudi_vat', options])
        self.assertEqual(self._value(payload, 'sa_1', 'base'), '100.00')
        self.assertEqual(self._value(payload, 'sa_16', 'tax'), '15.00')
        action = call('get_move_line_action', ['saudi_vat', options, 'sa_1', 'tax'])
        self.assertEqual(action['res_model'], 'account.move.line')
        self.assertEqual(len(self.env['account.move.line'].search(action['domain'])), 1)
        self.assertTrue(call('export_xlsx', ['saudi_vat', options])['content'])
        self.assertTrue(call('export_pdf', ['saudi_vat', options])['type'])

    def test_drafts_and_refunds(self):
        company = self._company('VAT draft test')
        company.account_fiscal_country_id = self.env.ref('base.sa')
        journal = self._journal(company, 'VAD')
        debit = self._account(company, '121009', 'asset_current')
        credit = self._account(company, '411009', 'income')
        tag = self.env['account.account.tag']._get_tax_tags('-1(B)', company.account_fiscal_country_id.id)
        draft = self._entry(company, journal, '2041-02-01', debit, credit, 100, posted=False)
        draft.line_ids.filtered(lambda line: line.account_id == credit).tax_tag_ids = [Command.set(tag.ids)]
        engine = self._engine(company)
        self.assertEqual(self._value(engine.get_report('saudi_vat', self._options()), 'sa_1', 'base'), '0.00')
        self.assertEqual(self._value(engine.get_report('saudi_vat', self._options(posted_only=False)), 'sa_1', 'base'), '100.00')
        draft.action_post()
        refund = self._entry(company, journal, '2041-03-01', credit, debit, 40, posted=False)
        refund.line_ids.filtered(lambda line: line.account_id == credit).tax_tag_ids = [Command.set(tag.ids)]
        refund.action_post()
        self.assertEqual(self._value(engine.get_report('saudi_vat', self._options()), 'sa_1', 'base'), '60.00')

    def test_arabic_menu(self):
        self.env['res.lang']._activate_lang('ar_001')
        self.env['ir.module.module']._load_module_terms(['baseer_report_engine_vat'], ['ar_001'], overwrite=True)
        menu = self.env.ref('baseer_report_engine_vat.menu_vat')
        self.assertEqual(menu.with_context(lang='ar_001').name, 'تقرير ضريبة القيمة المضافة (جديد)')

    def test_saudi_chart_invoices_and_legacy_parity(self):
        company = self._company('Saudi chart VAT')
        company.country_id = self.env.ref('base.sa')
        self.env['account.chart.template'].try_loading('sa', company=company, install_demo=False)
        env = self.env(context=dict(self.env.context, allowed_company_ids=[company.id]))
        chart = env['account.chart.template']
        tax = lambda name: chart.ref(name)
        partner = env['res.partner'].create({'name': 'VAT fixture partner'})
        income = env['account.account'].search([('company_ids', 'in', company.id), ('account_type', '=', 'income')], limit=1)
        expense = env['account.account'].search([('company_ids', 'in', company.id), ('account_type', '=', 'expense')], limit=1)
        def invoice(kind, entries, post=True):
            account = income if kind.startswith('out_') else expense
            move = env['account.move'].create({
                'move_type': kind, 'partner_id': partner.id, 'invoice_date': '2024-02-01',
                'date': '2024-02-01', 'company_id': company.id,
                'invoice_line_ids': [Command.create({'name': name, 'quantity': 1,
                    'price_unit': amount, 'account_id': account.id,
                    'tax_ids': [Command.set(tax(tax_name).ids)]})
                    for name, amount, tax_name in entries],
            })
            if post:
                move.action_post()
            return move
        invoice('out_invoice', [('Sale', 1000, 'sa_sales_tax_15'), ('Zero', 200, 'sa_international_transport_passengers_tax_0'), ('Exempt', 100, 'sa_exempt_sales_tax_0')])
        invoice('out_refund', [('Credit', 100, 'sa_sales_tax_15')])
        invoice('in_invoice', [('Purchase', 400, 'sa_purchase_tax_15'), ('Reverse charge', 200, 'sa_rcp_tax_15')])
        invoice('in_refund', [('Refund', 100, 'sa_purchase_tax_15')])
        invoice('out_invoice', [('Draft', 500, 'sa_sales_tax_15')], post=False)
        # POS-like aggregate journal entry, using the localization's real tags.
        journal = self._journal(company, 'POSV')
        clearing = self._account(company, '129991', 'asset_current')
        sale_tax = tax('sa_sales_tax_15')
        base_rep = sale_tax.invoice_repartition_line_ids.filtered(lambda r: r.repartition_type == 'base')
        tax_rep = sale_tax.invoice_repartition_line_ids.filtered(lambda r: r.repartition_type == 'tax')
        pos = env['account.move'].create({'journal_id': journal.id, 'date': '2024-02-02',
            'line_ids': [Command.create({'name': 'Clearing', 'account_id': clearing.id, 'debit': 57.5}),
                Command.create({'name': 'POS sale', 'account_id': income.id, 'credit': 50, 'tax_tag_ids': [Command.set(base_rep.tag_ids.ids)]}),
                Command.create({'name': 'POS VAT', 'account_id': tax_rep.account_id.id, 'credit': 7.5, 'tax_tag_ids': [Command.set(tax_rep.tag_ids.ids)]})]})
        pos.action_post()
        options = self._options(date_from='2024-01-01', date_to='2024-03-31')
        payload = self._engine(company).get_report('saudi_vat', options)
        draft_payload = self._engine(company).get_report('saudi_vat', dict(options, posted_only=False))
        self.assertEqual(self._value(draft_payload, 'sa_1', 'base'), '1450.00')
        self.assertEqual(self._value(draft_payload, 'sa_1', 'tax'), '217.50')
        expected = [(950, 142.5), (0, None), (200, None), (0, None), (100, None), (1250, 142.5),
                    (300, 45), (0, 0), (200, 0), (0, None), (0, None), (500, 45),
                    (None, 97.5), (None, 0), (None, 0), (None, 97.5)]
        for number, pair in enumerate(expected, 1):
            for column, amount in zip(('base', 'tax'), pair):
                value = self._value(payload, 'sa_%s' % number, column)
                self.assertEqual(value, None if amount is None else '%.2f' % amount, (number, column))
        self.assertEqual(self._value(payload, 'vat_difference', 'tax'), '0.00')
        grouped = self._engine(company).get_report('saudi_vat', dict(options, tax_grouping='tax'))
        for section, box in [('sale', 'sa_6'), ('purchase', 'sa_12')]:
            for column in ('base', 'tax'):
                self.assertEqual(self._value(grouped, 'tax_total_' + section, column), self._value(payload, box, column))
                total = sum(float(next(a['value'] for a in row['amounts'] if a['key'] == column) or 0)
                            for row in grouped['lines'] if row['code'].startswith('tax_' + section + '_'))
                self.assertAlmostEqual(total, float(self._value(payload, box, column)))
        self.assertEqual(self._value(payload, 'vat_draft', 'tax'), '75.00')
        self.assertTrue(self._engine(company).get_move_line_action('saudi_vat', options, 'vat_draft', 'tax')['domain'])
        for lang, difference in [('en_US', 'Difference'), ('ar_001', 'الفرق')]:
            self.env['res.lang']._activate_lang(lang)
            if lang == 'ar_001':
                self.env['ir.module.module']._load_module_terms(['baseer_report_engine_vat'], [lang], overwrite=True)
            localized = self._engine(company).with_context(lang=lang)
            for grouping in ('grid', 'tax'):
                export_options = dict(options, tax_grouping=grouping)
                exported = load_workbook(io.BytesIO(base64.b64decode(localized.export_xlsx('saudi_vat', export_options)['content'])))
                self.assertIn(difference, [r[0] for r in exported.active.values])
                html_group, _ = self.env['ir.actions.report'].with_company(company).with_context(lang=lang, allowed_company_ids=[company.id])._render_qweb_html(
                    'baseer_report_engine.report_pdf', docids=localized._definition('saudi_vat').ids,
                    data={'report_code': 'saudi_vat', 'options': export_options})
                self.assertIn(difference, html_group.decode())
            workbook = load_workbook(io.BytesIO(base64.b64decode(localized.export_xlsx('saudi_vat', options)['content'])))
            sheet = workbook.active
            rows = list(sheet.values)
            self.assertIn(difference, [row[0] for row in rows], (lang, [row[0] for row in rows]))
            difference_row = next(row for row in rows if row[0] == difference)
            self.assertIsNotNone(difference_row[2])
            self.assertTrue(any(row[2] == 97.5 for row in rows))
            if lang.startswith('ar'):
                self.assertTrue(sheet.sheet_view.rightToLeft)
            html, _ = self.env['ir.actions.report'].with_company(company).with_context(lang=lang, allowed_company_ids=[company.id])._render_qweb_html(
                'baseer_report_engine.report_pdf', docids=localized._definition('saudi_vat').ids,
                data={'report_code': 'saudi_vat', 'options': options})
            self.assertIn(difference, html.decode())
            self.assertIn('97.50', html.decode())
        if 'baseer.tax.report.wizard' in env:
            wizard = env['baseer.tax.report.wizard'].new({'company_id': company.id, 'period_type': 'quarter', 'year': 2024, 'quarter': '1', 'month': '1', 'display_mode': 'detailed'})
            for row in wizard._build_report()['rows']:
                for column in ('base', 'tax'):
                    value = self._value(payload, 'sa_' + row['number'], column)
                    self.assertEqual(value, None if row[column] is None else '%.2f' % row[column])

        # A direct posting to a VAT account is visible as an untagged cause.
        self._entry(company, journal, '2024-02-03', clearing, tax_rep.account_id, 10)
        discrepant = self._engine(company).get_report('saudi_vat', options)
        self.assertEqual(self._value(discrepant, 'vat_difference', 'tax'), '-10.00')
        self.assertTrue(any('without tax tags: 1' in note for note in discrepant['notes']))
        self.assertEqual(self._value(discrepant, 'vat_untagged', 'tax'), '10.00')
        self.assertTrue(self._engine(company).get_move_line_action('saudi_vat', options, 'vat_untagged', 'tax')['domain'])
        tobacco = self._account(company, '201021', 'liability_current')
        self._entry(company, journal, '2024-02-04', clearing, tobacco, 25)
        after_fee = self._engine(company).get_report('saudi_vat', options)
        for code in ('sa_16', 'vat_movement', 'vat_difference', 'vat_untagged'):
            self.assertEqual(self._value(after_fee, code, 'tax'), self._value(discrepant, code, 'tax'))

    def test_default_last_full_period(self):
        company = self._company('VAT default period')
        company.account_fiscal_country_id = self.env.ref('base.sa')
        engine = self._engine(company)
        options = engine._normalize_options(engine._definition('saudi_vat'), {'anchor_date': '2024-05-16'})
        monthly = getattr(company, 'account_tax_periodicity', False) in ('monthly', 'month')
        self.assertEqual(options['preset'], 'last_month' if monthly else 'last_quarter')
        self.assertEqual((options['date_from'], options['date_to']),
                         ('2024-04-01', '2024-04-30') if monthly else ('2024-01-01', '2024-03-31'))
