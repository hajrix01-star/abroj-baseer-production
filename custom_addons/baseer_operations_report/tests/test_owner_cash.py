"""Focused source-contract tests for the private owner cash projection."""

from collections import Counter
from decimal import Decimal
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'operations_owner_cash', 'operations_owner_access_perf')
class TestOwnerCash(TransactionCase):

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.report = self.env['baseer.operations.report']
        self.accounts = self.env['account.account'].with_company(self.company)

        def account(code, name, account_type, reconcile=False):
            return self.accounts.create({
                'code': code,
                'name': name,
                'account_type': account_type,
                'reconcile': reconcile,
                'company_ids': [Command.set(self.company.ids)],
            })

        self.expense = account('959101', 'Owner cash operating expense', 'expense')
        self.payable = account('959102', 'Owner cash payable', 'liability_payable', True)
        self.outstanding = account('959103', 'Owner cash outstanding', 'asset_current', True)
        self.bank = self.env['account.journal'].with_company(self.company).search([
            ('company_id', '=', self.company.id), ('type', '=', 'bank'),
        ], limit=1)
        self.assertTrue(self.bank and self.bank.default_account_id)
        self.assertEqual(self.bank.default_account_id.account_type, 'asset_cash')
        self.method = self.bank.outbound_payment_method_line_ids.filtered(
            lambda line: line.payment_method_id.code == 'manual',
        )[:1]
        self.assertTrue(self.method)
        self.method.payment_account_id = self.outstanding
        self.partner = self.env['res.partner'].with_company(self.company).create({
            'name': 'Owner cash supplier',
            'property_account_payable_id': self.payable.id,
        })
        self.purchase = self.env['account.journal'].with_company(self.company).create({
            'name': 'Owner cash purchases',
            'code': 'OCP',
            'type': 'purchase',
            'company_id': self.company.id,
        })
        self.category_root = self.env['product.category'].create({
            'name': 'Owner cash test root',
        })
        self.category_leaf = self.env['product.category'].create({
            'name': 'Owner cash test leaf',
            'parent_id': self.category_root.id,
        })
        self.category_leaf_two = self.env['product.category'].create({
            'name': 'Owner cash second leaf',
            'parent_id': self.category_root.id,
        })

    def _statement(self, amount='40.00', counterpart=None, day='2026-06-18'):
        statement = self.env['account.bank.statement.line'].with_company(
            self.company,
        ).create({
            'journal_id': self.bank.id,
            'date': day,
            'payment_ref': 'Owner cash actual operating payment',
            'partner_id': self.partner.id,
            'amount': -Decimal(amount),
            'counterpart_account_id': (counterpart or self.expense).id,
        })
        self.assertEqual(statement.move_id.state, 'posted')
        return statement

    def _posted_bill_line(self, category=None):
        product = self.env['product.product'].with_company(self.company).create({
            'name': 'Owner cash dual-use product',
            'categ_id': (category or self.category_leaf).id,
            # A vendor bill, rather than these mutable flags, is the purchase
            # evidence.  Keep both true to prevent an accidental sale_ok gate.
            'purchase_ok': True,
            'sale_ok': True,
        })
        bill = self.env['account.move'].with_company(self.company).create({
            'move_type': 'in_invoice',
            'partner_id': self.partner.id,
            'journal_id': self.purchase.id,
            'invoice_date': '2026-06-18',
            'invoice_line_ids': [Command.create({
                'name': 'Owner cash classified item',
                'product_id': product.id,
                'quantity': 1,
                'price_unit': 20,
                'account_id': self.expense.id,
            })],
        })
        bill.action_post()
        return bill.invoice_line_ids

    def _payment_to_outstanding(self, bill, amount, payment_day, bank_day):
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=bill.ids,
        ).create({
            'journal_id': self.bank.id,
            'payment_method_line_id': self.method.id,
            'amount': amount,
            'payment_date': payment_day,
            'installments_mode': 'full',
            'payment_difference_handling': 'open',
        })
        payment = wizard._create_payments()
        payable = payment.move_id.line_ids.filtered(
            lambda line: line.account_id == self.payable,
        )
        outstanding_credit = payment.move_id.line_ids.filtered(
            lambda line: line.account_id == self.outstanding,
        )
        self.assertEqual(len(payable), 1)
        self.assertEqual(len(outstanding_credit), 1)
        statement = self._statement(amount, self.outstanding, bank_day)
        outstanding_debit = statement.move_id.line_ids.filtered(
            lambda line: line.account_id == self.outstanding,
        )
        (outstanding_credit + outstanding_debit).reconcile()
        liquidity = statement.move_id.line_ids.filtered(
            lambda line: line.account_id == self.bank.default_account_id,
        )
        self.assertEqual(len(liquidity), 1)
        return statement, liquidity

    def _reader(self):
        return self.env['res.users'].create({
            'name': 'Owner cash source reader',
            'login': 'owner_cash_source_reader',
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_user').id,
                self.env.ref('point_of_sale.group_pos_user').id,
            ])],
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
        })

    def test_owner_cash_uses_a_posted_statement_and_keeps_account_identity(self):
        statement = self._statement()
        liquidity = statement.move_id.line_ids.filtered(
            lambda line: line.account_id == self.bank.default_account_id,
        )
        result = self.report._owner_cash(
            self.company, '2026-06-01', '2026-06-30', [],
        )
        self.assertTrue(result['coverage_complete'], result['excluded'])
        self.assertEqual(result['liquidity_totals'], {liquidity.id: Decimal('40.00')})
        self.assertEqual(len(result['events']), 1)
        event = result['events'][0]
        self.assertEqual(event['company_id'], self.company.id)
        self.assertEqual(event['direction'], 'outgoing')
        self.assertEqual(event['source_model'], 'account.bank.statement.line')
        self.assertEqual(event['source_id'], statement.id)
        self.assertEqual(event['payment_line_id'], liquidity.id)
        self.assertEqual(event['amount'], Decimal('40.00'))
        self.assertEqual(event['classification'], 'operating_account')
        self.assertEqual(event['account_id'], self.expense.id)
        self.assertEqual(event['account_name'], self.expense.name)

    def test_vendor_bill_product_category_does_not_require_purchase_only_product(self):
        line = self._posted_bill_line()
        classification = self.report._owner_cash_classification(line, self.company)
        self.assertEqual(classification['classification'], 'purchase')
        self.assertEqual(classification['category_path'], [
            (self.category_root.id, self.category_root.name),
            (self.category_leaf.id, self.category_leaf.name),
        ])

    def test_root_only_product_category_is_not_a_purchase_bucket(self):
        line = self._posted_bill_line(self.category_root)
        self.assertEqual(
            self.report._owner_cash_classification(line, self.company),
            {'classification': 'unclassified'},
        )

    def _catalog_reference(self, key, product):
        if not hasattr(self.company, '_baseer_service_identity'):
            self.skipTest('The optional service catalog is not installed.')
        name = f'product_{key}_company_{self.company.id}'
        data = self.env['ir.model.data'].search([
            ('module', '=', 'baseer_service_seed'), ('name', '=', name),
        ])
        values = {'module': 'baseer_service_seed', 'name': name,
                  'model': 'product.product', 'res_id': product.id}
        if data:
            data.write(values)
        else:
            self.env['ir.model.data'].create(values)

    def test_proven_utility_bill_uses_catalog_identity_not_product_name(self):
        line = self._posted_bill_line()
        self._catalog_reference('electricity', line.product_id)
        line.product_id.name = 'Deliberately unrelated display name'
        self._payment_to_outstanding(line.move_id, line.move_id.amount_total,
                                     '2026-06-19', '2026-06-20')
        result = self.report.with_context(lang='en_US')._owner_cash(
            self.company, '2026-06-01', '2026-06-30', [],
        )
        self.assertTrue(result['coverage_complete'], result['excluded'])
        self.assertEqual(len(result['events']), 1)
        self.assertEqual(result['events'][0]['classification'], 'operating_services')
        self.assertEqual(result['events'][0]['service_key'], 'electricity')
        self.assertEqual(result['events'][0]['service_name'], 'Electricity')
        arabic = self.report.with_context(lang='ar_001')._owner_cash_classification(line, self.company)
        self.assertEqual(arabic['service_name'], 'الكهرباء')

    def test_hr_catalog_product_without_service_document_is_not_a_purchase(self):
        line = self._posted_bill_line()
        self._catalog_reference('iqama_issue', line.product_id)
        self.assertEqual(self.report._owner_cash_classification(line, self.company),
                         {'classification': 'unclassified'})

    def test_utility_name_alone_does_not_prove_operating_service(self):
        line = self._posted_bill_line()
        line.product_id.name = 'Electricity'
        self.assertEqual(self.report._owner_cash_classification(line, self.company)['classification'],
                         'purchase')

    def test_partial_bank_cash_allocates_two_real_bill_categories_exactly(self):
        first = self.env['product.product'].with_company(self.company).create({
            'name': 'Owner cash partial first item',
            'categ_id': self.category_leaf.id,
            'purchase_ok': True,
            'sale_ok': True,
        })
        second = self.env['product.product'].with_company(self.company).create({
            'name': 'Owner cash partial second item',
            'categ_id': self.category_leaf_two.id,
            'purchase_ok': True,
            'sale_ok': True,
        })
        bill = self.env['account.move'].with_company(self.company).create({
            'move_type': 'in_invoice',
            'partner_id': self.partner.id,
            'journal_id': self.purchase.id,
            'invoice_date': '2026-06-10',
            'invoice_line_ids': [
                Command.create({
                    'name': 'First actual item', 'product_id': first.id,
                    'quantity': 1, 'price_unit': 100, 'account_id': self.expense.id,
                }),
                Command.create({
                    'name': 'Second actual item', 'product_id': second.id,
                    'quantity': 1, 'price_unit': 40, 'account_id': self.expense.id,
                }),
            ],
        })
        bill.action_post()
        statement, liquidity = self._payment_to_outstanding(
            bill, 50, '2026-06-12', '2026-06-15',
        )
        result = self.report._owner_cash(
            self.company, '2026-06-01', '2026-06-30', [],
        )
        self.assertTrue(result['coverage_complete'], result['excluded'])
        self.assertNotIn('unsupported_native_payment', result['excluded'])
        self.assertEqual(result['liquidity_totals'], {liquidity.id: Decimal('50.00')})
        events = result['events']
        self.assertEqual(len(events), 2)
        self.assertEqual({event['source_id'] for event in events}, {statement.id})
        self.assertEqual({event['source_model'] for event in events},
                         {'account.bank.statement.line'})
        self.assertEqual({event['payment_line_id'] for event in events}, {liquidity.id})
        self.assertEqual(sum((event['amount'] for event in events), Decimal('0')), Decimal('50.00'))
        by_path = {tuple(event['category_path']): event['amount'] for event in events}
        self.assertEqual(by_path[(
            (self.category_root.id, self.category_root.name),
            (self.category_leaf.id, self.category_leaf.name),
        )], Decimal('35.71'))
        self.assertEqual(by_path[(
            (self.category_root.id, self.category_root.name),
            (self.category_leaf_two.id, self.category_leaf_two.name),
        )], Decimal('14.29'))

    def test_outstanding_vendor_payment_before_statement_is_zero_cash_complete(self):
        bill = self.env['account.move'].with_company(self.company).create({
            'move_type': 'in_invoice',
            'partner_id': self.partner.id,
            'journal_id': self.purchase.id,
            'invoice_date': '2026-06-10',
            'invoice_line_ids': [Command.create({
                'name': 'Outstanding before statement', 'quantity': 1,
                'price_unit': 20, 'account_id': self.expense.id,
            })],
        })
        bill.action_post()
        self._payment_to_outstanding(bill, 20, '2026-06-12', '2026-06-15')

        result = self.report._owner_cash(
            self.company, '2026-06-12', '2026-06-12', [],
        )

        self.assertTrue(result['coverage_complete'], result['excluded'])
        self.assertEqual(result['liquidity_totals'], {})
        self.assertEqual(result['events'], [])
        self.assertNotIn('unsupported_native_payment', result['excluded'])

    def test_native_vendor_payment_with_product_stays_unconfirmed(self):
        line = self._posted_bill_line()
        bill = line.move_id
        self.method.payment_account_id = self.bank.default_account_id
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=bill.ids,
        ).create({
            'journal_id': self.bank.id,
            'payment_method_line_id': self.method.id,
            'amount': 20,
            'payment_date': '2026-06-20',
            'installments_mode': 'full',
            'payment_difference_handling': 'open',
        })
        payment = wizard._create_payments()
        liquidity = payment.move_id.line_ids.filtered(
            lambda row: row.account_id == self.bank.default_account_id,
        )
        self.assertEqual(len(liquidity), 1)
        result = self.report._owner_cash(
            self.company, '2026-06-01', '2026-06-30', [],
        )
        self.assertTrue(result['coverage_complete'])
        self.assertEqual(result['liquidity_totals'], {liquidity.id: Decimal('20.00')})
        self.assertEqual(len(result['events']), 1)
        event = result['events'][0]
        self.assertEqual(event['line_id'], line.id)
        self.assertEqual(event['classification'], 'unconfirmed_bill_classification')
        self.assertEqual(event['link_status'], 'unconfirmed')
        self.assertNotIn('category_path', event)

    def test_native_read_facts_keep_events_and_coverage_identical_to_default(self):
        line = self._posted_bill_line()
        bill = line.move_id
        self.method.payment_account_id = self.bank.default_account_id
        payment = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=bill.ids,
        ).create({
            'journal_id': self.bank.id,
            'payment_method_line_id': self.method.id,
            'amount': bill.amount_total,
            'payment_date': '2026-06-20',
            'installments_mode': 'full',
            'payment_difference_handling': 'open',
        })._create_payments()

        def collect(read_facts):
            sections = {key: {} for key in (
                'income', 'income_other', 'expense_direct_cost', 'expense',
                'expense_depreciation', 'expense_other',
            )}
            excluded = Counter()
            self.report._native_payment_outflows(
                self.company, '2026-06-01', '2026-06-30', [], sections, excluded,
                read_facts=read_facts,
            )
            events = [event for section in sections.values()
                      for entry in section.values() for event in entry['events']]
            return events, dict(excluded), self.report._coverage_complete(excluded)

        baseline = collect(None)
        memoized = collect({})
        self.assertEqual(memoized, baseline)
        self.assertEqual({event['source_id'] for event in memoized[0]}, {payment.id})

    def test_owner_cash_fresh_invocation_does_not_reuse_revoked_read_access(self):
        line = self._posted_bill_line()
        bill = line.move_id
        self.method.payment_account_id = self.bank.default_account_id
        payment = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=bill.ids,
        ).create({
            'journal_id': self.bank.id,
            'payment_method_line_id': self.method.id,
            'amount': bill.amount_total,
            'payment_date': '2026-06-20',
            'installments_mode': 'full',
            'payment_difference_handling': 'open',
        })._create_payments()
        reader = self._reader()
        secured = self.report.with_user(reader).with_context(
            allowed_company_ids=self.company.ids,
        )
        self.assertTrue(secured._owner_cash(
            self.company, '2026-06-01', '2026-06-30', [])['coverage_complete'])

        targets = (
            ('account.account', self.bank.default_account_id.id),
            ('account.move', payment.move_id.id),
            ('account.journal', self.bank.id),
        )
        for model, record_id in targets:
            rule = self.env['ir.rule'].create({
                'name': 'Owner read-facts fresh %s' % model,
                'model_id': self.env['ir.model']._get(model).id,
                'domain_force': "[('id', '!=', %s)]" % record_id,
            })
            try:
                rule.flush_recordset()
                secured.env.invalidate_all()
                with self.assertRaises(AccessError):
                    secured._owner_cash(self.company, '2026-06-01', '2026-06-30', [])
            finally:
                rule.unlink()
                secured.env.invalidate_all()

    def test_native_raw_identity_mismatch_fails_before_read_facts_acl(self):
        line = self._posted_bill_line()
        bill = line.move_id
        self.method.payment_account_id = self.bank.default_account_id
        payment = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=bill.ids,
        ).create({
            'journal_id': self.bank.id,
            'payment_method_line_id': self.method.id,
            'amount': bill.amount_total,
            'payment_date': '2026-06-20',
            'installments_mode': 'full',
            'payment_difference_handling': 'open',
        })._create_payments()
        payable = payment.move_id.line_ids.filtered(
            lambda row: row.account_id == self.payable,
        )
        partials = payable.matched_credit_ids
        cache = self.report._native_payment_identity_census(payment)
        key = ('account_partial_reconcile', 'debit_move_id', payable.id)
        damaged = {'ids': dict(cache['ids']), 'partial_edges': dict(cache['partial_edges'])}
        damaged['ids'][key] = set()
        calls = []
        original = type(self.report)._owner_check_read

        def counted(instance, records, read_facts=None):
            calls.append(records)
            return original(instance, records, read_facts)

        with patch.object(type(self.report), '_owner_check_read', new=counted):
            with self.assertRaises(AccessError):
                self.report._native_payment_cached_visible(
                    damaged, *key, partials, read_facts={})
        self.assertEqual(calls, [])

    def test_hidden_product_category_fails_closed(self):
        line = self._posted_bill_line()
        reader = self._reader()
        secured = self.report.with_user(reader).with_context(
            allowed_company_ids=self.company.ids,
        )
        rule = self.env['ir.rule'].create({
            'name': 'Owner cash hide classified category',
            'model_id': self.env['ir.model']._get('product.category').id,
            'domain_force': "[('id', '!=', %s)]" % self.category_leaf.id,
        })
        try:
            rule.flush_recordset()
            with self.assertRaises(AccessError):
                secured._owner_cash_classification(line, self.company)
        finally:
            rule.unlink()

    def test_read_facts_are_isolated_by_real_odoo_environment_context_user_and_company(self):
        account = self.bank.default_account_id
        reader = self._reader()
        facts, calls = {}, []
        depth = 0
        original = type(account).check_access

        def counted(records, operation):
            # Odoo's real ``check_access`` may call this model hook again while
            # evaluating its own rules.  Count only the outer call emitted by
            # ``_owner_check_read``; the original ACL path still executes.
            nonlocal depth
            outer = depth == 0
            depth += 1
            try:
                if outer:
                    calls.append((records.env, records.ids, operation))
                return original(records, operation)
            finally:
                depth -= 1

        base = account
        context = account.with_context(baseer_owner_read_probe='context')
        user = account.with_user(reader).with_context(allowed_company_ids=self.company.ids)
        company = account.with_context(
            allowed_company_ids=self.company.ids,
            force_company=self.company.id,
            baseer_owner_read_probe='company',
        )
        with patch.object(type(account), 'check_access', new=counted):
            self.report._owner_check_read(base, facts)
            self.report._owner_check_read(base, facts)
            self.report._owner_check_read(context, facts)
            self.report._owner_check_read(user, facts)
            self.report._owner_check_read(company, facts)
        self.assertEqual(len(calls), 4)
        self.assertEqual({call[2] for call in calls}, {'read'})
        self.assertEqual({id(call[0]) for call in calls}, {
            id(base.env), id(context.env), id(user.env), id(company.env),
        })

    def test_hidden_statement_source_fails_closed(self):
        statement = self._statement()
        reader = self._reader()
        secured = self.report.with_user(reader).with_context(
            allowed_company_ids=self.company.ids,
        )
        rule = self.env['ir.rule'].create({
            'name': 'Owner cash hide statement source',
            'model_id': self.env['ir.model']._get('account.bank.statement.line').id,
            'domain_force': "[('id', '!=', %s)]" % statement.id,
        })
        try:
            rule.flush_recordset()
            with self.assertRaises(AccessError):
                secured._owner_cash(self.company, '2026-06-01', '2026-06-30', [])
        finally:
            rule.unlink()


@tagged('post_install', '-at_install', 'operations_owner_access_perf')
class TestOwnerReadFacts(TransactionCase):
    """Small contract tests for the request-local owner read proof memo."""

    class _Records:
        def __init__(self, env, model, ids, calls, failures=None):
            self.env = env
            self._name = model
            self.ids = list(ids)
            self.calls = calls
            self.failures = failures if failures is not None else {}

        def __bool__(self):
            return bool(self.ids)

        def browse(self, ids):
            return self.__class__(self.env, self._name, ids, self.calls, self.failures)

        def check_access(self, operation):
            key = (self.env, self._name, operation, tuple(self.ids))
            self.calls.append(key)
            if self.failures.get(key):
                self.failures[key] -= 1
                raise AccessError('deliberate failed read proof')

    def setUp(self):
        super().setUp()
        self.report = self.env['baseer.operations.report']

    def test_read_facts_are_exact_environment_model_and_identity(self):
        calls, facts = [], {}
        first_env, second_env = object(), object()
        first = self._Records(first_env, 'account.move', [7], calls)
        same = self._Records(first_env, 'account.move', [7], calls)
        other_model = self._Records(first_env, 'account.payment', [7], calls)
        other_environment = self._Records(second_env, 'account.move', [7], calls)

        for records in (first, same, other_model, other_environment):
            self.report._owner_check_read(records, facts)

        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0][1:3], ('account.move', 'read'))
        self.assertEqual(calls[1][1:3], ('account.payment', 'read'))
        self.assertIs(calls[2][0], second_env)

    def test_read_facts_never_cache_empty_default_or_failed_batch(self):
        calls, facts = [], {}
        env = object()
        failed_key = (env, 'account.move', 'read', (3, 4))
        failures = {failed_key: 1}
        failed = self._Records(env, 'account.move', [3, 4], calls, failures)
        with self.assertRaises(AccessError):
            self.report._owner_check_read(failed, facts)
        self.assertEqual(next(iter(facts.values())), set())
        self.report._owner_check_read(failed, facts)
        self.report._owner_check_read(failed, facts)
        self.assertEqual([call[3] for call in calls], [(3, 4), (3, 4)])

        empty = self._Records(env, 'account.journal', [], calls)
        self.report._owner_check_read(empty, facts)
        self.report._owner_check_read(empty, facts)
        default = self._Records(env, 'account.account', [9], calls)
        self.report._owner_check_read(default)
        self.report._owner_check_read(default)
        self.assertEqual([call[3] for call in calls[-4:]], [(), (), (9,), (9,)])
