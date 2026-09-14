import math

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

    @staticmethod
    def _check_finite_target_amount(value):
        """Reject values PostgreSQL/Odoo cannot safely round before insertion."""
        try:
            amount = float(value)
        except (TypeError, ValueError):
            amount = None
        if isinstance(value, bool) or amount is None or not math.isfinite(amount) or amount < 0:
            raise ValidationError(_('The target amount must be a finite, non-negative number.'))

    @api.model_create_multi
    def create(self, values_list):
        for values in values_list:
            if 'target_amount' in values:
                self._check_finite_target_amount(values['target_amount'])
        return super().create(values_list)

    def write(self, values):
        if 'target_amount' in values:
            self._check_finite_target_amount(values['target_amount'])
        return super().write(values)

    @api.constrains('year', 'month', 'weekday', 'target_amount')
    def _check_target_scope(self):
        for record in self:
            if record.year < 1 or record.year > 9999:
                raise ValidationError(_('Choose a valid calendar year for this target.'))
            if not 1 <= record.month <= 12:
                raise ValidationError(_('Choose a calendar month from January to December.'))
            if not 0 <= record.weekday <= 6:
                raise ValidationError(_('Choose one named weekday for this target.'))
            self._check_finite_target_amount(record.target_amount)
