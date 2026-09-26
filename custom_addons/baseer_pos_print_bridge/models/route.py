from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class BaseerPrintRoute(models.Model):
    """Internal POS-owned preparation binding; never a stand-alone daily menu."""

    _name = 'baseer.print.route'
    _description = 'Baseer POS Preparation Binding'
    _order = 'pos_config_id, printer_id, priority, pos_category_id, id'
    _check_company_auto = False

    name = fields.Char(compute='_compute_name', store=True)
    # Preserves PRINT-1 data. New values are copied from pos_config by the server.
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    pos_config_id = fields.Many2one('pos.config', required=True, ondelete='restrict', index=True)
    ticket_type = fields.Selection([('receipt', 'Receipt'), ('preparation', 'Preparation')],
                                   required=True, default='preparation', index=True)
    pos_category_id = fields.Many2one('pos.category', ondelete='restrict', string='POS Category')
    printer_id = fields.Many2one('baseer.print.printer', required=True, ondelete='restrict', index=True)
    copies = fields.Integer(required=True, default=1)
    priority = fields.Integer(required=True, default=10)
    active = fields.Boolean(default=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('pos_config_id'):
                config = self.env['pos.config'].browse(vals['pos_config_id'])
                vals['company_id'] = config.company_id.id
            vals.setdefault('ticket_type', 'preparation')
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('pos_config_id'):
            vals['company_id'] = self.env['pos.config'].browse(vals['pos_config_id']).company_id.id
        return super().write(vals)

    @api.depends('pos_config_id', 'pos_category_id', 'printer_id')
    def _compute_name(self):
        for record in self:
            record.name = '%s · %s · %s' % (
                record.pos_config_id.display_name or '', record.pos_category_id.display_name or '',
                record.printer_id.display_name or '',
            )

    @api.constrains('pos_config_id', 'printer_id', 'copies', 'priority', 'ticket_type')
    def _check_binding(self):
        for record in self:
            if record.ticket_type != 'preparation':
                raise ValidationError(_('Receipt routing is configured directly on the point of sale.'))
            if not 1 <= record.copies <= 10:
                raise ValidationError(_('Copies must be between 1 and 10.'))
            if not 1 <= record.priority <= 99:
                raise ValidationError(_('Priority must be between 1 and 99.'))
            if not record.printer_id._allows_company(record.pos_config_id.company_id):
                raise ValidationError(_('This Windows printer is not authorized for the point-of-sale company.'))

    @api.constrains('pos_config_id', 'pos_category_id', 'active')
    def _check_duplicate(self):
        for record in self.filtered('active'):
            duplicate = self.search([
                ('id', '!=', record.id), ('active', '=', True), ('ticket_type', '=', 'preparation'),
                ('pos_config_id', '=', record.pos_config_id.id), ('pos_category_id', '=', record.pos_category_id.id),
            ], limit=1)
            if duplicate:
                raise ValidationError(_('Only one active preparation binding may use this POS category.'))

    @api.model
    def _select_binding(self, config, categories):
        bindings = self.sudo().search([
            ('pos_config_id', '=', config.id), ('ticket_type', '=', 'preparation'), ('active', '=', True),
            ('printer_id.active', '=', True), ('printer_id.agent_id.active', '=', True),
        ], order='priority, id')
        candidates = bindings.filtered(lambda binding: binding.pos_category_id in categories)
        return candidates[:1] or bindings.filtered(lambda binding: not binding.pos_category_id)[:1]
