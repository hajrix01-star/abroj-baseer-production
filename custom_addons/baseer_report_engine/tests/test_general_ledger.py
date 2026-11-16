import base64
import io
import zipfile

from odoo.service.model import call_kw
from odoo.tests.common import tagged

from .common import EngineCase


@tagged('post_install', '-at_install')
class TestGeneralLedger(EngineCase):
    def test_paging_reconciliation_and_exports(self):
        company = self._company('Ledger company')
        engine = self._engine(company)
        journal = self._journal(company, 'GLT')
        cash = self._account(company, '1000', 'asset_cash')
        income = self._account(company, '4000', 'income')
        self._entry(company, journal, '2040-05-01', cash, income, 10)
        moves = [self._entry(company, journal, '2041-04-%02d' % day, cash, income, day) for day in range(1, 6)]
        options = self._options(date_from='2041-04-01', date_to='2041-04-30')
        gl = call_kw(engine, 'get_report', ['general_ledger', options], {'context': engine.env.context})
        self.assertEqual(float(gl['lines'][-1]['amounts'][0]['value']), float(gl['lines'][-1]['amounts'][1]['value']))
        tb = engine.get_report('trial_balance', options)
        tb_rows = {(r['account_id'], r['company_id']): r for r in tb['lines'][:-1]}
        for row in gl['lines'][:-1]:
            self.assertEqual(float(row['amounts'][-1]['value']), float(tb_rows[(row['account_id'], row['company_id'])]['amounts'][-1]['value']))
        row = next(r for r in gl['lines'] if r.get('account_id') == cash.id)
        paged = engine.with_context(baseer_gl_page_size=2)
        pages = [call_kw(paged, 'get_ledger_lines', ['general_ledger', options, cash.id, company.id, offset], {'context': paged.env.context}) for offset in (0, 2, 4)]
        self.assertEqual([p['has_more'] for p in pages], [True, True, False])
        rows = sum((p['rows'] for p in pages), [])
        whole = engine.with_context(baseer_gl_page_size=100).get_ledger_lines('general_ledger', options, cash.id, company.id)
        self.assertEqual(rows, whole['rows'])
        self.assertEqual(rows[0]['type'], 'initial')
        self.assertEqual([float(r['amounts'][-1]['value']) for r in rows if r['type'] == 'item'], [11, 13, 16, 20, 25])
        self.assertEqual(rows[-1]['type'], 'total')
        self.assertEqual(call_kw(engine, 'get_move_action', [moves[0].line_ids.filtered(lambda l: l.account_id == cash).id], {'context': engine.env.context})['res_id'], moves[0].id)
        action = call_kw(engine, 'get_general_ledger_action', ['trial_balance', options, cash.id, company.id], {'context': engine.env.context})
        self.assertEqual(action['context']['baseer_options']['unfolded_accounts'], [[cash.id, company.id]])
        self.assertEqual(action['context']['baseer_options']['date_from'], options['date_from'])
        action = engine.get_move_line_action('general_ledger', options, row['code'], 'end', cash.id, company.id)
        self.assertEqual(sum(self.env['account.move.line'].search(action['domain']).mapped('balance')), 25)
        expanded = dict(options, unfolded_accounts=[[cash.id, company.id]])
        result = call_kw(engine, 'export_xlsx', ['general_ledger', expanded], {'context': engine.env.context})
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(result['content']))) as archive:
            self.assertIn(b'Initial Balance', archive.read('xl/sharedStrings.xml'))
        self.assertTrue(call_kw(engine, 'export_pdf', ['general_ledger', expanded], {'context': engine.env.context})['type'])
        for lang, title in [('en_US', 'General Ledger'), ('ar_001', 'دفتر الأستاذ العام')]:
            self.env['res.lang']._activate_lang(lang)
            self.env['ir.module.module']._load_module_terms(['baseer_report_engine'], [lang], overwrite=True)
            html, _ = self.env['ir.actions.report'].with_company(company).with_context(lang=lang, allowed_company_ids=[company.id])._render_qweb_html('baseer_report_engine.report_pdf', docids=self.env.ref('baseer_report_engine.report_general_ledger').ids, data={'report_code': 'general_ledger', 'options': expanded})
            self.assertIn(title.encode(), html)
        self.assertEqual(self.env.ref('baseer_report_engine.menu_general_ledger').with_context(lang='ar_001').name, 'دفتر الأستاذ العام (جديد)')

    def test_filters_access_and_query_scaling(self):
        from odoo import Command
        from odoo.exceptions import AccessError
        company = self._company('Ledger filters')
        engine = self._engine(company)
        journal = self._journal(company, 'GLF')
        other = self._journal(company, 'GLO')
        cash = self._account(company, '1000', 'asset_cash')
        income = self._account(company, '4000', 'income')
        self._entry(company, journal, '2041-03-01', cash, income, 10)
        self._entry(company, other, '2041-04-01', cash, income, 5, posted=False)
        options = self._options(date_from='2041-04-01', date_to='2041-04-30')
        def balance(opts):
            report = engine.get_report('general_ledger', opts)
            return float(next(r for r in report['lines'] if r.get('account_id') == cash.id)['amounts'][-1]['value'])
        self.assertEqual(balance(options), 10)
        self.assertEqual(balance(dict(options, posted_only=False)), 15)
        self.assertEqual(balance(dict(options, posted_only=False, journal_ids=[journal.id])), 10)
        user = self.env['res.users'].create({'name': 'Ledger reader', 'login': 'ledger_reader', 'company_id': company.id, 'company_ids': [Command.set(company.ids)], 'group_ids': [Command.set([self.env.ref('base.group_user').id, self.env.ref('account.group_account_readonly').id])]})
        self.assertTrue(engine.with_user(user).get_report('general_ledger', options)['lines'])
        user.group_ids = [Command.set([self.env.ref('base.group_user').id])]
        with self.assertRaises(AccessError):
            engine.with_user(user).get_report('general_ledger', options)
        for index in range(15):
            account = self._account(company, str(5000 + index), 'expense')
            self._entry(company, journal, '2041-04-01', account, cash, 1)
        for opts in (options, dict(options, unfold_all=True)):
            engine.get_report('general_ledger', opts)
            start = self.cr.sql_log_count
            engine.get_report('general_ledger', opts)
            self.assertLess(self.cr.sql_log_count - start, 100)

    def test_analytic_paging_and_multicompany(self):
        first = self._company('Ledger A')
        second = self._company('Ledger B')
        engine = self.env['baseer.report.engine'].with_company(first).with_context(allowed_company_ids=[first.id, second.id], baseer_gl_page_size=2)
        plan = self.env['account.analytic.plan'].create({'name': 'Ledger plan'})
        analytic = self.env['account.analytic.account'].create({'name': 'Ledger analytic', 'plan_id': plan.id, 'company_id': first.id})
        for company, code in [(first, 'GLA'), (second, 'GLB')]:
            journal = self._journal(company, code)
            cash = self._account(company, '1000', 'asset_cash')
            income = self._account(company, '4000', 'income')
            if company == first:
                first_cash = cash
                for day in range(1, 5):
                    self._entry(company, journal, '2041-04-%02d' % day, cash, income, 10, analytic={str(analytic.id): 50})
            else:
                self._entry(company, journal, '2041-04-01', cash, income, 10)
        options = self._options(date_from='2041-04-01', date_to='2041-04-30')
        report = engine.get_report('general_ledger', options)
        cash_rows = [r for r in report['lines'] if r.get('account_code') == '1000']
        self.assertEqual(len(cash_rows), 2)
        self.assertTrue(all(' — ' in row['name'] for row in cash_rows))
        filtered = dict(options, analytic_account_ids=[analytic.id])
        first_page = engine.get_ledger_lines('general_ledger', filtered, first_cash.id, first.id)
        second_page = engine.get_ledger_lines('general_ledger', filtered, first_cash.id, first.id, 2)
        self.assertTrue(first_page['has_more'])
        self.assertFalse(second_page['has_more'])
        self.assertEqual([float(r['amounts'][-1]['value']) for r in first_page['rows'] + second_page['rows'] if r['type'] == 'item'], [5, 10, 15, 20])

    def test_item_metadata_and_export_dates(self):
        from odoo import Command
        company = self._company('Ledger item metadata')
        engine = self._engine(company)
        journal = self._journal(company, 'GLM')
        cash = self._account(company, '1000', 'asset_cash')
        income = self._account(company, '4000', 'income')
        partner = self.env['res.partner'].create({'name': 'Ledger partner'})
        currency = self.env.ref('base.EUR')
        currency.active = True
        move = self.env['account.move'].with_company(company).create({
            'company_id': company.id, 'date': '2041-04-01', 'journal_id': journal.id,
            'line_ids': [
                Command.create({'name': 'communication', 'account_id': cash.id, 'partner_id': partner.id, 'debit': 10, 'currency_id': currency.id, 'amount_currency': 10}),
                Command.create({'name': 'counterpart', 'account_id': income.id, 'credit': 10, 'currency_id': currency.id, 'amount_currency': -10}),
            ],
        })
        move._post(soft=False)
        options = self._options(date_from='2041-04-01', date_to='2041-04-30', unfolded_accounts=[[cash.id, company.id]])
        payload = engine.get_report('general_ledger', options)
        row = next(r for r in payload['lines'] if r.get('account_id') == cash.id)
        item = next(r for r in row['ledger']['rows'] if r['type'] == 'item')
        self.assertEqual(item['name'], move.name + ' communication')
        self.assertEqual(item['partner'], partner.name)
        self.assertTrue(item['currency'])
        self.assertEqual(item['date_raw'], '2041-04-01')
        result = engine.export_xlsx('general_ledger', options)
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(result['content']))) as archive:
            self.assertIn(b'communication', archive.read('xl/sharedStrings.xml'))
            self.assertIn(b'yyyy-mm-dd', archive.read('xl/styles.xml'))
        self.assertTrue(call_kw(engine, 'get_bootstrap', ['general_ledger'], {'context': engine.env.context}))
        self.assertEqual(call_kw(engine, 'get_draft_entries_action', ['general_ledger', options], {'context': engine.env.context})['res_model'], 'account.move')
