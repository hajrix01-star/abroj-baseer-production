"""Native posting/record-rule fixtures only; never business data on QA/Live."""
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from odoo import Command, SUPERUSER_ID
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import new_test_user, tagged

from ..models.spending import SpendingBudget, SpendingReader


@tagged('post_install', '-at_install', 'bwork_combined_spending')
class TestCombinedSpendingOrm(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.fixture = cls.env(user=SUPERUSER_ID, context={
            **cls.env.context, 'allowed_company_ids': cls.env.company.ids,
        })
        cls.company = cls.fixture.company
        sar = cls.fixture.ref('base.SAR')
        sar.active = True
        cls.company.currency_id = sar
        cls.reader = new_test_user(cls.fixture, login='bwork_spending_native_reader',
            groups='base.group_user,account.group_account_invoice',
            company_id=cls.company.id, company_ids=[Command.set(cls.company.ids)])
        cls.read_env = cls.env(user=cls.reader, context={'allowed_company_ids': cls.company.ids})
        cls.stock_reader = new_test_user(cls.fixture, login='bwork_spending_stock_reader',
            groups='base.group_user,account.group_account_invoice,stock.group_stock_user',
            company_id=cls.company.id, company_ids=[Command.set(cls.company.ids)])
        cls.stock_env = cls.env(user=cls.stock_reader, context={'allowed_company_ids': cls.company.ids})
        cls.expense = cls.company_data['default_account_expense'].with_env(cls.fixture)
        cls.counterpart = cls.company_data['default_account_revenue'].with_env(cls.fixture)
        cls.journal = cls.company_data['default_journal_misc'].with_env(cls.fixture)
        cls.partner = cls.fixture['res.partner'].create({'name': 'Synthetic spending source',
            'property_account_payable_id': cls.company_data['default_account_payable'].id})
        cls.ranges = [(date(2026, 10, 1), date(2026, 10, 31))]

    def _entry(self, value=Decimal('10.00'), day='2026-10-02', account=None, **extra):
        value = Decimal(str(value))
        expense, counter = (value, -value)
        move = self.fixture['account.move'].create({
            'move_type': 'entry', 'company_id': self.company.id,
            'journal_id': self.journal.id, 'date': day, **extra,
            'line_ids': [Command.create({'name': 'Native operating', 'account_id': (account or self.expense).id,
                'debit': float(max(expense, 0)), 'credit': float(max(-expense, 0))}),
                Command.create({'name': 'Counterpart, not another expense', 'account_id': self.counterpart.id,
                'debit': float(max(counter, 0)), 'credit': float(max(-counter, 0))})],
        })
        move.action_post()
        return move

    def _bill(self, value=100, kind='in_invoice', day='2026-10-02', tax=None, **extra):
        bill = self.fixture['account.move'].create({
            'move_type': kind, 'company_id': self.company.id,
            'partner_id': self.partner.id, 'invoice_date': day, **extra,
            'invoice_line_ids': [Command.create({'name': 'Synthetic vendor document',
                'quantity': 1, 'price_unit': value, 'account_id': self.expense.id,
                'tax_ids': [Command.set(tax.ids)] if tax else [Command.clear()]})],
        })
        bill.action_post()
        return bill

    def _read(self, ranges=None, budget=None, env=None):
        env = env or self.read_env
        self.assertFalse(env.su)
        return SpendingReader(env, self.company.with_env(env), ranges or self.ranges,
                              budget or SpendingBudget()).collect()

    def _account(self, kind, code):
        return self.fixture['account.account'].create({'name': 'Synthetic classification',
            'code': code, 'account_type': kind, 'company_ids': [Command.set(self.company.ids)]})

    def _deny(self, model, record):
        return self.fixture['ir.rule'].create({'name': 'Synthetic independent source denial',
            'model_id': self.fixture['ir.model']._get_id(model),
            'domain_force': "[('id', '!=', %s)]" % record.id})

    def test_bill_and_operating_partitions_once(self):
        self._bill(100)
        self._entry(17)
        self.assertEqual(self._read().totals(self.ranges[0]), (Decimal('100'), Decimal('17')))

    def test_native_credit_reduces_purchases(self):
        self._bill(100)
        self._bill(25, 'in_refund')
        self.assertEqual(self._read().totals(self.ranges[0]), (Decimal('75'), Decimal('0')))

    def test_global_bill_partition_across_invoice_posting_month(self):
        self._bill(100, day='2026-09-30', date='2026-10-02')
        reader = self._read([(date(2026, 9, 1), date(2026, 10, 31))])
        self.assertEqual(reader.totals(self.ranges[0]), (Decimal('0'), Decimal('0')))
        self.assertEqual(reader.totals((date(2026, 9, 1), date(2026, 9, 30)))[0], Decimal('100'))

    def test_draft_sources_do_not_become_spending(self):
        draft = self._entry(13)
        draft.button_draft()
        self.assertEqual(self._read().totals(self.ranges[0]), (Decimal('0'), Decimal('0')))

    def test_operating_credit_is_not_absolute_value(self):
        self._entry(40)
        self._entry(-7)
        self.assertEqual(self._read().totals(self.ranges[0])[1], Decimal('33'))

    def test_pure_salary_expense_does_not_sum_both_sides(self):
        move = self._entry(125)
        move.button_draft()
        # Native salary-shaped journal:125expense,100payable,25advance
        # recovery. The expense must remain125, not netpay100 or sum250.
        move.line_ids = [Command.clear(),
            Command.create({'name': 'Salary expense', 'account_id': self.expense.id, 'debit': 125}),
            Command.create({'name': 'Net payable', 'partner_id': self.partner.id,
                'account_id': self.company_data['default_account_payable'].id, 'credit': 100}),
            Command.create({'name': 'Advance recovery', 'partner_id': self.partner.id,
                'account_id': self.company_data['default_account_receivable'].id, 'credit': 25})]
        move.action_post()
        # The salary payable/recovery/payment source totals are not another
        # input; the only financial input is the posted expense-side balance.
        self.assertEqual(self._read().totals(self.ranges[0])[1], Decimal('125'))

    def test_unproven_mixed_asset_cost_adjustment_is_unavailable(self):
        move = self._entry(19)
        move.button_draft()
        move.line_ids.filtered(lambda row: row.account_id == self.counterpart).account_id = self._account('asset_current', 'BCSASSET')
        move.action_post()
        with self.assertRaises(ValidationError):
            self._read()

    def test_depreciation_excluded_by_native_type(self):
        self._entry(20, account=self._account('expense_depreciation', 'BCSDEP'))
        result = self._read()
        self.assertEqual(result.totals(self.ranges[0])[1], Decimal('0'))
        self.assertEqual(result.excluded, 1)

    def test_untraced_direct_cost_is_unavailable(self):
        self._entry(20, account=self._account('expense_direct_cost', 'BCSCOGS'))
        with self.assertRaises(ValidationError):
            self._read()

    def test_other_operating_type_uses_native_balance(self):
        self._entry(18, account=self._account('expense_other', 'BCSOTHER'))
        self.assertEqual(self._read().totals(self.ranges[0])[1], Decimal('18'))

    def test_independent_move_rule_cannot_silently_reduce_total(self):
        move = self._entry(40)
        self._deny('account.move', move)
        with self.assertRaises(AccessError):
            self._read()

    def test_independent_account_rule_cannot_silently_reduce_total(self):
        self._entry(40)
        self._deny('account.account', self.expense)
        with self.assertRaises(AccessError):
            self._read()

    def test_independent_journal_rule_is_checked(self):
        self._entry(40)
        self._deny('account.journal', self.journal)
        with self.assertRaises(AccessError):
            self._read()

    def test_hidden_bill_child_line_rejects_partial_coverage(self):
        bill = self._bill(40)
        hidden = bill.invoice_line_ids.filtered(lambda row: row.display_type == 'product')[:1]
        self._deny('account.move.line', hidden)
        with self.assertRaises(AccessError):
            self._read()

    def test_bill_children_capacity_fails_before_aml_materialization(self):
        bill = self._bill(40)
        bill.button_draft()
        bill.invoice_line_ids = [Command.create({'name': 'Bounded synthetic row',
            'account_id': self.expense.id, 'quantity': 1, 'price_unit': 1,
            'tax_ids': [Command.clear()]}) for _ in range(10)]
        bill.action_post()
        with patch.object(type(self.read_env['account.move.line']), 'search',
                          side_effect=AssertionError('Capacity must fail before AML materialization')):
            with self.assertRaises(ValidationError):
                self._read(budget=SpendingBudget(7))

    def test_shared_budget_rejects_link_work_before_partial_total(self):
        self._entry(40)
        with self.assertRaises(ValidationError):
            self._read(budget=SpendingBudget(2))

    def test_bill_target_entry_reversal_is_not_silently_omitted(self):
        bill = self._bill(40)
        self._entry(-40, reversed_entry_id=bill.id)
        with self.assertRaises(ValidationError):
            self._read()

    def test_vat_uses_bill_gross_and_native_operating_balance(self):
        tax = self.fixture['account.tax'].create({'name': 'Synthetic15%', 'amount': 15,
            'amount_type': 'percent', 'type_tax_use': 'purchase', 'company_id': self.company.id})
        bill = self._bill(100, tax=tax)
        self._entry(7)
        purchases, operating = self._read().totals(self.ranges[0])
        self.assertEqual(purchases, -Decimal(str(bill.amount_total_signed)))
        self.assertEqual(purchases, Decimal('115'))
        self.assertEqual(operating, Decimal('7'))

    def test_overlapping_periods_are_one_source_read(self):
        self._entry(12)
        reader = self._read([self.ranges[0], (date(2026, 10, 1), date(2026, 10, 15))])
        self.assertEqual(reader.totals(self.ranges[0])[1], Decimal('12'))

    def test_foreign_bill_uses_posted_company_currency(self):
        usd = self.fixture.ref('base.USD')
        usd.active = True
        self.fixture['res.currency.rate'].create({'currency_id': usd.id,
            'company_id': self.company.id, 'name': '2026-01-01', 'rate': 0.25})
        bill = self._bill(20, currency_id=usd.id)
        self.assertNotEqual(bill.currency_id, self.company.currency_id)
        self.assertEqual(self._read().totals(self.ranges[0])[0], -Decimal(str(bill.amount_total_signed)))

    def _valuation_fixture(self):
        if 'stock_move_ids' not in self.fixture['account.move']._fields:
            self.fail('Isolated combined spending profile must install stock_account')
        move = self._entry(19)
        product = self.fixture['product.product'].create({'name': 'Synthetic stock lineage', 'is_storable': True})
        field = move._fields['stock_move_ids']
        self.assertEqual(field.comodel_name, 'stock.move')
        stock = self.fixture['stock.move'].create({'product_id': product.id,
            'product_uom_qty': 1, 'product_uom': product.uom_id.id,
            'location_id': self.fixture.ref('stock.stock_location_suppliers').id,
            'location_dest_id': self.fixture.ref('stock.stock_location_stock').id,
            'company_id': self.company.id, field.inverse_name: move.id})
        return stock

    def test_stock_valuation_link_excludes_second_purchase_cost(self):
        self._valuation_fixture()
        result = self._read(env=self.stock_env)
        self.assertEqual(result.totals(self.ranges[0])[1], Decimal('0'))
        self.assertEqual(result.excluded, 1)

    def test_hidden_stock_link_cannot_turn_cost_into_operating(self):
        stock = self._valuation_fixture()
        self._deny('stock.move', stock)
        with self.assertRaises(AccessError):
            self._read(env=self.stock_env)

    def test_native_valuation_entry_reversal_is_unavailable(self):
        stock = self._valuation_fixture()
        original = stock.account_move_id
        reverse = original._reverse_moves([{'date': '2026-10-03'}], cancel=False)
        reverse.action_post()
        self.assertEqual(reverse.reversed_entry_id, original)
        with self.assertRaises(ValidationError):
            self._read(env=self.stock_env)

    def test_hidden_valuation_ancestor_fails_coverage(self):
        stock = self._valuation_fixture()
        reverse = stock.account_move_id._reverse_moves([{'date': '2026-10-03'}], cancel=False)
        reverse.action_post()
        self._deny('stock.move', stock)
        with self.assertRaises(AccessError):
            self._read(env=self.stock_env)

    def test_native_ordinary_operating_reversal_stays_supported(self):
        original = self._entry(40)
        reverse = original._reverse_moves([{'date': '2026-10-03'}], cancel=False)
        reverse.action_post()
        self.assertEqual(self._read().totals(self.ranges[0])[1], Decimal('0'))

    def test_native_customer_invoice_cogs_is_not_unsupported_opex(self):
        account = self._account('expense_direct_cost', 'BCSSALECOST')
        move = self.fixture['account.move'].create({
            'move_type': 'out_invoice', 'company_id': self.company.id,
            'partner_id': self.partner.id, 'invoice_date': '2026-10-02',
            'invoice_line_ids': [Command.create({'name': 'Native sale', 'quantity': 1,
                'price_unit': 20, 'account_id': self.counterpart.id, 'tax_ids': [Command.clear()]})]})
        move.line_ids = [Command.create({'name': 'Native COGS', 'display_type': 'cogs',
            'account_id': account.id, 'debit': 9}), Command.create({'name': 'COGS counterpart',
            'display_type': 'cogs', 'account_id': self.counterpart.id, 'credit': 9})]
        move.action_post()
        result = self._read()
        self.assertEqual(result.totals(self.ranges[0]), (Decimal('0'), Decimal('0')))
        self.assertEqual(result.excluded, 1)

    def test_plain_operating_reader_needs_no_unused_hr_or_stock_role(self):
        self.assertFalse(self.reader.has_group('stock.group_stock_user'))
        self.assertFalse(self.reader.has_group('hr.group_hr_user'))
        self._bill(3)
        self._entry(7)
        self.assertEqual(self._read().totals(self.ranges[0]), (Decimal('3'), Decimal('7')))
