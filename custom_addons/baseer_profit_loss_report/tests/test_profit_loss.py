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
        dashboard = result['dashboard']
        self.assertEqual([card['key'] for card in dashboard['cards']], [
            'income', 'cost_of_sales', 'gross_profit', 'gross_margin', 'expense', 'net_income',
        ])
        dashboard_cards = {card['key']: card for card in dashboard['cards']}
        self.assertEqual(dashboard_cards['income']['value']['amount'], '180.00')
        self.assertEqual(dashboard_cards['cost_of_sales']['value']['amount'], '60.00')
        self.assertEqual(dashboard_cards['gross_profit']['value']['amount'], '120.00')
        self.assertEqual(dashboard_cards['gross_margin']['value']['display'], '66.67%')
        self.assertEqual(dashboard_cards['expense']['value']['amount'], '35.00')
        self.assertEqual(dashboard_cards['net_income']['value']['amount'], '91.00')
        self.assertEqual([step['key'] for step in dashboard['waterfall']], [
            'income', 'cost_of_sales', 'expense', 'net_other_income', 'net_income',
        ])
        self.assertEqual(dashboard['waterfall'][3]['amount']['amount'], '6.00')
        shares = {account['amount']['amount']: account['share']['display']
                  for account in dashboard['revenue_accounts']}
        self.assertEqual(shares['180.00'], '94.74%')
        self.assertEqual(shares['10.00'], '5.26%')
        self.assertIn('posted_only', dashboard['notes'])
        self.assertIn('comparison_unavailable', dashboard['notes'])
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
            tax.refund_repartition_line_ids.filtered(
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
        result = self.report.get_report({**self.filters, 'tax_inclusive': False})
        self.assertEqual(self._section(result, 'income')['amount'], '100.00')
        self.assertEqual(self._section(result, 'expense')['amount'], '-100.00')
        self.assertEqual(result['net_profit']['amount'], '0.00')
        inclusive = self.report.get_report(self.filters)
        self.assertEqual(self._section(inclusive, 'income')['amount'], '115.00')
        self.assertEqual(self._section(inclusive, 'expense')['amount'], '-115.00')
        self.assertEqual(inclusive['net_profit']['amount'], '0.00')
        income = self.report.get_accounts(self.filters, 'income')
        self.assertEqual(income['total_amount'], '115.00')
        lines = self.report.get_lines(self.filters, self.accounts['income'].id)
        self.assertEqual(lines['total_amount'], '115.00')
        self.assertEqual(lines['lines'][0]['amount'], '115.00')
        sale_journal = self.env['account.journal'].search([('company_id', '=', self.company.id), ('code', '=', 'PLI')])
        sale_tax = self.env['account.tax'].search([('company_id', '=', self.company.id), ('name', '=', 'P&L sale VAT 15%')])
        other_tax = self.env['account.tax'].with_company(self.company).create({
            'name': 'P&L second sales tax', 'amount': 5, 'type_tax_use': 'sale', 'company_id': self.company.id,
        })
        other_tax.invoice_repartition_line_ids.filtered(lambda line: line.repartition_type == 'tax').write({'account_id': vat_due.id})
        split = self.env['account.move'].with_company(self.company).create({
            'move_type': 'out_invoice', 'partner_id': partner.id, 'journal_id': sale_journal.id,
            'invoice_date': '2041-05-10', 'invoice_line_ids': [
                Command.create({'name': 'First tax', 'quantity': 1, 'price_unit': 100,
                                'account_id': self.accounts['income'].id, 'tax_ids': [Command.set(sale_tax.ids)]}),
                Command.create({'name': 'Second tax', 'quantity': 1, 'price_unit': 50,
                                'account_id': self.accounts['income_other'].id, 'tax_ids': [Command.set(other_tax.ids)]}),
            ],
        })
        split.action_post()
        proved = self.report.get_report(self.filters)
        self.assertEqual(self._section(proved, 'income')['amount'], '230.00')
        self.assertEqual(self._section(proved, 'income_other')['amount'], '52.50')
        ambiguous = self.env['account.move'].with_company(self.company).create({
            'move_type': 'out_invoice', 'partner_id': partner.id, 'journal_id': sale_journal.id,
            'invoice_date': '2041-05-10', 'invoice_line_ids': [
            Command.create({'name': 'First', 'quantity': 1, 'price_unit': 100, 'discount': 10,
                            'account_id': self.accounts['income'].id, 'tax_ids': [Command.set(sale_tax.ids)]}),
            Command.create({'name': 'Second', 'quantity': 1, 'price_unit': 50,
                            'account_id': self.accounts['income_other'].id, 'tax_ids': [Command.set(sale_tax.ids)]})]})
        ambiguous.action_post()
        shared = self.report.get_report(self.filters)
        self.assertEqual(self._section(shared, 'income')['amount'], '333.50')
        self.assertEqual(self._section(shared, 'income_other')['amount'], '110.00')
        refund = self.env['account.move'].with_company(self.company).create({
            'move_type': 'out_refund', 'partner_id': partner.id, 'journal_id': sale_journal.id,
            'invoice_date': '2041-05-10', 'invoice_line_ids': [
                Command.create({'name': 'First refund', 'quantity': 1, 'price_unit': 100, 'discount': 10,
                                'account_id': self.accounts['income'].id, 'tax_ids': [Command.set(sale_tax.ids)]}),
                Command.create({'name': 'Second refund', 'quantity': 1, 'price_unit': 50,
                                'account_id': self.accounts['income_other'].id, 'tax_ids': [Command.set(sale_tax.ids)]}),
            ],
        })
        refund.action_post()
        reconciled = self.report.get_report(self.filters)
        self.assertEqual(self._section(reconciled, 'income')['amount'], '230.00')
        self.assertEqual(self._section(reconciled, 'income_other')['amount'], '52.50')
        rounded = self.env['account.move'].with_company(self.company).create({
            'move_type': 'out_invoice', 'partner_id': partner.id, 'journal_id': sale_journal.id,
            'invoice_date': '2041-05-10', 'invoice_line_ids': [
                Command.create({'name': 'Small first', 'quantity': 1, 'price_unit': 0.03,
                                'account_id': self.accounts['income'].id, 'tax_ids': [Command.set(sale_tax.ids)]}),
                Command.create({'name': 'Small second', 'quantity': 1, 'price_unit': 0.04,
                                'account_id': self.accounts['income_other'].id, 'tax_ids': [Command.set(sale_tax.ids)]}),
            ],
        })
        rounded.action_post()
        reconciled = self.report.get_report(self.filters)
        self.assertEqual(self._section(reconciled, 'income')['amount'], '230.03')
        self.assertEqual(self._section(reconciled, 'income_other')['amount'], '52.55')
        zero_tax = self.env['account.tax'].with_company(self.company).create({
            'name': 'P&L zero tax', 'amount': 0, 'type_tax_use': 'sale', 'company_id': self.company.id,
        })
        for amount, account in ((10, self.accounts['income']), (30, self.accounts['income_other'])):
            mixed = self.env['account.move'].with_company(self.company).create({
                'move_type': 'out_invoice', 'partner_id': partner.id, 'journal_id': sale_journal.id,
                'invoice_date': '2041-05-10', 'invoice_line_ids': [
                    Command.create({'name': 'Taxable', 'quantity': 1, 'price_unit': 10,
                                    'account_id': self.accounts['income'].id, 'tax_ids': [Command.set(sale_tax.ids)]}),
                    Command.create({'name': 'Zero tax', 'quantity': 1, 'price_unit': amount,
                                    'account_id': account.id, 'tax_ids': [Command.set(zero_tax.ids)]}),
                ],
            })
            mixed.action_post()
        mixed_report = self.report.get_report(self.filters)
        self.assertEqual(self._section(mixed_report, 'income')['amount'], '263.03')
        self.assertEqual(self._section(mixed_report, 'income_other')['amount'], '82.55')
        self.report.get_report({**self.filters, 'tax_inclusive': False})

    def test_noorix_original_gross_channels_reconcile_to_posted_entry(self):
        if 'baseer.noorix.sales.evidence' not in self.env:
            self.skipTest('Noorix reader is optional in the profit and loss module')
        sar = self.env.ref('base.SAR')
        sar.active = True
        self.company.currency_id = sar
        Account = self.env['account.account'].with_company(self.company)
        funding = Account.create({'code': '959107', 'name': 'Noorix cash',
                                  'account_type': 'asset_current', 'company_ids': [Command.set(self.company.ids)]})
        vat = Account.create({'code': '959108', 'name': 'Noorix VAT',
                              'account_type': 'liability_current', 'company_ids': [Command.set(self.company.ids)]})
        tag = self.env['account.account.tag'].create({'name': '+Noorix test VAT', 'applicability': 'taxes',
                                                      'country_id': self.company.account_fiscal_country_id.id})
        self.env['account.tax'].with_company(self.company).create({
            'name': 'Noorix test tax', 'amount': 15, 'type_tax_use': 'sale', 'company_id': self.company.id,
            'invoice_repartition_line_ids': [Command.clear(), Command.create({'repartition_type': 'base'}),
                Command.create({'repartition_type': 'tax', 'account_id': vat.id, 'tag_ids': [Command.set(tag.ids)]})],
        })
        move = self.env['account.move'].with_company(self.company).create({
            'date': '2041-05-10', 'journal_id': self.journal.id, 'move_type': 'entry',
            'ref': 'NOORIX-SALES SHAMI 2041-05-10 | src:synthetic-1',
            'line_ids': [
                Command.create({'name': 'Noorix sales cash 2041-05-10', 'account_id': funding.id, 'debit': 115}),
                Command.create({'name': 'Noorix sales', 'account_id': self.accounts['income'].id, 'credit': 100}),
                Command.create({'name': 'Noorix VAT', 'account_id': vat.id, 'credit': 15,
                                'tax_tag_ids': [Command.set(tag.ids)]}),
            ],
        })
        move.action_post()
        current = self.report.get_report(self.filters)
        self.assertEqual(self._section(current, 'income')['amount'], '115.00')
        accounts = self.report.get_accounts(self.filters, 'income')['accounts']
        account = next(row for row in accounts if row['id'] == self.accounts['income'].id)
        self.assertEqual(account['amounts']['current']['amount'], '115.00')
        self.assertEqual(sum(Decimal(row['amounts']['current']['amount'].replace(',', ''))
                             for row in account['channels']), Decimal('115.00'))
        channel = next(row for row in account['channels'] if row['key'] == 'noorix_cash')
        self.assertEqual(channel['amounts']['current']['amount'], '115.00')
        selector = {'kind': 'channel', 'account_id': self.accounts['income'].id,
                    'channel_key': 'noorix_cash', 'period_key': 'current'}
        drilled = self.report._get_drilldown(self.filters, selector)
        self.assertEqual(drilled['value'], '115.00')
        self.assertEqual(drilled['total_count'], 1)
        self.assertEqual(drilled['rows'][0]['cells']['amount'], '115.00')
        self.assertEqual(self.report._open_drill_source(self.filters, drilled['rows'][0]['source'])['res_id'], move.id)
        document = self.report._get_export_document(self.filters)
        exported = [row for row in document['rows'] if row.get('indent') == 2]
        self.assertEqual(len(exported), 1)
        self.assertEqual(exported[0]['cells']['current'], Decimal('115.00'))
        self.assertEqual(self._section(self.report.get_report({**self.filters, 'tax_inclusive': False}),
                                       'income')['amount'], '100.00')
        untaxed = self.env['account.move'].with_company(self.company).create({
            'date': '2041-05-11', 'journal_id': self.journal.id, 'move_type': 'entry',
            'ref': 'NOORIX-SALES SHAMI 2041-05-11 | src:untaxed-1',
            'line_ids': [
                Command.create({'name': 'Noorix sales cash 2041-05-11', 'account_id': funding.id, 'debit': 20}),
                Command.create({'name': 'Noorix sales', 'account_id': self.accounts['income'].id, 'credit': 20}),
            ],
        })
        untaxed.action_post()
        account = next(row for row in self.report.get_accounts(self.filters, 'income')['accounts']
                       if row['id'] == self.accounts['income'].id)
        self.assertEqual(next(row for row in account['channels'] if row['key'] == 'noorix_cash')
                         ['amounts']['current']['amount'], '135.00')
        other_journal = self.env['account.journal'].with_company(self.company).create({
            'name': 'Other Noorix journal', 'code': 'NRO', 'type': 'general', 'company_id': self.company.id,
        })
        unrelated = self._entry('income', '10', journal=other_journal)
        unrelated.ref = 'NOORIX-SALES invalid unrelated source'
        filtered = {**self.filters, 'journal_ids': [self.journal.id]}
        self.assertEqual(self._section(self.report.get_report(filtered), 'income')['amount'], '135.00')
        prefix = move.copy(default={'journal_id': other_journal.id,
                                    'ref': 'NOORIX-SALES SHAMI 2041-05-10 | src:synthetic-12'})
        prefix.action_post()
        rule = self._hide_record('account.move', prefix)
        try:
            user_report = self.report.with_user(self._accountant()).with_context(allowed_company_ids=self.company.ids)
            self.assertEqual(self._section(user_report.get_report(filtered), 'income')['amount'], '135.00')
        finally:
            rule.unlink()
        hidden_tax_move = self.env['account.move'].with_company(self.company).create({
            'date': '2041-05-12', 'journal_id': other_journal.id, 'move_type': 'entry',
            'ref': 'NOORIX-SALES SHAMI 2041-05-12 | src:hidden-tax-1',
            'line_ids': [
                Command.create({'name': 'Noorix sales cash 2041-05-12', 'account_id': funding.id, 'debit': 21}),
                Command.create({'name': 'Noorix sales', 'account_id': self.accounts['income'].id, 'credit': 20}),
                Command.create({'name': 'Noorix VAT', 'account_id': vat.id, 'credit': 1,
                                'tax_tag_ids': [Command.set(tag.ids)]}),
            ],
        })
        hidden_tax_move.action_post()
        rule = self._hide_record('account.move.line', hidden_tax_move.line_ids.filtered(lambda line: line.account_id == vat))
        try:
            with self.assertRaises(AccessError):
                user_report.get_report({**self.filters, 'journal_ids': [other_journal.id]})
        finally:
            rule.unlink()
        duplicate = move.copy(default={'journal_id': other_journal.id, 'ref': move.ref})
        duplicate.action_post()
        with self.assertRaises(ValidationError):
            self.report.get_report(filtered)
        rule = self._hide_record('account.move', duplicate)
        try:
            with self.assertRaises(AccessError):
                user_report.get_report(filtered)
        finally:
            rule.unlink()

    def test_explicit_noorix_mapping_groups_with_native_pos_and_keeps_sources(self):
        if 'baseer.noorix.sales.evidence' not in self.env or 'pos.order' not in self.env:
            self.skipTest('Optional Noorix and POS sources are unavailable')
        from .test_unified_export import TestUnifiedExport
        sar = self.env.ref('base.SAR')
        sar.active = True
        self.company.currency_id = sar
        self.cash = self.env['account.account'].create({
            'code': '959118', 'name': 'Native POS cash', 'account_type': 'asset_cash',
            'company_ids': [Command.set(self.company.ids)],
        })
        self.income = self.accounts['income']
        orders, pos_move, _reader = TestUnifiedExport._native_channel_orders(self, count=1)
        method = orders.payment_ids.payment_method_id
        self.env['baseer.pl.noorix.channel.mapping'].create({
            'company_id': self.company.id, 'source_channel': 'cash', 'payment_method_id': method.id,
            'date_from': '2044-10-01', 'date_to': '2044-10-31', 'approval_reference': 'Synthetic approval',
        })
        noorix = self.env['account.move'].with_company(self.company).create({
            'date': '2044-10-19', 'journal_id': self.journal.id,
            'ref': 'NOORIX-SALES SHAMI 2044-10-19 | src:group-fixture',
            'line_ids': [
                Command.create({'name': 'Noorix sales cash 2044-10-19', 'account_id': self.cash.id, 'debit': 20}),
                Command.create({'name': 'Noorix sales', 'account_id': self.income.id, 'credit': 20}),
            ],
        })
        noorix.action_post()
        filters = {**self.filters, 'date_from': '2044-10-01', 'date_to': '2044-10-31', 'tax_inclusive': True}
        details = self.report.get_accounts(filters, 'income')['accounts']
        account = next(row for row in details if row['id'] == self.income.id)
        channel_key = 'payment_' + str(method.id)
        self.assertEqual([(row['key'], row['amounts']['current']['amount']) for row in account['channels']],
                         [(channel_key, '120.00')])
        selector = {'kind': 'channel', 'account_id': self.income.id,
                    'channel_key': channel_key, 'period_key': 'current'}
        drilled = self.report._get_drilldown(filters, selector)
        self.assertEqual(drilled['value'], '120.00')
        self.assertEqual({row['source']['move_id'] for row in drilled['rows']}, {pos_move.id, noorix.id})
        self.assertEqual(sum(Decimal(row['cells']['amount'].replace(',', '')) for row in drilled['rows']), Decimal('120.00'))
        doc = self.report._get_export_document(filters)
        channel_rows = [row for row in doc['rows'] if row.get('indent') == 2]
        self.assertEqual(len(channel_rows), 1)
        self.assertEqual(channel_rows[0]['cells']['current'], Decimal('120.00'))

    def test_noorix_explicit_mapping_is_scoped_and_drillable(self):
        if 'baseer.noorix.sales.evidence' not in self.env or 'pos.payment.method' not in self.env:
            self.skipTest('Optional Noorix and POS sources are unavailable')
        sar = self.env.ref('base.SAR')
        sar.active = True
        self.company.currency_id = sar
        Account = self.env['account.account'].with_company(self.company)
        receivable = Account.create({'code': '959115', 'name': 'Mapping receivable',
                                     'account_type': 'asset_receivable', 'reconcile': True,
                                     'company_ids': [Command.set(self.company.ids)]})
        funding = Account.create({'code': '959116', 'name': 'Noorix funding', 'account_type': 'asset_current',
                                  'company_ids': [Command.set(self.company.ids)]})
        cash = self.env['account.journal'].with_company(self.company).create({
            'name': 'Mapping cash', 'code': 'MPC', 'type': 'cash', 'company_id': self.company.id,
        })
        method = self.env['pos.payment.method'].with_company(self.company).create({
            'name': 'Approved cash', 'company_id': self.company.id,
            'journal_id': cash.id, 'receivable_account_id': receivable.id,
        })
        Mapping = self.env['baseer.pl.noorix.channel.mapping']
        vals = {'company_id': self.company.id, 'source_channel': 'cash', 'payment_method_id': method.id,
                'date_from': '2041-05-01', 'date_to': '2041-05-18', 'approval_reference': 'Owner test approval'}
        mapping = Mapping.create(vals)
        # Simulate a concurrent committed reservation invisible to the
        # preliminary overlap query. Catching the error must not retain an
        # unprotected parent mapping in this transaction.
        self.cr.execute('''INSERT INTO baseer_pl_noorix_mapping_day
            (mapping_id, company_id, source_channel, payment_method_id, day)
            VALUES (%s,%s,%s,%s,%s)''',
            [mapping.id, self.company.id, 'cash', method.id, '2041-06-01'])
        with self.assertRaises(ValidationError):
            Mapping.create({**vals, 'date_from': '2041-06-01', 'date_to': '2041-06-01',
                            'approval_reference': 'unique race failure must not persist'})
        self.assertFalse(Mapping.search([('approval_reference', '=', 'unique race failure must not persist')]))
        self.cr.execute('DELETE FROM baseer_pl_noorix_mapping_day WHERE mapping_id=%s AND day=%s',
                        [mapping.id, '2041-06-01'])
        with self.assertRaises(ValidationError), self.cr.savepoint():
            Mapping.create({**vals, 'date_from': '2041-05-18', 'date_to': '2041-05-20'})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            Mapping.create({**vals, 'source_channel': 'bank'})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            Mapping.create({**vals, 'date_from': '2041-06-01', 'date_to': '2041-05-01'})
        foreign = self.env['res.company'].create({'name': 'Foreign mapping company'})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            Mapping.create({**vals, 'company_id': foreign.id})
        reader = self._accountant()
        foreign_receivable = Account.with_company(foreign).create({
            'code': '959117', 'name': 'Foreign mapping receivable', 'account_type': 'asset_receivable',
            'reconcile': True, 'company_ids': [Command.set(foreign.ids)],
        })
        foreign_journal = self.env['account.journal'].with_company(foreign).create({
            'name': 'Foreign mapping cash', 'code': 'FMC', 'type': 'cash', 'company_id': foreign.id,
        })
        foreign_method = self.env['pos.payment.method'].with_company(foreign).create({
            'name': 'Foreign cash', 'company_id': foreign.id, 'journal_id': foreign_journal.id,
            'receivable_account_id': foreign_receivable.id,
        })
        foreign_mapping = Mapping.with_company(foreign).create({
            **vals, 'company_id': foreign.id, 'payment_method_id': foreign_method.id,
        })
        visible = Mapping.with_user(reader).with_context(allowed_company_ids=self.company.ids)
        self.assertFalse(visible.search([('id', '=', foreign_mapping.id)]))
        with self.assertRaises(AccessError), self.cr.savepoint():
            visible.browse(foreign_mapping.id).read(['source_channel'])
        with self.assertRaises(AccessError), self.cr.savepoint():
            Mapping.with_user(reader).create(vals)

        def source(day, amount):
            move = self.env['account.move'].with_company(self.company).create({
                'date': day, 'journal_id': self.journal.id, 'move_type': 'entry',
                'ref': 'NOORIX-SALES SHAMI ' + day + ' | src:map-' + day,
                'line_ids': [
                    Command.create({'name': 'Noorix sales cash ' + day, 'account_id': funding.id, 'debit': amount}),
                    Command.create({'name': 'Noorix sales', 'account_id': self.accounts['income'].id, 'credit': amount}),
                ],
            })
            move.action_post()
            return move
        inside = source('2041-05-10', 20)
        outside = source('2041-05-19', 30)
        details = self.report.get_accounts(self.filters, 'income')['accounts']
        account = next(item for item in details if item['id'] == self.accounts['income'].id)
        channels = {item['key']: item['amounts']['current']['amount'] for item in account['channels']}
        self.assertEqual(channels['payment_' + str(method.id)], '20.00')
        self.assertEqual(channels['noorix_cash'], '30.00')
        self.assertEqual(account['amounts']['current']['amount'], '50.00')
        selector = {'kind': 'channel', 'account_id': self.accounts['income'].id,
                    'channel_key': 'payment_' + str(method.id), 'period_key': 'current'}
        drilled = self.report._get_drilldown(self.filters, selector)
        self.assertEqual(drilled['value'], '20.00')
        self.assertEqual(drilled['total_count'], 1)
        self.assertEqual(self.report._open_drill_source(self.filters, drilled['rows'][0]['source'])['res_id'], inside.id)
        document = self.report._get_export_document(self.filters)
        amounts = [row['cells']['current'] for row in document['rows'] if row.get('indent') == 2]
        self.assertEqual(sum(amounts), Decimal('50.00'))
        comparison = {'company_id': self.company.id, 'journal_ids': [],
                      'period': {'kind': 'month', 'anchor_date': '2041-05-01', 'direction': 0},
                      'comparison': {'kind': 'previous_period', 'count': 1, 'order': 'descending'}}
        compared = self.report.get_accounts(comparison, 'income')['accounts']
        compared = next(item for item in compared if item['id'] == self.accounts['income'].id)
        mapped = next(item for item in compared['channels'] if item['key'] == 'payment_' + str(method.id))
        self.assertEqual(mapped['amounts']['previous_1']['amount'], '0.00')
        previous = self.report._get_drilldown(comparison, {**selector, 'period_key': 'previous_1'})
        self.assertEqual(previous['value'], '0.00')
        self.assertEqual(previous['total_count'], 0)
        rule = self._hide_record('baseer.pl.noorix.channel.mapping', mapping)
        try:
            user_report = self.report.with_user(reader).with_context(allowed_company_ids=self.company.ids)
            with self.assertRaises(AccessError):
                user_report.get_accounts(self.filters, 'income')
        finally:
            rule.unlink()
        method.active = False
        inactive = self.report.get_accounts(self.filters, 'income')['accounts']
        inactive = next(item for item in inactive if item['id'] == self.accounts['income'].id)
        self.assertNotIn('payment_' + str(method.id), [item['key'] for item in inactive['channels']])
        method.active = True
        with self.assertRaises(AccessError), self.cr.savepoint():
            mapping.write({'approval_reference': 'Edited without audit'})
        mapping.write({'revoked': True, 'revocation_reason': 'Replace the approved target'})
        revoked = self.report.get_accounts(self.filters, 'income')['accounts']
        revoked = next(item for item in revoked if item['id'] == self.accounts['income'].id)
        self.assertNotIn('payment_' + str(method.id), [item['key'] for item in revoked['channels']])
        replacement = self.env['pos.payment.method'].with_company(self.company).create({
            'name': 'Replacement cash', 'company_id': self.company.id,
            'journal_id': cash.id, 'receivable_account_id': receivable.id,
        })
        Mapping.create({**vals, 'payment_method_id': replacement.id,
                        'approval_reference': 'Owner replacement approval'})
        replacement_key = 'payment_' + str(replacement.id)
        updated = self.report.get_accounts(self.filters, 'income')['accounts']
        updated = next(item for item in updated if item['id'] == self.accounts['income'].id)
        self.assertEqual(next(item for item in updated['channels'] if item['key'] == replacement_key)
                         ['amounts']['current']['amount'], '20.00')
        self.assertEqual(self.report._get_drilldown(self.filters, {**selector, 'channel_key': replacement_key})
                         ['value'], '20.00')
        document = self.report._get_export_document(self.filters)
        self.assertEqual(sum(row['cells']['current'] for row in document['rows'] if row.get('indent') == 2),
                         Decimal('50.00'))
        exclusive = self.report.get_accounts({**self.filters, 'tax_inclusive': False}, 'income')['accounts']
        self.assertEqual(next(item for item in exclusive if item['id'] == self.accounts['income'].id)
                         ['amounts']['current']['amount'], '50.00')
        self.assertEqual(outside.state, 'posted')
        self.assertEqual(mapping.company_id, self.company)

    def test_empty_reversal_and_late_posting_changes_rerun(self):
        empty = self.report.get_report(self.filters)
        self.assertEqual(empty['net_profit']['amount'], '0.00')
        dashboard_cards = {card['key']: card for card in empty['dashboard']['cards']}
        self.assertFalse(dashboard_cards['gross_margin']['value']['available'])
        self.assertEqual(empty['dashboard']['waterfall'][-1]['amount']['amount'], '0.00')
        self.assertEqual(self.report.get_accounts(self.filters, 'income')['accounts'], [])
        self._entry('income', '10')
        self._entry('income', '-15')
        first = self.report.get_report(self.filters)
        self.assertEqual(first['net_profit']['amount'], '-5.00')
        self.assertTrue(first['net_profit']['negative'])
        dashboard_cards = {card['key']: card for card in first['dashboard']['cards']}
        self.assertFalse(dashboard_cards['gross_margin']['value']['available'])
        self.assertIn('gross_margin_unavailable', first['dashboard']['notes'])
        self.assertTrue(first['dashboard']['revenue_accounts'])
        self.assertFalse(first['dashboard']['revenue_accounts'][0]['share']['available'])
        self.assertIn('revenue_share_unavailable', first['dashboard']['notes'])
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
