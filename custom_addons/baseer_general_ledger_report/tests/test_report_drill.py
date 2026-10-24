"""Synthetic exact-source and security contracts for the unified amount links."""

from decimal import Decimal
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged
from .test_general_ledger import TestGeneralLedger


class DrillFixture(TransactionCase):
    """Shared setup only; importing it does not run the legacy financial suite."""
    _entry = TestGeneralLedger._entry
    _accountant = TestGeneralLedger._accountant
    report_model = 'baseer.general.ledger.report'

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.company.write({'fiscalyear_last_day': 31, 'fiscalyear_last_month': '12'})
        self.filters = {'company_id': self.company.id, 'date_from': '2047-06-01',
                        'date_to': '2047-06-30', 'journal_ids': []}
        self.report = self.env[self.report_model]
        self.journal = self.env['account.journal'].search([
            ('company_id', '=', self.company.id), ('type', '=', 'general')], limit=1)
        self.assertTrue(self.journal)
        for index, (name, kind) in enumerate((('cash', 'asset_cash'), ('income', 'income'),
                ('expense', 'expense'), ('unaffected', 'equity_unaffected'), ('equity', 'equity')), 1):
            setattr(self, name, self.env['account.account'].create({
                'code': '96370' + str(index), 'name': 'Drill synthetic ' + name,
                'account_type': kind, 'company_ids': [Command.set(self.company.ids)]}))
        self.prior = self._entry('2046-12-31', self.cash, 100, 0, self.income)
        self.opening = self._entry('2047-01-10', self.cash, 20, 0, self.income)
        self.sale = self._entry('2047-06-10', self.cash, 30, 0, self.income)
        self.cost = self._entry('2047-06-11', self.expense, 10, 0, self.cash)
        self.reader = self._accountant()
        self.secured = self.report.with_user(self.reader).sudo(False).with_context(
            allowed_company_ids=self.company.ids, lang='en_US')

    @staticmethod
    def source_ids(result):
        return {row['source']['line_id'] for row in result['rows'] if 'source' in row}

    @staticmethod
    def amount(text):
        return Decimal(text.replace(',', ''))

    def check_boundaries(self, selector):
        denied = self.env['res.users'].create({'name': 'Denied drill reader', 'login': 'denied.drill',
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set(self.env.ref('base.group_user').ids)]})
        with self.assertRaises(AccessError):
            self.report.with_user(denied).sudo(False)._get_drilldown(self.filters, selector)
        other = self.env['res.company'].create({'name': 'Foreign drill company'})
        with self.assertRaises(AccessError):
            self.report.with_context(allowed_company_ids=[self.company.id, other.id])._get_drilldown(
                {**self.filters, 'company_id': other.id}, selector)
        for wrong in (dict(selector, domain=[]), dict(selector, kind=[])):
            with self.assertRaises(ValidationError):
                self.secured._get_drilldown(self.filters, wrong)
        for page in (0, True, -1, 99999):
            with self.assertRaises(ValidationError):
                self.secured._get_drilldown(self.filters, selector, page)
        detail = self.secured._get_drilldown(self.filters, selector)
        source = next(row['source'] for row in detail['rows'] if 'source' in row)
        with self.assertRaises(ValidationError):
            self.secured._open_drill_source(self.filters, dict(source, res_model='res.users'))
        # Readable source on the opposite account is still not a member of this cell.
        foreign_line = self.sale.line_ids.filtered(lambda line: line.account_id == self.income)[0]
        with self.assertRaises(AccessError):
            self.secured._open_drill_source(self.filters, dict(source, line_id=foreign_line.id))
        with patch.object(type(self.secured), 'DRILL_SOURCE_LIMIT', 1), self.assertRaises(ValidationError):
            self.secured._get_drilldown(self.filters, selector)
        for model, identity in (('account.move.line', self.sale.line_ids[0].id),
                                ('account.move', self.sale.id), ('account.journal', self.journal.id)):
            rule = self.env['ir.rule'].create({'name': 'Hide a drill source relation',
                'model_id': self.env['ir.model']._get_id(model), 'domain_force': "[('id', '!=', %s)]" % identity})
            try:
                with self.assertRaises(AccessError):
                    self.secured._get_drilldown(self.filters, selector)
                with self.assertRaises(AccessError):
                    self.secured._open_drill_source(self.filters, source)
            finally:
                rule.unlink()


@tagged('post_install', '-at_install', 'reports_unified_drill')
class TestLedgerDrill(DrillFixture):
    def test_fixed_dispatch_roundtrip(self):
        engine = self.env['baseer.report.drill'].with_user(self.reader).sudo(False).with_context(allowed_company_ids=self.company.ids)
        result = engine.get_drilldown('general_ledger', self.filters, {'kind': 'account', 'account_id': self.cash.id, 'measure': 'closing'}, 1)
        source = result['rows'][0]['source']
        action = engine.open_source('general_ledger', self.filters, source)
        self.assertEqual((action['res_model'], action['res_id']), ('account.move', self.prior.id))

    def test_all_measures_and_totals_match_authoritative_collector(self):
        report = self.secured._build_report(self.filters, full=True)
        for measure in ('opening', 'debit', 'credit', 'closing'):
            total = self.secured._get_drilldown(self.filters, {'kind': 'total', 'measure': measure})
            self.assertEqual(total['value'], report['total'][measure])
            self.assertEqual(sum((self.amount(row['cells']['amount']) for row in total['rows']), Decimal(0)),
                             self.amount(total['value']))
            for account in report['accounts']:
                result = self.secured._get_drilldown(self.filters, {
                    'kind': 'account', 'account_id': account['id'], 'measure': measure})
                self.assertEqual(result['value'], account[measure])
                self.assertEqual(sum((self.amount(row['cells']['amount']) for row in result['rows']), Decimal(0)),
                                 self.amount(result['value']))

    def test_zero_period_has_no_opening_fallback_and_rbf_source_membership(self):
        later = {**self.filters, 'date_from': '2047-07-01', 'date_to': '2047-07-31'}
        zero = self.secured._get_drilldown(later, {'kind': 'account', 'account_id': self.cash.id, 'measure': 'debit'})
        self.assertEqual((zero['value'], zero['rows']), ('0.00', []))
        rbf = self.secured._get_drilldown(self.filters, {'kind': 'rbf', 'measure': 'opening'})
        child = next(row['drill'] for row in rbf['rows'] if row['drill']['account_id'] == self.income.id)
        detail = self.secured._get_drilldown(self.filters, child)
        self.assertEqual(detail['value'], '-100.00')
        self.assertEqual(self.source_ids(detail), set(self.prior.line_ids.filtered(lambda line: line.account_id == self.income).ids))
        source = detail['rows'][0]['source']
        self.assertEqual(self.secured._open_drill_source(self.filters, source)['res_id'], self.prior.id)
        wrong_period_line = self.sale.line_ids.filtered(lambda line: line.account_id == self.income)[0]
        with self.assertRaises(AccessError):
            self.secured._open_drill_source(self.filters, dict(source, line_id=wrong_period_line.id))

    def test_offsetting_zero_keeps_sources_and_page_two_is_complete(self):
        # A real zero balance retains both contributing source rows.
        self._entry('2047-06-12', self.cash, 10, 0, self.expense)
        result = self.secured._get_drilldown(self.filters, {'kind': 'account', 'account_id': self.expense.id, 'measure': 'closing'})
        self.assertEqual(result['value'], '0.00')
        self.assertEqual(result['total_count'], 2)
        for _index in range(51):
            self._entry('2047-06-20', self.cash, 1, 0, self.income)
        selector = {'kind': 'account', 'account_id': self.cash.id, 'measure': 'debit'}
        first = self.secured._get_drilldown(self.filters, selector)
        second = self.secured._get_drilldown(self.filters, selector, 2)
        self.assertEqual((len(first['rows']), len(second['rows'])), (50, 3))
        self.assertFalse(self.source_ids(first) & self.source_ids(second))
        self.assertEqual(first['value'], second['value'])

    def test_security_malformed_source_and_complete_source_cap(self):
        self.check_boundaries({'kind': 'account', 'account_id': self.cash.id, 'measure': 'closing'})
