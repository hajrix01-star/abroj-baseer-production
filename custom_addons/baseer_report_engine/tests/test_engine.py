"""Engine computations: formulas, domains, periods, filters and access."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import tagged

from odoo.addons.baseer_report_engine.models.formula import (
    FormulaError, evaluate_formula, referenced_codes,
)
from odoo.addons.baseer_report_engine.tests.common import EngineCase


@tagged('post_install', '-at_install')
class TestReportEngine(EngineCase):
    def test_formula_parser_precedence_and_errors(self):
        variables = {'A': Decimal('2'), 'B': Decimal('3'), 'C': Decimal('4')}
        self.assertEqual(evaluate_formula('A + B * C', variables), Decimal('14'))
        self.assertEqual(evaluate_formula('(A + B) * C', variables), Decimal('20'))
        self.assertEqual(evaluate_formula('-A + C', variables), Decimal('2'))
        self.assertEqual(referenced_codes('CA + FA + NCA'), ['CA', 'FA', 'NCA'])
        with self.assertRaises(FormulaError):
            evaluate_formula('A +', variables)
        with self.assertRaises(FormulaError):
            evaluate_formula('A / (B - B)', variables)

    def test_prefix_domain_debit_and_implicit_sum(self):
        company = self._company('Engine prefix')
        engine = self._engine(company)
        journal = self._journal(company, 'BRP')
        other = self._journal(company, 'BRQ')
        cash = self._account(company, '981100', 'asset_cash')
        other_cash = self._account(company, '981200', 'asset_cash')
        income = self._account(company, '981300', 'income')
        self._entry(company, journal, '2041-02-01', cash, income, 30)
        self._entry(company, other, '2041-02-02', other_cash, income, 99)
        self._entry(company, journal, '2040-12-01', cash, income, 5)
        report = self._report('prefix_case', 'range', [
            Command.create({
                'code': 'P11', 'name': 'Prefix 9811', 'sequence': 10,
                'expression_ids': [Command.create({
                    'engine': 'code_prefix', 'code_prefixes': '9811',
                    'figure': 'balance', 'sign': '1', 'date_scope': 'report',
                })],
            }),
            Command.create({
                'code': 'DOM', 'name': 'Journal domain', 'sequence': 20,
                'expression_ids': [Command.create({
                    'engine': 'domain', 'domain': repr([('journal_id', '=', journal.id)]),
                    'figure': 'debit', 'sign': '1', 'date_scope': 'report',
                })],
            }),
            Command.create({
                'code': 'CRED', 'name': 'Credit figure', 'sequence': 30,
                'expression_ids': [Command.create({
                    'engine': 'code_prefix', 'code_prefixes': '9813',
                    'figure': 'credit', 'sign': '1', 'date_scope': 'report',
                })],
            }),
            Command.create({
                'code': 'CHILD', 'name': 'Child', 'sequence': 40,
                'expression_ids': [Command.create({
                    'engine': 'account_type', 'account_types': 'asset_cash',
                    'figure': 'balance', 'sign': '1', 'date_scope': 'to_date',
                })],
            }),
        ])
        summary = self.env['baseer.report.line'].create({
            'report_id': report.id, 'code': 'SUM', 'name': 'Implicit sum', 'sequence': 50,
        })
        report.line_ids.filtered(lambda line: line.code == 'P11').parent_id = summary
        payload = engine.get_report('prefix_case', self._options(
            date_from='2041-01-01', date_to='2041-12-31',
        ))
        self.assertEqual(self._value(payload, 'P11'), '30.00')
        self.assertEqual(self._value(payload, 'DOM'), '30.00')
        self.assertEqual(self._value(payload, 'CRED'), '129.00')
        self.assertEqual(self._value(payload, 'SUM'), '30.00')
        cumulative = engine.get_report('prefix_case', self._options())
        self.assertEqual(self._value(cumulative, 'CHILD'), '134.00')

    def test_formula_cycle_unknown_and_division(self):
        company = self._company('Engine formula')
        engine = self._engine(company)
        self._report('cycle_case', 'as_of', [
            Command.create({
                'code': 'A', 'name': 'A', 'sequence': 1,
                'expression_ids': [Command.create({'engine': 'formula', 'formula': 'B'})],
            }),
            Command.create({
                'code': 'B', 'name': 'B', 'sequence': 2,
                'expression_ids': [Command.create({'engine': 'formula', 'formula': 'A'})],
            }),
        ])
        with self.assertRaises(ValidationError):
            engine.get_report('cycle_case', self._options())
        self._report('missing_case', 'as_of', [
            Command.create({
                'code': 'A', 'name': 'A', 'sequence': 1,
                'expression_ids': [Command.create({'engine': 'formula', 'formula': 'MISSING'})],
            }),
        ])
        with self.assertRaises(ValidationError):
            engine.get_report('missing_case', self._options())
        journal = self._journal(company, 'BRF')
        cash = self._account(company, '981100', 'asset_cash')
        income = self._account(company, '981300', 'income')
        self._entry(company, journal, '2041-02-01', cash, income, 10)
        self._report('divide_case', 'as_of', [
            Command.create({
                'code': 'CASH', 'name': 'Cash', 'sequence': 1,
                'expression_ids': [Command.create({
                    'engine': 'account_type', 'account_types': 'asset_cash',
                    'figure': 'balance', 'sign': '1', 'date_scope': 'to_date',
                })],
            }),
            Command.create({
                'code': 'GAP', 'name': 'Gap', 'sequence': 2,
                'expression_ids': [Command.create({
                    'engine': 'account_type', 'account_types': 'asset_fixed',
                    'figure': 'balance', 'sign': '1', 'date_scope': 'to_date',
                })],
            }),
            Command.create({
                'code': 'BAD', 'name': 'Bad', 'sequence': 3,
                'expression_ids': [Command.create({'engine': 'formula', 'formula': 'CASH / GAP'})],
            }),
        ])
        with self.assertRaises(ValidationError):
            engine.get_report('divide_case', self._options())

    def test_drafts_journals_analytic_comparison_and_companies(self):
        company = self._company('Engine filters')
        engine = self._engine(company)
        journal = self._journal(company, 'BR1')
        other_journal = self._journal(company, 'BR2')
        cash = self._account(company, '981100', 'asset_cash')
        income = self._account(company, '981300', 'income')
        self._entry(company, journal, '2041-04-10', cash, income, 4)
        self._entry(company, journal, '2041-05-15', cash, income, 10)
        self._entry(company, other_journal, '2041-05-20', cash, income, 7)
        self._entry(company, journal, '2041-05-21', cash, income, 999, posted=False)
        plan = self.env['account.analytic.plan'].create({'name': 'Engine plan'})
        analytic = self.env['account.analytic.account'].create({
            'name': 'Engine analytic', 'plan_id': plan.id, 'company_id': company.id,
        })
        self._entry(
            company, journal, '2041-05-22', cash, income, 100,
            analytic={str(analytic.id): 50},
        )
        posted = engine.get_report('balance_sheet', self._options(as_of='2041-05-31'))
        # 4 + 10 + 7 + 100. The draft is excluded. Analytic weighting applies only when filtered.
        self.assertEqual(self._value(posted, 'ASSETS'), '121.00')
        drafts = engine.get_report('balance_sheet', self._options(
            as_of='2041-05-31', posted_only=False,
        ))
        self.assertEqual(self._value(drafts, 'ASSETS'), '1120.00')
        selected = engine.get_report('balance_sheet', self._options(
            as_of='2041-05-31', journal_ids=[journal.id],
        ))
        self.assertEqual(self._value(selected, 'ASSETS'), '114.00')
        weighted = engine.get_report('balance_sheet', self._options(
            as_of='2041-05-31', analytic_account_ids=[analytic.id],
        ))
        self.assertEqual(self._value(weighted, 'ASSETS'), '50.00')
        compared = engine.get_report('balance_sheet', self._options(
            as_of='2041-05-31', comparison=1, comparison_unit='month',
        ))
        self.assertEqual(self._value(compared, 'ASSETS', 'c0'), '121.00')
        self.assertEqual(self._value(compared, 'ASSETS', 'c1'), '4.00')
        self.assertEqual(self._value(compared, 'ASSETS', 'variation'), '117.00')
        self.assertEqual(compared['columns'][1]['date_to'], '2041-04-30')
        foreign = self._company('Engine foreign')
        foreign_journal = self._journal(foreign, 'BRF')
        foreign_cash = self._account(foreign, '981100', 'asset_cash')
        foreign_income = self._account(foreign, '981300', 'income')
        self._entry(foreign, foreign_journal, '2041-05-01', foreign_cash, foreign_income, 80)
        self.assertEqual(self._value(
            engine.get_report('balance_sheet', self._options(as_of='2041-05-31')), 'ASSETS',
        ), '121.00')
        both = self.env['baseer.report.engine'].with_company(company).with_context(
            allowed_company_ids=[company.id, foreign.id],
        )
        self.assertEqual(self._value(
            both.get_report('balance_sheet', self._options(as_of='2041-05-31')), 'ASSETS',
        ), '201.00')
        with self.assertRaises(AccessError):
            engine.get_report('balance_sheet', self._options(journal_ids=[foreign_journal.id]))

    def test_presets_follow_the_company_fiscal_year(self):
        company = self._company('Engine calendar', month='12')
        engine = self._engine(company)
        frozen = date(2041, 5, 15)
        with patch.object(fields.Date, 'context_today', return_value=frozen):
            month = engine.get_report('balance_sheet', self._options(preset='this_month'))
            last_month = engine.get_report('balance_sheet', self._options(preset='last_month'))
            quarter = engine.get_report('balance_sheet', self._options(preset='this_quarter'))
            last_quarter = engine.get_report('balance_sheet', self._options(preset='last_quarter'))
            year = engine.get_report('balance_sheet', self._options(preset='this_year'))
            last_year = engine.get_report('balance_sheet', self._options(preset='last_year'))
            shifted = engine.get_report('balance_sheet', self._options(
                preset='this_month', direction=-1,
            ))
        self.assertEqual(month['options']['as_of'], '2041-05-31')
        self.assertEqual(last_month['options']['as_of'], '2041-04-30')
        self.assertEqual(quarter['options']['as_of'], '2041-06-30')
        self.assertEqual(last_quarter['options']['as_of'], '2041-03-31')
        self.assertEqual(year['options']['as_of'], '2041-12-31')
        self.assertEqual(last_year['options']['as_of'], '2040-12-31')
        self.assertEqual(shifted['options']['as_of'], '2041-04-30')
        march = self._company('Engine march', month='3')
        march_engine = self._engine(march)
        with patch.object(fields.Date, 'context_today', return_value=frozen):
            march_year = march_engine.get_report('balance_sheet', self._options(preset='this_year'))
            march_last = march_engine.get_report('balance_sheet', self._options(preset='last_year'))
            march_quarter = march_engine.get_report('balance_sheet', self._options(preset='this_quarter'))
        self.assertEqual(march_year['options']['as_of'], '2042-03-31')
        self.assertEqual(march_last['options']['as_of'], '2041-03-31')
        self.assertEqual(march_quarter['options']['as_of'], '2041-06-30')
        self.assertEqual(march_quarter['columns'][0]['fiscal_start'], '2041-04-01')

    def test_hide_zero_and_access(self):
        company = self._company('Engine access')
        engine = self._engine(company)
        journal = self._journal(company, 'BRA')
        cash = self._account(company, '981100', 'asset_cash')
        income = self._account(company, '981300', 'income')
        self._entry(company, journal, '2041-05-01', cash, income, 15)
        hidden = engine.get_report('balance_sheet', self._options(hide_zero=True))
        codes = {line['code'] for line in hidden['lines']}
        self.assertIn('ASSETS', codes)
        self.assertIn('CASH', codes)
        self.assertNotIn('REC', codes)
        self.assertIn('LIAB', codes)
        self.assertIn('LE', codes)
        shown = engine.get_report('balance_sheet', self._options(hide_zero=False))
        self.assertIn('REC', {line['code'] for line in shown['lines']})
        internal = self.env['res.users'].create({
            'name': 'Engine internal', 'login': 'engine_internal_user',
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
            'company_id': company.id,
            'company_ids': [Command.set(company.ids)],
        })
        with self.assertRaises(AccessError):
            engine.with_user(internal).get_report('balance_sheet', self._options())
        accountant = self.env['res.users'].create({
            'name': 'Engine readonly', 'login': 'engine_readonly_user',
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_readonly').id,
            ])],
            'company_id': company.id,
            'company_ids': [Command.set(company.ids)],
        })
        viewed = self.env['baseer.report.engine'].with_user(accountant).with_company(company).get_report(
            'balance_sheet', self._options(),
        )
        self.assertEqual(self._value(viewed, 'ASSETS'), '15.00')
        module = self.env['ir.module.module'].search([('name', '=', 'baseer_report_engine')])
        self.assertEqual(set(module.dependencies_id.mapped('name')), {'account', 'analytic', 'web'})
