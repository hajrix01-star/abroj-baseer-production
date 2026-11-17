from odoo.service.model import call_kw
from odoo.tests.common import tagged

from .common import EngineCase


@tagged('post_install', '-at_install')
class TestRpcRegressions(EngineCase):
    def test_rpc_methods_and_account_batch(self):
        company = self._company('RPC test')
        engine = self._engine(company)
        journal = self._journal(company, 'RPC')
        cash = self._account(company, '1000', 'asset_cash')
        income = self._account(company, '4000', 'income')
        self._entry(company, journal, '2041-04-15', cash, income, 100)
        options = self._options()
        for code, line in [('balance_sheet', 'CASH'), ('profit_and_loss', 'REV')]:
            self.assertTrue(call_kw(engine, 'get_bootstrap', [code], {})['labels'])
            full = call_kw(engine, 'get_report', [code, options, True], {})
            expected = next(row['accounts'] for row in full['lines'] if row['code'] == line)
            actual = call_kw(engine, 'get_line_accounts', [code, options, line], {})
            self.assertEqual(actual['accounts'], expected)
            self.assertEqual(call_kw(engine, 'get_lines_accounts', [code, options, [line]], {}), [actual])
            action = call_kw(engine, 'get_move_line_action', [code, options, line, 'c0'], {})
            self.assertTrue(self.env['account.move.line'].search(action['domain']))
            self.assertTrue(call_kw(engine, 'export_xlsx', [code, options], {})['content'])
            self.assertTrue(call_kw(engine, 'export_pdf', [code, options], {})['type'])

    def test_or_domain_keeps_each_conjunction(self):
        from ..models.definition import _or_domains
        company = self._company('Domain test')
        journal = self._journal(company, 'DOM')
        cash = self._account(company, '1000', 'asset_cash')
        income = self._account(company, '4000', 'income')
        posted = self._entry(company, journal, '2041-04-15', cash, income, 100)
        self._entry(company, journal, '2041-04-16', cash, income, 50, posted=False)
        common = [('company_id', '=', company.id), ('parent_state', '=', 'posted')]
        domain = _or_domains([common + [('account_id', '=', cash.id)], common + [('account_id', '=', income.id)]])
        self.assertEqual(self.env['account.move.line'].search(domain), posted.line_ids)

    def test_formula_drill_and_arabic_labels(self):
        company = self._company('Formula and language')
        engine = self._engine(company)
        self.env['res.lang']._activate_lang('ar_001')
        self.env['ir.module.module']._load_module_terms(['baseer_report_engine'], ['ar_001'], overwrite=True)
        arabic = engine.with_context(lang='ar_001')
        self.assertEqual(arabic.get_bootstrap('balance_sheet')['labels']['period'], 'الفترة')
        report = arabic.get_report('profit_and_loss', self._options())
        self.assertIn('من', report['columns'][0]['label'])
        self.assertTrue(any('القيود' in note for note in report['notes']))
        net = next(line for line in report['lines'] if line['code'] == 'NET')
        self.assertFalse(net['amounts'][0]['drill'])

    def test_javascript_translation_catalog(self):
        from odoo.tools.translate import code_translations
        messages = code_translations.get_web_translations('baseer_report_engine', 'ar_001')['messages']
        self.assertEqual(next(item['string'] for item in messages if item['id'] == 'End of Month'), 'نهاية الشهر')

    def test_pdf_rendering_and_report_action(self):
        company = self._company('PDF test')
        engine = self._engine(company)
        action = engine.export_pdf('balance_sheet', self._options())
        self.assertEqual(action['type'], 'ir.actions.act_window')
        company.external_report_layout_id = self.env.ref('web.external_layout_standard')
        self.assertEqual(engine.export_pdf('balance_sheet', self._options())['type'], 'ir.actions.report')
        reports = self.env['ir.actions.report'].with_company(company).with_context(
            allowed_company_ids=[company.id], force_report_rendering=True,
        )
        report_ids = self.env.ref('baseer_report_engine.report_balance_sheet').ids
        data = {'report_code': 'balance_sheet', 'options': self._options()}
        if reports.get_wkhtmltopdf_state() == 'ok':
            self.env['ir.config_parameter'].sudo().set_param('report.url', 'http://127.0.0.1:9')
            pdf, kind = reports._render_qweb_pdf(
                'baseer_report_engine.report_pdf', res_ids=report_ids, data=data,
            )
            self.assertEqual(kind, 'pdf')
            self.assertTrue(pdf.startswith(b'%PDF'))
        else:
            html, kind = reports._render_qweb_html(
                'baseer_report_engine.report_pdf', docids=report_ids, data=data,
            )
            self.assertEqual(kind, 'html')
            self.assertIn(b'Balance Sheet', html)
            self.assertIn(b'class="page"', html)
