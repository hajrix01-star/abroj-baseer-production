from odoo import _, fields, models
from odoo.exceptions import UserError


class PosConfig(models.Model):
    _inherit = 'pos.config'

    baseer_zatca_phase2_enabled = fields.Boolean(
        string='Enable ZATCA Phase 2 POS invoicing',
        help='Require invoices and ZATCA reporting for this POS only.',
        default=False,
    )

    def _load_pos_data_fields(self, config):
        return [*super()._load_pos_data_fields(config), 'baseer_zatca_phase2_enabled']


class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _generate_pos_order_invoice(self):
        if any(not order.config_id.baseer_zatca_phase2_enabled for order in self):
            raise UserError(_("ZATCA POS invoicing is not enabled for this point of sale."))
        return super()._generate_pos_order_invoice()
