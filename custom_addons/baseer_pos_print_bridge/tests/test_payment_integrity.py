"""Payment boundary tests use native POS amounts and a POS-only cashier."""
from copy import deepcopy
from contextlib import contextmanager
from uuid import uuid4

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'baseer_payment_integrity')
class TestBaseerPaymentIntegrity(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.currency = cls.company.currency_id
        cls.income = cls.env['account.account'].search([
            ('company_ids', 'in', cls.company.ids), ('account_type', '=', 'income'),
        ], limit=1)
        if not cls.income:
            cls.income = cls.env['account.account'].create({
                'name': 'Payment integrity income', 'code': '987610',
                'account_type': 'income', 'company_ids': [Command.set(cls.company.ids)],
            })
        cls.tax = cls.env['account.tax'].create({
            'name': 'Payment integrity VAT 15%', 'amount': 15, 'amount_type': 'percent',
            'type_tax_use': 'sale', 'company_id': cls.company.id,
        })
        cls.included_tax = cls.tax.copy({
            'name': 'Payment integrity included VAT', 'price_include_override': 'tax_included',
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Payment integrity service', 'type': 'service', 'available_in_pos': True,
            'list_price': 100, 'property_account_income_id': cls.income.id,
            'taxes_id': [Command.set(cls.tax.ids)],
        })
        cls.config = cls.env['pos.config'].create({'name': 'Payment integrity ordinary POS'})
        cls.config.open_ui()
        cls.session = cls.config.current_session_id
        cls.session.set_opening_control(0, 'Payment integrity fixture')
        cls.method = cls.config.payment_method_ids[:1]
        cls.cash_method = cls.config.payment_method_ids.filtered('is_cash_count')[:1]
        cls.cashier = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Payment integrity cashier', 'login': 'payment-integrity-%s' % uuid4().hex,
            'company_id': cls.company.id, 'company_ids': [Command.set(cls.company.ids)],
            'group_ids': [Command.set([
                cls.env.ref('base.group_user').id,
                cls.env.ref('point_of_sale.group_pos_user').id,
            ])],
        })

    def setUp(self):
        super().setUp()
        self.Pos = self.env['pos.order'].with_user(self.cashier).with_context(
            allowed_company_ids=self.company.ids,
        )
        self.assertFalse(self.Pos.env.su)
        self.assertFalse(self.cashier.has_group('point_of_sale.group_pos_manager'))
        self.assertFalse(self.config.baseer_direct_print_enabled)

    def _line(self, quantity=1, price=100, tax=None, discount=0):
        tax = self.tax if tax is None else tax
        # Native taxes supply the frozen line fields; no local VAT formula.
        totals = tax.compute_all(
            price * (1 - discount / 100), self.currency, quantity,
            product=self.product,
        )
        return {
            'uuid': str(uuid4()), 'product_id': self.product.id, 'qty': quantity,
            'price_unit': price, 'discount': discount,
            'price_subtotal': totals['total_excluded'],
            'price_subtotal_incl': totals['total_included'],
            'tax_ids': [Command.set(tax.ids)], 'full_product_name': self.product.display_name,
        }

    def _draft(self, lines=None):
        order = self.Pos.create({
            'uuid': str(uuid4()), 'session_id': self.session.id, 'user_id': self.cashier.id,
            'amount_total': 0, 'amount_tax': 0, 'amount_paid': 0, 'amount_return': 0,
            'lines': [Command.create(line) for line in (lines if lines is not None else [self._line()])],
        })
        order._compute_prices()
        return order

    def _payload(self, order=None, lines=None, total=115, tax=15):
        return {
            'uuid': order.uuid if order else str(uuid4()), 'session_id': self.session.id,
            'company_id': self.company.id, 'user_id': self.cashier.id, 'state': 'paid',
            'amount_total': total, 'amount_tax': tax, 'amount_paid': total, 'amount_return': 0,
            'lines': lines if lines is not None else [Command.create(self._line())],
            'payment_ids': [Command.create({
                'payment_method_id': self.method.id, 'amount': total,
                'payment_date': fields.Datetime.now(),
            })],
        }

    def _snapshot(self):
        """Observable writes must all roll back with the rejected sync."""
        self.env.flush_all()
        result = {}
        for table in ('pos_order', 'pos_order_line', 'pos_payment', 'account_move',
                      'account_move_line', 'stock_picking', 'baseer_print_job'):
            self.env.cr.execute('SELECT row_to_json(t)::text FROM "%s" t ORDER BY id' % table)
            result[table] = self.env.cr.fetchall()
        return result

    def _reject_sync(self, payload):
        before = self._snapshot()
        with self.assertRaisesRegex(ValidationError, 'items'), self.env.cr.savepoint():
            self.Pos.sync_from_ui([deepcopy(payload)])
        self.assertEqual(before, self._snapshot())

    def _pay(self, order, amount=None, method=None):
        amount = order.amount_total if amount is None else amount
        self.env['pos.payment'].with_user(self.cashier).create({
            'pos_order_id': order.id, 'payment_method_id': (method or self.method).id,
            'amount': amount,
        })
        order.amount_paid = order._compute_amount_paid()
        frozen = (order.amount_total, order.amount_tax, order.amount_paid, order.amount_return,
                  order.lines.read(['price_subtotal', 'price_subtotal_incl']))
        order.action_pos_order_paid()
        self.assertEqual(order.state, 'paid')
        self.assertEqual(frozen, (
            order.amount_total, order.amount_tax, order.amount_paid, order.amount_return,
            order.lines.read(['price_subtotal', 'price_subtotal_incl']),
        ))

    def _rounding(self, only_cash=False, strategy='add_invoice_line'):
        rounding = self.env['account.cash.rounding'].create({
            'name': 'Payment integrity nickel', 'rounding': 0.05,
            'rounding_method': 'HALF-UP', 'strategy': strategy,
            'profit_account_id': self.income.id, 'loss_account_id': self.income.id,
        })
        self.config.write({
            'cash_rounding': True, 'only_round_cash_method': only_cash,
            'rounding_method': rounding.id,
        })
        return rounding

    @contextmanager
    def _hidden(self, record):
        rule = self.env['ir.rule'].create({
            'name': 'Payment integrity hidden source',
            'model_id': self.env['ir.model']._get_id(record._name),
            'domain_force': repr([('id', '!=', record.id)]),
            'perm_read': True, 'perm_write': False, 'perm_create': False, 'perm_unlink': False,
        })
        self.env.invalidate_all()
        try:
            self.assertFalse(record.with_user(self.cashier).search([('id', '=', record.id)]))
            yield
        finally:
            rule.unlink()
            self.env.invalidate_all()

    def test_new_nonzero_paid_without_items_rolls_back(self):
        self._reject_sync(self._payload(lines=[]))

    def test_clear_all_items_and_pay_rolls_back(self):
        order = self._draft()
        self._reject_sync(self._payload(order, lines=[Command.clear()]))
        self.assertEqual(order.state, 'draft')
        self.assertEqual(len(order.lines), 1)

    def test_delete_all_items_and_pay_rolls_back(self):
        order = self._draft()
        self._reject_sync(self._payload(order, lines=[Command.delete(order.lines.id)]))

    def test_missing_draft_items_with_stale_headers_rolls_back(self):
        order = self._draft()
        order.lines.unlink()
        self.assertEqual(order.amount_total, 115)
        self._reject_sync(self._payload(order, lines=[]))

    def test_nonempty_wrong_gross_and_tax_roll_back(self):
        for total, tax in ((114, 15), (115, 14), (100, 0)):
            with self.subTest(total=total, tax=tax):
                self._reject_sync(self._payload(total=total, tax=tax))

    def test_empty_zero_headers_cannot_hide_offsetting_tenders(self):
        order = self._draft(lines=[])
        for amount in (10, -10):
            self.env['pos.payment'].with_user(self.cashier).create({
                'pos_order_id': order.id, 'payment_method_id': self.method.id, 'amount': amount,
            })
        before = self._snapshot()
        with self.assertRaisesRegex(ValidationError, 'no items'), self.env.cr.savepoint():
            order.action_pos_order_paid()
        self.assertEqual(before, self._snapshot())

    def test_hidden_line_cannot_validate_a_partial_header(self):
        order = self._draft([self._line(), self._line(price=50)])
        hidden = order.lines[-1:]
        order.write({'amount_total': 115, 'amount_tax': 15, 'amount_paid': 115})
        self.env['pos.payment'].with_user(self.cashier).create({
            'pos_order_id': order.id, 'payment_method_id': self.method.id, 'amount': 115,
        })
        with self._hidden(hidden):
            before = self._snapshot()
            with self.assertRaises(AccessError), self.env.cr.savepoint():
                order.action_pos_order_paid()
            self.assertEqual(before, self._snapshot())

    def test_hidden_payment_does_not_prove_empty_tenders(self):
        order = self._draft(lines=[])
        hidden = self.env['pos.payment'].with_user(self.cashier).create({
            'pos_order_id': order.id, 'payment_method_id': self.method.id, 'amount': 10,
        })
        with self._hidden(hidden):
            before = self._snapshot()
            with self.assertRaises(AccessError), self.env.cr.savepoint():
                order.action_pos_order_paid()
            self.assertEqual(before, self._snapshot())

    def test_hidden_group_child_tax_cannot_prove_payment(self):
        self._assert_hidden_child_tax_rejected(partial_header=False)

    def test_hidden_direct_tax_cannot_validate_tampered_partial_header(self):
        order = self._draft()
        order.write({'amount_total': 100, 'amount_tax': 0, 'amount_paid': 100})
        self.env['pos.payment'].with_user(self.cashier).create({
            'pos_order_id': order.id, 'payment_method_id': self.method.id, 'amount': 100,
        })
        with self._hidden(self.tax):
            before = self._snapshot()
            with self.assertRaises(AccessError), self.env.cr.savepoint():
                order.action_pos_order_paid()
            self.assertEqual(before, self._snapshot())

    def test_hidden_group_child_tax_cannot_validate_tampered_partial_header(self):
        self._assert_hidden_child_tax_rejected(partial_header=True)

    def _assert_hidden_child_tax_rejected(self, partial_header):
        group = self.env['account.tax'].create({
            'name': 'Payment integrity grouped VAT', 'amount_type': 'group',
            'type_tax_use': 'sale', 'company_id': self.company.id,
            'children_tax_ids': [Command.set(self.tax.ids)],
        })
        order = self._draft([self._line(tax=group)])
        if partial_header:
            order.write({'amount_total': 100, 'amount_tax': 0})
        self.env['pos.payment'].with_user(self.cashier).create({
            'pos_order_id': order.id, 'payment_method_id': self.method.id,
            'amount': order.amount_total,
        })
        order.amount_paid = order._compute_amount_paid()
        with self._hidden(self.tax):
            before = self._snapshot()
            with self.assertRaises(AccessError), self.env.cr.savepoint():
                order.action_pos_order_paid()
            self.assertEqual(before, self._snapshot())

    def test_native_cashier_ui_sale_succeeds(self):
        payload = self._payload()
        self.Pos.sync_from_ui([deepcopy(payload)])
        order = self.Pos.search([('uuid', '=', payload['uuid'])])
        self.assertEqual(order.state, 'paid')
        self.assertEqual((order.amount_total, order.amount_tax), (115, 15))

    def test_native_taxes_discount_refund_and_mixed_return_succeed(self):
        original = self._draft()
        self._pay(original)
        refund_line = self._line(quantity=-1)
        refund_line['refunded_orderline_id'] = original.lines.id
        fixtures = (
            [self._line(price=115, tax=self.included_tax, discount=10)],
            [self._line(quantity=-1)],
            [refund_line],
            [self._line(quantity=-1), self._line(quantity=2)],
            [self._line(quantity=-2), self._line(quantity=1)],
        )
        for lines in fixtures:
            with self.subTest(lines=lines):
                self._pay(self._draft(lines))

    def test_native_global_rounding_and_per_line_rounding_succeed(self):
        for method in ('round_per_line', 'round_globally'):
            self.company.tax_calculation_rounding_method = method
            order = self._draft([self._line(price=0.05), self._line(price=0.05)])
            self._pay(order)

    def test_zero_gift_and_zero_empty_order_succeed(self):
        for lines in ([self._line(price=0)], []):
            self._pay(self._draft(lines))

    def test_native_backend_cash_rounding_and_ui_header_succeed(self):
        self._rounding()
        backend = self._draft([self._line(price=10.02, tax=self.env['account.tax'])])
        self.assertEqual(backend.amount_total, 10)
        self._pay(backend)
        payload = self._payload(
            lines=[Command.create(self._line(price=10.02, tax=self.env['account.tax']))],
            total=10.02, tax=0,
        )
        payload['payment_ids'][0][2]['amount'] = 10
        self.Pos.sync_from_ui([deepcopy(payload)])
        ui_order = self.Pos.search([('uuid', '=', payload['uuid'])])
        self.assertEqual((ui_order.state, ui_order.amount_total, ui_order.amount_paid), ('paid', 10.02, 10))
        self._reject_sync(self._payload(
            lines=[Command.create(self._line(price=10.02, tax=self.env['account.tax']))],
            total=10.01, tax=0,
        ))

    def test_only_cash_rounding_preserves_native_header(self):
        self._rounding(only_cash=True)
        order = self._draft([self._line(price=10.02, tax=self.env['account.tax'])])
        self.assertEqual(order.amount_total, 10.02)
        self.assertTrue(self.cash_method)
        self._pay(order, amount=10, method=self.cash_method)

    def test_native_pos_rejects_biggest_tax_rounding_strategy(self):
        before = self.config.read(['cash_rounding', 'only_round_cash_method', 'rounding_method'])
        with self.assertRaisesRegex(ValidationError, 'Add a rounding line'), self.env.cr.savepoint():
            self._rounding(only_cash=True, strategy='biggest_tax')
        self.assertEqual(before, self.config.read([
            'cash_rounding', 'only_round_cash_method', 'rounding_method',
        ]))

    def test_supported_taxed_cash_native_pairs_and_mismatch(self):
        self._rounding()
        backend = self._draft([self._line(price=100.02)])
        self.assertEqual((backend.amount_total, backend.amount_tax), (115, 15))
        self._pay(backend)
        payload = self._payload(
            lines=[Command.create(self._line(price=100.02))], total=115.02, tax=15,
        )
        payload['payment_ids'][0][2]['amount'] = 115
        self.Pos.sync_from_ui([deepcopy(payload)])
        order = self.Pos.search([('uuid', '=', payload['uuid'])])
        self.assertEqual((order.state, order.amount_total, order.amount_tax), ('paid', 115.02, 15))
        self._reject_sync(self._payload(
            lines=[Command.create(self._line(price=100.02))], total=115.02, tax=14.98,
        ))
        self._reject_sync(self._payload(
            lines=[Command.create(self._line(price=100.02))], total=115.01, tax=15,
        ))

    def test_native_cash_rounding_refund_backend_and_ui_succeed(self):
        self._rounding()
        no_tax = self.env['account.tax']
        backend = self._draft([self._line(quantity=-1, price=10.02, tax=no_tax)])
        self.assertEqual(backend.amount_total, -10)
        self._pay(backend)
        payload = self._payload(
            lines=[Command.create(self._line(quantity=-1, price=10.02, tax=no_tax))],
            total=-10.02, tax=0,
        )
        payload['payment_ids'][0][2]['amount'] = -10
        self.Pos.sync_from_ui([deepcopy(payload)])
        order = self.Pos.search([('uuid', '=', payload['uuid'])])
        self.assertEqual((order.state, order.amount_total, order.amount_paid), ('paid', -10.02, -10))

    def test_paid_late_clear_is_ignored_and_native_unlink_stays_blocked(self):
        payload = self._payload()
        self.Pos.sync_from_ui([deepcopy(payload)])
        order = self.Pos.search([('uuid', '=', payload['uuid'])])
        before = self._snapshot()
        self.Pos.sync_from_ui([self._payload(order, lines=[Command.clear()])])
        self.assertEqual(before, self._snapshot())
        with self.assertRaises(UserError), self.env.cr.savepoint():
            order.lines.unlink()
        self.assertEqual(before, self._snapshot())

