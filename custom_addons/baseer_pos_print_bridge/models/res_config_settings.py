from odoo import api, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    @api.depends('pos_module_pos_restaurant', 'pos_config_id',
                 'pos_config_id.iface_printbill', 'pos_config_id.iface_splitbill')
    def _compute_pos_module_pos_restaurant(self):
        super()._compute_pos_module_pos_restaurant()
        # Keep the native per-register switches when restaurant mode is off.
        for settings in self.filtered(lambda record: not record.pos_module_pos_restaurant):
            settings.pos_iface_printbill = settings.pos_config_id.iface_printbill
            settings.pos_iface_splitbill = settings.pos_config_id.iface_splitbill
