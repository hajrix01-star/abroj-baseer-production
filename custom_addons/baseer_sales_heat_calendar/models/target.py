from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HeatCalendarTarget(models.Model):
    _name = 'baseer.heat.calendar.target'
    _description = 'Heat calendar sales target'
    _order = 'company_id, year desc, month desc, weekday desc, id desc'

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True, ondelete='cascade',
    )
    currency_id = fields.Many2one(
        related='company_id.currency_id', string='Currency', readonly=True,
    )
    year = fields.Integer(
        string='Year', required=True,
        default=lambda self: fields.Date.context_today(self).year,
        help='This target applies to one calendar year.',
    )
    month = fields.Integer(
        string='Month', required=True,
        default=lambda self: fields.Date.context_today(self).month,
        help='This target applies to one calendar month.',
    )
    weekday = fields.Integer(
        string='Weekday', required=True, default=0,
        help='This target applies to one weekday. The setup dialog shows the day by name.',
    )
    target_amount = fields.Monetary(
        string='Target amount', required=True, currency_field='currency_id',
    )
    active = fields.Boolean(string='Active', default=True)

    _target_scope_unique = models.Constraint(
        'unique(company_id, year, month, weekday)', 'Only one target is allowed for this scope.'
    )

    @api.constrains('year', 'month', 'weekday', 'target_amount')
    def _check_target_scope(self):
        for record in self:
            if record.year < 1 or record.year > 9999:
                raise ValidationError(_('Choose a valid calendar year for this target.'))
            if not 1 <= record.month <= 12:
                raise ValidationError(_('Choose a calendar month from January to December.'))
            if not 0 <= record.weekday <= 6:
                raise ValidationError(_('Choose one named weekday for this target.'))
            if record.target_amount < 0:
                raise ValidationError(_('The target amount cannot be negative.'))
