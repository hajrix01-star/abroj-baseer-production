from calendar import monthrange
from datetime import date, datetime
import base64
from time import monotonic
from zoneinfo import ZoneInfo

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

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
# Stable PostgreSQL int32 namespace, separate from other application advisory locks.
TOBACCO_EXPORT_LOCK_NAMESPACE = 0x42544258
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

    @api.model
    def _hub_wizard_values(self, options):
        """Validate the small, public report contract before making a virtual wizard."""
        if not isinstance(options, dict) or set(options) != {
            'company_id', 'period', 'month', 'year', 'date_from', 'date_to',
            'show_products', 'page',
        }:
            raise ValidationError(_('Invalid report options.'))
        company_id = options['company_id']
        month = options['month']
        year = options['year']
        page = options['page']
        period = options['period']
        if (
            type(company_id) is not int or company_id <= 0
            or type(month) is not int or not 1 <= month <= 12
            or type(year) is not int or not 2000 <= year <= 2100
            or type(page) is not int or not 1 <= page <= 50
            or type(options['show_products']) is not bool
            or period not in ('month', 'custom')
        ):
            raise ValidationError(_('Invalid report options.'))
        company = self.env['res.company'].browse(company_id).exists()
        if not company or company not in self.env.companies:
            raise AccessError(_('The selected company is not available to your user.'))
        values = {
            'company_id': company.id,
            'period': period,
            'month': str(month),
            'year': year,
            'show_products': options['show_products'],
        }
        if period == 'month':
            start = date(year, month, 1)
            values['date_from'] = start
            values['date_to'] = date(year, month, monthrange(year, month)[1])
        else:
            dates = []
            for key in ('date_from', 'date_to'):
                raw = options[key]
                if not isinstance(raw, str) or len(raw) != 10:
                    raise ValidationError(_('Enter a valid From and To date.'))
                try:
                    parsed = date.fromisoformat(raw)
                except ValueError as error:
                    raise ValidationError(_('Enter a valid From and To date.')) from error
                if parsed.isoformat() != raw or not 2000 <= parsed.year <= 2100:
                    raise ValidationError(_('Enter a valid From and To date.'))
                dates.append(parsed)
            values['date_from'], values['date_to'] = dates
        return company, values

    @api.model
    def get_hub_context(self):
        now = datetime.now(RIYADH).date()
        virtual = self.new({'company_id': self.env.company.id})
        virtual.check_access('read')
        virtual._check_report_access()
        companies = []
        for company in self.env.companies:
            if company.currency_id.name != 'SAR' or company.currency_id.decimal_places != 2:
                continue
            scoped = self.with_company(company).new({'company_id': company.id})
            try:
                scoped._check_report_access()
            except AccessError:
                continue
            companies.append({'id': company.id, 'name': company.name})
        if not companies:
            raise ValidationError(_('No SAR company is available for this report.'))
        selected = next((item['id'] for item in companies if item['id'] == self.env.company.id), companies[0]['id'])
        return {
            'company_id': selected,
            'companies': companies,
            'month': now.month,
            'year': now.year,
            'date_from': now.replace(day=1).isoformat(),
            'date_to': now.isoformat(),
        }

    @api.model
    def get_hub_report(self, options):
        company, values = self._hub_wizard_values(options)
        page = options['page']
        wizard = self.with_company(company).new(values)
        report_model = self.env['report.baseer_pos_tobacco_report.report_pos_tobacco_fees'].with_company(company)
        try:
            data = report_model._build_report(wizard)
        except TobaccoReportTooLarge:
            return {'overflow': True, 'rows': [], 'exceptions': [], 'page': 1}
        count = len(data['rows'])
        pages = max(1, (count + PREVIEW_PAGE_SIZE - 1) // PREVIEW_PAGE_SIZE)
        page = min(page, pages)
        start = (page - 1) * PREVIEW_PAGE_SIZE
        return {
            'overflow': False,
            'company_name': company.name,
            'from_text': data['from_text'],
            'to_text': data['to_text'],
            'currency': data['currency'],
            'show_products': data['show_products'],
            'rows': [dict(row) for row in data['rows'][start:start + PREVIEW_PAGE_SIZE]],
            'exceptions': [dict(row) for row in data['exceptions'][:PREVIEW_PAGE_SIZE]],
            'opening': data['opening'],
            'debit_total': data['debit_total'],
            'credit_total': data['credit_total'],
            'closing': data['closing'],
            'exception_count': data['exception_count'],
            'row_count': count,
            'page': page,
            'pages': pages,
            'first_row': start + 1 if count else 0,
            'last_row': min(start + PREVIEW_PAGE_SIZE, count),
        }

    @api.model
    def action_hub_pdf(self, options):
        company, values = self._hub_wizard_values(options)
        virtual = self.with_company(company).new(values)
        virtual.check_access('read')
        virtual._check_report_access()
        virtual._check_period()
        # The report engine also enforces SAR and the 5,000-line safety limit.
        self.env['report.baseer_pos_tobacco_report.report_pos_tobacco_fees'].with_company(
            company,
        )._build_report(virtual)
        wizard = self.with_company(company).create(values)
        return wizard.action_print_report()

    @api.model
    def export_hub_xlsx(self, options):
        """Export the whole authorized period regardless of the preview page."""
        started_at = monotonic()
        company, values = self._hub_wizard_values(options)
        wizard = self.with_company(company).new(values)
        wizard.check_access('read')
        wizard._check_report_access()
        wizard._check_period()
        # Transaction-scoped and non-blocking across all Odoo workers. The caller's
        # commit/rollback releases the company slot, including on export failure.
        self.env.cr.execute('SELECT pg_try_advisory_xact_lock(%s, %s)', (
            TOBACCO_EXPORT_LOCK_NAMESPACE, company.id,
        ))
        if not self.env.cr.fetchone()[0]:
            raise UserError(_('Tobacco report export is running for this company. Please retry.'))
        report = self.env['report.baseer_pos_tobacco_report.report_pos_tobacco_fees'].with_company(
            company,
        )._build_report(wizard, for_export=True)
        export_model = self.env['baseer.pos.tobacco.xlsx']
        payload = export_model._render_workbook(report, started_at=started_at)
        encoded = base64.b64encode(payload).decode('ascii')
        if monotonic() - started_at > 10:
            raise UserError(_('Tobacco Excel export exceeded its safe time limit. Split the period.'))
        export = export_model.create({
            'company_id': company.id,
            'period': values['period'],
            'month': int(values['month']), 'year': values['year'],
            'date_from': values['date_from'], 'date_to': values['date_to'],
            'show_products': values['show_products'],
            'file_data': encoded,
            'file_name': 'baseer_tobacco_%s_%s.xlsx' % (
                values['date_from'].isoformat(), values['date_to'].isoformat(),
            ),
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/baseer/pos/tobacco/export/%s?company_id=%s' % (export.id, company.id),
            'target': 'download',
        }

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
