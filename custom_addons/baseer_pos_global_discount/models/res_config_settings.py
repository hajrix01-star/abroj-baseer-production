from odoo import _, api, fields, models
from odoo.exceptions import AccessError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pos_baseer_global_discount_max_percent = fields.Float(
        related='pos_config_id.baseer_global_discount_max_percent', readonly=False,
    )
    pos_baseer_global_discount_max_amount = fields.Monetary(
        related='pos_config_id.baseer_global_discount_max_amount', readonly=False,
        currency_field='baseer_global_discount_currency_id',
    )
    baseer_global_discount_currency_id = fields.Many2one(related='pos_config_id.currency_id')
    pos_baseer_global_discount_enabled = fields.Boolean(related='pos_config_id.baseer_global_discount_enabled')
    pos_baseer_global_discount_product_id = fields.Many2one(related='pos_config_id.baseer_global_discount_product_id')

    @api.model
    def _gd_check_settings_actor(self):
        if not self.env.user.has_group('point_of_sale.group_pos_manager'):
            raise AccessError(_('Only a POS manager can configure invoice discounts.'))

    def _gd_apply_native_discount_choice(self, enabled):
        """Only an explicit save of this selected POS opts into the managed path."""
        self._gd_check_settings_actor()
        for settings in self:
            config = settings.pos_config_id
            if not config:
                continue
            config.check_access('write')
            if config.company_id not in self.env.companies:
                raise AccessError(_('This point of sale does not belong to an allowed company.'))
            if enabled:
                config.action_baseer_setup_global_discount()
            else:
                config.write({'baseer_global_discount_enabled': False})

    @api.model
    def _gd_preserve_native_product_on_disable(self, values, config):
        # Native settings derives an empty product when its switch is off.
        # That empty DTO is not an instruction to erase the historical product.
        if ('pos_module_pos_discount' in values and not values['pos_module_pos_discount']
                and 'pos_discount_product_id' in values and not values['pos_discount_product_id']
                and config):
            config.check_access('write')
            if config.discount_product_id:
                values['pos_discount_product_id'] = config.discount_product_id.id

    @api.model_create_multi
    def create(self, values_list):
        # Native POS create consumes pos_* values. Capture the explicit switch
        # before it does so; merely opening settings must not enable other POS.
        choices = [values.get('pos_module_pos_discount')
                   if values.get('pos_config_id') and 'pos_module_pos_discount' in values else None
                   for values in values_list]
        if any(value is not None for value in choices):
            self._gd_check_settings_actor()
        for values in values_list:
            if values.get('pos_config_id'):
                self._gd_preserve_native_product_on_disable(
                    values, self.env['pos.config'].browse(values['pos_config_id']))
        result = super().create(values_list)
        for settings, enabled in zip(result, choices):
            if enabled is not None:
                settings._gd_apply_native_discount_choice(bool(enabled))
        return result

    def write(self, values):
        explicit = 'pos_module_pos_discount' in values and bool(self.filtered('pos_config_id'))
        if explicit:
            self._gd_check_settings_actor()
        if (explicit and not values['pos_module_pos_discount']
                and 'pos_discount_product_id' in values and not values['pos_discount_product_id']):
            result = True
            for settings in self:
                preserved = dict(values)
                settings._gd_preserve_native_product_on_disable(preserved, settings.pos_config_id)
                result = super(ResConfigSettings, settings).write(preserved) and result
        else:
            result = super().write(values)
        if explicit:
            self._gd_apply_native_discount_choice(bool(values['pos_module_pos_discount']))
        return result
