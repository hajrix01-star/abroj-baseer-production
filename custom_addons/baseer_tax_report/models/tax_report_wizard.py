from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import re

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Domain


MONTHS = [(str(index), name) for index, name in enumerate((
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December',
), 1)]
QUARTERS = [('1', 'Q1'), ('2', 'Q2'), ('3', 'Q3'), ('4', 'Q4')]
BOXES = [(str(index), str(index)) for index in range(1, 17)]
TOKEN = re.compile(r'^(sa_\d+)\.(base|tax)$')
ARABIC_BOX_LABELS = {
    'sa_1': 'المبيعات الخاضعة للنسبة الأساسية',
    'sa_2': 'الرعاية الصحية والتعليم الخاص والمسكن الأول للمواطنين',
    'sa_3': 'المبيعات المحلية الخاضعة لنسبة الصفر',
    'sa_4': 'الصادرات',
    'sa_5': 'المبيعات المعفاة',
    'sa_6': 'إجمالي المبيعات',
    'sa_7': 'المشتريات المحلية الخاضعة للنسبة الأساسية',
    'sa_8': 'الواردات المدفوعة ضريبتها للجمارك',
    'sa_9': 'الواردات الخاضعة للاحتساب العكسي',
    'sa_10': 'المشتريات الخاضعة لنسبة الصفر',
    'sa_11': 'المشتريات المعفاة',
    'sa_12': 'إجمالي المشتريات',
    'sa_13': 'إجمالي ضريبة القيمة المضافة المستحقة للفترة',
    'sa_14': 'تصحيحات الفترات السابقة ضمن ±5,000 ريال',
    'sa_15': 'الرصيد الدائن المرحّل من الفترة السابقة',
    'sa_16': 'صافي ضريبة القيمة المضافة المستحقة أو القابلة للاسترداد',
}


class BaseerTaxReportWizard(models.TransientModel):
    _name = 'baseer.tax.report.wizard'
    _description = 'Saudi VAT Report Period'

    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)
    period_type = fields.Selection([('month', 'Monthly'), ('quarter', 'Quarterly')], string='Period', required=True, default='month')
    year = fields.Integer(string='Year', required=True, default=lambda self: fields.Date.context_today(self).year)
    month = fields.Selection(MONTHS, string='Month', required=True, default=lambda self: str(fields.Date.context_today(self).month))
    quarter = fields.Selection(QUARTERS, string='Quarter', required=True, default=lambda self: str((fields.Date.context_today(self).month - 1) // 3 + 1))
    selected_box = fields.Selection(BOXES, string='View supporting entries')
    selected_component = fields.Selection([('base', 'Amount'), ('tax', 'VAT Amount')],
                                          string='Column', default='tax', required=True)
    date_from = fields.Date(string='From', compute='_compute_dates')
    date_to = fields.Date(string='To', compute='_compute_dates')
    preview_html = fields.Html(compute='_compute_preview', sanitize=True, string='VAT report')

    def _check_report_access(self):
        self.ensure_one()
        if not self.env.user.has_group('account.group_account_readonly') and not self.env.user.has_group('account.group_account_user') and not self.env.user.has_group('account.group_account_manager'):
            raise AccessError(_('Accounting access is required.'))
        if self.company_id not in self.env.companies:
            raise AccessError(_('The selected company is not allowed.'))
        if self.company_id.account_fiscal_country_id.code != 'SA':
            raise ValidationError(_('Select a Saudi company for the Saudi VAT report.'))

    def _period_dates(self):
        self.ensure_one()
        if not 2000 <= self.year <= 2100:
            raise ValidationError(_('Select a year from 2000 to 2100.'))
        if self.period_type == 'month':
            month = int(self.month or 0)
            if not 1 <= month <= 12:
                raise ValidationError(_('Select a month.'))
            first = date(self.year, month, 1)
            last = date(self.year, month, monthrange(self.year, month)[1])
        elif self.period_type == 'quarter':
            quarter = int(self.quarter or 0)
            if not 1 <= quarter <= 4:
                raise ValidationError(_('Select a quarter.'))
            month = (quarter - 1) * 3 + 1
            first = date(self.year, month, 1)
            end_month = month + 2
            last = date(self.year, end_month, monthrange(self.year, end_month)[1])
        else:
            raise ValidationError(_('Select a monthly or quarterly period.'))
        return first, last

    @api.depends('period_type', 'year', 'month', 'quarter')
    def _compute_dates(self):
        for wizard in self:
            try:
                wizard.date_from, wizard.date_to = wizard._period_dates()
            except (ValueError, ValidationError):
                wizard.date_from = wizard.date_to = False

    def _base_domain(self):
        self.ensure_one()
        first, last = self._period_dates()
        aml = self.env['account.move.line']
        return (Domain('company_id', '=', self.company_id.id)
                & Domain('parent_state', '=', 'posted')
                & Domain('date', '>=', first)
                & Domain('date', '<=', last)
                & aml._get_tax_exigible_domain())

    def _tax_tag_expression(self, expression, base_domain):
        formula = expression.formula
        if not re.fullmatch(r'-?\d+\([BT]\)', formula):
            raise UserError(_('Unsupported Saudi VAT tax-tag formula: %s') % formula)
        tags = self.env['account.account.tag']._get_tax_tags(
            formula, self.company_id.account_fiscal_country_id.id,
        )
        if not tags:
            raise UserError(_('Missing Saudi VAT tax tag: %s') % formula)
        domain = base_domain & Domain('tax_tag_ids', 'in', tags.ids)
        grouped = self.env['account.move.line']._read_group(domain, [], ['balance:sum'])
        balance = Decimal(str((grouped[0][0] if grouped else 0) or 0))
        return -balance if formula.startswith('-') else balance

    def _aggregation_expression(self, expression, values):
        formula = expression.formula.replace(' ', '')
        parts = re.findall(r'[+-]?sa_\d+\.(?:base|tax)', formula)
        if not parts or ''.join(parts) != formula:
            raise UserError(_('Unsupported Saudi VAT aggregation formula: %s') % expression.formula)
        result = Decimal('0')
        for part in parts:
            sign = -1 if part.startswith('-') else 1
            key = part.lstrip('+-')
            if not TOKEN.fullmatch(key) or key not in values:
                raise UserError(_('Unresolved Saudi VAT aggregation formula: %s') % expression.formula)
            result += sign * values[key]
        return result

    def _untagged_vat(self, base_domain):
        """Classify untagged taxes; never blend exceptions into official VAT boxes."""
        country = self.company_id.account_fiscal_country_id
        vat_tags = self.env['account.account.tag']
        for tag_name in ('1(T)', '7(T)', '8(T)', '9(T)'):
            vat_tags |= vat_tags._get_tax_tags(tag_name, country.id)
        tax_groups = self.env['account.tax.repartition.line'].search([
            ('company_id', '=', self.company_id.id), ('tag_ids', 'in', vat_tags.ids),
            ('repartition_type', '=', 'tax'),
        ]).mapped('tax_id.tax_group_id')
        vat_named_groups = self.env['account.tax.group'].search([
            ('country_id', '=', country.id),
            '|', ('name', 'ilike', 'VAT'), ('name', 'ilike', 'القيمة المضافة'),
        ])
        tax_groups |= vat_named_groups
        untagged = (base_domain & Domain('tax_line_id', '!=', False)
                    & Domain('tax_tag_ids', '=', False))
        domain = untagged & Domain('tax_line_id.tax_group_id', 'in', tax_groups.ids)
        other_domain = untagged & Domain('tax_line_id.tax_group_id', 'not in', tax_groups.ids)
        aml = self.env['account.move.line']
        grouped = aml._read_group(domain, [], ['balance:sum'])
        other_grouped = aml._read_group(other_domain, [], ['balance:sum'])
        return {
            'count': aml.search_count(domain),
            'amount': Decimal(str((grouped[0][0] if grouped else 0) or 0)),
            'domain': domain,
            'other_count': aml.search_count(other_domain),
            'other_amount': Decimal(str((other_grouped[0][0] if other_grouped else 0) or 0)),
            'other_domain': other_domain,
        }

    def _build_report(self):
        self._check_report_access()
        report = self.env.ref('l10n_sa.tax_report_vat_filing', raise_if_not_found=False)
        if not report:
            raise UserError(_('The original Saudi VAT report definition is not installed.'))
        base_domain = self._base_domain()
        values = {}
        rows = []
        is_rtl = (self.env.lang or '').startswith('ar')
        quantum = Decimal('1').scaleb(-self.company_id.currency_id.decimal_places)
        lines = report.line_ids.filtered(lambda line: line.code and re.fullmatch(r'sa_(?:[1-9]|1[0-6])', line.code))
        if len(lines) != 16:
            raise UserError(_('The Saudi VAT report must define all 16 boxes.'))
        for line in sorted(lines, key=lambda item: int(item.code[3:])):
            cells = {}
            direct = {}
            for expression in line.expression_ids:
                if expression.label not in ('base', 'tax'):
                    continue
                key = '%s.%s' % (line.code, expression.label)
                if expression.engine == 'tax_tags':
                    amount = self._tax_tag_expression(expression, base_domain)
                    direct[expression.label] = expression.formula
                elif expression.engine == 'aggregation':
                    amount = self._aggregation_expression(expression, values)
                else:
                    raise UserError(_('Unsupported Saudi VAT expression engine: %s') % expression.engine)
                values[key] = amount.quantize(quantum, rounding=ROUND_HALF_UP)
                cells[expression.label] = values[key]
            rows.append({
                'number': line.code[3:],
                'name': ARABIC_BOX_LABELS[line.code] if is_rtl else line.name,
                'base': cells.get('base'), 'tax': cells.get('tax'), 'direct': direct,
                'base_text': f"{cells['base']:,.2f}" if 'base' in cells else '—',
                'tax_text': f"{cells['tax']:,.2f}" if 'tax' in cells else '—',
            })
        exception = self._untagged_vat(base_domain)
        first, last = self._period_dates()
        return {
            'wizard': self, 'company': self.company_id,
            'date_from': first, 'date_to': last, 'rows': rows,
            'exception': exception, 'currency': self.company_id.currency_id,
            'exception_amount_text': f"{exception['amount']:,.2f}",
            'other_tax_amount_text': f"{exception['other_amount']:,.2f}",
            'is_rtl': is_rtl,
        }

    @api.depends('company_id', 'period_type', 'year', 'month', 'quarter')
    def _compute_preview(self):
        for wizard in self:
            wizard.preview_html = False
            if not wizard.company_id or not wizard.year:
                continue
            try:
                data = wizard._build_report()
            except (ValidationError, ValueError):
                continue
            wizard.preview_html = self.env['ir.qweb']._render(
                'baseer_tax_report.preview_tax_report', {'report_data': data},
            )

    def action_print(self):
        self._check_report_access()
        self._build_report()
        return self.env.ref('baseer_tax_report.action_report_tax').report_action(self)

    def action_view_entries(self):
        self._check_report_access()
        if not self.selected_box:
            raise ValidationError(_('Select a box first.'))
        data = self._build_report()
        row = next(row for row in data['rows'] if row['number'] == self.selected_box)
        formula = row['direct'].get(self.selected_component)
        if not formula:
            raise ValidationError(_('This total is calculated from other boxes; open a component box to see its entries.'))
        tags = self.env['account.account.tag']._get_tax_tags(
            formula, self.company_id.account_fiscal_country_id.id,
        )
        domain = self._base_domain() & Domain('tax_tag_ids', 'in', tags.ids)
        return {
            'type': 'ir.actions.act_window',
            'name': _('VAT box %(box)s — %(column)s entries',
                      box=self.selected_box, column=self.selected_component),
            'res_model': 'account.move.line', 'view_mode': 'list,form',
            'domain': list(domain),
            'context': {'search_default_group_by_move': 0, 'allowed_company_ids': [self.company_id.id]},
        }

    def action_view_untagged(self):
        self._check_report_access()
        exception = self._untagged_vat(self._base_domain())
        return {
            'type': 'ir.actions.act_window', 'name': _('Untagged VAT entries'),
            'res_model': 'account.move.line', 'view_mode': 'list,form',
            'domain': list(exception['domain']),
            'context': {'allowed_company_ids': [self.company_id.id]},
        }

    def action_view_other_untagged(self):
        self._check_report_access()
        exception = self._untagged_vat(self._base_domain())
        return {
            'type': 'ir.actions.act_window', 'name': _('Other untagged tax entries'),
            'res_model': 'account.move.line', 'view_mode': 'list,form',
            'domain': list(exception['other_domain']),
            'context': {'allowed_company_ids': [self.company_id.id]},
        }
