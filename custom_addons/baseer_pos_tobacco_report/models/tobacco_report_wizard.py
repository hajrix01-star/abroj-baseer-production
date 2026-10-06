from calendar import monthrange
from datetime import date, datetime
from zoneinfo import ZoneInfo

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

from .tobacco_report import TobaccoReportTooLarge


ACCOUNT_GROUPS = (
    'account.group_account_readonly',
    'account.group_account_invoice',
    'account.group_account_user',
    'account.group_account_manager',
)
POS_GROUPS = ('point_of_sale.group_pos_user', 'point_of_sale.group_pos_manager')
RIYADH = ZoneInfo('Asia/Riyadh')
PREVIEW_PAGE_SIZE = 100
MONTHS = [
    ('1', 'January'), ('2', 'February'), ('3', 'March'),
    ('4', 'April'), ('5', 'May'), ('6', 'June'),
    ('7', 'July'), ('8', 'August'), ('9', 'September'),
    ('10', 'October'), ('11', 'November'), ('12', 'December'),
]


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
    month = fields.Selection(
        MONTHS, required=True, default=lambda self: str(datetime.now(RIYADH).month),
        string='Month',
    )
    year = fields.Integer(required=True, default=lambda self: datetime.now(RIYADH).year, string='Year')
    show_products = fields.Boolean(string='Show products')
    preview_page = fields.Integer(default=1, string='Page')
    preview_total_pages = fields.Integer(compute='_compute_preview', string='Pages')
    preview_total_rows = fields.Integer(compute='_compute_preview', string='Fee rows')
    preview_overflow = fields.Boolean(compute='_compute_preview')
    preview_html = fields.Html(compute='_compute_preview', sanitize=True, string='Report preview')

    def _month_range(self):
        self.ensure_one()
        if not self.month or not self.year or not 2000 <= self.year <= 2100:
            raise ValidationError(_('Select a year from 2000 to 2100 and a month.'))
        month = int(self.month)
        if not 1 <= month <= 12:
            raise ValidationError(_('Select a year from 2000 to 2100 and a month.'))
        start = date(self.year, month, 1)
        return start, date(self.year, month, monthrange(self.year, month)[1])

    @api.onchange('month', 'year', 'company_id')
    def _onchange_monthly_selection(self):
        self.preview_page = 1
        if self.month and self.year and 2000 <= self.year <= 2100:
            self.date_from, self.date_to = self._month_range()

    @api.depends('month', 'year', 'company_id', 'preview_page', 'show_products')
    def _compute_preview(self):
        for wizard in self:
            wizard.preview_total_pages = 1
            wizard.preview_total_rows = 0
            wizard.preview_overflow = False
            wizard.preview_html = False
            if not wizard.company_id or not wizard.month or not wizard.year:
                continue
            try:
                date_from, date_to = wizard._month_range()
            except ValidationError as error:
                wizard.preview_html = str(error)
                continue
            virtual = self.with_company(wizard.company_id).new({
                'company_id': wizard.company_id.id,
                'period': 'month',
                'date_from': date_from,
                'date_to': date_to,
                'month': wizard.month,
                'year': wizard.year,
                'show_products': wizard.show_products,
            })
            report = self.env['report.baseer_pos_tobacco_report.report_pos_tobacco_fees'].with_company(
                wizard.company_id,
            )
            try:
                data = report._build_report(virtual)
            except TobaccoReportTooLarge:
                wizard.preview_overflow = True
                continue
            count = len(data['rows'])
            pages = max(1, (count + PREVIEW_PAGE_SIZE - 1) // PREVIEW_PAGE_SIZE)
            page = min(max(1, wizard.preview_page), pages)
            start = (page - 1) * PREVIEW_PAGE_SIZE
            preview_data = dict(data, rows=data['rows'][start:start + PREVIEW_PAGE_SIZE],
                                exceptions=data['exceptions'][:PREVIEW_PAGE_SIZE])
            wizard.preview_total_rows = count
            wizard.preview_total_pages = pages
            wizard.preview_html = self.env['ir.qweb']._render(
                'baseer_pos_tobacco_report.preview_pos_tobacco_fees',
                {'report_data': preview_data, 'page': page, 'pages': pages,
                 'first_row': start + 1 if count else 0,
                 'last_row': min(start + PREVIEW_PAGE_SIZE, count)},
            )

    def _reopen_monthly(self):
        self.ensure_one()
        action = self.env.ref('baseer_pos_tobacco_report.action_pos_tobacco_report_wizard').read()[0]
        action['res_id'] = self.id
        return action

    def action_previous_page(self):
        self.ensure_one()
        self._check_report_access()
        if self.preview_page > 1:
            self.preview_page -= 1
        return self._reopen_monthly()

    def action_next_page(self):
        self.ensure_one()
        self._check_report_access()
        if not self.preview_overflow and self.preview_page < self.preview_total_pages:
            self.preview_page += 1
        return self._reopen_monthly()

    def action_open_custom_range(self):
        self.ensure_one()
        self._check_report_access()
        date_from, date_to = self._month_range()
        action = self.env.ref('baseer_pos_tobacco_report.action_pos_tobacco_report_custom_range').read()[0]
        action['context'] = {
            'default_company_id': self.company_id.id,
            'default_period': 'custom',
            'default_date_from': fields.Date.to_string(date_from),
            'default_date_to': fields.Date.to_string(date_to),
            'default_show_products': self.show_products,
        }
        return action

    def action_print_monthly(self):
        self.ensure_one()
        self._check_report_access()
        self.date_from, self.date_to = self._month_range()
        return self.action_print_report()

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
