import base64
import io
import zipfile

from odoo.tests.common import tagged
from odoo.service.model import call_kw

from .common import EngineCase


@tagged('post_install', '-at_install')
class TestTrialBalance(EngineCase):
    def test_grid_values_drill_and_exports(self):
        company = self._company('Trial balance')
        engine = self._engine(company)
        journal = self._journal(company, 'TBL')
        cash = self._account(company, '1000', 'asset_cash')
        income = self._account(company, '4000', 'income')
        earnings = self._account(company, '3000', 'equity_unaffected')
        self._entry(company, journal, '2040-05-01', cash, income, 100)
        self._entry(company, journal, '2041-02-01', cash, income, 30)
        self._entry(company, journal, '2041-04-01', cash, income, 20)
        options = self._options(date_from='2041-04-01', date_to='2041-04-30')
        payload = call_kw(engine, 'get_report', ['trial_balance', options], {})
        self.assertEqual([g['kind'] for g in payload['column_groups']], ['initial', 'period', 'end'])
        rows = {r.get('account_id'): r for r in payload['lines'] if r.get('account_id')}
        self.assertEqual([float(a['value']) for a in rows[cash.id]['amounts']], [130, 20, 0, 150])
        self.assertEqual([float(a['value']) for a in rows[income.id]['amounts']], [-30, 0, 20, -50])
        self.assertEqual(float(rows[earnings.id]['amounts'][0]['value']), -100)
        self.assertEqual(float(payload['lines'][-1]['amounts'][0]['value']), 0)
        self.assertEqual(float(payload['lines'][-1]['amounts'][-1]['value']), 0)
        for row in rows.values():
            for column, amount in zip(payload['columns'], row['amounts']):
                action = call_kw(engine, 'get_move_line_action', ['trial_balance', options, row['code'], column['key'], row['account_id'], company.id], {})
                lines = self.env['account.move.line'].search(action['domain'])
                self.assertAlmostEqual(sum(lines.mapped(column['figure'])), float(amount['value']))
        drill_options = dict(options, comparison=1, posted_only=False)
        drill_report = engine.get_report('trial_balance', drill_options)
        for row in drill_report['lines'][:-1]:
            for column, amount in zip(drill_report['columns'], row['amounts']):
                if float(amount['value']):
                    action = call_kw(engine, 'get_move_line_action', ['trial_balance', drill_options, row['code'], column['key'], row['account_id'], company.id], {})
                    self.assertAlmostEqual(sum(self.env['account.move.line'].search(action['domain']).mapped(column['figure'])), float(amount['value']))
        comparison = engine.get_report('trial_balance', dict(options, comparison=2))
        self.assertEqual([g['period_key'] for g in comparison['column_groups'][1:-1]], ['c2', 'c1', 'c0'])
        self.assertEqual(engine.get_bootstrap('trial_balance')['defaults']['preset'], 'this_month')
        result = engine.export_xlsx('trial_balance', options)
        self.assertEqual(result['filename'], 'trial-balance.xlsx')
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(result['content']))) as archive:
            self.assertIn(b'Initial Balance', archive.read('xl/sharedStrings.xml'))
        self.env['res.lang']._activate_lang('ar_001')
        self.env['ir.module.module']._load_module_terms(['baseer_report_engine'], ['ar_001'], overwrite=True)
        self.assertEqual(self.env.ref('baseer_report_engine.menu_trial_balance').with_context(lang='ar_001').name, 'ميزان المراجعة (جديد)')
        for lang, name in [('en_US', 'Trial Balance'), ('ar_001', 'ميزان المراجعة')]:
            html, _ = self.env['ir.actions.report'].with_company(company).with_context(lang=lang, allowed_company_ids=[company.id])._render_qweb_html('baseer_report_engine.report_pdf', docids=self.env.ref('baseer_report_engine.report_trial_balance').ids, data={'report_code': 'trial_balance', 'options': options})
            self.assertIn(name.encode(), html)
            self.assertIn(b'150.00', html)

    def test_earnings_account_excludes_archived(self):
        company = self._company('Archived earnings')
        engine = self._engine(company)
        archived = self._account(company, '1000', 'equity_unaffected')
        archived.active = False
        active = self._account(company, '3000', 'equity_unaffected')
        journal = self._journal(company, 'TEA')
        cash = self._account(company, '2000', 'asset_cash')
        income = self._account(company, '4000', 'income')
        self._entry(company, journal, '2040-05-01', cash, income, 100)
        options = self._options(date_from='2041-04-01', date_to='2041-04-30')
        report = engine.with_context(active_test=False).get_report('trial_balance', options)
        row = next(row for row in report['lines'] if row.get('account_id') == active.id)
        self.assertEqual(float(row['amounts'][0]['value']), -100)
        self.assertEqual(engine._grid_earnings_accounts()[company.id], active)
        active.active = False
        self.assertFalse(engine._grid_earnings_accounts()[company.id])
        report = engine.get_report('trial_balance', options)
        self.assertEqual(float(next(row for row in report['lines'] if row.get('account_id') == 0)['amounts'][0]['value']), -100)

    def test_filters_and_fiscal_year(self):
        company = self._company('March fiscal year', month='3', day=31)
        engine = self._engine(company)
        journal = self._journal(company, 'TBF')
        other = self._journal(company, 'TBG')
        cash = self._account(company, '1000', 'asset_cash')
        income = self._account(company, '4000', 'income')
        earnings = self._account(company, '3000', 'equity_unaffected')
        self._entry(company, journal, '2041-03-01', cash, income, 100)
        self._entry(company, journal, '2041-04-01', cash, income, 20)
        self._entry(company, other, '2041-05-01', cash, income, 10, posted=False)
        options = self._options(date_from='2041-05-01', date_to='2041-05-31')
        report = engine.get_report('trial_balance', options)
        rows = {r.get('account_id'): r for r in report['lines']}
        self.assertEqual(float(rows[earnings.id]['amounts'][0]['value']), -100)
        self.assertEqual(float(rows[income.id]['amounts'][0]['value']), -20)
        self.assertTrue(report['has_draft_entries'])
        draft = engine.get_report('trial_balance', dict(options, posted_only=False))
        self.assertEqual(float(next(r for r in draft['lines'] if r.get('account_id') == cash.id)['amounts'][1]['value']), 10)
        filtered = engine.get_report('trial_balance', dict(options, journal_ids=[other.id], hide_zero=True))
        self.assertEqual(len(filtered['lines']), 1)
        self.assertEqual(engine.get_draft_entries_action('trial_balance', options)['res_model'], 'account.move')
        self.assertTrue(engine.export_pdf('trial_balance', options)['type'])

    def test_access_and_multicompany(self):
        from odoo import Command
        from odoo.exceptions import AccessError
        first = self._company('Grid company A')
        second = self._company('Grid company B')
        for company, jcode in [(first, 'TBA'), (second, 'TBB')]:
            journal = self._journal(company, jcode)
            cash = self._account(company, '1000', 'asset_cash')
            income = self._account(company, '4000', 'income')
            self._entry(company, journal, '2041-04-01', cash, income, 10)
        engine = self.env['baseer.report.engine'].with_company(first).with_context(allowed_company_ids=[first.id, second.id])
        payload = engine.get_report('trial_balance', self._options())
        cash_rows = [r for r in payload['lines'] if r.get('account_code') == '1000']
        self.assertEqual(len(cash_rows), 2)
        self.assertTrue(all(' — ' in row['name'] for row in cash_rows))
        user = self.env['res.users'].create({'name': 'Grid reader', 'login': 'grid_reader', 'company_id': first.id, 'company_ids': [Command.set(first.ids)], 'group_ids': [Command.set([self.env.ref('base.group_user').id, self.env.ref('account.group_account_readonly').id])]})
        self.assertTrue(self._engine(first).with_user(user).get_report('trial_balance', self._options())['lines'])
        user.group_ids = [Command.set([self.env.ref('base.group_user').id])]
        with self.assertRaises(AccessError):
            self._engine(first).with_user(user).get_report('trial_balance', self._options())

    def test_statement_reconciliation_and_query_bound(self):
        company = self._company('Grid reconciliation')
        engine = self._engine(company)
        journal = self._journal(company, 'TBR')
        cash = self._account(company, '1000', 'asset_cash')
        income = self._account(company, '4000', 'income')
        self._account(company, '3000', 'equity_unaffected')
        self._entry(company, journal, '2041-02-01', cash, income, 100)
        for index in range(20):
            account = self._account(company, str(5000 + index), 'expense')
            self._entry(company, journal, '2041-03-01', account, cash, 1)
        options = self._options(date_from='2041-01-01', date_to='2041-06-30')
        engine.get_report('trial_balance', options)
        start = self.cr.sql_log_count
        grid = engine.get_report('trial_balance', options)
        self.assertLess(self.cr.sql_log_count - start, 100)
        bs = engine.get_report('balance_sheet', self._options(as_of='2041-06-30'))
        pl = engine.get_report('profit_and_loss', options)
        by_id = {row.get('account_id'): row for row in grid['lines']}
        self.assertEqual(float(by_id[cash.id]['amounts'][-1]['value']), float(self._value(bs, 'CASH')))
        pl_accounts = self.env['account.account'].browse([key for key in by_id if key]).filtered(lambda a: a.account_type in ('income', 'income_other', 'expense', 'expense_other', 'expense_depreciation', 'expense_direct_cost'))
        self.assertEqual(-sum(float(by_id[a.id]['amounts'][-1]['value']) for a in pl_accounts), float(self._value(pl, 'NET')))

    def test_gap_synthetic_and_exhaustive_drill(self):
        company = self._company('No earnings account')
        engine = self._engine(company)
        journal = self._journal(company, 'TBS')
        cash = self._account(company, '1000', 'asset_cash')
        income = self._account(company, '4000', 'income')
        for day, amount, posted in [('2039-12-01', 100, True), ('2040-04-10', 20, True),
                                    ('2040-09-10', 30, True), ('2041-04-10', 40, True),
                                    ('2041-04-15', 5, False), ('2041-05-10', 60, True)]:
            self._entry(company, journal, day, cash, income, amount, posted=posted)
        base = self._options(date_from='2041-04-01', date_to='2041-04-30', posted_only=False)
        gap = engine.get_report('trial_balance', dict(base, comparison=1, comparison_mode='year'))
        cash_row = next(row for row in gap['lines'] if row.get('account_id') == cash.id)
        self.assertEqual(float(cash_row['amounts'][-1]['value']), 195)
        synthetic = next(row for row in gap['lines'] if row.get('account_id') == 0)
        self.assertEqual(synthetic['name'], 'Undistributed Profits/Losses')
        self.assertEqual(float(synthetic['amounts'][0]['value']), -100)
        self.assertEqual(float(gap['lines'][-1]['amounts'][-1]['value']), 0)
        for options in (dict(base, comparison=1), dict(base, comparison=1, comparison_mode='year')):
            report = engine.get_report('trial_balance', options)
            total = report['lines'][-1]['amounts']
            self.assertEqual(float(total[0]['value']), 0)
            self.assertEqual(float(total[-1]['value']), 0)
            for index in range(1, len(total) - 1, 2):
                self.assertEqual(float(total[index]['value']), float(total[index + 1]['value']))
            for row in report['lines'][:-1]:
                for column, amount in zip(report['columns'], row['amounts']):
                    if not float(amount['value']):
                        continue
                    action = engine.get_move_line_action('trial_balance', options, row['code'], column['key'], row['account_id'], company.id)
                    lines = self.env['account.move.line'].search(action['domain'])
                    self.assertAlmostEqual(sum(lines.mapped(column['figure'])), float(amount['value']))
        self.env['res.lang']._activate_lang('ar_001')
        self.env['ir.module.module']._load_module_terms(['baseer_report_engine'], ['ar_001'], overwrite=True)
        translated = engine.with_context(lang='ar_001').get_report('trial_balance', base)
        self.assertEqual(next(row for row in translated['lines'] if row.get('account_id') == 0)['name'], 'الأرباح/الخسائر غير الموزعة')

    def test_rpc_dispatch_and_company_drill(self):
        first = self._company('RPC company A')
        second = self._company('RPC company B')
        for company, code, amount in ((first, 'TRA', 11), (second, 'TRB', 22)):
            journal = self._journal(company, code)
            cash = self._account(company, '1000', 'asset_cash')
            income = self._account(company, '4000', 'income')
            self._entry(company, journal, '2041-04-01', cash, income, amount)
        engine = self.env['baseer.report.engine'].with_company(first).with_context(allowed_company_ids=[first.id, second.id])
        options = self._options()
        self.assertTrue(call_kw(engine, 'get_bootstrap', ['trial_balance'], {}))
        report = call_kw(engine, 'get_report', ['trial_balance', options], {})
        for row in (row for row in report['lines'] if row.get('account_code') == '1000'):
            self.assertIn(' — ', row['name'])
            action = call_kw(engine, 'get_move_line_action', ['trial_balance', options, row['code'], 'end', row['account_id'], row['company_id']], {})
            lines = self.env['account.move.line'].search(action['domain'])
            self.assertEqual(set(lines.company_id.ids), {row['company_id']})
            self.assertEqual(sum(lines.mapped('balance')), float(row['amounts'][-1]['value']))
        self.assertTrue(call_kw(engine, 'export_xlsx', ['trial_balance', options], {})['content'])
        self.assertTrue(call_kw(engine, 'export_pdf', ['trial_balance', options], {})['type'])

    def test_row_drill_covers_displayed_periods(self):
        company = self._company('Range drill')
        engine = self._engine(company)
        journal = self._journal(company, 'TRD')
        cash = self._account(company, '1000', 'asset_cash')
        income = self._account(company, '4000', 'income')
        self._entry(company, journal, '2041-02-01', cash, income, 5)
        self._entry(company, journal, '2041-03-01', cash, income, 7)
        self._entry(company, journal, '2041-04-01', cash, income, 11)
        options = self._options(date_from='2041-04-01', date_to='2041-04-30', comparison=1)
        report = engine.get_report('trial_balance', options)
        row = next(row for row in report['lines'] if row.get('account_id') == cash.id)
        action = engine.get_move_line_action('trial_balance', options, row['code'], 'range', cash.id, company.id)
        lines = self.env['account.move.line'].search(action['domain'])
        self.assertEqual(sum(lines.mapped('debit')), 18)

    def test_all_statement_leaves_and_query_bound(self):
        company = self._company('Reconcile all accounts')
        engine = self._engine(company)
        journal = self._journal(company, 'TRC')
        kinds = {'CASH': ('asset_cash', 1), 'REC': ('asset_receivable', 1),
                 'CUR': ('asset_current', 1), 'PRE': ('asset_prepayments', 1),
                 'FA': ('asset_fixed', 1), 'NCA': ('asset_non_current', 1),
                 'PAY': ('liability_payable', -1), 'OCL': ('liability_current', -1),
                 'NCL': ('liability_non_current', -1), 'RE': ('equity', -1)}
        accounts = {code: self._account(company, str(1000 + i), kind) for i, (code, (kind, sign)) in enumerate(kinds.items())}
        income = self._account(company, '4000', 'income')
        expense = self._account(company, '5000', 'expense')
        earnings = self._account(company, '3000', 'equity_unaffected')
        self._entry(company, journal, '2040-05-01', accounts['CASH'], income, 100)
        for i, account in enumerate(accounts.values()):
            self._entry(company, journal, '2041-02-01', account, income, i + 1)
        self._entry(company, journal, '2041-03-01', expense, accounts['CASH'], 17)
        options = self._options(date_from='2041-01-01', date_to='2041-06-30')
        for i in range(30):
            self._account(company, str(6000 + i), 'expense')
        engine.get_report('trial_balance', options)
        start = self.cr.sql_log_count
        grid = engine.get_report('trial_balance', options)
        self.assertLess(self.cr.sql_log_count - start, 100)
        by_id = {row.get('account_id'): row for row in grid['lines']}
        bs = engine.get_report('balance_sheet', self._options(as_of='2041-06-30'))
        for code, account in accounts.items():
            self.assertAlmostEqual(float(self._value(bs, code)), kinds[code][1] * float(by_id[account.id]['amounts'][-1]['value']))
        self.assertAlmostEqual(float(self._value(bs, 'PY_UNA')), -float(by_id[earnings.id]['amounts'][-1]['value']))
        pl_total = sum(float(by_id[a.id]['amounts'][-1]['value']) for a in (income, expense))
        self.assertAlmostEqual(float(self._value(bs, 'CY_EARN')), -pl_total)
        year_options = self._options(preset='this_year', anchor_date='2041-06-30')
        year_grid = engine.get_report('trial_balance', year_options)
        year_rows = {row.get('account_id'): row for row in year_grid['lines']}
        pl = engine.get_report('profit_and_loss', year_options)
        self.assertAlmostEqual(float(self._value(pl, 'NET')), -sum(float(year_rows[a.id]['amounts'][-1]['value']) for a in (income, expense)))

    def test_query_bound_five_and_forty_active_accounts(self):
        company = self._company('Query scaling')
        engine = self._engine(company)
        journal = self._journal(company, 'TQS')
        cash = self._account(company, '1000', 'asset_cash')
        options = self._options()
        for index in range(39):
            account = self._account(company, str(5000 + index), 'expense')
            self._entry(company, journal, '2041-03-01', account, cash, 1)
            if index in (3, 38):
                engine.get_report('trial_balance', options)
                start = self.cr.sql_log_count
                report = engine.get_report('trial_balance', options)
                self.assertEqual(len(report['lines']) - 1, index + 2)
                self.assertLess(self.cr.sql_log_count - start, 100)
