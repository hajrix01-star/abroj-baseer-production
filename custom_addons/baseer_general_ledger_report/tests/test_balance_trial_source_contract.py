"""Characterize Odoo 19 sources for the proposed balance sheet/trial balance.

This is G2 evidence, not a report calculator.  In particular, a report must
not create a profit-appropriation entry or infer prior-year earnings from the
current residual of an income account.
"""

from datetime import date
from decimal import Decimal

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBalanceTrialNativeSourceContract(TransactionCase):

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.company.write({'fiscalyear_last_day': 31, 'fiscalyear_last_month': '12'})
        self.cash = self._account(self.company, '957101', 'asset_cash')
        self.income = self._account(self.company, '957102', 'income')
        self.expense = self._account(self.company, '957103', 'expense')
        self.unaffected = self._account(self.company, '957104', 'equity_unaffected')
        self.equity = self._account(self.company, '957105', 'equity')
        self.journal = self._journal(self.company)

    def _account(self, company, code, kind):
        return self.env['account.account'].with_company(company).create({
            'code': code,
            'name': f'Balance/trial source {kind} {code}',
            'account_type': kind,
            'company_ids': [Command.set(company.ids)],
        })

    def _journal(self, company):
        journal = self.env['account.journal'].with_company(company).search([
            ('company_id', '=', company.id), ('type', '=', 'general'),
        ], limit=1)
        if not journal:
            journal = self.env['account.journal'].with_company(company).create({
                'name': 'Balance/trial synthetic journal',
                'code': 'BTG',
                'type': 'general',
                'company_id': company.id,
            })
        return journal

    def _entry(self, company, journal, day, debit_account, credit_account,
               amount, posted=True):
        move = self.env['account.move'].with_company(company).create({
            'date': day,
            'journal_id': journal.id,
            'move_type': 'entry',
            'line_ids': [
                Command.create({'name': 'Balance/trial debit source',
                                'account_id': debit_account.id, 'debit': amount}),
                Command.create({'name': 'Balance/trial credit source',
                                'account_id': credit_account.id, 'credit': amount}),
            ],
        })
        if posted:
            move._post(soft=False)
        return move

    def _amounts(self, company, account, before=None, from_day=None, through=None):
        """Return native posted debit, credit, balance, with no report formula."""
        domain = [
            ('company_id', '=', company.id),
            ('account_id', '=', account.id),
            ('move_id.state', '=', 'posted'),
        ]
        if before:
            domain.append(('date', '<', before))
        if from_day:
            domain.append(('date', '>=', from_day))
        if through:
            domain.append(('date', '<=', through))
        lines = self.env['account.move.line'].with_context(active_test=False).search(domain)
        debit = sum((Decimal(str(line.debit)) for line in lines), Decimal('0'))
        credit = sum((Decimal(str(line.credit)) for line in lines), Decimal('0'))
        balance = sum((Decimal(str(line.balance)) for line in lines), Decimal('0'))
        self.assertEqual(balance, debit - credit)
        return debit, credit, balance

    def test_october_opening_of_income_and_expense_is_fiscal_ytd(self):
        self._entry(self.company, self.journal, '2041-01-10',
                    self.cash, self.income, 100)
        self._entry(self.company, self.journal, '2041-09-30',
                    self.expense, self.cash, 20)
        self._entry(self.company, self.journal, '2041-10-01',
                    self.cash, self.income, 30)
        self._entry(self.company, self.journal, '2041-10-31',
                    self.expense, self.cash, 10)
        self._entry(self.company, self.journal, '2041-10-15',
                    self.cash, self.income, 999, posted=False)
        fiscal = self.company.compute_fiscalyear_dates(date(2041, 10, 1))
        self.assertEqual(fiscal['date_from'], date(2041, 1, 1))
        self.assertFalse(self.income.include_initial_balance)
        self.assertFalse(self.expense.include_initial_balance)
        self.assertFalse(self.unaffected.include_initial_balance)
        self.assertTrue(self.cash.include_initial_balance)
        self.assertTrue(self.equity.include_initial_balance)

        self.assertEqual(self._amounts(
            self.company, self.income, from_day=fiscal['date_from'],
            before='2041-10-01',
        ), (Decimal('0'), Decimal('100'), Decimal('-100')))
        self.assertEqual(self._amounts(
            self.company, self.expense, from_day=fiscal['date_from'],
            before='2041-10-01',
        ), (Decimal('20'), Decimal('0'), Decimal('20')))
        self.assertEqual(self._amounts(
            self.company, self.income, from_day='2041-10-01',
            through='2041-10-31',
        ), (Decimal('0'), Decimal('30'), Decimal('-30')))
        self.assertEqual(self._amounts(
            self.company, self.expense, from_day='2041-10-01',
            through='2041-10-31',
        ), (Decimal('10'), Decimal('0'), Decimal('10')))

        # An account with historical posted activity must remain visible even
        # if it is archived after posting.
        self.expense.active = False
        self.assertEqual(self._amounts(
            self.company, self.expense, from_day='2041-10-01',
            through='2041-10-31',
        )[2], Decimal('10'))

    def test_prior_year_result_is_offset_by_real_current_year_appropriation(self):
        self._entry(self.company, self.journal, '2040-12-31',
                    self.cash, self.income, 100)
        fiscal_start = self.company.compute_fiscalyear_dates(
            date(2041, 1, 1),
        )['date_from']
        self.assertEqual(fiscal_start, date(2041, 1, 1))
        old_income = self._amounts(
            self.company, self.income, before=fiscal_start,
        )[2]
        self.assertEqual(old_income, Decimal('-100'))
        self.assertEqual(self._amounts(
            self.company, self.unaffected, from_day=fiscal_start,
            through=fiscal_start,
        )[2], Decimal('0'))

        # Odoo's year-end appropriation is a real, posted manual journal entry.
        # It must not be fabricated by the future report.  Until it exists,
        # prior-year result remains a dynamic brought-forward presentation.
        count_before = self.env['account.move'].search_count([
            ('company_id', '=', self.company.id), ('date', '=', '2041-01-02'),
        ])
        appropriation = self._entry(
            self.company, self.journal, '2041-01-02',
            self.unaffected, self.equity, 100,
        )
        self.assertEqual(self.env['account.move'].search_count([
            ('company_id', '=', self.company.id), ('date', '=', '2041-01-02'),
        ]), count_before + 1)
        self.assertEqual(appropriation.state, 'posted')
        self.assertEqual(self._amounts(
            self.company, self.unaffected, from_day=fiscal_start,
            through='2041-01-02',
        )[2], Decimal('100'))
        self.assertEqual(self._amounts(
            self.company, self.equity, from_day=fiscal_start,
            through='2041-01-02',
        )[2], Decimal('-100'))
        # The source bridge is old non-initial income (-100) plus the current
        # year's actual unaffected-equity debit (+100): zero, not -100 or +100.
        self.assertEqual(old_income + self._amounts(
            self.company, self.unaffected, from_day=fiscal_start,
            through='2041-01-02',
        )[2], Decimal('0'))
        self.assertEqual(self._amounts(
            self.company, self.cash, through='2041-01-02',
        )[2], Decimal('100'))

    def test_two_fiscal_year_ends_have_distinct_october_opening(self):
        march_company = self.env['res.company'].create({
            'name': 'Balance/trial March fiscal company',
            'fiscalyear_last_day': 31,
            'fiscalyear_last_month': '3',
        })
        march_cash = self._account(march_company, '957101', 'asset_cash')
        march_income = self._account(march_company, '957102', 'income')
        march_journal = self._journal(march_company)
        self._entry(march_company, march_journal, '2041-03-31',
                    march_cash, march_income, 40)
        self._entry(march_company, march_journal, '2041-04-01',
                    march_cash, march_income, 50)
        self._entry(march_company, march_journal, '2041-10-01',
                    march_cash, march_income, 60)
        self.assertEqual(self.company.compute_fiscalyear_dates(
            date(2041, 10, 1),
        )['date_from'], date(2041, 1, 1))
        self.assertEqual(march_company.compute_fiscalyear_dates(
            date(2041, 10, 1),
        )['date_from'], date(2041, 4, 1))
        self.assertEqual(march_company.compute_fiscalyear_dates(
            date(2042, 3, 31),
        )['date_from'], date(2041, 4, 1))
        self.assertEqual(march_company.compute_fiscalyear_dates(
            date(2042, 4, 1),
        )['date_from'], date(2042, 4, 1))
        self.assertEqual(self._amounts(
            march_company, march_income, from_day='2041-04-01',
            before='2041-10-01',
        )[2], Decimal('-50'))
        self.assertEqual(self._amounts(
            march_company, march_income, from_day='2041-10-01',
            through='2041-10-31',
        )[2], Decimal('-60'))
        self.assertEqual(self._amounts(
            march_company, march_income, before='2041-04-01',
        )[2], Decimal('-40'))
        self.assertEqual(self._amounts(
            self.company, self.income, through='2041-10-31',
        )[2], Decimal('0'))

    def test_native_rules_can_hide_each_ledger_source_relation(self):
        move = self._entry(self.company, self.journal, '2041-10-01',
                           self.cash, self.income, 25)
        source = move.line_ids.filtered(lambda line: line.account_id == self.cash)
        readonly = self.env['res.users'].create({
            'name': 'Balance/trial readonly source',
            'login': 'balance_trial_source_readonly',
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_readonly').id,
            ])],
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
        })
        for model_name, record in (
            ('account.move.line', source),
            ('account.move', move),
            ('account.account', self.cash),
            ('account.journal', self.journal),
        ):
            with self.subTest(model=model_name):
                record.with_user(readonly).check_access('read')
                rule = self.env['ir.rule'].create({
                    'name': f'Balance/trial source hide {model_name}',
                    'model_id': self.env['ir.model']._get(model_name).id,
                    'domain_force': f"[('id', '!=', {record.id})]",
                })
                try:
                    with self.assertRaises(AccessError):
                        record.with_user(readonly).check_access('read')
                    self.assertFalse(self.env[model_name].with_user(readonly).search([
                        ('id', '=', record.id),
                    ]))
                    # Existing GL implements a fail-closed pattern against all
                    # four source relations; a future B calculator must obtain
                    # its own independent G5 proof before QA.
                    filters = {
                        'company_id': self.company.id,
                        'date_from': '2041-10-01',
                        'date_to': '2041-10-31',
                        'journal_ids': [],
                    }
                    report = self.env['baseer.general.ledger.report'].with_user(
                        readonly,
                    ).with_context(allowed_company_ids=self.company.ids)
                    with self.assertRaises(AccessError):
                        report.get_report(filters)
                finally:
                    rule.unlink()
