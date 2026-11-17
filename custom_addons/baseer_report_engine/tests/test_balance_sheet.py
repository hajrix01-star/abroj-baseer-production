"""Balance sheet structure, signs, fiscal year, menu and exports."""

import base64
import io
import logging
import zipfile

from odoo.exceptions import ValidationError
from odoo.tests.common import tagged

from odoo.addons.baseer_report_engine.tests.common import EngineCase

_logger = logging.getLogger(__name__)


@tagged('post_install', '-at_install')
class TestBalanceSheet(EngineCase):
    def _books(self):
        company = self._company('Engine balance sheet')
        engine = self._engine(company)
        journal = self._journal(company, 'BRB')
        kinds = {
            'cash': ('981001', 'asset_cash'),
            'receivable': ('981002', 'asset_receivable'),
            'current': ('981003', 'asset_current'),
            'prepayment': ('981004', 'asset_prepayments'),
            'fixed': ('981005', 'asset_fixed'),
            'noncurrent_asset': ('981006', 'asset_non_current'),
            'payable': ('981007', 'liability_payable'),
            'current_liability': ('981008', 'liability_current'),
            'card': ('981009', 'liability_credit_card'),
            'noncurrent_liability': ('981010', 'liability_non_current'),
            'equity': ('981011', 'equity'),
            'unaffected': ('981012', 'equity_unaffected'),
            'income': ('981013', 'income'),
            'expense': ('981014', 'expense'),
            'off_a': ('981015', 'off_balance'),
            'off_b': ('981016', 'off_balance'),
        }
        accounts = {
            key: self._account(company, code, kind) for key, (code, kind) in kinds.items()
        }

        def entry(day, debit, credit, amount, posted=True):
            self._entry(
                company, journal, day, accounts[debit], accounts[credit], amount, posted=posted,
            )

        entry('2040-06-01', 'cash', 'income', 100)
        entry('2040-12-31', 'unaffected', 'equity', 40)
        entry('2041-03-01', 'cash', 'income', 25)
        entry('2041-03-15', 'expense', 'cash', 10)
        entry('2041-04-01', 'unaffected', 'equity', 5)
        entry('2041-05-01', 'cash', 'payable', 30)
        entry('2041-05-02', 'receivable', 'income', 12)
        entry('2041-05-03', 'fixed', 'cash', 70)
        entry('2041-05-04', 'prepayment', 'cash', 8)
        entry('2041-05-05', 'current', 'cash', 9)
        entry('2041-05-06', 'noncurrent_asset', 'cash', 15)
        entry('2041-05-07', 'cash', 'current_liability', 20)
        entry('2041-05-08', 'cash', 'noncurrent_liability', 11)
        entry('2041-05-09', 'cash', 'card', 6)
        entry('2041-05-10', 'cash', 'income', 999, posted=False)
        entry('2041-05-11', 'off_a', 'off_b', 17)
        return engine, accounts

    def test_statement_balances_and_signs(self):
        engine, accounts = self._books()
        payload = engine.get_report('balance_sheet', self._options())
        _logger.info('Balance sheet as of %s', payload['options']['as_of'])
        for line in payload['lines']:
            _logger.info(
                '%s%s %s',
                '  ' * line['level'],
                line['code'],
                line['amounts'][0]['value'],
            )
        expected = {
            'CASH': '80.00', 'REC': '12.00', 'CUR': '9.00', 'PRE': '8.00',
            'CA': '109.00', 'FA': '70.00', 'NCA': '15.00', 'ASSETS': '194.00',
            'OCL': '26.00', 'PAY': '30.00', 'CL': '56.00', 'NCL': '11.00', 'LIAB': '67.00',
            'CY_EARN': '27.00', 'CY_ALLOC': '-5.00', 'CY_UNA': '22.00',
            'PY_UNA': '60.00', 'UNA': '82.00', 'RE': '45.00', 'EQUITY': '127.00',
            'LE': '194.00',
        }
        for code, amount in expected.items():
            self.assertEqual(self._value(payload, code), amount, code)
        self.assertEqual(self._value(payload, 'ASSETS'), self._value(payload, 'LE'))
        alloc = next(line for line in payload['lines'] if line['code'] == 'CY_ALLOC')
        cell = next(amount for amount in alloc['amounts'] if amount['key'] == 'c0')
        self.assertTrue(cell['negative'])
        self.assertTrue(cell['display'].startswith('-'))
        unfolded = engine.get_line_accounts('balance_sheet', self._options(), 'CASH')
        self.assertEqual(unfolded['accounts'][0]['id'], accounts['cash'].id)
        self.assertEqual(unfolded['accounts'][0]['amounts'][0]['value'], '80.00')
        cash_action = engine.get_move_line_action(
            'balance_sheet', self._options(), 'CASH', 'c0', accounts['cash'].id,
        )
        self.assertEqual(cash_action['res_model'], 'account.move.line')
        self.assertIn(('account_id', '=', accounts['cash'].id), cash_action['domain'])
        self.assertIn(('date', '<=', '2041-06-30'), cash_action['domain'])
        self.assertIn(('parent_state', 'in', ['posted']), cash_action['domain'])
        self.assertFalse(any(
            isinstance(term, tuple) and term[0] == 'date' and term[1] == '>='
            for term in cash_action['domain']
        ))
        current = engine.get_move_line_action('balance_sheet', self._options(), 'CY_EARN', 'c0')
        self.assertIn(('date', '>=', '2041-01-01'), current['domain'])
        self.assertIn(('date', '<=', '2041-06-30'), current['domain'])
        previous = engine.get_move_line_action('balance_sheet', self._options(), 'PY_UNA', 'c0')
        self.assertIn(('date', '<', '2041-01-01'), previous['domain'])
        compared = engine.get_report('balance_sheet', self._options(comparison=1))
        self.assertEqual(len(compared['columns']), 4)
        with self.assertRaises(ValidationError):
            engine.get_move_line_action(
                'balance_sheet', self._options(comparison=1), 'ASSETS', 'variation',
            )

    def test_march_fiscal_year_splits_earnings(self):
        company = self._company('Engine march books', month='3')
        engine = self._engine(company)
        journal = self._journal(company, 'BRM')
        cash = self._account(company, '981001', 'asset_cash')
        income = self._account(company, '981013', 'income')
        self._entry(company, journal, '2041-03-31', cash, income, 40)
        self._entry(company, journal, '2041-04-01', cash, income, 50)
        closing = engine.get_report('balance_sheet', self._options(as_of='2041-03-31'))
        self.assertEqual(closing['columns'][0]['fiscal_start'], '2040-04-01')
        self.assertEqual(self._value(closing, 'ASSETS'), '40.00')
        self.assertEqual(self._value(closing, 'CY_EARN'), '40.00')
        self.assertEqual(self._value(closing, 'PY_UNA'), '0.00')
        opened = engine.get_report('balance_sheet', self._options(as_of='2041-04-01'))
        self.assertEqual(opened['columns'][0]['fiscal_start'], '2041-04-01')
        self.assertEqual(self._value(opened, 'ASSETS'), '90.00')
        self.assertEqual(self._value(opened, 'CY_EARN'), '50.00')
        self.assertEqual(self._value(opened, 'PY_UNA'), '40.00')
        self.assertEqual(self._value(opened, 'ASSETS'), self._value(opened, 'LE'))

    def test_comparison_matches_single_dates_and_query_count(self):
        first = self._company('Comparison first', month='3')
        second = self._company('Comparison second')
        euro = self.env.ref('base.EUR')
        euro.active = True
        second.currency_id = euro
        self.env['res.currency.rate'].create([
            {'currency_id': euro.id, 'company_id': second.id, 'name': '2040-01-01', 'rate': 2},
            {'currency_id': euro.id, 'company_id': second.id, 'name': '2041-01-01', 'rate': 3},
        ])
        plan = self.env['account.analytic.plan'].create({'name': 'Comparison plan'})
        analytic = self.env['account.analytic.account'].create({
            'name': 'Comparison analytic', 'plan_id': plan.id, 'company_id': first.id,
        })
        for company in (first, second):
            journal = self._journal(company, 'CMP')
            cash = self._account(company, '1010', 'asset_cash')
            income = self._account(company, '4010', 'income')
            for day, amount in [('2040-03-31', 10), ('2040-12-30', 20),
                                ('2041-03-30', 30), ('2041-04-30', 40), ('2041-06-30', 50)]:
                self._entry(company, journal, day, cash, income, amount, analytic={str(analytic.id): 50})
        engine = self.env['baseer.report.engine'].with_company(first).with_context(
            allowed_company_ids=[first.id, second.id],
        )
        for filters in ({}, {'analytic_account_ids': [analytic.id]}):
            options = self._options(comparison=12, **filters)
            compared = engine.get_report('balance_sheet', options, with_accounts=True)
            for column in compared['columns'][:13]:
                single = engine.get_report('balance_sheet', self._options(as_of=column['date_to'], **filters), with_accounts=True)
                for line in compared['lines']:
                    self.assertEqual(self._value(compared, line['code'], column['key']),
                                     self._value(single, line['code']), (filters, line['code'], column['key']))
                    single_line = next(item for item in single['lines'] if item['code'] == line['code'])
                    for row in line['accounts']:
                        other = next((item for item in single_line['accounts'] if (item['id'], item['company_id']) == (row['id'], row['company_id'])), None)
                        actual = next(amount['value'] for amount in row['amounts'] if amount['key'] == column['key'])
                        self.assertEqual(actual, other['amounts'][0]['value'] if other else '0.00')

        # Warm metadata and currency caches before comparing report query counts.
        engine.get_report('balance_sheet', self._options())
        start = self.env.cr.sql_log_count
        engine.get_report('balance_sheet', self._options())
        single_queries = self.env.cr.sql_log_count - start
        start = self.env.cr.sql_log_count
        engine.get_report('balance_sheet', self._options(comparison=12))
        compared_queries = self.env.cr.sql_log_count - start
        self.assertLessEqual(compared_queries, single_queries + 3)

    def test_every_profit_and_loss_type_rolls_into_current_earnings(self):
        company = self._company('Engine earnings types')
        engine = self._engine(company)
        journal = self._journal(company, 'BRT')
        cash = self._account(company, '981001', 'asset_cash')
        for index, kind in enumerate(('income', 'income_other'), start=1):
            account = self._account(company, f'98110{index}', kind)
            self._entry(company, journal, '2041-02-01', cash, account, 10)
        for index, kind in enumerate(
            ('expense', 'expense_other', 'expense_depreciation', 'expense_direct_cost'), start=1,
        ):
            account = self._account(company, f'98120{index}', kind)
            self._entry(company, journal, '2041-02-02', account, cash, 3)
        payload = engine.get_report('balance_sheet', self._options())
        self.assertEqual(self._value(payload, 'CY_EARN'), '8.00')
        self.assertEqual(self._value(payload, 'ASSETS'), '8.00')
        self.assertEqual(self._value(payload, 'LE'), '8.00')

    def test_menu_translations_and_exports(self):
        menu = self.env.ref('baseer_report_engine.menu_new_version')
        child = self.env.ref('baseer_report_engine.menu_balance_sheet')
        action = self.env.ref('baseer_report_engine.action_balance_sheet')
        self.assertEqual(menu.parent_id, self.env.ref('account.menu_finance_entries'))
        self.assertEqual(menu.sequence, 100)
        self.assertEqual(menu.name, 'New Version')
        self.assertEqual(child.parent_id, menu)
        self.assertEqual(child.name, 'Balance Sheet (New)')
        self.assertEqual(action.tag, 'baseer_report_engine')
        self.assertIn('balance_sheet', action.context)
        self.assertIn(self.env.ref('account.group_account_readonly'), menu.group_ids)
        self.assertEqual(self.env.ref('baseer_report_engine.line_bs_assets').name, 'Assets')
        self.env['res.lang']._activate_lang('ar_001')
        self.env['ir.module.module']._load_module_terms(
            ['baseer_report_engine'], ['ar_001'], overwrite=True,
        )
        self.assertEqual(menu.with_context(lang='ar_001').name, 'النسخة الجديدة')
        self.assertEqual(child.with_context(lang='ar_001').name, 'الميزانية العمومية (جديد)')
        self.assertEqual(
            self.env.ref('baseer_report_engine.line_bs_assets').with_context(lang='ar_001').name,
            'الأصول',
        )
        self.assertEqual(
            self.env.ref('baseer_report_engine.line_bs_le').with_context(lang='ar_001').name,
            'الخصوم وحقوق الملكية',
        )
        self.assertEqual(
            self.env.ref('baseer_report_engine.line_bs_cash').with_context(lang='ar_001').name,
            'البنك والنقد',
        )
        self.assertEqual(
            self.env.ref('baseer_report_engine.report_balance_sheet').with_context(lang='ar_001').name,
            'الميزانية العمومية',
        )
        engine, _accounts = self._books()
        company = engine.env.company
        options = self._options()
        exported = engine.export_xlsx('balance_sheet', options)
        workbook = base64.b64decode(exported['content'])
        self.assertTrue(workbook.startswith(b'PK'))
        self.assertEqual(exported['filename'], 'balance-sheet.xlsx')
        with zipfile.ZipFile(io.BytesIO(workbook)) as book:
            sheet = book.read('xl/worksheets/sheet1.xml')
        self.assertIn(b'194', sheet)
        report_ids = self.env.ref('baseer_report_engine.report_balance_sheet').ids
        arabic_report = self.env['ir.actions.report'].with_company(company).with_context(
            lang='ar_001', allowed_company_ids=[company.id],
        )
        html, output = arabic_report._render_qweb_html(
            'baseer_report_engine.report_pdf', docids=report_ids,
            data={'report_code': 'balance_sheet', 'options': options},
        )
        self.assertEqual(output, 'html')
        self.assertIn('الأصول'.encode(), html)
        self.assertIn(b'194.00', html)
        self.assertIn(b'class="page"', html)
        english, _output = self.env['ir.actions.report'].with_company(company).with_context(
            allowed_company_ids=[company.id], lang='en_US',
        )._render_qweb_html(
            'baseer_report_engine.report_pdf', docids=report_ids,
            data={'report_code': 'balance_sheet', 'options': options},
        )
        self.assertIn(b'Balance Sheet', english)
        self.assertIn(b'Bank and Cash', english)
        self.assertIn(b'194.00', english)

    def test_all_drillable_amounts_and_account_details(self):
        engine, accounts = self._books()
        company = engine.env.company
        journal = self.env['account.journal'].search([('company_id', '=', company.id), ('code', '=', 'BRB')], limit=1)
        for code in ('balance_sheet', 'profit_and_loss'):
            for posted in (True, False):
                options = self._options(posted_only=posted, journal_ids=[journal.id], comparison=1)
                payload = engine.get_report(code, options, with_accounts=True)
                definition = engine._definition(code)
                details = [line for line in payload['lines'] if line['has_accounts']]
                batched = engine.get_lines_accounts(code, options, [line['code'] for line in details])
                for line, batch in zip(details, batched):
                    self.assertEqual(line['accounts'], batch['accounts'])
                    self.assertEqual(batch, engine.get_line_accounts(code, options, line['code']))
                    for amount in line['amounts']:
                        if amount['key'].startswith('c'):
                            self.assertAlmostEqual(sum(float(next(a['value'] for a in row['amounts'] if a['key'] == amount['key'])) for row in batch['accounts']), float(amount['value']), places=2)
                for line in payload['lines']:
                    source = definition.line_ids.filtered(lambda record: record.code == (line.get('source_code') or line['code']))
                    expressions = engine._drill_expressions(source)
                    for amount in line['amounts']:
                        if amount['key'].startswith('c'):
                            self.assertEqual(amount['drill'], bool(expressions), line['code'])
                        if not amount['drill']:
                            continue
                        sign = float(expressions[0].sign)
                        action = engine.get_move_line_action(code, options, source.code, amount['key'])
                        moves = engine.env['account.move.line'].search(action['domain'])
                        self.assertAlmostEqual(sum(moves.mapped('balance')) * sign, float(amount['value']), places=2, msg=line['code'])
                        if float(amount['value']):
                            self.assertTrue(moves)
                    for account in line['accounts']:
                        for amount in account['amounts']:
                            if amount['drill']:
                                action = engine.get_move_line_action(code, options, source.code, amount['key'], account['id'], account['company_id'])
                                moves = engine.env['account.move.line'].search(action['domain'])
                                self.assertAlmostEqual(sum(moves.mapped('balance')) * float(expressions[0].sign), float(amount['value']), places=2)
                                if float(amount['value']):
                                    self.assertTrue(moves)

    def test_shared_account_company_details(self):
        first = self._company('Shared first')
        second = self._company('Shared second')
        cash = self._account(first, '1010', 'asset_current')
        cash.with_context(defer_account_code_checks=True).write({'company_ids': [(4, second.id)]})
        cash.with_company(second).code = '2020'
        for company, amount in ((first, 10), (second, 20)):
            journal = self._journal(company, 'SHR')
            income = self._account(company, '4010', 'income')
            self._entry(company, journal, '2041-04-15', cash, income, amount)
        engine = self.env['baseer.report.engine'].with_company(first).with_context(allowed_company_ids=[first.id, second.id])
        rows = engine.get_line_accounts('balance_sheet', self._options(), 'CUR')['accounts']
        self.assertEqual({(r['code'], r['company_id'], r['amounts'][0]['value']) for r in rows}, {('1010', first.id, '10.00'), ('2020', second.id, '20.00')})
        for row in rows:
            action = engine.get_move_line_action('balance_sheet', self._options(), 'CUR', 'c0', cash.id, row['company_id'])
            self.assertEqual(set(engine.env['account.move.line'].search(action['domain']).mapped('company_id').ids), {row['company_id']})
        cash.with_company(second).code = '1010'
        rows = engine.get_line_accounts('balance_sheet', self._options(), 'CUR')['accounts']
        self.assertEqual({r['name'] for r in rows}, {cash.name + ' — Shared first', cash.name + ' — Shared second'})
