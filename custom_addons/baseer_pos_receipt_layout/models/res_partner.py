from odoo import models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def _load_pos_data_fields(self, config):
        """Load the mobile field only for the customer-details receipt layout."""
        fields_to_load = super()._load_pos_data_fields(config)
        if (config and config.baseer_receipt_layout_mode == 'baseer_80_customer'
                and 'mobile' in self._fields and 'mobile' not in fields_to_load):
            fields_to_load = [*fields_to_load, 'mobile']
        return fields_to_load
