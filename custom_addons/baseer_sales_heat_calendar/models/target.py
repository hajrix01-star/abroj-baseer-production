import math
from decimal import Decimal, InvalidOperation

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


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

    @api.model
    def _check_target_company_in_session(self, company_id):
        """Make company isolation explicit for every direct target CRUD path.

        A record rule is not enough for ``create`` because a caller can supply
        a foreign company id before there is a target record to filter.  The
        superuser remains available for installation/migration work; every
        normal manager must use a company explicitly available in the current
        Odoo session.
        """
        if self.env.is_superuser():
            return
        if not company_id or company_id not in self.env.companies.ids:
            raise AccessError(_('Choose a company available in the current session.'))

    @api.model
    def _lock_target_scopes(self, scopes):
        """Serialize target writers by company/year in one shared lock space.

        The batch service, legacy wizard, and raw ORM CRUD all take this lock.
        Sorting the scope pairs keeps cross-scope create/write operations free
        from lock-order deadlocks.
        """
        normalized = set()
        for company_id, year in scopes:
            if (isinstance(company_id, bool) or not isinstance(company_id, int)
                    or isinstance(year, bool) or not isinstance(year, int)):
                continue
            if company_id > 0 and 1 <= year <= 9999:
                normalized.add((company_id, year))
        for company_id, year in sorted(normalized):
            self.env.cr.execute(
                'SELECT pg_advisory_xact_lock(%s, %s)',
                (company_id, year),
            )

    @api.model
    def _target_year_from_values(self, values):
        """Resolve the create default only for advisory-lock scoping."""
        year = values.get('year')
        if year is None:
            year = fields.Date.context_today(self).year
        return year

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
            self._check_target_company_in_session(values.get('company_id'))
            if 'target_amount' in values:
                self._check_finite_target_amount(values['target_amount'])
        self._lock_target_scopes([
            (values.get('company_id'), self._target_year_from_values(values))
            for values in values_list
        ])
        return super().create(values_list)

    def write(self, values):
        if 'target_amount' in values:
            self._check_finite_target_amount(values['target_amount'])
        scope_pairs = []
        for record in self:
            final_company_id = values.get('company_id', record.company_id.id)
            final_year = values.get('year', record.year)
            self._check_target_company_in_session(final_company_id)
            # Lock both sides for a move across company or year so no batch
            # snapshot can race either scope during the mutation.
            scope_pairs.extend([
                (record.company_id.id, record.year),
                (final_company_id, final_year),
            ])
        self._lock_target_scopes(scope_pairs)
        return super().write(values)

    def unlink(self):
        """Keep direct removal in the same write-serialization boundary.

        Batch saves take their snapshot before acquiring the advisory lock.
        A direct delete must therefore lock the affected company/year too, so
        it cannot interleave with a batch save after that snapshot.
        """
        self._lock_target_scopes([
            (record.company_id.id, record.year)
            for record in self
        ])
        return super().unlink()

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
