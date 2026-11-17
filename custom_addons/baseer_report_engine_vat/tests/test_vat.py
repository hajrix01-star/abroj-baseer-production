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
