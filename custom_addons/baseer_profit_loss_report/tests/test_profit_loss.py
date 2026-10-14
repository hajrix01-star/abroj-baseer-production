from datetime import date
from decimal import Decimal
from unittest.mock import patch

from lxml import html as lxml_html

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged

from ..models.profit_loss import BaseerProfitLossReport, SECTION_KEYS


@tagged('post_install', '-at_install')
class TestProfitLoss(TransactionCase):
    """Posted AML is the sole financial source for this period report."""

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.report = self.env['baseer.profit.loss.report']
        self.filters = {
            'company_id': self.company.id,
            'date_from': '2041-01-01',
            'date_to': '2041-12-31',
            'journal_ids': [],
        }
        Account = self.env['account.account'].with_company(self.company)
        self.accounts = {}
        for index, kind in enumerate(SECTION_KEYS, 1):
            account = Account.with_context(active_test=False).search([
                ('company_ids', 'in', self.company.id),
                ('account_type', '=', kind),
            ], limit=1)
            if not account:
                account = Account.create({
                    'code': f'9590{index:02d}', 'name': f'P&L {kind}',
                    'account_type': kind,
                    'company_ids': [Command.set(self.company.ids)],
                })
            self.accounts[kind] = account
        self.balance = Account.search([
            ('company_ids', 'in', self.company.id),
            ('account_type', '=', 'asset_current'),
            ('reconcile', '=', False),
        ], limit=1)
        self.journal = self.env['account.journal'].with_company(self.company).search([
            ('company_id', '=', self.company.id), ('type', '=', 'general'),
        ], limit=1)
        self.assertTrue(self.balance and self.journal)

    def _entry(self, kind, amount, day='2041-05-10', posted=True,
               journal=None, account=None):
        account = account or self.accounts[kind]
        amount = Decimal(str(amount))
        if amount >= 0:
            debit, credit = (amount, 0) if kind.startswith('expense') else (0, amount)
        else:
            debit, credit = (0, -amount) if kind.startswith('expense') else (-amount, 0)
        move = self.env['account.move'].with_company(self.company).create({
            'date': day, 'journal_id': (journal or self.journal).id,
            'move_type': 'entry',
            'line_ids': [
                Command.create({'name': 'P&L source', 'account_id': account.id,
                                'debit': float(debit), 'credit': float(credit)}),
                Command.create({'name': 'P&L balance', 'account_id': self.balance.id,
                                'debit': float(credit), 'credit': float(debit)}),
            ],
        })
        if posted:
            move._post(soft=False)
        return move

    def _section(self, result, kind):
        return next(row for row in result['sections'] if row['key'] == kind)

    def _accountant(self):
        return self.env['res.users'].create({
            'name': 'P&L readonly accountant', 'login': 'pl_readonly_accountant',
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_readonly').id,
            ])],
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
        })

    def _hide_record(self, model, record):
        """A global rule intersects other rules and reliably hides one record."""
        return self.env['ir.rule'].create({
            'name': f'P&L hide {model} {record.id}',
            'model_id': self.env['ir.model']._get(model).id,
            'domain_force': f"[('id', '!=', {record.id})]",
        })

    def test_financial_formula_filters_and_partial_journal(self):
        sale = self._entry('income', '200', day='2041-01-01')
        self._entry('income', '-20', day='2041-12-31')
        self._entry('income_other', '10')
        self._entry('expense_direct_cost', '60')
        self._entry('expense', '30')
        self._entry('expense_other', '4')
        self._entry('expense_depreciation', '5')
        self._entry('income', '999', posted=False)
        self._entry('income', '999', day='2040-12-31')
        self._entry('income', '999', day='2042-01-01')
        result = self.report.get_report(self.filters)
        self.assertEqual([row['key'] for row in result['sections']], list(SECTION_KEYS))
        self.assertEqual(self._section(result, 'income')['amount'], '180.00')
        self.assertEqual(self._section(result, 'income_other')['amount'], '10.00')
        self.assertEqual(self._section(result, 'expense_direct_cost')['amount'], '-60.00')
        self.assertEqual(self._section(result, 'expense')['amount'], '-30.00')
        self.assertEqual(self._section(result, 'expense_other')['amount'], '-4.00')
        self.assertEqual(self._section(result, 'expense_depreciation')['amount'], '-5.00')
        self.assertEqual(result['gross_profit']['amount'], '120.00')
        self.assertEqual(result['net_profit']['amount'], '91.00')
        sources = self.env['account.move.line'].search([
            ('company_id', '=', self.company.id),
            ('parent_state', '=', 'posted'),
            ('date', '>=', '2041-01-01'), ('date', '<=', '2041-12-31'),
            ('account_id', 'in', [account.id for account in self.accounts.values()]),
        ])
        expected = {key: Decimal('0') for key in SECTION_KEYS}
        for source in sources:
            signed = Decimal(str(source.debit)) - Decimal(str(source.credit))
            kind = source.account_id.account_type
            expected[kind] += signed if kind.startswith('expense') else -signed
        self.assertEqual(Decimal(result['net_profit']['amount']),
                         expected['income'] + expected['income_other']
                         - expected['expense_direct_cost'] - expected['expense']
                         - expected['expense_other']
                         - expected['expense_depreciation'])
        self.assertFalse(result['is_partial_journals'])
        self.assertEqual(self.report.get_accounts(self.filters, 'income')['total_amount'], '180.00')
        other = self.env['account.journal'].with_company(self.company).create({
            'name': 'P&L second general journal', 'code': 'PLX',
            'type': 'general', 'company_id': self.company.id,
        })
        self._entry('income', '15', journal=other)
        selected = {**self.filters, 'journal_ids': [other.id]}
        partial = self.report.get_report(selected)
        self.assertTrue(partial['is_partial_journals'])
        self.assertEqual(self._section(partial, 'income')['amount'], '15.00')
        self.assertEqual(partial['net_profit']['amount'], '15.00')
        self.assertEqual(self.report.get_accounts(selected, 'income')['total_amount'], '15.00')
        lines = self.report.get_lines(selected, self.accounts['income'].id)
        self.assertEqual((lines['total_count'], lines['total_amount']), (1, '15.00'))
        self.assertEqual(self.report.get_lines(selected, self.accounts['income'].id, 1)['lines'],
                         lines['lines'])
        self.assertEqual(lines['lines'][0]['move_id'],
                         self.env['account.move.line'].browse(lines['lines'][0]['id']).move_id.id)
        self.assertEqual(self.report.get_source_line(selected, lines['lines'][0]['id']), {
            'line_id': lines['lines'][0]['id'], 'move_id': lines['lines'][0]['move_id'],
        })
        action = self.report.get_account_action(selected, self.accounts['income'].id)
        self.assertEqual(action['res_model'], 'account.move.line')
        self.assertEqual(action['target'], 'current')
        self.assertIn(('company_id', '=', self.company.id), action['domain'])
        self.assertIn(('parent_state', '=', 'posted'), action['domain'])
        self.assertIn(('date', '>=', selected['date_from']), action['domain'])
        self.assertIn(('date', '<=', selected['date_to']), action['domain'])
        self.assertIn(('account_id', '=', self.accounts['income'].id), action['domain'])
        self.assertIn(('journal_id', 'in', [other.id]), action['domain'])
        with self.assertRaises(AccessError):
            self.report.get_source_line(selected, sale.line_ids.filtered(
                lambda line: line.account_id == self.accounts['income'],
            ).id)
        self.assertEqual(sale.date, date(2041, 1, 1))

    def test_posted_sale_and_purchase_invoices_exclude_vat_from_profit(self):
        Account = self.env['account.account'].with_company(self.company)
        receivable = Account.create({
            'code': '959101', 'name': 'P&L invoice receivable',
            'account_type': 'asset_receivable', 'reconcile': True,
            'company_ids': [Command.set(self.company.ids)],
        })
        payable = Account.create({
            'code': '959102', 'name': 'P&L bill payable',
            'account_type': 'liability_payable', 'reconcile': True,
            'company_ids': [Command.set(self.company.ids)],
        })
        vat_due = Account.create({
            'code': '959103', 'name': 'P&L output VAT',
            'account_type': 'liability_current',
            'company_ids': [Command.set(self.company.ids)],
        })
        vat_paid = Account.create({
            'code': '959104', 'name': 'P&L input VAT',
            'account_type': 'asset_current',
            'company_ids': [Command.set(self.company.ids)],
        })
        partner = self.env['res.partner'].with_company(self.company).create({
            'name': 'P&L invoice counterparty',
            'property_account_receivable_id': receivable.id,
            'property_account_payable_id': payable.id,
        })
        for move_type, journal_type, section, tax_use, vat_account in (
            ('out_invoice', 'sale', 'income', 'sale', vat_due),
            ('in_invoice', 'purchase', 'expense', 'purchase', vat_paid),
        ):
            journal = self.env['account.journal'].with_company(self.company).create({
                'name': f'P&L {journal_type} invoices',
                'code': 'PLI' if journal_type == 'sale' else 'PLB',
                'type': journal_type, 'company_id': self.company.id,
            })
            tax = self.env['account.tax'].with_company(self.company).create({
                'name': f'P&L {tax_use} VAT 15%', 'amount': 15,
                'amount_type': 'percent', 'type_tax_use': tax_use,
                'company_id': self.company.id,
            })
            tax.invoice_repartition_line_ids.filtered(
                lambda line: line.repartition_type == 'tax',
            ).write({'account_id': vat_account.id})
            move = self.env['account.move'].with_company(self.company).create({
                'move_type': move_type, 'partner_id': partner.id,
                'journal_id': journal.id, 'invoice_date': '2041-05-10',
                'invoice_line_ids': [Command.create({
                    'name': 'P&L taxable invoice line', 'quantity': 1,
                    'price_unit': 100, 'account_id': self.accounts[section].id,
                    'tax_ids': [Command.set(tax.ids)],
                })],
            })
            move.action_post()
            self.assertEqual(move.state, 'posted')
            self.assertEqual(Decimal(str(move.amount_total)), Decimal('115'))
        result = self.report.get_report(self.filters)
        self.assertEqual(self._section(result, 'income')['amount'], '100.00')
        self.assertEqual(self._section(result, 'expense')['amount'], '-100.00')
        self.assertEqual(result['net_profit']['amount'], '0.00')

    def test_empty_reversal_and_late_posting_changes_rerun(self):
        empty = self.report.get_report(self.filters)
        self.assertEqual(empty['net_profit']['amount'], '0.00')
        self.assertEqual(self.report.get_accounts(self.filters, 'income')['accounts'], [])
        self._entry('income', '10')
        self._entry('income', '-15')
        first = self.report.get_report(self.filters)
        self.assertEqual(first['net_profit']['amount'], '-5.00')
        self.assertTrue(first['net_profit']['negative'])
        self._entry('income', '8', day='2041-02-01')
        self.assertEqual(self.report.get_report(self.filters)['net_profit']['amount'], '3.00')

    def test_foreign_currency_amount_is_not_added_to_company_currency_profit(self):
        foreign = self.env['res.currency'].create({
            'name': 'PLF', 'symbol': 'PLF', 'rounding': 0.01, 'active': True,
        })
        move = self.env['account.move'].with_company(self.company).create({
            'date': '2041-05-10', 'journal_id': self.journal.id,
            'move_type': 'entry',
            'line_ids': [
                Command.create({
                    'name': 'Foreign currency revenue',
                    'account_id': self.accounts['income'].id,
                    'credit': 100, 'debit': 0,
                    'currency_id': foreign.id, 'amount_currency': -125,
                }),
                Command.create({
                    'name': 'Foreign currency balancing line',
                    'account_id': self.balance.id,
                    'credit': 0, 'debit': 100,
                    'currency_id': foreign.id, 'amount_currency': 125,
                }),
            ],
        })
        move._post(soft=False)
        result = self.report.get_report(self.filters)
        self.assertEqual(result['company']['currency_code'], self.company.currency_id.name)
        self.assertEqual(result['net_profit']['amount'], '100.00')
        self.assertEqual(self.report.get_accounts(self.filters, 'income')['total_amount'], '100.00')
        lines = self.report.get_lines(self.filters, self.accounts['income'].id)
        self.assertEqual(lines['lines'][0]['credit'], '100.00')
        self.assertEqual(lines['total_amount'], '100.00')

    def test_aml_rule_excludes_hidden_source_from_every_total(self):
        hidden_move = self._entry('income', '25')
        self._entry('income', '10')
        hidden = hidden_move.line_ids.filtered(
            lambda line: line.account_id == self.accounts['income'],
        )
        report = self.report.with_user(self._accountant()).with_context(
            allowed_company_ids=self.company.ids,
        )
        self._hide_record('account.move.line', hidden)
        self.assertEqual(report.get_report(self.filters)['net_profit']['amount'], '10.00')
        self.assertEqual(report.get_accounts(self.filters, 'income')['total_amount'], '10.00')
        lines = report.get_lines(self.filters, self.accounts['income'].id)
        self.assertEqual((lines['total_count'], lines['total_amount']), (1, '10.00'))
        self.assertNotIn(hidden.id, [line['id'] for line in lines['lines']])
        with self.assertRaises(AccessError):
            report.get_source_line(self.filters, hidden.id)

    def test_archived_account_and_pagination_total(self):
        original = self.accounts['income']
        self._entry('income', '7')
        original.active = False
        page = self.report.get_accounts(self.filters, 'income')
        self.assertEqual(page['total_amount'], '7.00')
        self.assertIn(original.id, [row['id'] for row in page['accounts']])
        with self.assertRaises(ValidationError):
            self.report.get_accounts(self.filters, 'income', page=0)
        self.assertEqual(self.report.get_accounts(self.filters, 'income', page=2)['accounts'], [])
        self.assertEqual(self.report.get_accounts(self.filters, 'income', page=2)['total_amount'], '7.00')
        self.assertEqual(self.report.get_lines(self.filters, original.id)['total_amount'], '7.00')
        with self.assertRaises(ValidationError):
            self.report.get_lines(self.filters, original.id, 0)

    def test_other_expense_refund_archived_and_journal_scope(self):
        account = self.accounts['expense_other']
        self._entry('expense_other', '10')
        self._entry('expense_other', '-2')
        account.active = False
        selected = {**self.filters, 'journal_ids': [self.journal.id]}
        result = self.report.get_report(selected)
        self.assertEqual(self._section(result, 'expense_other')['amount'], '-8.00')
        self.assertEqual(result['net_profit']['amount'], '-8.00')
        self.assertEqual(next(row for row in result['rows'] if row['key'] == 'other_expense')
                         ['amounts']['current']['amount'], '8.00')
        page = self.report.get_accounts(selected, 'expense_other')
        self.assertEqual(page['total_amount'], '8.00')
        self.assertEqual(page['accounts'][0]['id'], account.id)
        lines = self.report.get_lines(selected, account.id)
        self.assertEqual(lines['total_count'], 2)
        self.assertEqual(lines['total_amount'], '8.00')
        source = self.env['account.move.line'].with_context(active_test=False).search([
            ('company_id', '=', self.company.id),
            ('parent_state', '=', 'posted'),
            ('account_id', '=', account.id),
            ('journal_id', '=', self.journal.id),
            ('date', '>=', selected['date_from']),
            ('date', '<=', selected['date_to']),
        ])
        raw = sum((Decimal(str(row.debit)) - Decimal(str(row.credit)) for row in source), Decimal('0'))
        self.assertEqual(raw, Decimal('8'))

    def test_account_pages_do_not_change_section_total(self):
        extra = self.env['account.account'].with_company(self.company).create({
            'code': '959099', 'name': 'P&L second revenue',
            'account_type': 'income',
            'company_ids': [Command.set(self.company.ids)],
        })
        self._entry('income', '7')
        self._entry('income', '11', account=extra)
        with patch.object(BaseerProfitLossReport, 'PAGE_SIZE', 1):
            first = self.report.get_accounts(self.filters, 'income', 1)
            second = self.report.get_accounts(self.filters, 'income', 2)
        self.assertEqual(first['total_count'], 2)
        self.assertEqual((first['total_amount'], second['total_amount']), ('18.00', '18.00'))
        self.assertEqual(len(first['accounts']), 1)
        self.assertEqual(len(second['accounts']), 1)
        self.assertNotEqual(first['accounts'][0]['id'], second['accounts'][0]['id'])

    def test_company_journal_and_input_boundaries(self):
        other = self.env['res.company'].create({'name': 'P&L other company'})
        report = self.report.with_user(self._accountant())
        with self.assertRaises(AccessError):
            report.get_report({**self.filters, 'company_id': other.id})
        with self.assertRaises(AccessError):
            report.get_context(other.id)
        with self.assertRaises(AccessError):
            report.get_account_action({**self.filters, 'company_id': other.id},
                                      self.accounts['income'].id)
        with self.assertRaises(AccessError):
            report.get_account_action(self.filters, self.accounts['income'].id,
                                      period_key='not-a-period')
        with self.assertRaises(AccessError):
            self.report.get_report({**self.filters, 'journal_ids': [999999999]})
        for invalid in (
            {**self.filters, 'date_from': '2041-12-31', 'date_to': '2041-01-01'},
            {**self.filters, 'date_from': '2040-01-01', 'date_to': '2041-12-31'},
            {**self.filters, 'journal_ids': [True]},
            {**self.filters, 'journal_ids': [self.journal.id, self.journal.id]},
        ):
            with self.assertRaises(ValidationError):
                self.report.get_report(invalid)

    def test_pdf_uses_one_live_server_report_and_expected_a4_orientation(self):
        self._entry('income', '60')
        self._entry('expense_other', '4')
        portrait = self.env['report.baseer_profit_loss_report.profit_loss_pdf_portrait']
        with patch.object(BaseerProfitLossReport, 'get_report', side_effect=AssertionError('early financial read')):
            action = self.report.action_print(self.filters)
        self.assertEqual(action['report_name'], 'baseer_profit_loss_report.profit_loss_pdf_portrait')
        self.assertEqual(action['data'], {'filters': self.filters})
        values = portrait._get_report_values([], action['data'])
        expected = self.report.get_report(self.filters)
        self.assertEqual([row['key'] for row in values['rows']], [row['key'] for row in expected['rows']])
        self.assertEqual(values['rows'][-1]['amounts']['current']['amount'], '56.00')
        self.assertEqual(len(values['periods']), 1)
        self.assertEqual(self.env.ref('baseer_profit_loss_report.action_profit_loss_pdf_portrait').paperformat_id.orientation, 'Portrait')
        html, _output_type = self.env['ir.actions.report']._render_qweb_html(
            'baseer_profit_loss_report.profit_loss_pdf_portrait', docids=[],
            data={'filters': self.filters},
        )
        self.assertIn(b'56.00', html)
        document = lxml_html.fromstring(html)
        printed_rows = document.xpath("//div[contains(@class, 'bpl-pdf')]//table/tbody/tr")
        summary_rows = [row for row in printed_rows if row.get('class') not in ('account', 'channel')]
        self.assertEqual(len(summary_rows), 9)
        self.assertTrue(document.xpath("//tr[@class='channel']"))
        for account in values['revenue_accounts']['income']:
            self.assertEqual(sum(Decimal(channel['amounts']['current']['amount'].replace(',', ''))
                                 for channel in account['channels']),
                             Decimal(account['amounts']['current']['amount'].replace(',', '')))
        self.assertTrue(all(len(row.xpath('./td')) == 1 for row in printed_rows))

        compared = {
            'company_id': self.company.id, 'journal_ids': [self.journal.id],
            'period': {'kind': 'month', 'anchor_date': '2041-05-15', 'direction': 0},
            'comparison': {'kind': 'previous_periods', 'count': 3, 'order': 'descending'},
        }
        action = self.report.action_print(compared)
        self.assertEqual(action['report_name'], 'baseer_profit_loss_report.profit_loss_pdf_landscape')
        values = self.env['report.baseer_profit_loss_report.profit_loss_pdf_landscape']._get_report_values([], action['data'])
        self.assertEqual(len(values['periods']), 4)
        self.assertEqual(values['rows'][-1]['amounts']['current']['amount'], '56.00')
        self.assertTrue(values['journal_names'])
        self.assertEqual(self.env.ref('baseer_profit_loss_report.action_profit_loss_pdf_landscape').paperformat_id.orientation, 'Landscape')
        html, _output_type = self.env['ir.actions.report']._render_qweb_html(
            'baseer_profit_loss_report.profit_loss_pdf_landscape', docids=[],
            data={'filters': compared},
        )
        document = lxml_html.fromstring(html)
        printed_rows = document.xpath("//div[contains(@class, 'bpl-pdf')]//table/tbody/tr")
        summary_rows = [row for row in printed_rows if row.get('class') not in ('account', 'channel')]
        self.assertEqual(len(summary_rows), 9)
        self.assertTrue(all(len(row.xpath('./td')) == 4 for row in printed_rows))
        self.assertIn(b'56.00', html)

    def test_pdf_direct_render_rechecks_active_company_and_accounting_rights(self):
        portrait = self.env['report.baseer_profit_loss_report.profit_loss_pdf_portrait']
        for data in (None, {}, {'filters': []}):
            with self.assertRaises(ValidationError):
                portrait._get_report_values([], data)
        with self.assertRaises(AccessError):
            portrait._get_report_values([], {'filters': {'company_id': True}})
        other = self.env['res.company'].create({'name': 'P&L PDF other company'})
        accountant = self._accountant()
        accountant.company_ids = [Command.link(other.id)]
        allowed = portrait.with_user(accountant).with_context(allowed_company_ids=[self.company.id, other.id])
        with self.assertRaises(AccessError):
            allowed._get_report_values([], {'filters': {**self.filters, 'company_id': other.id}})
        with self.assertRaises(AccessError):
            self.env['ir.actions.report'].with_user(accountant).with_context(
                allowed_company_ids=[self.company.id, other.id],
            )._render_qweb_html('baseer_profit_loss_report.profit_loss_pdf_portrait',
                docids=[], data={'filters': {**self.filters, 'company_id': other.id}})
        other_context = allowed.with_context(allowed_company_ids=[other.id, self.company.id])
        other_filters = {**self.filters, 'company_id': other.id}
        self.assertEqual(other_context._get_report_values([], {'filters': other_filters})['report']['company']['id'], other.id)
        internal = self.env['res.users'].create({
            'name': 'P&L PDF internal', 'login': 'pl_pdf_internal',
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
        })
        with self.assertRaises(AccessError):
            portrait.with_user(internal)._get_report_values([], {'filters': self.filters})
        with self.assertRaises(AccessError):
            self.env['ir.actions.report'].with_user(internal)._render_qweb_html(
                'baseer_profit_loss_report.profit_loss_pdf_portrait', docids=[],
                data={'filters': self.filters},
            )
        move = self._entry('income', '25')
        rule = self._hide_record('account.move', move)
        try:
            with self.assertRaises(AccessError):
                portrait.with_user(accountant)._get_report_values([], {'filters': self.filters})
        finally:
            rule.unlink()

    def test_source_line_rejects_draft_and_outside_period(self):
        draft = self._entry('income', '9', posted=False)
        outside = self._entry('income', '11', day='2040-12-31')
        for move in (draft, outside):
            line = move.line_ids.filtered(
                lambda item: item.account_id == self.accounts['income'],
            )
            with self.assertRaises(AccessError):
                self.report.get_source_line(self.filters, line.id)
        with self.assertRaises(ValidationError):
            self.report.get_source_line(self.filters, True)

    def test_non_accountant_cannot_call_any_entrypoint(self):
        user = self.env['res.users'].create({
            'name': 'P&L internal', 'login': 'pl_internal',
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
        })
        report = self.report.with_user(user).with_context(allowed_company_ids=self.company.ids)
        with self.assertRaises(AccessError):
            report.get_context()
        with self.assertRaises(AccessError):
            report.get_report(self.filters)
        with self.assertRaises(AccessError):
            report.get_accounts(self.filters, 'income')
        with self.assertRaises(AccessError):
            report.get_lines(self.filters, self.accounts['income'].id)
        with self.assertRaises(AccessError):
            report.get_account_action(self.filters, self.accounts['income'].id)
        with self.assertRaises(AccessError):
            report.get_source_line(self.filters, 1)

    def test_linked_record_rules_fail_closed_for_totals_and_accounts(self):
        move = self._entry('income', '25')
        source_line = move.line_ids.filtered(
            lambda line: line.account_id == self.accounts['income'],
        )
        user = self._accountant()
        report = self.report.with_user(user).with_context(allowed_company_ids=self.company.ids)
        self.assertEqual(report.get_report(self.filters)['net_profit']['amount'], '25.00')
        for model, record in (
            ('account.move', move),
            ('account.journal', self.journal),
            ('account.account', self.accounts['income']),
        ):
            rule = self._hide_record(model, record)
            try:
                with self.assertRaises(AccessError):
                    report.get_report(self.filters)
                with self.assertRaises(AccessError):
                    report.get_accounts(self.filters, 'income')
                with self.assertRaises(AccessError):
                    report.get_lines(self.filters, self.accounts['income'].id)
                with self.assertRaises(AccessError):
                    report.get_account_action(self.filters, self.accounts['income'].id)
                with self.assertRaises(AccessError):
                    report.get_source_line(self.filters, source_line.id)
            finally:
                rule.unlink()

    def test_grouped_sums_stay_consistent_across_api_pages(self):
        self._entry('income', '0.10')
        self._entry('income', '0.20')
        self._entry('income', '1234567890123.45')
        report = self.report.get_report(self.filters)
        accounts = self.report.get_accounts(self.filters, 'income')
        lines = self.report.get_lines(self.filters, self.accounts['income'].id)
        self.assertEqual(self._section(report, 'income')['amount'], '1,234,567,890,123.75')
        self.assertEqual(accounts['total_amount'], '1,234,567,890,123.75')
        self.assertEqual(lines['total_amount'], '1,234,567,890,123.75')
        self.assertEqual(lines['total_count'], 3)

    def test_unrounded_source_and_currency_precision(self):
        # Formatter is shared by totals and accounts, and only rounds at output.
        currency = self.company.currency_id
        self.assertEqual(BaseerProfitLossReport._format_money(Decimal('0.005')
                          + Decimal('0.005'), currency), '0.01')
        three_place = self.env['res.currency'].create({
            'name': 'PL3', 'symbol': 'PL3', 'rounding': 0.001, 'active': True,
        })
        self.assertEqual(BaseerProfitLossReport._format_money(Decimal('1.2345'),
                          three_place), '1.235')

    def test_server_resolves_month_quarter_fiscal_and_previous_periods(self):
        self._entry('income', '10', day='2041-01-10')
        self._entry('income', '7', day='2040-12-10')
        month = {
            'company_id': self.company.id,
            'journal_ids': [],
            'period': {'kind': 'month', 'anchor_date': '2041-01-15', 'direction': 0},
            'comparison': {'kind': 'previous_period', 'count': 1, 'order': 'descending'},
        }
        result = self.report.get_report(month)
        self.assertEqual([(period['key'], period['date_from'], period['date_to'])
                          for period in result['periods']], [
            ('current', '2041-01-01', '2041-01-31'),
            ('previous_1', '2040-12-01', '2040-12-31'),
        ])
        net_income = next(row for row in result['rows'] if row['key'] == 'net_income')
        self.assertEqual(net_income['amounts']['current']['amount'], '10.00')
        self.assertEqual(net_income['amounts']['previous_1']['amount'], '7.00')
        self.assertEqual(result['period_controls']['anchor_date'], '2041-01-15')
        self.assertEqual(result['periods'][0]['display_label'], 'January 2041')
        self.assertEqual(result['periods'][1]['display_label'], 'December 2040')
        self.assertEqual(result['period_controls']['options'], [
            {'kind': 'month', 'display_label': 'January 2041'},
            {'kind': 'quarter', 'display_label': 'Q1 2041'},
            {'kind': 'fiscal_year', 'display_label': '2041'},
            {'kind': 'custom', 'display_label': 'Custom Dates'},
        ])
        previous = self.report.get_report({
            **month, 'period': {**month['period'], 'direction': -1},
        })
        self.assertEqual(previous['period']['date_from'], '2040-12-01')
        quarter = self.report.get_report({
            **month, 'period': {'kind': 'quarter', 'anchor_date': '2041-05-15', 'direction': 0},
            'comparison': {'kind': 'none', 'order': 'descending'},
        })
        self.assertEqual(quarter['period'], {'date_from': '2041-04-01', 'date_to': '2041-06-30'})
        fiscal = self.report.get_report({
            **month, 'period': {'kind': 'fiscal_year', 'anchor_date': '2041-05-15', 'direction': 0},
            'comparison': {'kind': 'none', 'order': 'descending'},
        })
        expected_fiscal = self.company.compute_fiscalyear_dates(date(2041, 5, 15))
        self.assertEqual(fiscal['period'], {
            'date_from': str(expected_fiscal['date_from']),
            'date_to': str(expected_fiscal['date_to']),
        })

    def test_summary_rows_keep_all_financial_details_without_duplicate_totals(self):
        result = self.report.get_report({
            'company_id': self.company.id,
            'journal_ids': [],
            'period': {'kind': 'month', 'anchor_date': '2041-05-15', 'direction': 0},
            'comparison': {'kind': 'none', 'order': 'descending'},
        })
        rows = {row['key']: row for row in result['rows']}
        self.assertNotIn('total_income', rows)
        self.assertNotIn('total_expense', rows)
        self.assertEqual(rows['income']['kind'], 'section')
        self.assertEqual(rows['expense']['kind'], 'section')
        self.assertEqual(rows['net_income']['kind'], 'result')
        for key, section in (
            ('cost_of_sales', 'expense_direct_cost'),
            ('other_income', 'income_other'),
            ('other_expense', 'expense_other'),
        ):
            self.assertEqual(rows[key]['kind'], 'detail')
            self.assertTrue(rows[key]['expandable'])
            self.assertEqual(rows[key]['section'], section)

    def test_comparison_accounts_are_a_union_and_details_are_period_scoped(self):
        previous_account = self.env['account.account'].with_company(self.company).create({
            'code': '959199', 'name': 'P&L comparison-only income',
            'account_type': 'income', 'company_ids': [Command.set(self.company.ids)],
        })
        self._entry('income', '11', day='2041-01-10')
        previous_move = self._entry('income', '7', day='2040-12-10', account=previous_account)
        filters = {
            'company_id': self.company.id,
            'journal_ids': [],
            'period': {'kind': 'month', 'anchor_date': '2041-01-15', 'direction': 0},
            'comparison': {'kind': 'previous_period', 'count': 1, 'order': 'descending'},
        }
        accounts = self.report.get_accounts(filters, 'income')
        by_id = {account['id']: account for account in accounts['accounts']}
        self.assertEqual(set(by_id), {self.accounts['income'].id, previous_account.id})
        self.assertEqual(by_id[self.accounts['income'].id]['amounts']['current']['amount'], '11.00')
        self.assertEqual(by_id[self.accounts['income'].id]['amounts']['previous_1']['amount'], '0.00')
        self.assertEqual(by_id[previous_account.id]['amounts']['current']['amount'], '0.00')
        self.assertEqual(by_id[previous_account.id]['amounts']['previous_1']['amount'], '7.00')
        source_line = previous_move.line_ids.filtered(
            lambda line: line.account_id == previous_account,
        )
        lines = self.report.get_lines(filters, previous_account.id, period_key='previous_1')
        self.assertEqual(lines['period_key'], 'previous_1')
        self.assertEqual((lines['total_count'], lines['total_amount']), (1, '7.00'))
        self.assertEqual(self.report.get_source_line(filters, source_line.id, 'previous_1'), {
            'line_id': source_line.id, 'move_id': previous_move.id,
        })
        with self.assertRaises(AccessError):
            self.report.get_lines(filters, previous_account.id, period_key='unknown')
        with self.assertRaises(AccessError):
            self.report.get_source_line(filters, source_line.id, 'current')

    def test_last_year_and_custom_comparisons_are_calculated_on_the_server(self):
        self._entry('income', '29', day='2040-02-29')
        self._entry('income', '31', day='2041-02-28')
        last_year = self.report.get_report({
            'company_id': self.company.id,
            'journal_ids': [],
            'period': {'kind': 'custom', 'date_from': '2041-02-28', 'date_to': '2041-02-28'},
            'comparison': {'kind': 'same_period_last_year', 'order': 'descending'},
        })
        self.assertEqual(last_year['periods'][1]['date_from'], '2040-02-28')
        self.assertEqual(last_year['periods'][1]['date_to'], '2040-02-28')
        custom = self.report.get_report({
            'company_id': self.company.id,
            'journal_ids': [],
            'period': {'kind': 'custom', 'date_from': '2041-02-28', 'date_to': '2041-02-28'},
            'comparison': {
                'kind': 'custom', 'date_from': '2040-02-29', 'date_to': '2040-02-29',
                'order': 'descending',
            },
        })
        net_income = next(row for row in custom['rows'] if row['key'] == 'net_income')
        self.assertEqual(net_income['amounts']['current']['amount'], '31.00')
        self.assertEqual(net_income['amounts']['custom']['amount'], '29.00')

    def test_custom_previous_periods_use_inclusive_non_overlapping_boundaries(self):
        def periods(date_from, date_to):
            result = self.report.get_report({
                'company_id': self.company.id,
                'journal_ids': [],
                'period': {'kind': 'custom', 'date_from': date_from, 'date_to': date_to},
                'comparison': {
                    'kind': 'previous_periods', 'count': 3, 'order': 'descending',
                },
            })
            return [(period['date_from'], period['date_to']) for period in result['periods']]

        self.assertEqual(periods('2041-01-10', '2041-01-10'), [
            ('2041-01-10', '2041-01-10'),
            ('2041-01-09', '2041-01-09'),
            ('2041-01-08', '2041-01-08'),
            ('2041-01-07', '2041-01-07'),
        ])
        multi_day = periods('2041-01-10', '2041-01-12')
        self.assertEqual(multi_day, [
            ('2041-01-10', '2041-01-12'),
            ('2041-01-07', '2041-01-09'),
            ('2041-01-04', '2041-01-06'),
            ('2041-01-01', '2041-01-03'),
        ])
        parsed = [(date.fromisoformat(start), date.fromisoformat(end))
                  for start, end in multi_day]
        self.assertTrue(all(next_end < previous_start for
                            (_next_start, next_end), (previous_start, _previous_end)
                            in zip(parsed[1:], parsed)))

    def test_expense_row_accounts_and_details_include_depreciation_naturally(self):
        depreciation = self.accounts['expense_depreciation']
        self._entry('expense', '30')
        depreciation_move = self._entry('expense_depreciation', '5')
        filters = {
            'company_id': self.company.id,
            'journal_ids': [],
            'period': {'kind': 'month', 'anchor_date': '2041-05-15', 'direction': 0},
            'comparison': {'kind': 'none', 'order': 'descending'},
        }
        result = self.report.get_report(filters)
        expense = next(row for row in result['rows'] if row['key'] == 'expense')
        self.assertEqual(result['periods'][0]['role'], 'primary')
        self.assertEqual(expense['amounts']['current']['amount'], '35.00')
        accounts = self.report.get_accounts(filters, 'expense')
        by_id = {account['id']: account for account in accounts['accounts']}
        self.assertEqual(by_id[depreciation.id]['amounts']['current']['amount'], '5.00')
        self.assertEqual(by_id[depreciation.id]['move_line_counts']['current'], 1)
        lines = self.report.get_lines(filters, depreciation.id)
        self.assertEqual(lines['total_amount'], '5.00')
        self.assertEqual(lines['lines'][0]['amount'], '5.00')
        source = depreciation_move.line_ids.filtered(lambda line: line.account_id == depreciation)
        self.assertEqual(self.report.get_source_line(filters, source.id), {
            'line_id': source.id, 'move_id': depreciation_move.id,
        })
