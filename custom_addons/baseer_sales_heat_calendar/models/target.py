import math
from decimal import Decimal, InvalidOperation

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
    def _validate_target_amount(value):
        """Return a safe two-decimal Decimal for every target write path.

        ``fields.Monetary`` is stored by Odoo as a float, so accepting a
        browser float without a Decimal boundary would allow rounding drift
        and non-finite values to enter the persistent target table.  Keep the
        persistent field for Odoo compatibility, but make this one validator
        the authority for direct CRUD, the legacy wizard, and batch RPC.
        """
        if isinstance(value, bool):
            raise ValidationError(_(
                'The target amount must be a finite, non-negative number with at most two decimal places.'
            ))
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            amount = None
        if amount is None or not amount.is_finite() or amount < 0:
            raise ValidationError(_(
                'The target amount must be a finite, non-negative number with at most two decimal places.'
            ))
        try:
            rounded = amount.quantize(Decimal('0.01'))
            stored_amount = float(rounded)
        except (InvalidOperation, OverflowError, ValueError):
            raise ValidationError(_(
                'The target amount must be a finite, non-negative number with at most two decimal places.'
            ))
        if not math.isfinite(stored_amount) or amount != rounded:
            raise ValidationError(_(
                'The target amount must be a finite, non-negative number with at most two decimal places.'
            ))
        return rounded

    @classmethod
    def _check_finite_target_amount(cls, value):
        """Compatibility name retained for existing callers and migrations."""
        return cls._validate_target_amount(value)

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
