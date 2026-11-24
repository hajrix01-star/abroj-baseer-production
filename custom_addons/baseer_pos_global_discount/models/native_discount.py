from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo import _


class PosConfig(models.Model):
    _inherit = 'pos.config'

    baseer_fixed_discount_enabled = fields.Boolean(string='Fixed discount enabled')
    baseer_fixed_discount_max_amount = fields.Monetary(string='Maximum fixed discount', currency_field='currency_id', help='Zero means no additional cap.')
    baseer_fixed_discount_allowed = fields.Selection([('all', 'All cashiers allowed to discount'), ('managers', 'Managers only')], default='managers', required=True, string='Fixed discount access')

    @api.constrains('baseer_fixed_discount_max_amount')
    def _check_fixed_discount_max_amount(self):
        if any(config.baseer_fixed_discount_max_amount < 0 for config in self):
            raise ValidationError(_('The fixed discount limit cannot be negative.'))

    @api.model
    def _load_pos_data_fields(self, config):
        result = super()._load_pos_data_fields(config)
        return list(dict.fromkeys(result + ['baseer_fixed_discount_enabled', 'baseer_fixed_discount_max_amount', 'baseer_fixed_discount_allowed'])) if result else result


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pos_baseer_fixed_discount_enabled = fields.Boolean(related='pos_config_id.baseer_fixed_discount_enabled', readonly=False)
    pos_baseer_fixed_discount_max_amount = fields.Monetary(related='pos_config_id.baseer_fixed_discount_max_amount', readonly=False, currency_field='baseer_global_discount_currency_id')
    pos_baseer_fixed_discount_allowed = fields.Selection(related='pos_config_id.baseer_fixed_discount_allowed', readonly=False)


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    baseer_discount_kind = fields.Selection([('percent', 'Percentage'), ('fixed', 'Fixed amount')], string='Discount kind')
    baseer_discount_input = fields.Float(string='Discount input')
    baseer_discount_approved_by_user_id = fields.Many2one('res.users', string='Discount approving user')
    baseer_discount_approved_by_employee = fields.Integer(string='Discount approving employee ID')
    baseer_discount_approved_by_employee_name = fields.Char(string='Discount approving employee')

    @api.model
    def _load_pos_data_fields(self, config):
        result = super()._load_pos_data_fields(config)
        return list(dict.fromkeys(result + ['baseer_discount_kind', 'baseer_discount_input', 'baseer_discount_approved_by_user_id', 'baseer_discount_approved_by_employee', 'baseer_discount_approved_by_employee_name'])) if result else result
