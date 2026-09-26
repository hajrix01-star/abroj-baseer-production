from odoo import models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def _load_pos_data_fields(self, config):
        """The POS receipt uses the native partner phone field in Odoo 19."""
        fields_to_load = super()._load_pos_data_fields(config)
        return fields_to_load
