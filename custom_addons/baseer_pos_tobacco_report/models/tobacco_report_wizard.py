from datetime import datetime
from zoneinfo import ZoneInfo

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


ACCOUNT_GROUPS = (
    'account.group_account_readonly',
    'account.group_account_invoice',
    'account.group_account_user',
    'account.group_account_manager',
)
POS_GROUPS = ('point_of_sale.group_pos_user', 'point_of_sale.group_pos_manager')
RIYADH = ZoneInfo('Asia/Riyadh')


class BaseerPosTobaccoReportWizard(models.TransientModel):
    _name = 'baseer.pos.tobacco.report.wizard'
    _description = 'POS Tobacco Fee Register Period'

    def _default_date_from(self):
        return datetime.now(RIYADH).date().replace(day=1)

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
        string='Company',
    )
    period = fields.Selection(
        [('month', 'This Month'), ('quarter', 'This Quarter'),
         ('year', 'This Year'), ('custom', 'Custom Range')],
        default='month', required=True, string='Period',
    )
    date_from = fields.Date(required=True, default=_default_date_from, string='From')
    date_to = fields.Date(required=True, default=lambda self: datetime.now(RIYADH).date(), string='To')

    @api.onchange('period')
    def _onchange_period(self):
        today = datetime.now(RIYADH).date()
        if self.period == 'month':
            self.date_from = today.replace(day=1)
            self.date_to = today
        elif self.period == 'quarter':
            self.date_from = today.replace(month=((today.month - 1) // 3) * 3 + 1, day=1)
            self.date_to = today
        elif self.period == 'year':
            self.date_from = today.replace(month=1, day=1)
            self.date_to = today

    def _check_report_access(self):
        self.ensure_one()
        user = self.env.user
        if not any(user.has_group(group) for group in ACCOUNT_GROUPS) or not any(
            user.has_group(group) for group in POS_GROUPS
        ):
            raise AccessError(_('The tobacco fee register requires both Accounting and POS read access.'))
        if self.company_id not in self.env.companies:
            raise AccessError(_('The selected company is not available to your user.'))
        self.env['pos.order'].check_access('read')
        self.env['pos.order.line'].check_access('read')

    def _check_period(self):
        self.ensure_one()
        if not self.date_from or not self.date_to or self.date_from > self.date_to:
            raise ValidationError(_('Enter a valid From and To date.'))
        if (self.date_to - self.date_from).days + 1 > 366:
            raise ValidationError(_('Select at most 366 days. Split a longer period into separate reports.'))

    def action_print_report(self):
        self.ensure_one()
        self.check_access('read')
        self._check_report_access()
        self._check_period()
        return self.env.ref('baseer_pos_tobacco_report.action_report_pos_tobacco_fees').report_action(self)
