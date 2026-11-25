"""Historical discount links remain readable and allocated in POS reporting."""
from odoo import Command
from odoo.tests.common import TransactionCase, tagged
from .test_global_discount import TestGlobalDiscount


@tagged('post_install', '-at_install')
class TestHistoricalReporting(TransactionCase):
    _order = TestGlobalDiscount._order

    def setUp(self):
        super().setUp()
        self.tax = self.env['account.tax'].create({'name': 'History VAT', 'amount': 0, 'type_tax_use': 'sale'})
        self.product = self.env['product.product'].create({'name': 'History item', 'type': 'service', 'available_in_pos': True})
        self.allowance = self.env['product.product'].create({'name': 'Old discount', 'type': 'service', 'available_in_pos': True, 'company_id': self.env.company.id})
        self.config = self.env['pos.config'].create({'name': 'History register', 'baseer_global_discount_product_id': self.allowance.id})
        self.config.open_ui()
        self.config.current_session_id.state = 'opened'

    def test_historical_allocation_and_stored_metadata(self):
        order = self._order()
        source = order.lines
        allowance = self.env['pos.order.line'].sudo().create({
            'order_id': order.id, 'product_id': self.allowance.id, 'qty': 1, 'price_unit': -10,
            'price_subtotal': -10, 'price_subtotal_incl': -10, 'tax_ids': [Command.clear()],
            'baseer_global_discount_line': True, 'baseer_global_discount_source_id': source.id,
        })
        order.sudo().write({'baseer_global_discount_locked': True, 'baseer_global_discount_kind': 'fixed',
                            'baseer_global_discount_value': '10', 'baseer_global_discount_gross': 10,
                            'baseer_global_discount_snapshot': {'history': True}})
        order._compute_prices()
        self.env.flush_all()
        rows = self.env['report.pos.order'].search([('order_id', '=', order.id)])
        self.assertEqual(rows.ids, source.ids)
        self.assertAlmostEqual(sum(rows.mapped('baseer_invoice_discount')), 10)
        self.assertTrue(order.baseer_global_discount_locked)
        self.assertEqual(order.baseer_global_discount_snapshot, {'history': True})
        self.assertEqual(allowance.baseer_global_discount_source_id, source)

    def _payload(self, order):
        return {'uuid': order.uuid, 'session_id': order.session_id.id, 'company_id': order.company_id.id,
                'state': 'draft', 'amount_total': order.amount_total, 'amount_tax': order.amount_tax,
                'amount_paid': 0, 'amount_return': 0, 'payment_ids': [], 'lines': []}

    def test_old_transport_keys_are_ignored_without_mutating_payload(self):
        order = self._order()
        payload = self._payload(order)
        payload.update({'baseer_offline_draft_command': {'revision': 3},
                        'baseer_offline_discount_intent': False,
                        'baseer_offline_discount_digest': 'old'})
        self.env['pos.order'].sync_from_ui([payload])
        self.assertIn('baseer_offline_draft_command', payload)
        self.assertEqual(order.lines.product_id, self.product)

    def test_legacy_refund_blocked_in_sync_and_direct_create(self):
        from odoo.exceptions import UserError
        order = self._order()
        source = order.lines
        order.sudo().write({'baseer_global_discount_locked': True})
        refund = self._order()
        values = {'product_id': self.product.id, 'qty': -1, 'price_unit': 100,
                  'price_subtotal': -100, 'price_subtotal_incl': -100,
                  'refunded_orderline_id': source.id}
        with self.assertRaisesRegex(UserError, 'old invoice discount'):
            self.env['pos.order.line'].create(dict(values, order_id=refund.id))
        payload = self._payload(refund)
        payload['lines'] = [Command.create(values)]
        with self.assertRaisesRegex(UserError, 'old invoice discount'):
            self.env['pos.order'].sync_from_ui([payload])

    def test_new_legacy_discount_lines_and_financial_intent_blocked(self):
        from odoo.exceptions import UserError
        order = self._order()
        payload = self._payload(order)
        payload['lines'] = [Command.create({'product_id': self.allowance.id, 'qty': 1,
                           'price_unit': -10, 'baseer_global_discount_line': True})]
        with self.assertRaisesRegex(UserError, 'old invoice discount'):
            self.env['pos.order'].sync_from_ui([payload])
        payload['lines'][0][2].pop('baseer_global_discount_line')
        with self.assertRaisesRegex(UserError, 'old invoice discount'):
            self.env['pos.order'].sync_from_ui([payload])
        payload['lines'] = []
        payload['baseer_offline_discount_intent'] = {'kind': 'fixed', 'value': '10'}
        with self.assertRaisesRegex(UserError, 'old invoice discount'):
            self.env['pos.order'].sync_from_ui([payload])
        payload['baseer_offline_discount_intent'] = False
        payload['baseer_offline_draft_kind'] = 'fixed'
        with self.assertRaisesRegex(UserError, 'old invoice discount'):
            self.env['pos.order'].sync_from_ui([payload])
        payload['baseer_offline_draft_kind'] = False
        old_line = self.env['pos.order.line'].sudo().create({
            'order_id': order.id, 'product_id': self.allowance.id, 'qty': 1, 'price_unit': -10,
            'price_subtotal': -10, 'price_subtotal_incl': -10, 'baseer_global_discount_line': True,
        })
        payload['lines'] = [Command.delete(old_line.id)]
        with self.assertRaisesRegex(UserError, 'old invoice discount'):
            self.env['pos.order'].sync_from_ui([payload])
        self.assertTrue(old_line.exists())

    def test_checkout_checks_only_draft_transition(self):
        from odoo.exceptions import UserError
        order = self._order()
        order.sudo().write({'baseer_global_discount_locked': True})
        with self.assertRaisesRegex(UserError, 'old invoice discount'):
            order.write({'state': 'paid'})
        order.write({'state': 'cancel'})
        order.write({'state': 'paid'})
        order.write({'state': 'done'})
        order.write({'account_move': False})
        self.assertEqual(order.state, 'done')

    def test_pos_javascript_bundle_compiles(self):
        bundle = self.env['ir.qweb']._get_asset_bundle(
            'point_of_sale._assets_pos', css=False, js=True, debug_assets=False,
        )
        self.assertTrue(any(asset.url and 'legacy_history_guard.js' in asset.url for asset in bundle.javascripts))
        self.assertTrue(bundle.js())
