"""Posted balance sheet bridge, company isolation and source rights."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from lxml import html as lxml_html

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBalanceSheet(TransactionCase):
    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.company.write({'fiscalyear_last_day': 31, 'fiscalyear_last_month': '12'})
        self.report = self.env['baseer.balance.sheet.report']
        self.filters = {'company_id': self.company.id,
                        'date_from': '2041-10-01', 'date_to': '2041-10-31',
                        'journal_ids': []}
        self.cash = self._account(self.company, '956101', 'asset_cash')
        self.income = self._account(self.company, '956102', 'income')
        self.expense = self._account(self.company, '956103', 'expense')
        self.unaffected = self._account(self.company, '956104', 'equity_unaffected')
        self.equity = self._account(self.company, '956105', 'equity')
        self.payable = self._account(self.company, '956106', 'liability_payable')
        self.journal = self._journal(self.company)

    def _account(self, company, code, kind):
        return self.env['account.account'].with_company(company).create({
            'code': code, 'name': f'BS {kind} {code}',
            'account_type': kind, 'company_ids': [Command.set(company.ids)],
        })

    def _journal(self, company):
        journal = self.env['account.journal'].with_company(company).search([
            ('company_id', '=', company.id), ('type', '=', 'general'),
        ], limit=1)
        if not journal:
            journal = self.env['account.journal'].with_company(company).create({
                'name': 'Balance sheet synthetic journal', 'code': 'BSG',
                'type': 'general', 'company_id': company.id,
            })
        return journal

    def _entry(self, day, debit_account, credit_account, amount,
               company=None, journal=None, posted=True, currency=None):
        company = company or self.company
        journal = journal or self.journal
        debit = {'name': 'BS debit source', 'company_id': company.id,
                 'account_id': debit_account.id, 'debit': amount}
        credit = {'name': 'BS credit source', 'company_id': company.id,
                  'account_id': credit_account.id, 'credit': amount}
        if currency:
            debit.update({'currency_id': currency.id, 'amount_currency': amount})
            credit.update({'currency_id': currency.id, 'amount_currency': -amount})
        move = self.env['account.move'].with_company(company).create({
            'company_id': company.id, 'date': day, 'journal_id': journal.id,
            'move_type': 'entry', 'line_ids': [Command.create(debit), Command.create(credit)],
        })
        if posted:
            move._post(soft=False)
        return move

    @staticmethod
    def _section(result, key):
        return next(item for item in result['sections'] if item['key'] == key)

    def _accountant(self):
        return self.env['res.users'].create({
            'name': 'BS readonly accountant', 'login': 'bs_readonly_accountant',
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_readonly').id,
            ])],
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
        })

    def test_dynamic_prior_result_before_and_after_real_allocation(self):
        self._entry('2040-12-31', self.cash, self.income, 100)
        before = self.report.get_report(self.filters)
        self.assertEqual(self._section(before, 'assets')['amount'], '100.00')
        self.assertEqual(self._section(before, 'brought_forward')['amount'], '100.00')
        self.assertEqual(self._section(before, 'equity')['amount'], '0.00')
        self.assertEqual(before['equation']['assets'], before['equation']['liabilities_equity_results'])
        self._entry('2041-01-02', self.unaffected, self.equity, 100)
        after = self.report.get_report(self.filters)
        self.assertEqual(self._section(after, 'brought_forward')['amount'], '0.00')
        self.assertEqual(self._section(after, 'equity')['amount'], '100.00')
        self.assertEqual(after['equation']['assets'], after['equation']['liabilities_equity_results'])
        breakdown = self.report.get_section_accounts(self.filters, 'brought_forward')
        self.assertEqual(breakdown['account_count'], 2)
        self.assertEqual(sum((Decimal(row['amount'].replace(',', ''))
                              for row in breakdown['accounts']), Decimal('0')), Decimal('0'))
        self.assertFalse(self.env['account.move'].search([
            ('company_id', '=', self.company.id), ('date', '=', '2041-10-31'),
        ]))

    def test_current_result_excludes_unaffected_and_uses_company_currency(self):
        self._entry('2040-12-31', self.cash, self.income, 100)
        self._entry('2041-01-02', self.unaffected, self.equity, 100)
        foreign = self.env.ref('base.USD')
        self._entry('2041-10-01', self.cash, self.income, 40, currency=foreign)
        self._entry('2041-10-31', self.expense, self.cash, 10)
        self._entry('2041-10-12', self.cash, self.income, 999, posted=False)
        self.expense.active = False
        result = self.report.get_report(self.filters)
        self.assertEqual(self._section(result, 'assets')['amount'], '130.00')
        self.assertEqual(self._section(result, 'current_result')['amount'], '30.00')
        self.assertEqual(self._section(result, 'equity')['amount'], '100.00')
        self.assertEqual(result['equation']['assets'], result['equation']['liabilities_equity_results'])
        rows = self.report.get_section_accounts(self.filters, 'current_result')['accounts']
        self.assertEqual({row['id'] for row in rows}, {self.income.id, self.expense.id})
        self.assertEqual({row['id']: row['amount'] for row in rows}[self.expense.id], '-10.00')
        ordinary = self.report.get_section_accounts(self.filters, 'assets')['accounts']
        self.assertEqual(ordinary[0]['amount'], '130.00')
        action = self.report.get_account_action(self.filters, self.cash.id, 'assets')
        self.assertIn(('date', '<=', '2041-10-31'), action['domain'])
        self.assertNotIn(('date', '>=', '2041-01-01'), action['domain'])
        result_action = self.report.get_account_action(self.filters, self.income.id, 'current_result')
        self.assertIn(('date', '>=', '2041-01-01'), result_action['domain'])
        with self.assertRaises(AccessError):
            self.report.get_account_action(self.filters, self.cash.id, 'liabilities')

    def test_liability_sign_and_selected_journal_scope(self):
        self._entry('2041-10-10', self.cash, self.payable, 80)
        result = self.report.get_report({**self.filters, 'journal_ids': [self.journal.id]})
        self.assertTrue(result['is_partial_journals'])
        self.assertEqual(self._section(result, 'assets')['amount'], '80.00')
        self.assertEqual(self._section(result, 'liabilities')['amount'], '80.00')
        self.assertEqual(self.report.get_section_accounts(
            {**self.filters, 'journal_ids': [self.journal.id]}, 'liabilities',
        )['accounts'][0]['amount'], '80.00')

    def test_march_fiscal_cutoff_and_other_company_isolation(self):
        other = self.env['res.company'].create({
            'name': 'BS March company', 'fiscalyear_last_day': 31,
            'fiscalyear_last_month': '3',
        })
        cash = self._account(other, '956101', 'asset_cash')
        income = self._account(other, '956102', 'income')
        journal = self._journal(other)
        self._entry('2041-03-31', cash, income, 40, other, journal)
        self._entry('2041-04-01', cash, income, 50, other, journal)
        self._entry('2041-10-31', cash, income, 60, other, journal)
        report = self.report.with_company(other).with_context(allowed_company_ids=[other.id])
        result = report.get_report({**self.filters, 'company_id': other.id})
        self.assertEqual(result['period']['fiscal_start'], '2041-04-01')
        self.assertEqual(self._section(result, 'assets')['amount'], '150.00')
        self.assertEqual(self._section(result, 'brought_forward')['amount'], '40.00')
        self.assertEqual(self._section(result, 'current_result')['amount'], '110.00')
        with self.assertRaises(AccessError):
            self.report.with_context(allowed_company_ids=[self.company.id, other.id]).get_report(
                {**self.filters, 'company_id': other.id},
            )
        with self.assertRaises(ValidationError):
            report.get_report({**self.filters, 'company_id': other.id,
                               'date_from': '2041-03-31', 'date_to': '2041-04-01'})

    def test_off_balance_is_excluded_and_hidden_source_fails_closed(self):
        first = self._account(self.company, '956107', 'off_balance')
        second = self._account(self.company, '956108', 'off_balance')
        move = self._entry('2041-10-12', first, second, 17)
        result = self.report.get_report(self.filters)
        self.assertEqual(self._section(result, 'assets')['amount'], '0.00')
        self.assertEqual(result['equation']['assets'], '0.00')
        accountant = self._accountant()
        rule = self.env['ir.rule'].create({
            'name': 'BS hide off-balance source',
            'model_id': self.env['ir.model']._get('account.move.line').id,
            'domain_force': f"[('id', '!=', {move.line_ids[0].id})]",
        })
        try:
            with self.assertRaises(AccessError):
                self.report.with_user(accountant).with_context(
                    allowed_company_ids=self.company.ids,
                ).get_report(self.filters)
        finally:
            rule.unlink()

    def test_acl_related_rules_and_pdf_fail_closed(self):
        move = self._entry('2041-10-03', self.cash, self.payable, 20)
        accountant = self._accountant()
        internal = self.env['res.users'].create({
            'name': 'BS internal', 'login': 'bs_internal',
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
        })
        with self.assertRaises(AccessError):
            self.report.with_user(internal).get_report(self.filters)
        for model, record in (
            ('account.move.line', move.line_ids[0]),
            ('account.move', move),
            ('account.account', self.cash),
            ('account.journal', self.journal),
        ):
            with self.subTest(model=model):
                rule = self.env['ir.rule'].create({
                    'name': f'BS hide {model}',
                    'model_id': self.env['ir.model']._get(model).id,
                    'domain_force': f"[('id', '!=', {record.id})]",
                })
                secured = self.report.with_user(accountant).with_context(
                    allowed_company_ids=self.company.ids,
                )
                try:
                    with self.assertRaises(AccessError):
                        secured.get_report(self.filters)
                    with self.assertRaises(AccessError):
                        secured.get_section_accounts(self.filters, 'assets')
                    with self.assertRaises(AccessError):
                        secured.get_account_action(self.filters, self.cash.id, 'assets')
                    with self.assertRaises(AccessError):
                        self.env['report.baseer_balance_sheet_report.balance_sheet_pdf'].with_user(
                            accountant,
                        ).with_context(allowed_company_ids=self.company.ids)._get_report_values(
                            [], {'filters': self.filters},
                        )
                finally:
                    rule.unlink()

    def test_pdf_101_accounts_and_real_qweb_footer_structure(self):
        accounts = {index: SimpleNamespace(
            id=index, code=f'{index:06}', name=f'Account {index}',
            account_type='asset_cash', include_initial_balance=True,
        ) for index in range(1, 102)}
        snapshot = (self.company, date(2041, 10, 1), date(2041, 10, 31),
                    date(2041, 1, 1), [], {}, {}, {}, accounts)
        model_class = type(self.report)
        with patch.object(model_class, '_snapshot', return_value=snapshot), \
                patch.object(model_class, '_assert_complete_source'):
            summary = self.report.get_report(self.filters)
            page1 = self.report.get_section_accounts(self.filters, 'assets')
            page2 = self.report.get_section_accounts(self.filters, 'assets', 2)
            full = self.report._build_pdf_report(self.filters)
            html, _ = self.env['ir.actions.report']._render_qweb_html(
                'baseer_balance_sheet_report.balance_sheet_pdf', docids=[],
                data={'filters': self.filters},
            )
        self.assertEqual(summary['sections'][0]['account_count'], 101)
        self.assertEqual((len(page1['accounts']), len(page2['accounts'])), (100, 1))
        self.assertEqual(len(full['section_accounts']['assets']), 101)
        self.assertIn(b'Account 101', html)
        rows = lxml_html.fromstring(html).xpath(
            "//div[contains(@class, 'bbs-pdf')]//table/tbody/tr",
        )
        self.assertEqual(len(rows), 108)  # 5 section headings + 101 accounts + 2 totals.
        bodies, _ids, _header, footer, _paperformat = self.env['ir.actions.report']._prepare_html(
            html, report_model='baseer.balance.sheet.report',
        )
        self.assertEqual(len(bodies), 1)
        self.assertIn('class="page"', footer)
        self.assertIn('class="topage"', footer)
        self.assertEqual(self.env.ref(
            'baseer_balance_sheet_report.action_balance_sheet_pdf',
        ).paperformat_id.orientation, 'Portrait')
        with self.assertRaises(AccessError):
            self.env['report.baseer_balance_sheet_report.balance_sheet_pdf']._get_report_values(
                [], {'filters': {**self.filters, 'company_id': -1}},
            )
        self.assertEqual(self.report.action_print(self.filters)['data'], {'filters': self.filters})
        for index in range(102, 5002):
            accounts[index] = SimpleNamespace(
                id=index, code=f'{index:06}', name=f'Account {index}',
                account_type='asset_cash', include_initial_balance=True,
            )
        with patch.object(model_class, '_snapshot', return_value=snapshot), \
                patch.object(model_class, '_assert_complete_source'):
            with self.assertRaises(ValidationError):
                self.report._build_pdf_report(self.filters)
