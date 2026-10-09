"""Financial and access contract for the posted trial balance."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from lxml import html as lxml_html

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged

from ..models.trial_balance import BaseerTrialBalance


@tagged('post_install', '-at_install')
class TestTrialBalance(TransactionCase):
    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.company.write({'fiscalyear_last_day': 31, 'fiscalyear_last_month': '12'})
        self.report = self.env['baseer.trial.balance.report']
        self.gl = self.env['baseer.general.ledger.report']
        self.filters = {
            'company_id': self.company.id,
            'date_from': '2041-10-01',
            'date_to': '2041-10-31',
            'journal_ids': [],
        }
        self.cash = self._account(self.company, '958101', 'asset_cash')
        self.income = self._account(self.company, '958102', 'income')
        self.expense = self._account(self.company, '958103', 'expense')
        self.unaffected = self._account(self.company, '958104', 'equity_unaffected')
        self.equity = self._account(self.company, '958105', 'equity')
        self.journal = self._journal(self.company)

    def _account(self, company, code, kind):
        return self.env['account.account'].with_company(company).create({
            'code': code, 'name': f'TB {kind} {code}',
            'account_type': kind, 'company_ids': [Command.set(company.ids)],
        })

    def _journal(self, company):
        return self.env['account.journal'].with_company(company).search([
            ('company_id', '=', company.id), ('type', '=', 'general'),
        ], limit=1)

    def _entry(self, day, debit_account, credit_account, amount,
               company=None, journal=None, posted=True, currency=None):
        company = company or self.company
        journal = journal or self.journal
        debit = {'name': 'TB debit source', 'account_id': debit_account.id,
                 'debit': amount}
        credit = {'name': 'TB credit source', 'account_id': credit_account.id,
                  'credit': amount}
        if currency:
            debit.update({'currency_id': currency.id, 'amount_currency': amount})
            credit.update({'currency_id': currency.id, 'amount_currency': -amount})
        move = self.env['account.move'].with_company(company).create({
            'date': day, 'journal_id': journal.id, 'move_type': 'entry',
            'line_ids': [Command.create(debit), Command.create(credit)],
        })
        if posted:
            move._post(soft=False)
        return move

    @staticmethod
    def _row(report, account):
        return next(row for row in report['accounts'] if row['id'] == account.id)

    @staticmethod
    def _amount(value):
        return Decimal(value.replace(',', ''))

    def _accountant(self):
        return self.env['res.users'].create({
            'name': 'TB readonly accountant', 'login': 'tb_readonly_accountant',
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_readonly').id,
            ])],
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
        })

    def test_october_opening_is_fiscal_ytd_and_totals_match_general_ledger(self):
        self._entry('2041-01-10', self.cash, self.income, 100)
        self._entry('2041-09-30', self.expense, self.cash, 20)
        self._entry('2041-10-01', self.cash, self.income, 30)
        self._entry('2041-10-31', self.expense, self.cash, 10)
        self._entry('2041-10-15', self.cash, self.income, 999, posted=False)
        self.expense.active = False
        trial = self.report.get_report(self.filters)
        gl = self.gl.get_report(self.filters)
        self.assertEqual(self._row(trial, self.income)['opening_credit'], '100.00')
        self.assertEqual(self._row(trial, self.income)['credit'], '30.00')
        self.assertEqual(self._row(trial, self.expense)['opening_debit'], '20.00')
        self.assertEqual(self._row(trial, self.expense)['debit'], '10.00')
        self.assertEqual(self._row(trial, self.cash)['closing_debit'], '100.00')
        self.assertEqual(trial['total']['debit'], gl['total']['debit'])
        self.assertEqual(trial['total']['credit'], gl['total']['credit'])
        for left, right in (('opening_debit', 'opening_credit'),
                            ('debit', 'credit'),
                            ('closing_debit', 'closing_credit')):
            self.assertEqual(trial['total'][left], trial['total'][right])
        action = self.report.get_account_action(self.filters, self.income.id)
        self.assertEqual(action['res_model'], 'account.move.line')
        self.assertIn(('date', '>=', '2041-10-01'), action['domain'])
        self.assertIn(('date', '<=', '2041-10-31'), action['domain'])
        opening = self.report.get_account_action(self.filters, self.income.id, 'opening')
        self.assertIn(('date', '>=', '2041-01-01'), opening['domain'])

    def test_prior_result_is_dynamic_before_and_after_real_appropriation(self):
        self._entry('2040-12-31', self.cash, self.income, 100)
        early = self.report.get_report({**self.filters, 'date_from': '2041-01-01',
                                        'date_to': '2041-01-01'})
        self.assertEqual(early['rbf']['opening_credit'], '100.00')
        self.assertEqual(early['total']['opening_debit'], '100.00')
        self.assertEqual(early['total']['opening_credit'], '100.00')
        self._entry('2041-01-02', self.unaffected, self.equity, 100)
        later = self.report.get_report(self.filters)
        self.assertEqual(later['rbf']['opening_credit'], '100.00')
        self.assertEqual(self._row(later, self.unaffected)['opening_debit'], '100.00')
        self.assertEqual(self._row(later, self.equity)['opening_credit'], '100.00')
        self.assertEqual(later['total']['opening_debit'], later['total']['opening_credit'])
        self.assertEqual(later['total']['closing_debit'], later['total']['closing_credit'])
        rbf_action = self.report.get_account_action(self.filters, self.income.id, 'rbf')
        self.assertIn(('date', '<', '2041-01-01'), rbf_action['domain'])

    def test_march_fiscal_company_boundary_and_company_isolation(self):
        other = self.env['res.company'].create({
            'name': 'TB March company', 'fiscalyear_last_day': 31,
            'fiscalyear_last_month': '3',
        })
        cash = self._account(other, '958101', 'asset_cash')
        income = self._account(other, '958102', 'income')
        journal = self._journal(other)
        self._entry('2041-03-31', cash, income, 40, other, journal)
        self._entry('2041-04-01', cash, income, 50, other, journal)
        self._entry('2041-10-01', cash, income, 60, other, journal)
        report = self.report.with_company(other).with_context(allowed_company_ids=[other.id])
        result = report.get_report({**self.filters, 'company_id': other.id})
        self.assertEqual(result['period']['fiscal_start'], '2041-04-01')
        self.assertEqual(self._row(result, income)['opening_credit'], '50.00')
        self.assertEqual(self._row(result, income)['credit'], '60.00')
        self.assertEqual(result['rbf']['opening_credit'], '40.00')
        self.assertEqual(result['total']['debit'], result['total']['credit'])
        with self.assertRaises(AccessError):
            self.report.with_context(allowed_company_ids=[self.company.id, other.id]).get_report(
                {**self.filters, 'company_id': other.id},
            )
        with self.assertRaises(ValidationError):
            report.get_report({**self.filters, 'company_id': other.id,
                               'date_from': '2041-03-31', 'date_to': '2041-04-01'})

    def test_company_currency_not_amount_currency_and_selected_journal(self):
        currency = self.env.ref('base.USD')
        self._entry('2041-10-10', self.cash, self.income, 15,
                    currency=currency)
        result = self.report.get_report(self.filters)
        self.assertEqual(self._row(result, self.cash)['debit'], '15.00')
        self.assertEqual(self._row(result, self.income)['credit'], '15.00')
        selected = self.report.get_report({**self.filters, 'journal_ids': [self.journal.id]})
        self.assertTrue(selected['is_partial_journals'])
        self.assertEqual(selected['total']['debit'], selected['total']['credit'])

    def test_fail_closed_for_each_source_relation_and_nonaccountant(self):
        move = self._entry('2041-10-03', self.cash, self.income, 20)
        accountant = self._accountant()
        internal = self.env['res.users'].create({
            'name': 'TB internal', 'login': 'tb_internal',
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
                    'name': f'TB hide {model}',
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
                        secured.get_account_action(self.filters, self.cash.id)
                    with self.assertRaises(AccessError):
                        self.env['report.baseer_trial_balance_report.trial_balance_pdf'].with_user(
                            accountant,
                        ).with_context(allowed_company_ids=self.company.ids)._get_report_values(
                            [], {'filters': self.filters},
                        )
                finally:
                    rule.unlink()

    def test_pdf_is_complete_and_page_contract_is_bounded(self):
        accounts = {index: SimpleNamespace(
            id=index, code=f'{index:06}', name=f'Account {index}',
            include_initial_balance=True,
        ) for index in range(1, 102)}
        snapshot = (self.company, date(2041, 10, 1), date(2041, 10, 31),
                    date(2041, 1, 1), [], {}, {}, {}, accounts)
        with patch.object(BaseerTrialBalance, '_snapshot', return_value=snapshot), \
                patch.object(BaseerTrialBalance, '_assert_complete_source'):
            screen = self.report.get_report(self.filters)
            full = self.report._build_trial_balance(self.filters, full=True)
            pdf = self.env['report.baseer_trial_balance_report.trial_balance_pdf']
            html, _ = self.env['ir.actions.report']._render_qweb_html(
                'baseer_trial_balance_report.trial_balance_pdf', docids=[],
                data={'filters': self.filters},
            )
        self.assertEqual((len(screen['accounts']), screen['page_count']), (100, 2))
        self.assertEqual((len(full['accounts']), full['account_count']), (101, 101))
        self.assertEqual(full['total'], screen['total'])
        self.assertIn(b'Account 101', html)
        rows = lxml_html.fromstring(html).xpath(
            "//div[contains(@class, 'btb-pdf')]//table/tbody/tr",
        )
        self.assertEqual(len(rows), 102)
        self.assertEqual(self.env.ref(
            'baseer_trial_balance_report.action_trial_balance_pdf',
        ).paperformat_id.orientation, 'Landscape')
        with self.assertRaises(AccessError):
            pdf._get_report_values([], {'filters': {**self.filters, 'company_id': -1}})
        self.assertEqual(self.report.action_print(self.filters)['data'], {'filters': self.filters})
        accounts[5000] = SimpleNamespace(
            id=5000, code='005000', name='Account 5000', include_initial_balance=True,
        )
        with patch.object(BaseerTrialBalance, '_snapshot', return_value=snapshot), \
                patch.object(BaseerTrialBalance, '_assert_complete_source'):
            self.assertEqual(len(self.report._build_trial_balance(self.filters, full=True)['accounts']), 102)
            for index in range(102, 5002):
                accounts[index] = SimpleNamespace(
                    id=index, code=f'{index:06}', name=f'Account {index}',
                    include_initial_balance=True,
                )
            with self.assertRaises(ValidationError):
                self.report._build_trial_balance(self.filters, full=True)
