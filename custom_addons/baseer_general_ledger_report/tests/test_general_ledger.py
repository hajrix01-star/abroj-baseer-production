from collections import Counter
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from lxml import html as lxml_html

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged

from ..models.general_ledger import BaseerGeneralLedger


@tagged('post_install', '-at_install')
class TestGeneralLedger(TransactionCase):
    """The report reads posted AMLs, never a preview or Heritage balance."""

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.company.write({'fiscalyear_last_day': 31, 'fiscalyear_last_month': '12'})
        self.report = self.env['baseer.general.ledger.report']
        self.filters = {
            'company_id': self.company.id,
            'date_from': '2041-03-01',
            'date_to': '2041-03-31',
            'journal_ids': [],
        }
        Account = self.env['account.account'].with_company(self.company)
        self.cash = Account.create({
            'code': '959201', 'name': 'GL cash', 'account_type': 'asset_cash',
            'company_ids': [Command.set(self.company.ids)],
        })
        self.income = Account.create({
            'code': '959202', 'name': 'GL income', 'account_type': 'income',
            'company_ids': [Command.set(self.company.ids)],
        })
        self.appropriation = Account.create({
            'code': '959203', 'name': 'GL appropriation',
            'account_type': 'equity_unaffected',
            'company_ids': [Command.set(self.company.ids)],
        })
        self.equity = Account.create({
            'code': '959204', 'name': 'GL equity', 'account_type': 'equity',
            'company_ids': [Command.set(self.company.ids)],
        })
        self.journal = self.env['account.journal'].with_company(self.company).search([
            ('company_id', '=', self.company.id), ('type', '=', 'general'),
        ], limit=1)
        self.assertTrue(self.journal)
        self.assertEqual(self.company.compute_fiscalyear_dates(
            date(2041, 3, 1),
        )['date_from'].isoformat(), '2041-01-01')
        self.assertTrue(self.cash.include_initial_balance)
        self.assertFalse(self.income.include_initial_balance)
        self.assertFalse(self.appropriation.include_initial_balance)

    def _entry(self, day, first_account, first_debit, first_credit,
               other_account, posted=True, journal=None, currency=None):
        amount = max(first_debit, first_credit)
        first = {'name': 'GL test source', 'account_id': first_account.id,
                 'debit': first_debit, 'credit': first_credit}
        second = {'name': 'GL balancing source', 'account_id': other_account.id,
                  'debit': first_credit, 'credit': first_debit}
        if currency:
            first.update({'currency_id': currency.id,
                          'amount_currency': amount if first_debit else -amount})
            second.update({'currency_id': currency.id,
                           'amount_currency': -amount if first_debit else amount})
        move = self.env['account.move'].with_company(self.company).create({
            'date': day, 'journal_id': (journal or self.journal).id,
            'move_type': 'entry',
            'line_ids': [Command.create(first), Command.create(second)],
        })
        if posted:
            move._post(soft=False)
        return move

    @staticmethod
    def _row(report, account):
        return next(row for row in report['accounts'] if row['id'] == account.id)

    def _accountant(self):
        return self.env['res.users'].create({
            'name': 'GL readonly accountant', 'login': 'gl_readonly_accountant',
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_readonly').id,
            ])],
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
        })

    def _hide(self, model, record):
        return self.env['ir.rule'].create({
            'name': f'GL hide {model} {record.id}',
            'model_id': self.env['ir.model']._get(model).id,
            'domain_force': f"[('id', '!=', {record.id})]",
        })

    def _period(self, kind, anchor, direction=0, start='', end=''):
        return self.report.resolve_period({
            'company_id': self.company.id, 'kind': kind,
            'anchor_date': anchor, 'direction': direction,
            'date_from': start, 'date_to': end,
        })

    def test_pdf_summary_is_complete_while_screen_stays_paged(self):
        def snapshot(count):
            accounts = {index: SimpleNamespace(
                id=index, code=f'{index:06}', name=f'Account {index}',
                include_initial_balance=True,
            ) for index in range(1, count + 1)}
            return (self.company, date(2041, 3, 1), date(2041, 3, 31),
                    date(2041, 1, 1), [], {}, {}, {}, accounts)

        with patch.object(BaseerGeneralLedger, '_snapshot', return_value=snapshot(101)), \
                patch.object(BaseerGeneralLedger, '_assert_complete_source'):
            screen = self.report.get_report(self.filters)
            pdf = self.report._build_report(self.filters, full=True)
            html, _output_type = self.env['ir.actions.report']._render_qweb_html(
                'baseer_general_ledger_report.general_ledger_pdf', docids=[],
                data={'filters': self.filters},
            )
        self.assertEqual((len(screen['accounts']), screen['page_count']), (100, 2))
        self.assertEqual((len(pdf['accounts']), pdf['account_count']), (101, 101))
        self.assertEqual(pdf['accounts'][-1]['code'], '000101')
        self.assertEqual(pdf['total'], screen['total'])
        document = lxml_html.fromstring(html)
        printed = document.xpath("//div[contains(@class, 'bgl-pdf')]//table/tbody/tr")
        self.assertEqual(len(printed), 102)
        self.assertIn(b'Account 101', html)
        bodies, _ids, _header, footer, _paperformat = self.env['ir.actions.report']._prepare_html(
            html, report_model='baseer.general.ledger.report',
        )
        self.assertEqual(len(bodies), 1)
        self.assertIn('class="page"', footer)

        with patch.object(BaseerGeneralLedger, '_snapshot', return_value=snapshot(5000)), \
                patch.object(BaseerGeneralLedger, '_assert_complete_source'):
            at_limit = self.report._build_report(self.filters, full=True)
        self.assertEqual(len(at_limit['accounts']), 5000)

        with patch.object(BaseerGeneralLedger, '_snapshot', return_value=snapshot(5001)), \
                patch.object(BaseerGeneralLedger, '_assert_complete_source'):
            with self.assertRaises(ValidationError):
                self.report._build_report(self.filters, full=True)

    def test_pdf_direct_render_rechecks_company_rights_and_filters(self):
        move = self._entry('2041-03-07', self.cash, 50, 0, self.income)
        pdf = self.env['report.baseer_general_ledger_report.general_ledger_pdf']
        with patch.object(BaseerGeneralLedger, '_build_report', side_effect=AssertionError('early financial read')):
            action = self.report.action_print(self.filters)
        self.assertEqual(action['data'], {'filters': self.filters})
        self.assertEqual(self.env.ref(
            'baseer_general_ledger_report.action_general_ledger_pdf',
        ).paperformat_id.orientation, 'Landscape')
        values = pdf._get_report_values([], action['data'])
        self.assertEqual(values['report']['account_count'], 2)
        self.assertEqual(len(values['accounts']), 2)
        self.assertEqual(values['report']['total']['debit'], '50.00')
        html, _output_type = self.env['ir.actions.report']._render_qweb_html(
            'baseer_general_ledger_report.general_ledger_pdf', docids=[],
            data=action['data'],
        )
        document = lxml_html.fromstring(html)
        printed = document.xpath("//div[contains(@class, 'bgl-pdf')]//table/tbody/tr")
        self.assertEqual(len(printed), 3)
        self.assertIn(b'2041-03-01', html)
        self.assertIn(b'2041-03-31', html)
        self.assertIn(b'50.00', html)
        selected = {**self.filters, 'journal_ids': [self.journal.id]}
        selected_html, _output_type = self.env['ir.actions.report']._render_qweb_html(
            'baseer_general_ledger_report.general_ledger_pdf', docids=[],
            data={'filters': selected},
        )
        self.assertIn(self.journal.code.encode(), selected_html)

        other = self.env['res.company'].create({'name': 'GL PDF other company'})
        accountant = self._accountant()
        accountant.company_ids = [Command.link(other.id)]
        wrong = {**self.filters, 'company_id': other.id}
        with self.assertRaises(AccessError):
            pdf.with_user(accountant).with_context(
                allowed_company_ids=[self.company.id, other.id],
            )._get_report_values([], {'filters': wrong})
        internal = self.env['res.users'].create({
            'name': 'GL PDF internal', 'login': 'gl_pdf_internal',
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
        })
        with self.assertRaises(AccessError):
            pdf.with_user(internal)._get_report_values([], action['data'])
        rule = self._hide('account.move', move)
        try:
            with self.assertRaises(AccessError):
                pdf.with_user(accountant)._get_report_values([], action['data'])
        finally:
            rule.unlink()

    def test_period_resolver_full_month_quarter_fiscal_and_leap_day(self):
        month = self._period('month', '2040-02-15')
        self.assertEqual((month['date_from'], month['date_to']), ('2040-02-01', '2040-02-29'))
        self.assertTrue(month['is_full_calendar_month'])
        self.assertNotIn('2040-02-01', month['display_label'])
        quarter = self._period('quarter', '2041-10-08')
        self.assertEqual((quarter['date_from'], quarter['date_to']),
                         ('2041-10-01', '2041-12-31'))
        fiscal = self._period('fiscal_year', '2041-10-08')
        self.assertEqual((fiscal['date_from'], fiscal['date_to']),
                         ('2041-01-01', '2041-12-31'))

    def test_period_navigation_respects_mid_month_fiscal_boundary(self):
        self.company.write({'fiscalyear_last_day': 20, 'fiscalyear_last_month': '12'})
        before = self._period('month', '2041-12-20')
        self.assertEqual((before['date_from'], before['date_to']),
                         ('2041-12-01', '2041-12-20'))
        self.assertFalse(before['is_full_calendar_month'])
        self.assertIn('2041-12-01', before['display_label'])
        after = self._period('month', before['date_to'], 1)
        self.assertEqual((after['date_from'], after['date_to']),
                         ('2041-12-21', '2041-12-31'))
        self.assertEqual(self._period('month', after['date_from'], -1)['date_to'],
                         before['date_to'])
        quarter_before = self._period('quarter', '2041-12-20')
        quarter_after = self._period('quarter', quarter_before['date_to'], 1)
        self.assertEqual((quarter_after['date_from'], quarter_after['date_to']),
                         ('2041-12-21', '2041-12-31'))

    def test_period_resolver_rejects_invalid_dates_direction_company_and_custom_crossing(self):
        for invalid in (
            {'kind': 'week'}, {'direction': 2}, {'direction': True},
            {'anchor_date': '2041-02-30'}, {'date_from': '2041-03-01'},
        ):
            options = {'company_id': self.company.id, 'kind': 'month',
                       'anchor_date': '2041-03-15', 'direction': 0,
                       'date_from': '', 'date_to': ''}
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                self.report.resolve_period({**options, **invalid})
        with self.assertRaises(AccessError):
            self.report.resolve_period({
                'company_id': -1, 'kind': 'month', 'anchor_date': '2041-03-15',
                'direction': 0, 'date_from': '', 'date_to': '',
            })
        with self.assertRaises(ValidationError):
            self._period('custom', '2041-12-30', start='2041-12-30', end='2042-01-02')

    def test_opening_period_closing_and_result_brought_forward(self):
        prior = self._entry('2040-12-31', self.cash, 100, 0, self.income)
        self._entry('2041-02-28', self.cash, 40, 0, self.income)
        current = self._entry('2041-03-01', self.cash, 20, 0, self.income)
        self._entry('2041-03-31', self.cash, 0, 5, self.income)
        self._entry('2041-03-15', self.cash, 999, 0, self.income, posted=False)
        result = self.report.get_report(self.filters)
        cash = self._row(result, self.cash)
        income = self._row(result, self.income)
        self.assertEqual((cash['opening'], cash['debit'], cash['credit'], cash['closing']),
                         ('140.00', '20.00', '5.00', '155.00'))
        self.assertEqual((income['opening'], income['debit'], income['credit'], income['closing']),
                         ('-40.00', '5.00', '20.00', '-55.00'))
        self.assertEqual(result['rbf']['amount'], '-100.00')
        self.assertEqual(result['total']['opening'], '0.00')
        self.assertEqual(result['total']['debit'], result['total']['credit'])
        self.assertEqual(result['total']['closing'], '0.00')
        sources = self.report.get_rbf_accounts(self.filters)
        self.assertEqual(sources['accounts'][0]['id'], self.income.id)
        self.assertEqual(sources['accounts'][0]['amount'], '-100.00')
        lines = self.report.get_lines(self.filters, self.income.id, 'rbf')
        self.assertEqual(lines['lines'][0]['id'], prior.line_ids.filtered(
            lambda line: line.account_id == self.income,
        ).id)
        self.assertEqual(lines['lines'][0]['running'], '-100.00')
        self.assertEqual(self.report.get_source_line(self.filters, lines['lines'][0]['id'], 'rbf')
                         ['move_id'], prior.id)
        period_lines = self.report.get_lines(self.filters, self.cash.id)
        self.assertEqual(period_lines['lines'][0]['id'], current.line_ids.filtered(
            lambda line: line.account_id == self.cash,
        ).id)
        self.assertEqual(period_lines['lines'][0]['running'], '160.00')
        action = self.report.get_account_action(self.filters, self.cash.id)
        self.assertEqual(action['res_model'], 'account.move.line')
        self.assertEqual(action['target'], 'current')
        self.assertIn(('company_id', '=', self.company.id), action['domain'])
        self.assertIn(('parent_state', '=', 'posted'), action['domain'])
        self.assertIn(('account_id', '=', self.cash.id), action['domain'])
        self.assertIn(('date', '>=', self.filters['date_from']), action['domain'])
        self.assertIn(('date', '<=', self.filters['date_to']), action['domain'])
        opening_action = self.report.get_account_action(self.filters, self.cash.id, 'opening')
        self.assertIn(('date', '<', self.filters['date_from']), opening_action['domain'])
        self.assertNotIn(('date', '>=', self.filters['date_from']), opening_action['domain'])
        income_opening_action = self.report.get_account_action(
            self.filters, self.income.id, 'opening',
        )
        self.assertIn(('date', '>=', '2041-01-01'), income_opening_action['domain'])
        rbf_action = self.report.get_account_action(self.filters, self.income.id, 'rbf')
        self.assertIn(('date', '<', '2041-01-01'), rbf_action['domain'])

    def test_explicit_allocation_neutralizes_virtual_result(self):
        self._entry('2040-12-30', self.cash, 100, 0, self.income)
        before = self.report.get_report(self.filters)
        self.assertEqual(before['rbf']['amount'], '-100.00')
        self._entry('2040-12-31', self.appropriation, 100, 0, self.equity)
        after = self.report.get_report(self.filters)
        self.assertEqual(after['rbf']['amount'], '0.00')
        self.assertEqual(self._row(after, self.equity)['opening'], '-100.00')
        self.assertEqual(after['total']['opening'], '0.00')
        self.assertEqual(after['total']['closing'], '0.00')

    def test_opening_only_account_opens_its_posted_source(self):
        self._entry('2040-12-31', self.cash, 100, 0, self.income)
        self._entry('2041-02-28', self.cash, 40, 0, self.income)
        result = self.report.get_report(self.filters)
        cash = self._row(result, self.cash)
        income = self._row(result, self.income)
        self.assertEqual((cash['period_line_count'], cash['opening_source_count']), (0, 2))
        self.assertEqual((income['period_line_count'], income['opening_source_count']), (0, 1))
        cash_action = self.report.get_account_action(self.filters, self.cash.id)
        self.assertEqual(cash_action['res_model'], 'account.move.line')
        self.assertIn(('date', '<', '2041-03-01'), cash_action['domain'])
        self.assertNotIn(('date', '>=', '2041-01-01'), cash_action['domain'])
        income_action = self.report.get_account_action(self.filters, self.income.id)
        self.assertIn(('date', '>=', '2041-01-01'), income_action['domain'])
        self.assertIn(('date', '<', '2041-03-01'), income_action['domain'])
        with self.assertRaises(AccessError):
            self.report.get_account_action(self.filters, self.equity.id)

    def test_archived_account_reversal_and_journal_scope(self):
        self._entry('2041-03-02', self.cash, 12, 0, self.income)
        self._entry('2041-03-03', self.cash, 0, 2, self.income)
        other = self.env['account.journal'].with_company(self.company).create({
            'name': 'GL other', 'code': 'GLX', 'type': 'general',
            'company_id': self.company.id,
        })
        self._entry('2041-03-04', self.cash, 50, 0, self.income, journal=other)
        self.income.active = False
        selected = {**self.filters, 'journal_ids': [self.journal.id]}
        result = self.report.get_report(selected)
        self.assertTrue(result['is_partial_journals'])
        self.assertEqual(self._row(result, self.income)['closing'], '-10.00')
        self.assertEqual(self.report.get_lines(selected, self.income.id)['lines'][0]['credit'],
                         '12.00')
        self.assertEqual(self._row(self.report.get_report(selected), self.income)['closing'],
                         '-10.00')

    def test_page_size_and_cursor_are_bounded_and_stable(self):
        first = self._entry('2041-03-05', self.cash, 1, 0, self.income)
        second = self._entry('2041-03-05', self.cash, 2, 0, self.income)
        with patch.object(BaseerGeneralLedger, 'PAGE_SIZE', 1):
            page1 = self.report.get_lines(self.filters, self.cash.id)
            page2 = self.report.get_lines(self.filters, self.cash.id, 'period',
                                          page1['next_cursor']['date'],
                                          page1['next_cursor']['id'])
            accounts1 = self.report.get_report(self.filters, 1)
            accounts2 = self.report.get_report(self.filters, 2)
        self.assertEqual(page1['lines'][0]['id'], first.line_ids.filtered(
            lambda row: row.account_id == self.cash,
        ).id)
        self.assertEqual(page2['lines'][0]['id'], second.line_ids.filtered(
            lambda row: row.account_id == self.cash,
        ).id)
        self.assertEqual(page1['lines'][0]['running'], '1.00')
        self.assertEqual(page2['lines'][0]['running'], '3.00')
        self.assertEqual(accounts1['account_count'], accounts2['account_count'])
        self.assertEqual(len(accounts1['accounts']), 1)
        self.assertEqual(len(accounts2['accounts']), 1)
        self.assertEqual(accounts1['total'], accounts2['total'])
        with self.assertRaises(AccessError):
            self.report.get_lines(self.filters, self.cash.id, 'period', '2041-03-05',
                                  999999999)
        with self.assertRaises(ValidationError):
            self.report.get_report(self.filters, 0)

    def test_foreign_currency_and_decimal_precision(self):
        currency = self.env['res.currency'].create({
            'name': 'GLF', 'symbol': 'GLF', 'rounding': 0.01, 'active': True,
        })
        self._entry('2041-03-05', self.cash, 100, 0, self.income, currency=currency)
        result = self.report.get_report(self.filters)
        self.assertEqual(self._row(result, self.cash)['debit'], '100.00')
        self.assertEqual(self._row(result, self.income)['closing'], '-100.00')
        self.assertEqual(result['total']['closing'], '0.00')
        self.assertEqual(BaseerGeneralLedger._money(
            Decimal('0.005') + Decimal('0.005'), self.company.currency_id), '0.01')

    def test_large_decimal_sum_preserves_cents(self):
        amount = 1_000_000_000_000.01
        line_commands = []
        for _ in range(99):
            line_commands.extend([
                Command.create({'name': 'GL large debit', 'account_id': self.cash.id,
                                'debit': amount, 'credit': 0}),
                Command.create({'name': 'GL large credit', 'account_id': self.income.id,
                                'debit': 0, 'credit': amount}),
            ])
        move = self.env['account.move'].with_company(self.company).create({
            'date': '2041-03-06', 'journal_id': self.journal.id,
            'move_type': 'entry', 'line_ids': line_commands,
        })
        move._post(soft=False)
        result = self.report.get_report(self.filters)
        self.assertEqual(self._row(result, self.cash)['debit'],
                         '99,000,000,000,000.99')
        self.assertEqual(self._row(result, self.income)['credit'],
                         '99,000,000,000,000.99')
        self.assertEqual(result['total']['closing'], '0.00')

    def test_exact_batches_reject_missing_account_count(self):
        totals = {}
        with self.assertRaises(AccessError):
            BaseerGeneralLedger._merge_verified_batch(
                totals, Counter({self.cash.id: 2}),
                [(self.cash.id, '2.00', '0.00', 1)],
            )
        self.assertFalse(totals)
        expected = Counter({self.cash.id: 1})
        for _ in range(99):
            BaseerGeneralLedger._merge_verified_batch(
                totals, expected,
                [(self.cash.id, '1000000000000.01', '0.00', 1)],
            )
        self.assertEqual(totals[self.cash.id]['debit'],
                         Decimal('99000000000000.99'))
        self.assertEqual(totals[self.cash.id]['count'], 99)

    def test_verified_group_crosses_1000_line_boundary(self):
        commands = [Command.create({
            'name': 'GL batch debit', 'account_id': self.cash.id,
            'debit': 0.01, 'credit': 0,
        }) for _ in range(1001)]
        commands.append(Command.create({
            'name': 'GL batch credit', 'account_id': self.income.id,
            'debit': 0, 'credit': 10.01,
        }))
        move = self.env['account.move'].with_company(self.company).create({
            'date': '2041-03-07', 'journal_id': self.journal.id,
            'move_type': 'entry', 'line_ids': commands,
        })
        move._post(soft=False)
        result = self.report.get_report(self.filters)
        cash = self._row(result, self.cash)
        self.assertEqual(cash['debit'], '10.01')
        self.assertEqual(cash['period_line_count'], 1001)
        self.assertEqual(self._row(result, self.income)['credit'], '10.01')
        self.assertEqual(result['total']['closing'], '0.00')
        # The balancing account appears after the first 1,000 AML IDs.
        rule = self._hide('account.account', self.income)
        try:
            readonly = self.report.with_user(self._accountant()).with_context(
                allowed_company_ids=self.company.ids,
            )
            with self.assertRaises(AccessError):
                readonly.get_report(self.filters)
        finally:
            rule.unlink()

    def test_verified_group_handles_5001_lines_across_batches(self):
        commands = [Command.create({
            'name': 'GL security window debit', 'account_id': self.cash.id,
            'debit': 0.01, 'credit': 0,
        }) for _ in range(5001)]
        commands.append(Command.create({
            'name': 'GL security window credit', 'account_id': self.income.id,
            'debit': 0, 'credit': 50.01,
        }))
        move = self.env['account.move'].with_company(self.company).create({
            'date': '2041-03-08', 'journal_id': self.journal.id,
            'move_type': 'entry', 'line_ids': commands,
        })
        move._post(soft=False)
        result = self.report.get_report(self.filters)
        cash = self._row(result, self.cash)
        self.assertEqual(cash['debit'], '50.01')
        self.assertEqual(cash['period_line_count'], 5001)
        self.assertEqual(self._row(result, self.income)['credit'], '50.01')
        self.assertEqual(result['total']['closing'], '0.00')
        later_journal = self.env['account.journal'].with_company(self.company).create({
            'name': 'GL later batch', 'code': 'GLY', 'type': 'general',
            'company_id': self.company.id,
        })
        self._entry('2041-03-09', self.cash, 1, 0, self.income, journal=later_journal)
        rule = self._hide('account.journal', later_journal)
        try:
            readonly = self.report.with_user(self._accountant()).with_context(
                allowed_company_ids=self.company.ids,
            )
            with self.assertRaises(AccessError):
                readonly.get_report(self.filters)
        finally:
            rule.unlink()

    def test_company_dates_and_non_accountant_denied(self):
        other = self.env['res.company'].create({'name': 'GL other company'})
        readonly = self.report.with_user(self._accountant()).with_context(
            allowed_company_ids=self.company.ids,
        )
        with self.assertRaises(AccessError):
            readonly.get_report({**self.filters, 'company_id': other.id})
        with self.assertRaises(AccessError):
            readonly.get_context(other.id)
        with self.assertRaises(AccessError):
            readonly.resolve_period({
                'company_id': other.id, 'kind': 'month', 'anchor_date': '2041-03-15',
                'direction': 0, 'date_from': '', 'date_to': '',
            })
        for invalid in (
            {**self.filters, 'date_from': '2040-12-31'},
            {**self.filters, 'date_to': '2042-01-01'},
            {**self.filters, 'journal_ids': [True]},
            {**self.filters, 'journal_ids': [self.journal.id, self.journal.id]},
            {**self.filters, 'unknown': 1},
        ):
            with self.assertRaises(ValidationError):
                self.report.get_report(invalid)
        with self.assertRaises(AccessError):
            self.report.get_report({**self.filters, 'journal_ids': [999999999]})
        user = self.env['res.users'].create({
            'name': 'GL internal', 'login': 'gl_internal',
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
        })
        blocked = self.report.with_user(user).with_context(
            allowed_company_ids=self.company.ids,
        )
        for method, args in (
            ('get_context', ()), ('get_report', (self.filters,)),
            ('resolve_period', ({'company_id': self.company.id, 'kind': 'month',
                                 'anchor_date': '2041-03-15', 'direction': 0,
                                 'date_from': '', 'date_to': ''},)),
            ('get_rbf_accounts', (self.filters,)),
            ('get_lines', (self.filters, self.cash.id)),
            ('get_account_action', (self.filters, self.cash.id)),
            ('get_source_line', (self.filters, 1)),
        ):
            with self.assertRaises(AccessError):
                getattr(blocked, method)(*args)

    def test_linked_rules_fail_closed_and_aml_rule_cannot_leak(self):
        move = self._entry('2041-03-05', self.cash, 25, 0, self.income)
        source = move.line_ids.filtered(lambda row: row.account_id == self.cash)
        readonly = self.report.with_user(self._accountant()).with_context(
            allowed_company_ids=self.company.ids,
        )
        self.assertEqual(self._row(readonly.get_report(self.filters), self.cash)['debit'],
                         '25.00')
        for model, record in (
            ('account.move', move), ('account.journal', self.journal),
            ('account.account', self.cash),
        ):
            rule = self._hide(model, record)
            try:
                with self.assertRaises(AccessError):
                    readonly.get_report(self.filters)
                if model == 'account.account':
                    with self.assertRaises(AccessError):
                        readonly.with_context(lang='en_US').get_report(self.filters)
                with self.assertRaises(AccessError):
                    readonly.get_lines(self.filters, self.cash.id)
                with self.assertRaises(AccessError):
                    readonly.get_account_action(self.filters, self.cash.id)
                with self.assertRaises(AccessError):
                    readonly.get_source_line(self.filters, source.id)
            finally:
                rule.unlink()
        rule = self._hide('account.move.line', source)
        try:
            with self.assertRaises(AccessError):
                readonly.get_report(self.filters)
            with self.assertRaises(AccessError):
                readonly.get_rbf_accounts(self.filters)
            with self.assertRaises(AccessError):
                readonly.get_lines(self.filters, self.income.id)
            with self.assertRaises(AccessError):
                readonly.get_account_action(self.filters, self.income.id)
            with self.assertRaises(AccessError):
                readonly.get_source_line(self.filters, source.id)
        finally:
            rule.unlink()
        rule = self.env['ir.rule'].create({
            'name': 'GL hide balanced move',
            'model_id': self.env['ir.model']._get('account.move.line').id,
            'domain_force': f"[('id', 'not in', {move.line_ids.ids})]",
        })
        try:
            with self.assertRaises(AccessError):
                readonly.get_report(self.filters)
            with self.assertRaises(AccessError):
                readonly.get_rbf_accounts(self.filters)
            with self.assertRaises(AccessError):
                readonly.get_lines(self.filters, self.cash.id)
            with self.assertRaises(AccessError):
                readonly.get_account_action(self.filters, self.cash.id)
            with self.assertRaises(AccessError):
                readonly.get_source_line(self.filters, source.id)
        finally:
            rule.unlink()

    def test_explicit_link_fetch_rejects_field_without_read_access(self):
        self._entry('2041-03-05', self.cash, 25, 0, self.income)
        accountant = self._accountant()
        readonly = self.report.with_user(accountant).with_context(
            allowed_company_ids=self.company.ids,
        )
        aml_class = type(self.env['account.move.line'])
        original = aml_class._has_field_access

        def guarded(records, field, operation):
            if (records._name == 'account.move.line'
                    and records.env.uid == accountant.id
                    and field.name == 'journal_id' and operation == 'read'):
                return False
            return original(records, field, operation)

        with patch.object(aml_class, '_has_field_access', guarded):
            with self.assertRaises(AccessError):
                readonly.get_report(self.filters)

    def test_source_rejects_draft_outside_period_and_wrong_scope(self):
        draft = self._entry('2041-03-06', self.cash, 9, 0, self.income, posted=False)
        prior = self._entry('2040-12-31', self.cash, 8, 0, self.income)
        for move in (draft, prior):
            line = move.line_ids.filtered(lambda row: row.account_id == self.cash)
            with self.assertRaises(AccessError):
                self.report.get_source_line(self.filters, line.id)
        with self.assertRaises(AccessError):
            self.report.get_source_line(self.filters, prior.line_ids.filtered(
                lambda row: row.account_id == self.cash,
            ).id, 'rbf')
        with self.assertRaises(ValidationError):
            self.report.get_source_line(self.filters, True)
