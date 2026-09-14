from psycopg2 import IntegrityError

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

from .occasion import HEAT_CALENDAR_MANAGER_GROUP


WEEKDAY_SELECTION = [
    ('5', 'Saturday'),
    ('6', 'Sunday'),
    ('0', 'Monday'),
    ('1', 'Tuesday'),
    ('2', 'Wednesday'),
    ('3', 'Thursday'),
    ('4', 'Friday'),
]

MONTH_SELECTION = [
    ('1', 'January'), ('2', 'February'), ('3', 'March'), ('4', 'April'),
    ('5', 'May'), ('6', 'June'), ('7', 'July'), ('8', 'August'),
    ('9', 'September'), ('10', 'October'), ('11', 'November'), ('12', 'December'),
]


class HeatCalendarTargetWizard(models.TransientModel):
    _name = 'baseer.heat.calendar.target.wizard'
    _description = 'Set heat calendar target'

    @api.model
    def _weekday_selection(self):
        return [(value, _(label)) for value, label in WEEKDAY_SELECTION]

    @api.model
    def _month_selection(self):
        return [(value, _(label)) for value, label in MONTH_SELECTION]

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, readonly=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)
    year = fields.Integer(
        string='Year', required=True,
        default=lambda self: fields.Date.context_today(self).year,
    )
    month = fields.Selection(
        selection='_month_selection', string='Month', required=True,
        default=lambda self: str(fields.Date.context_today(self).month),
    )
    weekday = fields.Selection(
        selection='_weekday_selection', string='Day of week', required=True,
    )
    target_amount = fields.Monetary(
        string='Target amount', required=True, currency_field='currency_id',
    )
    active = fields.Boolean(string='Active', default=True)
    scope_message = fields.Char(compute='_compute_scope_message')

    @api.model
    def _is_manager(self):
        return (self.env.user.has_group('base.group_system')
                or self.env.user.has_group(HEAT_CALENDAR_MANAGER_GROUP))

    def _check_scope_access(self):
        self.ensure_one()
        if not self._is_manager():
            raise AccessError(_('Only a heat calendar manager can set targets.'))
        if self.company_id not in self.env.companies:
            raise AccessError(_('Choose a company available in the current session.'))

    def _existing_target_for_scope(self):
        """Return the single target for this exact scope, if it exists."""
        self.ensure_one()
        if not (self.company_id and self.year and self.month and self.weekday):
            return self.env['baseer.heat.calendar.target']
        return self.env['baseer.heat.calendar.target'].with_context(
            active_test=False,
        ).search([
            ('company_id', '=', self.company_id.id),
            ('year', '=', self.year),
            ('month', '=', int(self.month)),
            ('weekday', '=', int(self.weekday)),
        ], limit=1)

    @api.model_create_multi
    def create(self, values_list):
        if not self._is_manager():
            raise AccessError(_('Only a heat calendar manager can set targets.'))
        for values in values_list:
            company = self.env['res.company'].browse(
                values.get('company_id') or self.env.company.id
            )
            if company not in self.env.companies:
                raise AccessError(_('Choose a company available in the current session.'))
        return super().create(values_list)

    @api.model
    def default_get(self, field_names):
        # The action itself is intentionally a normal Odoo action.  Enforce
        # the manager boundary before its form can be opened, not only when a
        # save button is pressed through the dashboard.
        if not self._is_manager():
            raise AccessError(_('Only a heat calendar manager can set targets.'))
        values = super().default_get(field_names)
        company = self.env['res.company'].browse(
            values.get('company_id') or self.env.company.id
        )
        if company not in self.env.companies:
            raise AccessError(_('Choose a company available in the current session.'))
        return values

    @api.depends('company_id', 'year', 'month', 'weekday')
    def _compute_scope_message(self):
        month_names = dict(MONTH_SELECTION)
        weekday_names = dict(WEEKDAY_SELECTION)
        for wizard in self:
            if wizard.company_id and wizard.year and wizard.month and wizard.weekday:
                weekday_label = _(weekday_names.get(wizard.weekday, wizard.weekday))
                month_label = _(month_names.get(wizard.month, wizard.month))
                wizard.scope_message = _(
                    'One target only: %(company)s — %(weekday)s, %(month)s %(year)s.',
                    company=wizard.company_id.display_name,
                    weekday=weekday_label,
                    month=month_label,
                    year=wizard.year,
                )
            else:
                wizard.scope_message = _('Choose the company, month, and weekday.')

    @api.onchange('company_id', 'year', 'month', 'weekday')
    def _onchange_scope(self):
        """Load an existing rule before the manager changes it.

        Reopening a Thursday or Friday scope must never silently replace its
        amount with zero.  A new scope keeps the form defaults; an exact
        existing scope is presented as an edit of that one rule.
        """
        for wizard in self:
            if not wizard.company_id or wizard.company_id not in self.env.companies:
                continue
            existing = wizard._existing_target_for_scope()
            if existing:
                wizard.target_amount = existing.target_amount
                wizard.active = existing.active

    def action_apply(self):
        """Create or update exactly one company/month/weekday target.

        The unique database constraint remains the concurrency authority.  A
        simultaneous insert is retried as an update, so the manager never
        needs to resolve a duplicate rule manually.
        """
        self.ensure_one()
        self._check_scope_access()
        Target = self.env['baseer.heat.calendar.target']
        Target.check_access('create')
        scope = {
            'company_id': self.company_id.id,
            'year': self.year,
            'month': int(self.month),
            'weekday': int(self.weekday),
        }
        values = {**scope, 'target_amount': self.target_amount, 'active': self.active}
        existing = self._existing_target_for_scope()
        if existing:
            existing.check_access('write')
            existing.write(values)
        else:
            try:
                with self.env.cr.savepoint():
                    Target.create(values)
            except IntegrityError:
                # A simultaneous manager created the exact same rule.  The
                # unique constraint chose the winner; update it within this
                # request rather than showing a duplicate-rule dead end.
                existing = self._existing_target_for_scope()
                if not existing:
                    raise
                existing.check_access('write')
                existing.write(values)
        return {'type': 'ir.actions.act_window_close'}
