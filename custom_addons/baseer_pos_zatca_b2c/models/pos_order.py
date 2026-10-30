from odoo import api, models


class PosOrder(models.Model):
    _inherit = 'pos.order'

    @api.model
    def _process_order(self, order, existing_order):
        # Client-side assignment is only a usability aid. This server-side guard
        # preserves the same fiscal route when an offline/stale client submits a
        # final eligible order without the configured internal consumer.
        prepared_order = dict(order)
        session = self.env['pos.session'].browse(prepared_order.get('session_id')).exists()
        if session:
            partner = session.config_id._baseer_zatca_anonymous_partner_for_order(prepared_order)
            if partner:
                prepared_order['partner_id'] = partner.id
        return super()._process_order(prepared_order, existing_order)
