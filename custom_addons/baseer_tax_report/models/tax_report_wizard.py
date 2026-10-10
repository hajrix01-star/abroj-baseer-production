from calendar import monthrange
import base64
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import re
from time import monotonic

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


def _previous_quarter(today):
    """Return the last completed calendar quarter in the user's timezone."""
    current_quarter = (today.month - 1) // 3 + 1
    return (today.year - (current_quarter == 1), str((current_quarter - 2) % 4 + 1))


class BaseerTaxReportWizard(models.TransientModel):
    _name = 'baseer.tax.report.wizard'
    _description = 'Saudi VAT Report Period'

    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)
    period_type = fields.Selection([('month', 'Monthly'), ('quarter', 'Quarterly')], string='Period', required=True, default='quarter')
    year = fields.Integer(string='Year', required=True,
                          default=lambda self: _previous_quarter(fields.Date.context_today(self))[0])
    month = fields.Selection(MONTHS, string='Month', required=True, default=lambda self: str(fields.Date.context_today(self).month))
    quarter = fields.Selection(QUARTERS, string='Quarter', required=True,
                               default=lambda self: _previous_quarter(fields.Date.context_today(self))[1])
    display_mode = fields.Selection([('simple', 'Summary'), ('detailed', 'Detailed')],
                                    string='Display', required=True, default='simple')
    journal_ids = fields.Many2many('account.journal', string='Journals (optional)',
                                   domain="[('company_id', '=', company_id)]")
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
        if any(journal.company_id != self.company_id for journal in self.journal_ids):
            raise AccessError(_('The selected journals must belong to the report company.'))

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
        domain = (Domain('company_id', '=', self.company_id.id)
                & Domain('parent_state', '=', 'posted')
                & Domain('date', '>=', first)
                & Domain('date', '<=', last)
                & aml._get_tax_exigible_domain())
        if self.journal_ids:
            domain &= Domain('journal_id', 'in', self.journal_ids.ids)
        return domain

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
        # The municipal tobacco fee has its own report, not a VAT exception.
        # Use the company-specific account code already used by that report.
        tobacco_accounts = self.env['account.account'].with_company(self.company_id).search([
            ('company_ids', 'in', self.company_id.id), ('code', '=', '201021'),
        ])
        if tobacco_accounts:
            other_domain &= Domain('account_id', 'not in', tobacco_accounts.ids)
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
        source_components = {}
        rows = []
        is_rtl = (self.env.lang or '').startswith('ar')
        decimals = self.company_id.currency_id.decimal_places
        quantum = Decimal('1').scaleb(-decimals)
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
                    source_components[key] = [(key, 1)]
                elif expression.engine == 'aggregation':
                    amount = self._aggregation_expression(expression, values)
                    parts = re.findall(r'[+-]?sa_\d+\.(?:base|tax)', expression.formula.replace(' ', ''))
                    source_components[key] = [
                        (source_key, (-1 if part.startswith('-') else 1) * source_sign)
                        for part in parts
                        for source_key, source_sign in source_components[part.lstrip('+-')]
                    ]
                else:
                    raise UserError(_('Unsupported Saudi VAT expression engine: %s') % expression.engine)
                values[key] = amount.quantize(quantum, rounding=ROUND_HALF_UP)
                cells[expression.label] = values[key]
            rows.append({
                'number': line.code[3:],
                'name': ARABIC_BOX_LABELS[line.code] if is_rtl else line.name,
                'base': cells.get('base'), 'tax': cells.get('tax'), 'direct': direct,
                'components': {},
                'base_text': f"{cells['base']:,.{decimals}f}" if 'base' in cells else '—',
                'tax_text': f"{cells['tax']:,.{decimals}f}" if 'tax' in cells else '—',
            })
        rows_by_number = {row['number']: row for row in rows}
        for row in rows:
            for column in ('base', 'tax'):
                key = f"sa_{row['number']}.{column}"
                if key not in values or column in row['direct']:
                    continue
                components = []
                for source_key, sign in source_components[key]:
                    amount = (values[source_key] * sign).quantize(quantum, rounding=ROUND_HALF_UP)
                    if self.display_mode != 'detailed' and not amount:
                        continue
                    source_number, source_column = source_key[3:].split('.')
                    components.append({
                        'number': source_number,
                        'column': source_column,
                        'name': rows_by_number[source_number]['name'],
                        'amount_text': f'{amount:+,.{decimals}f}',
                    })
                row['components'][column] = components
        exception = self._untagged_vat(base_domain)
        first, last = self._period_dates()
        return {
            'wizard': self, 'company': self.company_id,
            'date_from': first, 'date_to': last, 'rows': rows,
            'visible_rows': rows if self.display_mode == 'detailed' else [
                row for row in rows if (row['base'] is not None and row['base'] != 0)
                or (row['tax'] is not None and row['tax'] != 0)
            ],
            'display_mode': self.display_mode,
            'exception': exception, 'currency': self.company_id.currency_id,
            'journal_names': ', '.join(self.journal_ids.mapped('display_name')),
            'exception_amount_text': f"{exception['amount']:,.{decimals}f}",
            'other_tax_amount_text': f"{exception['other_amount']:,.{decimals}f}",
            'is_rtl': is_rtl,
        }

    @api.depends('company_id', 'period_type', 'year', 'month', 'quarter', 'journal_ids', 'display_mode')
    def _compute_preview(self):
        for wizard in self:
            wizard.preview_html = False
            if not wizard.company_id or not wizard.year:
                continue
            try:
                data = wizard._build_report()
            except (ValidationError, ValueError):
                continue
            data['interactive'] = True
            wizard.preview_html = self.env['ir.qweb']._render(
                'baseer_tax_report.preview_tax_report', {'report_data': data},
            )

    @api.model
    def get_hub_options(self):
        """Only expose choices that the current accounting user can actually use."""
        if not any(self.env.user.has_group(group) for group in (
            'account.group_account_readonly', 'account.group_account_user',
            'account.group_account_manager',
        )):
            raise AccessError(_('Accounting access is required.'))
        companies = self.env.companies.filtered(
            lambda company: company.account_fiscal_country_id.code == 'SA')
        journals = self.env['account.journal'].search([
            ('company_id', 'in', companies.ids),
        ], order='name, id') if companies else self.env['account.journal']
        year, quarter = _previous_quarter(fields.Date.context_today(self))
        return {
            'companies': [{'id': company.id, 'name': company.name} for company in companies],
            'journals': [{'id': journal.id, 'name': journal.display_name,
                          'company_id': journal.company_id.id} for journal in journals],
            # The report follows Odoo's active company.  Never silently switch a
            # non-Saudi active company to another Saudi company in the toolbar.
            'default_company_id': self.env.company.id if self.env.company in companies else False,
            'default_year': year, 'default_quarter': quarter,
        }

    @api.model
    def _hub_wizard(self, options):
        """Validate primitive RPC input before reading any financial data."""
        keys = {'company_id', 'period_type', 'year', 'month', 'quarter',
                'display_mode', 'journal_ids'}
        if not isinstance(options, dict) or set(options) != keys:
            raise ValidationError(_('Invalid VAT report options.'))
        company_id, year = options['company_id'], options['year']
        if (type(company_id) is not int or company_id not in self.env.companies.ids
                or type(year) is not int or not 2000 <= year <= 2100):
            raise AccessError(_('The selected company or period is not allowed.'))
        if (options['period_type'] not in ('month', 'quarter')
                or options['display_mode'] not in ('simple', 'detailed')
                or type(options['month']) is not str or options['month'] not in dict(MONTHS)
                or type(options['quarter']) is not str or options['quarter'] not in dict(QUARTERS)):
            raise ValidationError(_('Invalid VAT report period or display.'))
        journal_ids = options['journal_ids']
        if (not isinstance(journal_ids, list) or len(journal_ids) > 100
                or any(type(journal_id) is not int or journal_id <= 0 for journal_id in journal_ids)
                or len(set(journal_ids)) != len(journal_ids)):
            raise ValidationError(_('Invalid VAT report journals.'))
        journals = self.env['account.journal'].search([
            ('id', 'in', journal_ids), ('company_id', '=', company_id),
        ]) if journal_ids else self.env['account.journal']
        if set(journals.ids) != set(journal_ids):
            raise AccessError(_('The selected journals must belong to the report company.'))
        wizard = self.new({
            'company_id': company_id, 'period_type': options['period_type'],
            'year': year, 'month': options['month'], 'quarter': options['quarter'],
            'display_mode': options['display_mode'], 'journal_ids': [(6, 0, journal_ids)],
        })
        wizard._check_report_access()
        wizard._period_dates()
        return wizard

    @api.model
    def get_hub_report(self, options):
        data = self._hub_wizard(options)._build_report()
        return {
            'company': data['company'].name,
            'currency': data['currency'].name,
            'period_type': data['wizard'].period_type,
            'date_from': data['date_from'].isoformat(),
            'date_to': data['date_to'].isoformat(),
            'journal_names': data['journal_names'],
            'rows': [{
                'number': row['number'], 'name': row['name'].split('. ', 1)[-1],
                'base_text': row['base_text'], 'tax_text': row['tax_text'],
                'base_state': self._hub_amount_state(row['base']),
                'tax_state': self._hub_amount_state(row['tax']),
                'direct': {column: bool(row['direct'].get(column)) for column in ('base', 'tax')},
                'components': {column: [
                    {'number': item['number'], 'column': item['column'],
                     'name': item['name'].split('. ', 1)[-1], 'amount_text': item['amount_text'],
                     'state': 'negative' if item['amount_text'].startswith('-') else 'normal'}
                    for item in row['components'].get(column, [])
                ] for column in ('base', 'tax')},
            } for row in data['visible_rows']],
            'exception': {
                'count': data['exception']['count'],
                'amount_text': data['exception_amount_text'],
                'amount_state': self._hub_amount_state(data['exception']['amount']),
                'other_count': data['exception']['other_count'],
                'other_amount_text': data['other_tax_amount_text'],
                'other_amount_state': self._hub_amount_state(data['exception']['other_amount']),
            },
        }

    @api.model
    def _hub_amount_state(self, amount):
        return 'empty' if amount is None else 'zero' if not amount else 'negative' if amount < 0 else 'normal'

    @api.model
    def print_hub_report(self, options):
        wizard = self._hub_wizard(options)
        # Reports require a persisted TransientModel record, unlike the read-only preview.
        saved = self.create({
            'company_id': wizard.company_id.id, 'period_type': wizard.period_type,
            'year': wizard.year, 'month': wizard.month, 'quarter': wizard.quarter,
            'display_mode': wizard.display_mode,
            'journal_ids': [(6, 0, wizard.journal_ids.ids)],
        })
        return saved.action_print()

    @api.model
    def export_hub_xlsx(self, options):
        """Build one complete, authorized VAT workbook before exposing a download URL."""
        started_at = monotonic()
        wizard = self._hub_wizard(options)
        report = wizard._build_report()
        export_model = self.env['baseer.tax.report.xlsx']
        payload = export_model._render_workbook(report, started_at=started_at)
        export = export_model.create({
            'company_id': wizard.company_id.id,
            'period_type': wizard.period_type,
            'year': wizard.year,
            'month': wizard.month,
            'quarter': wizard.quarter,
            'display_mode': wizard.display_mode,
            'journal_ids': [(6, 0, wizard.journal_ids.ids)],
            'file_data': base64.b64encode(payload).decode('ascii'),
            'file_name': 'baseer_vat_%s_%s%s.xlsx' % (
                wizard.year, 'Q' if wizard.period_type == 'quarter' else 'M',
                wizard.quarter if wizard.period_type == 'quarter' else wizard.month,
            ),
        })
        if monotonic() - started_at > 3:
            raise UserError(_('VAT Excel export exceeded its safe time limit. Please retry.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/baseer/tax/vat/export/%s?company_id=%s' % (
                export.id, wizard.company_id.id,
            ),
            'target': 'download',
        }

    @api.model
    def open_hub_cell(self, options, box, component):
        if type(box) is not str or type(component) is not str:
            raise ValidationError(_('Select a valid VAT box and column.'))
        return self._hub_wizard(options).action_open_cell(box, component)

    @api.model
    def open_hub_exception(self, options, kind):
        if kind not in ('vat', 'other') or type(kind) is not str:
            raise ValidationError(_('Select a valid exception type.'))
        wizard = self._hub_wizard(options)
        return wizard.action_view_untagged() if kind == 'vat' else wizard.action_view_other_untagged()

    def action_print(self):
        self._check_report_access()
        self._build_report()
        return self.env.ref('baseer_tax_report.action_report_tax').report_action(self)

    def action_view_entries(self):
        self._check_report_access()
        if not self.selected_box:
            raise ValidationError(_('Select a box first.'))
        return self.action_open_cell(self.selected_box, self.selected_component)

    def action_open_cell(self, box, component):
        self._check_report_access()
        if box not in dict(BOXES) or component not in ('base', 'tax'):
            raise ValidationError(_('Select a valid VAT box and column.'))
        data = self._build_report()
        row = next(row for row in data['rows'] if row['number'] == box)
        formula = row['direct'].get(component)
        if not formula:
            raise ValidationError(_('This total is calculated from other boxes; open a component box to see its entries.'))
        tags = self.env['account.account.tag']._get_tax_tags(
            formula, self.company_id.account_fiscal_country_id.id,
        )
        domain = self._base_domain() & Domain('tax_tag_ids', 'in', tags.ids)
        return {
            'type': 'ir.actions.act_window',
            'name': _('VAT box %(box)s — %(column)s entries',
                      box=box, column=component),
            'res_model': 'account.move.line', 'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': list(domain),
            'context': {'search_default_group_by_move': 0, 'allowed_company_ids': [self.company_id.id]},
        }

    def action_view_untagged(self):
        self._check_report_access()
        exception = self._untagged_vat(self._base_domain())
        return {
            'type': 'ir.actions.act_window', 'name': _('Untagged VAT entries'),
            'res_model': 'account.move.line', 'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': list(exception['domain']),
            'context': {'allowed_company_ids': [self.company_id.id]},
        }

    def action_view_other_untagged(self):
        self._check_report_access()
        exception = self._untagged_vat(self._base_domain())
        return {
            'type': 'ir.actions.act_window', 'name': _('Other untagged tax entries'),
            'res_model': 'account.move.line', 'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': list(exception['other_domain']),
            'context': {'allowed_company_ids': [self.company_id.id]},
        }
