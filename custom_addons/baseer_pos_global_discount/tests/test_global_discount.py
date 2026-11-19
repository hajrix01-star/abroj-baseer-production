from uuid import uuid4

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged

from ..models.pos_order import _number


@tagged('post_install', '-at_install')
class TestGlobalDiscount(TransactionCase):
    def setUp(self):
        super().setUp()
        self.account = self.env['account.account'].create({
            'name': 'GD QA revenue', 'code': 'GDQA001', 'account_type': 'income',
            'company_ids': [Command.set(self.env.company.ids)],
        })
        self.env.company.currency_id.rounding = 0.01
        self.tax = self.env['account.tax'].create({
            'name': 'GD VAT15', 'amount_type': 'percent', 'amount': 15,
            'type_tax_use': 'sale', 'company_id': self.env.company.id,
        })
        self.zero = self.env['account.tax'].create({
            'name': 'GD explicit zero', 'amount_type': 'percent', 'amount': 0,
            'type_tax_use': 'sale', 'company_id': self.env.company.id,
        })
        self.product = self.env['product.product'].create({
            'name': 'GD QA product', 'type': 'service', 'available_in_pos': True,
            'list_price': 100, 'property_account_income_id': self.account.id,
            'taxes_id': [Command.set(self.tax.ids)],
        })
        self.config = self.env['pos.config'].create({
            'name': 'GD QA register', 'baseer_global_discount_account_id': self.account.id,
        })
        self.config.action_baseer_setup_global_discount()
        self.config.baseer_global_discount_product_id.property_account_income_id = self.account
        self.config.open_ui()
        self.config.current_session_id.state = 'opened'

    def _order(self, *, price=100, qty=1, tax=None):
        tax = self.tax if tax is None else tax
        order = self.env['pos.order'].create({
            'session_id': self.config.current_session_id.id, 'company_id': self.env.company.id,
            'amount_total': 0, 'amount_tax': 0, 'amount_paid': 0, 'amount_return': 0,
            'lines': [Command.create({'product_id': self.product.id, 'uuid': str(uuid4()),
                                     'qty': qty, 'price_unit': price, 'price_subtotal': price * qty,
                                     'price_subtotal_incl': price * qty,
                                     'tax_ids': [Command.set(tax.ids)]})],
        })
        order._compute_prices()
        return order

    def _apply(self, order, value='10', kind='percent', action_uuid=None):
        return order.baseer_apply_global_discount(kind, value, 'QA approved discount', action_uuid or str(uuid4()), order._baseer_revision())

    def _paid(self, order):
        # Only the fixture skips payment processing; tests inspect immutable tax/refund contracts.
        order._gd_internal().write({'state': 'paid'})

    def _refund(self, order, quantity, source=None):
        source = source if source is not None else order.lines.filtered(lambda line: not line.baseer_global_discount_line).ensure_one()
        refund = self.env['pos.order'].create({
            'session_id': self.config.current_session_id.id, 'company_id': self.env.company.id,
            'amount_total': 0, 'amount_tax': 0, 'amount_paid': 0, 'amount_return': 0,
            'is_refund': True, 'fiscal_position_id': order.fiscal_position_id.id,
            'lines': [Command.create({'product_id': source.product_id.id, 'qty': -quantity,
                                     'price_unit': source.price_unit, 'discount': source.discount,
                                     'price_subtotal': 0, 'price_subtotal_incl': 0,
                                     'tax_ids': [Command.set(source.tax_ids.ids)],
                                     'refunded_orderline_id': source.id})],
        })
        refund._compute_prices()
        return refund

    def _prepare(self, refund):
        return refund.baseer_prepare_global_discount_refund(str(uuid4()), refund._baseer_revision())

    def _combo_order(self, *, parent_qty=1, ordinary=False, child_b_tax=None):
        """Real native choices: first component has quantity 2 per combo."""
        order = self._order(price=50)
        if not ordinary:
            order.lines.unlink()
        first_product = self.env['product.product'].create({
            'name': 'GD combo first component', 'type': 'service', 'available_in_pos': True,
            'list_price': 30, 'standard_price': 0,
            'property_account_income_id': self.product.property_account_income_id.id,
            'taxes_id': [Command.set(self.tax.ids)],
        })
        second_product = self.env['product.product'].create({
            'name': 'GD combo second component', 'type': 'service', 'available_in_pos': True,
            'list_price': 40, 'standard_price': 0,
            'property_account_income_id': self.product.property_account_income_id.id,
            'taxes_id': [Command.set((child_b_tax if child_b_tax is not None else self.tax).ids)],
        })
        first_choice, second_choice = self.env['product.combo'].create([
            {'name': 'GD first choice', 'company_id': order.company_id.id, 'qty_max': 2, 'qty_free': 2,
             'combo_item_ids': [Command.create({'product_id': first_product.id})]},
            {'name': 'GD second choice', 'company_id': order.company_id.id,
             'combo_item_ids': [Command.create({'product_id': second_product.id})]},
        ])
        parent_product = self.env['product.product'].create({
            'name': 'GD native combo', 'type': 'combo', 'available_in_pos': True, 'list_price': 100,
            'company_id': order.company_id.id,
            'combo_ids': [Command.set((first_choice | second_choice).ids)],
            'property_account_income_id': self.product.property_account_income_id.id,
            'taxes_id': [Command.clear()],
        })
        parent = self.env['pos.order.line'].create({
            'order_id': order.id, 'product_id': parent_product.id, 'qty': parent_qty, 'price_unit': 0,
            'discount': 0, 'price_subtotal': 0, 'price_subtotal_incl': 0, 'tax_ids': [Command.clear()],
            'combo_line_ids': [Command.create({
                'order_id': order.id, 'product_id': product.id, 'combo_item_id': choice.combo_item_ids.id,
                'qty': ratio * parent_qty, 'price_unit': price, 'discount': 0,
                'price_subtotal': 0, 'price_subtotal_incl': 0,
                'tax_ids': [Command.set(product.taxes_id.ids)],
            }) for product, choice, ratio, price in (
                (first_product, first_choice, 2, 30), (second_product, second_choice, 1, 40),
            )],
        })
        order._compute_prices()
        return order, parent

    def _combo_refund(self, order, parent, qty, *, ordinary=False):
        refund = self._refund(order, qty, parent)
        refund_parent = refund.lines.ensure_one()
        for source in parent.combo_line_ids:
            self.env['pos.order.line'].create({
                'order_id': refund.id, 'product_id': source.product_id.id,
                'qty': -(source.qty / parent.qty) * qty, 'price_unit': source.price_unit,
                'discount': source.discount, 'tax_ids': [Command.set(source.tax_ids.ids)],
                'price_subtotal': 0, 'price_subtotal_incl': 0,
                'refunded_orderline_id': source.id, 'combo_parent_id': refund_parent.id,
                # Native TicketScreen deliberately does not copy combo_item_id.
            })
        if ordinary:
            for source in order.lines.filtered(lambda line: not line.baseer_global_discount_line
                                                and not line.combo_parent_id and line != parent):
                self.env['pos.order.line'].create({
                    'order_id': refund.id, 'product_id': source.product_id.id,
                    'qty': -(source.qty / parent.qty) * qty, 'price_unit': source.price_unit,
                    'discount': source.discount, 'tax_ids': [Command.set(source.tax_ids.ids)],
                    'price_subtotal': 0, 'price_subtotal_incl': 0, 'refunded_orderline_id': source.id,
                })
        refund._compute_prices()
        return refund

    def test_native_combo_and_ordinary_fixed_one_basket_discount(self):
        order, parent = self._combo_order(ordinary=True)
        original_values = [(line.id, line.price_unit, line.discount) for line in order.lines]
        self.assertAlmostEqual(order.amount_total, 172.50, places=2)
        self._apply(order, '20', 'fixed')
        self.assertAlmostEqual(order.amount_total, 152.50, places=2)
        self.assertAlmostEqual(order.amount_tax, 19.89, places=2)
        sources = order.lines.filtered(lambda line: not line.baseer_global_discount_line)
        self.assertEqual(original_values, [(line.id, line.price_unit, line.discount) for line in sources])
        self.assertNotIn(parent, order.lines.filtered('baseer_global_discount_line').baseer_global_discount_source_id)

    def test_native_combo_and_ordinary_percentage_discount(self):
        order, _parent = self._combo_order(ordinary=True)
        self._apply(order, '10', 'percent')
        self.assertAlmostEqual(order.amount_total, 155.25, places=2)
        self.assertAlmostEqual(order.amount_tax, 20.25, places=2)

    def test_native_combo_mixed_tax_basket(self):
        order, _parent = self._combo_order(ordinary=True, child_b_tax=self.zero)
        self.assertAlmostEqual(order.amount_total, 166.50, places=2)
        self._apply(order, '20', 'fixed')
        self.assertAlmostEqual(order.amount_total, 146.50, places=2)
        self.assertAlmostEqual(order.amount_tax, 14.52, places=2)
        self.assertEqual(set(order.lines.filtered('baseer_global_discount_line').tax_ids.ids), set((self.tax | self.zero).ids))

    def test_native_combo_full_refund_infers_original_items(self):
        order, parent = self._combo_order(ordinary=True)
        self._apply(order, '20', 'fixed')
        self._paid(order)
        refund = self._combo_refund(order, parent, 1, ordinary=True)
        children = refund.lines.filtered('combo_parent_id')
        self.assertFalse(children.combo_item_id)
        self._prepare(refund)
        self.assertAlmostEqual(refund.amount_total, -order.amount_total, places=2)
        self.assertAlmostEqual(refund.amount_tax, -order.amount_tax, places=2)
        for child in children:
            self.assertEqual(child.combo_item_id, child.refunded_orderline_id.combo_item_id)
        sections = [item[2] for item in refund._prepare_invoice_lines('out_refund') if item[2].get('display_type') == 'line_section']
        self.assertEqual(len(sections), 1)
        with self.assertRaises(ValidationError):
            children[:1].write({'combo_item_id': False})

    def test_native_combo_successive_partial_refunds_use_historical_group(self):
        order, parent = self._combo_order(parent_qty=3)
        self._apply(order, '0.97', 'fixed')
        self._paid(order)
        # Removing a choice from the current catalog must not redefine the sale.
        parent.product_id.combo_ids = parent.product_id.combo_ids[:1]
        refunds = self.env['pos.order']
        for _index in range(3):
            refund = self._combo_refund(order, parent, 1)
            self._prepare(refund)
            self._paid(refund)
            refunds |= refund
        self.assertAlmostEqual(sum(refunds.mapped('amount_total')), -order.amount_total, places=2)
        self.assertAlmostEqual(sum(refunds.mapped('amount_tax')), -order.amount_tax, places=2)
        self.assertAlmostEqual(sum(refunds.mapped('baseer_global_discount_gross')), .97, places=2)

    def test_native_combo_malformed_sale_topology_rejected(self):
        for mutation in ('price', 'discount', 'subtotal', 'orphan', 'membership', 'cross_order', 'cycle', 'fixed_tax'):
            with self.subTest(mutation=mutation), self.assertRaises(ValidationError), self.cr.savepoint():
                order, parent = self._combo_order()
                first, second = parent.combo_line_ids
                if mutation == 'price':
                    parent.price_unit = 1
                elif mutation == 'discount':
                    parent.discount = 1
                elif mutation == 'subtotal':
                    parent.price_subtotal_incl = 1
                elif mutation == 'orphan':
                    first.combo_parent_id = False
                elif mutation == 'membership':
                    first.combo_item_id = second.combo_item_id
                elif mutation == 'cross_order':
                    first.order_id = self._order().id
                elif mutation == 'cycle':
                    parent.combo_parent_id = first
                else:
                    parent.tax_ids = self.env['account.tax'].create({
                        'name': 'GD combo fixed zero', 'amount_type': 'fixed', 'amount': 0,
                        'type_tax_use': 'sale', 'company_id': self.env.company.id,
                    })
                self._apply(order)

    def test_native_combo_sale_choice_quantity_bounds_and_required_choices(self):
        for mutation in ('below_minimum', 'above_maximum', 'missing_required_choice'):
            with self.subTest(mutation=mutation), self.assertRaises(ValidationError), self.cr.savepoint():
                order, parent = self._combo_order(parent_qty=2)
                first, second = parent.combo_line_ids
                if mutation == 'below_minimum':
                    first.qty = 2  # First choice requires 2 units per parent: 4 sold.
                elif mutation == 'above_maximum':
                    first.qty = 6
                else:
                    second.unlink()
                self._apply(order)

    def test_native_combo_refund_requires_complete_group_and_original_ratios(self):
        order, parent = self._combo_order(parent_qty=2)
        self._apply(order, '20', 'fixed')
        self._paid(order)
        for mutation in ('missing_parent', 'missing_child', 'ratio', 'membership', 'cross_order', 'cycle'):
            with self.subTest(mutation=mutation), self.assertRaises(ValidationError), self.cr.savepoint():
                refund = self._combo_refund(order, parent, 1)
                refund_parent = refund.lines.filtered(lambda line: line.product_id.type == 'combo')
                first, second = refund_parent.combo_line_ids
                if mutation == 'missing_parent':
                    refund_parent.unlink()
                elif mutation == 'missing_child':
                    first.unlink()
                elif mutation == 'ratio':
                    first.qty = -1
                elif mutation == 'membership':
                    first.combo_item_id = second.refunded_orderline_id.combo_item_id
                elif mutation == 'cross_order':
                    first.order_id = self._order().id
                else:
                    refund_parent.combo_parent_id = first
                self._prepare(refund)

    def test_percent_tax_excluded(self):
        order = self._order()
        self._apply(order)
        self.assertAlmostEqual(order.amount_total, 103.50, places=2)
        self.assertAlmostEqual(order.amount_tax, 13.50, places=2)
        self.assertAlmostEqual(order.baseer_global_discount_gross, 11.50, places=2)
        self.assertTrue(order.baseer_global_discount_locked)
        self.assertTrue(order.lines.filtered('baseer_global_discount_line').extra_tax_data)

    def test_account_is_pinned_and_drift_blocks_sale_but_removal_recovers(self):
        order = self._order()
        self._apply(order, '20', 'fixed')
        self.assertEqual(self.config.baseer_global_discount_account_id, self.account)
        self.assertEqual(self.config.baseer_global_discount_product_id.property_account_income_id, self.account)
        changed = self.account.copy({'code': 'GDQA002'})
        self.config.baseer_global_discount_product_id.property_account_income_id = changed
        with self.assertRaises(ValidationError):
            order._gd_assert_snapshot()
        self._apply(order, '0', 'remove')
        self.assertFalse(order.baseer_global_discount_locked)
        self.assertAlmostEqual(order.amount_total, 115, places=2)

    def test_account_history_change_blocks_refund_and_legacy_snapshot_remains_readable(self):
        order = self._order()
        self._apply(order)
        self._paid(order)
        old = dict(order.baseer_global_discount_snapshot)
        old['tax_configuration'] = [entry for entry in old['tax_configuration'] if '_gd_accounts' not in entry]
        order._gd_internal().write({'baseer_global_discount_snapshot': old})
        order._gd_assert_snapshot()
        # No history is invented for the old snapshot, but current policy still
        # requires the selected account to agree with the service product.
        product = self.config.baseer_global_discount_product_id
        product.property_account_income_id = self.account.copy({'code': 'GDQA003'})
        with self.assertRaises(ValidationError):
            self._prepare(self._refund(order, 1))

    def test_fiscal_mapping_of_discount_to_expense_is_rejected(self):
        expense = self.account.copy({'code': 'GDQA004', 'account_type': 'expense'})
        position = self.env['account.fiscal.position'].create({
            'name': 'GD invalid income mapping',
            'account_ids': [Command.create({'account_src_id': self.account.id, 'account_dest_id': expense.id})],
        })
        order = self._order()
        order.fiscal_position_id = position
        with self.assertRaises(ValidationError):
            self._apply(order)

    def test_loader_retains_native_bootstrap_fields(self):
        [payload] = self.config._load_pos_data_read(self.config, self.config)
        for key in ('currency_id', 'use_pricelist', 'name', 'baseer_global_discount_enabled',
                    'baseer_global_discount_product_id'):
            self.assertIn(key, payload)
        order = self._order()
        data = order.read_pos_data([], self.config)
        self.assertIn('session_id', data['pos.order'][0])
        self.assertIn('baseer_global_discount_locked', data['pos.order'][0])

    def test_fixed_means_exact_gross(self):
        order = self._order()
        self._apply(order, '20', 'fixed')
        self.assertAlmostEqual(order.amount_total, 95, places=2)
        self.assertAlmostEqual(order.amount_tax, 12.39, places=2)
        self.assertAlmostEqual(order.baseer_global_discount_gross, 20, places=2)

    def test_reason_is_optional_and_audit_is_automatic(self):
        order = self._order()
        command = str(uuid4())
        order.baseer_apply_global_discount('fixed', '20', '', command, order._baseer_revision())
        self.assertAlmostEqual(order.amount_total, 95, places=2)
        event = self.env['baseer.pos.global.discount.event'].search([('action_uuid', '=', command)])
        self.assertEqual(event.create_uid, self.env.user)
        self.assertTrue(event.create_date)
        self.assertEqual(event.payload['value'], '20')
        self.assertEqual(event.payload['reason'], '')

    def test_existing_discount_can_be_removed_after_settings_are_disabled(self):
        order = self._order()
        self._apply(order, '20', 'fixed')
        self.config.baseer_global_discount_enabled = False
        order.baseer_apply_global_discount('remove', '0', '', str(uuid4()), order._baseer_revision())
        self.assertFalse(order.baseer_global_discount_locked)
        self.assertAlmostEqual(order.amount_total, 115, places=2)

    def test_tax_included(self):
        self.tax.price_include_override = 'tax_included'
        order = self._order(price=115)
        self._apply(order)
        self.assertAlmostEqual(order.amount_total, 103.50, places=2)
        self.assertAlmostEqual(order.amount_tax, 13.50, places=2)

    def test_mixed_tax_categories_fixed(self):
        order = self._order()
        self.env['pos.order.line'].create({
            'order_id': order.id, 'product_id': self.product.id, 'qty': 1, 'price_unit': 100,
            'price_subtotal': 100, 'price_subtotal_incl': 100, 'tax_ids': [Command.set(self.zero.ids)],
        })
        self._apply(order, '20', 'fixed')
        self.assertAlmostEqual(order.amount_total, 195, places=2)
        self.assertEqual(len(order.lines.filtered('baseer_global_discount_line')), 2)
        self.assertEqual(set(order.lines.filtered('baseer_global_discount_line').mapped('baseer_global_discount_source_id').ids),
                         set(order.lines.filtered(lambda line: not line.baseer_global_discount_line).ids))

    def test_remove_replace_and_retry_preserve_audit(self):
        order = self._order()
        command = str(uuid4())
        revision = order._baseer_revision()
        first = order.baseer_apply_global_discount('fixed', '20', 'QA', command, revision)
        retry = order.baseer_apply_global_discount('fixed', '20', 'QA', command, revision)
        self.assertEqual(first['action_uuid'], retry['action_uuid'])
        self.assertEqual(len(order.lines), 2)
        self._apply(order, '5', 'fixed')
        self.assertAlmostEqual(order.amount_total, 110, places=2)
        self._apply(order, '0', 'remove')
        self.assertFalse(order.baseer_global_discount_locked)
        self.assertEqual(len(order.lines), 1)
        self.assertAlmostEqual(order.amount_total, 115, places=2)
        self.assertEqual(self.env['baseer.pos.global.discount.event'].search_count([('order_id', '=', order.id)]), 3)

    def test_limits_fixed_and_percent(self):
        self.config.baseer_global_discount_max_percent = 5
        order = self._order()
        for kind, value in [('percent', '6'), ('fixed', '6')]:
            with self.assertRaises(ValidationError), self.cr.savepoint():
                self._apply(order, value, kind)
        self.config.baseer_global_discount_max_amount = 2
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self._apply(order, '3', 'fixed')

    def test_raw_decimal_rejection(self):
        for raw in [True, 10, 'NaN', 'Infinity', '1e2', '-1', '1.001', '١٠', '', '9' * 33]:
            with self.assertRaises(ValidationError):
                _number(raw)
        self.assertEqual(str(_number('10.25')), '10.25')

    def test_direct_metadata_and_context_forgery_rejected(self):
        order = self._order()
        with self.assertRaises(AccessError):
            order.with_context(_baseer_global_discount_token=True).write({'baseer_global_discount_gross': 1})
        with self.assertRaises(ValidationError):
            order.lines.write({'baseer_global_discount_line': True})
        with self.assertRaises(AccessError):
            self.env['baseer.pos.global.discount.event'].create({
                'order_id': order.id, 'action_uuid': str(uuid4()), 'fingerprint': 'forged', 'payload': {},
            })

    def test_frozen_basket_direct_crud_and_headers(self):
        order = self._order()
        self._apply(order)
        source = order.lines.filtered(lambda line: not line.baseer_global_discount_line)
        for values in [{'qty': 2}, {'price_unit': 1}, {'discount': 1}, {'tax_ids': [Command.clear()]}, {'order_id': self._order().id}]:
            with self.assertRaises(ValidationError), self.cr.savepoint():
                source.write(values)
        with self.assertRaises(ValidationError):
            source.unlink()
        with self.assertRaises(ValidationError):
            order.write({'is_refund': True})
        with self.assertRaises(ValidationError):
            order.write({'amount_total': 1})
        outsider = self._order()
        with self.assertRaises(ValidationError):
            outsider.lines.write({'order_id': order.id})
        with self.assertRaises(ValidationError):
            self.env['pos.order.line'].create({'order_id': order.id, 'product_id': self.product.id, 'qty': 1, 'price_unit': 1,
                                              'price_subtotal': 1, 'price_subtotal_incl': 1})

    def test_stale_revision_and_disabled_and_paid(self):
        order = self._order()
        with self.assertRaises(ValidationError):
            order.baseer_apply_global_discount('fixed', '1', 'QA', str(uuid4()), 'stale')
        self.config.baseer_global_discount_enabled = False
        with self.assertRaises(AccessError):
            self._apply(order)
        self.config.baseer_global_discount_enabled = True
        self._paid(order)
        with self.assertRaises(AccessError):
            self._apply(order)

    def test_unsupported_protected_special_or_unclassified_tax(self):
        order = self._order()
        self.product.baseer_substitution_enabled = True
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self._apply(order)
        self.product.baseer_substitution_enabled = False
        fixed = self.env['account.tax'].create({
            'name': 'GD unsupported fixed', 'amount_type': 'fixed', 'amount': 1,
            'type_tax_use': 'sale', 'company_id': self.env.company.id,
        })
        order.lines.tax_ids = fixed
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self._apply(order)
        order.lines.tax_ids = False
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self._apply(order)

    def test_full_refund_and_invoice_line_tax_parity(self):
        order = self._order()
        self._apply(order, '20', 'fixed')
        self._paid(order)
        refund = self._refund(order, 1)
        self._prepare(refund)
        self.assertAlmostEqual(refund.amount_total, -order.amount_total, places=2)
        self.assertAlmostEqual(refund.amount_tax, -order.amount_tax, places=2)
        allowance = refund.lines.filtered('baseer_global_discount_line')
        self.assertEqual(allowance.refunded_orderline_id, order.lines.filtered('baseer_global_discount_line'))
        self.assertEqual(refund.refunded_order_id, order)
        invoice_values = refund._prepare_invoice_lines('out_refund')
        self.assertTrue(all(command[2].get('extra_tax_data') for command in invoice_values if command[2].get('product_id')))

    def test_successive_partial_refunds_take_base_and_tax_residual(self):
        order = self._order(price=0.05, qty=3)
        self._apply(order, '0.02', 'fixed')
        self._paid(order)
        refunds = self.env['pos.order']
        for _index in range(3):
            refund = self._refund(order, 1)
            self._prepare(refund)
            self._paid(refund)
            refunds |= refund
        self.assertAlmostEqual(sum(refunds.mapped('amount_total')), -order.amount_total, places=2)
        self.assertAlmostEqual(sum(refunds.mapped('amount_tax')), -order.amount_tax, places=2)
        self.assertAlmostEqual(sum(refunds.mapped('baseer_global_discount_gross')), order.baseer_global_discount_gross, places=2)

    def test_second_draft_reservation_is_rejected(self):
        order = self._order(qty=2)
        self._apply(order)
        self._paid(order)
        first = self._refund(order, 1)
        self._prepare(first)
        second = self._refund(order, 1)
        with self.assertRaises(ValidationError):
            self._prepare(second)

    def test_refund_requires_preparation_and_original_price(self):
        order = self._order()
        self._apply(order)
        self._paid(order)
        refund = self._refund(order, 1)
        with self.assertRaises(ValidationError):
            refund.write({'state': 'paid'})
        refund.lines.price_unit = 1
        with self.assertRaises(ValidationError):
            self._prepare(refund)

    def test_global_rounding_multiple_sources_refunds_match_original(self):
        self.env.company.tax_calculation_rounding_method = 'round_globally'
        order = self._order(price=0.03)
        for _index in range(2):
            self.env['pos.order.line'].create({
                'order_id': order.id, 'product_id': self.product.id, 'qty': 1, 'price_unit': 0.03,
                'price_subtotal': 0.03, 'price_subtotal_incl': 0.03, 'tax_ids': [Command.set(self.tax.ids)],
            })
        self._apply(order, '0.01', 'fixed')
        self._paid(order)
        refunds = self.env['pos.order']
        for source in order.lines.filtered(lambda line: not line.baseer_global_discount_line):
            refund = self._refund(order, 1, source)
            self._prepare(refund)
            self._paid(refund)
            refunds |= refund
        self.assertAlmostEqual(sum(refunds.mapped('amount_total')), -order.amount_total, places=2)
        self.assertAlmostEqual(sum(refunds.mapped('amount_tax')), -order.amount_tax, places=2)

    def test_tax_label_change_allowed_financial_change_requires_removal(self):
        order = self._order()
        self._apply(order)
        self.tax.name = 'Renamed label only'
        order._gd_assert_snapshot()
        # Native Odoo correctly refuses editing a tax already used by POS.
        with self.assertRaises(UserError), self.cr.savepoint():
            self.tax.amount = 10
        current_rounding = self.env.company.tax_calculation_rounding_method
        self.env.company.tax_calculation_rounding_method = (
            'round_globally' if current_rounding == 'round_per_line' else 'round_per_line'
        )
        with self.assertRaises(ValidationError):
            order._gd_assert_snapshot()
        self._apply(order, '0', 'remove')
        self.assertFalse(order.baseer_global_discount_locked)
        self.assertAlmostEqual(order.amount_total, 115, places=2)

    def test_cancelled_prepared_refund_cannot_revive_after_reallocation(self):
        order = self._order()
        self._apply(order)
        self._paid(order)
        first = self._refund(order, 1)
        self._prepare(first)
        first.write({'state': 'cancel'})
        second = self._refund(order, 1)
        self._prepare(second)
        self._paid(second)
        for state in ('draft', 'paid'):
            with self.assertRaises(ValidationError):
                first.write({'state': state})

    def test_native_sync_echo_with_raw_tax_id_arrays(self):
        order = self._order()
        self._apply(order)
        payload = {
            'uuid': order.uuid, 'session_id': order.session_id.id, 'company_id': order.company_id.id,
            'state': 'draft', 'amount_total': order.amount_total, 'amount_tax': order.amount_tax,
            'amount_paid': 0, 'amount_return': 0, 'payment_ids': [],
            'lines': [Command.update(line.id, {
                'uuid': line.uuid, 'product_id': line.product_id.id, 'qty': line.qty,
                'price_unit': line.price_unit, 'discount': line.discount, 'tax_ids': line.tax_ids.ids,
                'price_subtotal': line.price_subtotal, 'price_subtotal_incl': line.price_subtotal_incl,
                'extra_tax_data': line.extra_tax_data,
                'baseer_global_discount_line': line.baseer_global_discount_line,
                'baseer_global_discount_source_id': line.baseer_global_discount_source_id.id or False,
            }) for line in order.lines],
        }
        result = self.env['pos.order'].sync_from_ui([payload])
        self.assertEqual(result['pos.order'][0]['id'], order.id)
        self.assertAlmostEqual(order.amount_total, 103.50, places=2)

    def test_cashier_rpc_settings_permissions_and_event_company_isolation(self):
        user = self.env['res.users'].create({
            'name': 'GD cashier', 'login': 'gd-cashier-qa',
            'group_ids': [Command.set([self.env.ref('base.group_user').id,
                                       self.env.ref('point_of_sale.group_pos_user').id])],
            'company_id': self.env.company.id, 'company_ids': [Command.set(self.env.company.ids)],
        })
        order = self._order()
        self._apply(order.with_user(user))
        for values in ({'baseer_global_discount_enabled': False}, {'baseer_global_discount_max_percent': 99}):
            with self.assertRaises(AccessError):
                self.config.with_user(user).write(values)
        with self.assertRaises(AccessError):
            self.env['pos.config'].with_user(user).create({'name': 'Unauthorized', 'baseer_global_discount_enabled': True})
        other = self.env['res.company'].create({'name': 'GD other company'})
        outsider = self.env['res.users'].create({
            'name': 'GD other cashier', 'login': 'gd-other-cashier-qa',
            'group_ids': [Command.set([self.env.ref('base.group_user').id,
                                       self.env.ref('point_of_sale.group_pos_user').id])],
            'company_id': other.id, 'company_ids': [Command.set(other.ids)],
        })
        events = self.env['baseer.pos.global.discount.event'].with_user(outsider)
        self.assertFalse(events.search([('order_id', '=', order.id)]))
        with self.assertRaises(AccessError):
            order.with_user(outsider).baseer_read_global_discount_state()

    def test_native_credit_note_lineage_and_sa_return_reason(self):
        self.env.company.country_id = self.env.ref('base.sa')
        partner = self.env['res.partner'].create({'name': 'GD return customer', 'country_id': self.env.ref('base.sa').id})
        order = self._order()
        order.partner_id = partner
        self._apply(order, '20', 'fixed')
        invoice = self.env['account.move'].create(order._prepare_invoice_vals())
        order._gd_internal().write({'account_move': invoice.id})
        self._paid(order)
        refund = self._refund(order, 1)
        refund.partner_id = partner
        self._prepare(refund)
        values = refund._prepare_invoice_vals()
        self.assertEqual(values['move_type'], 'out_refund')
        self.assertEqual(values['reversed_entry_id'], invoice.id)
        self.assertIn(invoice.id, values['pos_refunded_invoice_ids'])
        if 'l10n_sa_reason' in self.env['account.move']._fields:
            self.assertEqual(values['l10n_sa_reason'], 'BR-KSA-17-reason-4')
        else:
            self.assertNotIn('l10n_sa_reason', values)
