from odoo import Command
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBaseerTableAvailability(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['pos.config'].create({
            'name': 'Table availability QA', 'module_pos_restaurant': True,
        })
        cls.floor = cls.env['restaurant.floor'].create({
            'name': 'QA only', 'pos_config_ids': [Command.link(cls.config.id)],
        })
        cls.table = cls.env['restaurant.table'].create({
            'table_number': 1, 'floor_id': cls.floor.id,
        })
        cls.config.open_ui()
        cls.config.current_session_id.write({'state': 'opened'})
        cls.product = cls.env['product.product'].create({
            'name': 'Free item still occupies table', 'available_in_pos': True,
            'list_price': 0,
        })

    def _empty_order(self):
        return self.env['pos.order'].create({
            'session_id': self.config.current_session_id.id,
            'table_id': self.table.id,
            'amount_tax': 0, 'amount_total': 0, 'amount_paid': 0, 'amount_return': 0,
        })

    def test_empty_draft_released_idempotently_without_unlink(self):
        order = self._empty_order()
        self.assertTrue(order.baseer_release_empty_table()['released'])
        self.assertEqual(order.state, 'cancel')
        self.assertTrue(order.exists())
        self.assertTrue(order.baseer_release_empty_table()['released'])

    def test_zero_price_or_refund_lines_are_not_empty(self):
        for quantity in (1, -1, 0):
            order = self._empty_order()
            order.write({'lines': [Command.create({
                'product_id': self.product.id, 'qty': quantity,
                'price_unit': 0, 'price_subtotal': 0, 'price_subtotal_incl': 0,
            })]})
            self.assertFalse(order.baseer_release_empty_table()['released'])
            self.assertEqual(order.state, 'draft')

    def test_payment_or_nonzero_balance_is_not_empty(self):
        order = self._empty_order()
        order.amount_total = 10
        self.assertFalse(order.baseer_release_empty_table()['released'])
        order.amount_total = 0
        self.env['pos.payment'].create({
            'pos_order_id': order.id, 'amount': 0,
            'payment_method_id': self.config.payment_method_ids[:1].id,
        })
        self.assertFalse(order.baseer_release_empty_table()['released'])

    def test_paid_order_is_never_released(self):
        order = self._empty_order()
        order.state = 'paid'
        self.assertFalse(order.baseer_release_empty_table()['released'])
        self.assertEqual(order.state, 'paid')

    def test_native_preparation_or_malformed_baseline_blocks_release(self):
        order = self._empty_order()
        for baseline in ('{"lines":{"old":{"quantity":1}}}', '{bad', '[]'):
            order.last_order_preparation_change = baseline
            self.assertFalse(order.baseer_release_empty_table()['released'])
            self.assertEqual(order.state, 'draft')

    def test_release_rechecks_new_lines(self):
        order = self._empty_order()
        # A second client saved an item after the first client's empty snapshot.
        other_view = self.env['pos.order'].browse(order.id)
        other_view.write({'lines': [Command.create({
            'product_id': self.product.id, 'qty': 1, 'price_unit': 0,
            'price_subtotal': 0, 'price_subtotal_incl': 0,
        })]})
        self.assertFalse(order.baseer_release_empty_table()['released'])
