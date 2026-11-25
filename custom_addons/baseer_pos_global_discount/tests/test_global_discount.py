from uuid import uuid4
from odoo import Command


class TestGlobalDiscount:
    """Shared native order fixtures."""
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

    def _apply(self, *args, **kwargs):
        raise AssertionError('The external acceptance fixture must construct historical discounts directly.')

    def _prepare(self, *args, **kwargs):
        raise AssertionError('Legacy POS refunds are retired.')

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
