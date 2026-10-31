from odoo import fields, models


class PosConfig(models.Model):
    _inherit = 'pos.config'

    baseer_default_customer_id = fields.Many2one(
        'res.partner',
        string='Default customer',
        check_company=True,
        help='This visible customer is selected only on new POS orders. The cashier can change it before payment.',
    )

    def get_limited_partners_loading(self, offset=0):
        partner_ids = super().get_limited_partners_loading(offset)
        if offset:
            return partner_ids
        default_partner = self.baseer_default_customer_id
        if default_partner and (default_partner.id,) not in partner_ids:
            partner_ids.append((default_partner.id,))
        return partner_ids

    def _load_pos_data_read(self, records, config):
        payload = super()._load_pos_data_read(records, config)
        if payload:
            payload[0]['baseer_default_customer_id'] = self.baseer_default_customer_id.id
        return payload
