from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .company import RECEIPT_LAYOUT_MODES


class PosConfig(models.Model):
    _inherit = 'pos.config'

    baseer_receipt_layout_mode = fields.Selection(
        RECEIPT_LAYOUT_MODES, string='Customer receipt layout', default='native', required=True,
        help='Original Odoo keeps the native visual layout. Baseer professional 80 mm changes presentation only.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            company_id = (
                values.get('company_id')
                or self.env.context.get('default_company_id')
                or self.env.company.id
            )
            company = self.env['res.company'].browse(company_id).exists()
            if company:
                for field_name, value in company._baseer_receipt_profile_values().items():
                    values.setdefault(field_name, value)
        return super().create(vals_list)

    @api.constrains(
        'baseer_receipt_layout_mode', 'baseer_direct_print_enabled',
        'baseer_native_receipt_enabled', 'baseer_receipt_printer_id',
    )
    def _check_baseer_receipt_layout(self):
        for config in self:
            if config.baseer_receipt_layout_mode != 'baseer_80':
                continue
            if not config.baseer_direct_print_enabled or not config.baseer_native_receipt_enabled:
                raise ValidationError(_(
                    'Enable Baseer direct printing and the original Odoo customer receipt before using the professional layout.'
                ))
            printer = config.baseer_receipt_printer_id
            if not printer or not printer.active or printer.paper_width != '80':
                raise ValidationError(_('The professional receipt layout requires an active 80 mm receipt printer.'))
            if not printer._allows_company(config.company_id):
                raise ValidationError(_('The receipt printer is not authorized for this company.'))

    @api.model
    def _load_pos_data_read(self, records, config):
        values = super()._load_pos_data_read(records, config)
        by_id = {record.id: record for record in records}
        for value in values:
            record = by_id.get(value.get('id'))
            if record:
                value['baseer_receipt_layout_mode'] = record.baseer_receipt_layout_mode
        return values
