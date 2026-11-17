"""Saudi return based on the installed localization's public report data."""
import re
import base64
import io
from copy import copy

from openpyxl import load_workbook
from decimal import Decimal, ROUND_HALF_UP

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Domain


class ReportDefinition(models.Model):
    _inherit = 'baseer.report.definition'
    report_kind = fields.Selection(selection_add=[('vat', 'VAT Report')], ondelete={'vat': 'cascade'})


class VatEngine(models.AbstractModel):
    _inherit = 'baseer.report.engine'

    @api.model
    def _vat_default_preset(self):
        # Community may not provide the periodicity field.
        periodicity = getattr(self.env.company, 'account_tax_periodicity', False)
        return 'last_month' if periodicity in ('monthly', 'month') else 'last_quarter'

    @api.model
    def get_bootstrap(self, report_code):
        result = super().get_bootstrap(report_code)
        if report_code == 'saudi_vat':
            result['defaults']['preset'] = self._vat_default_preset()
        return result

    @api.model
    def _normalize_options(self, report, raw):
        if report.report_kind == 'vat' and isinstance(raw, dict):
            raw = dict({'preset': self._vat_default_preset()}, **raw)
            if raw.get('comparison') or raw.get('analytic_account_ids'):
                raise ValidationError(_('Comparison, analytic filtering and tax grouping are not available for this report.'))
        result = super()._normalize_options(report, raw)
        if report.report_kind == 'vat':
            grouping = raw.get('tax_grouping', 'grid')
            if grouping not in ('grid', 'tax'):
                raise ValidationError(_('Choose a valid tax grouping.'))
            result['tax_grouping'] = grouping
        return result

    @api.model
    def _vat_tobacco_accounts(self):
        company = self.env.company
        taxes = self.env['account.tax'].with_context(lang='en_US', active_test=False).search([
            ('company_id', '=', company.id), '|', ('name', 'ilike', 'Tobacco service fee'),
            ('tax_group_id.name', 'ilike', 'Tobacco service fee')])
        accounts = (taxes.invoice_repartition_line_ids | taxes.refund_repartition_line_ids).filtered(
            lambda r: r.repartition_type == 'tax').account_id
        tokens = re.split(r'[,\s]+', self.env['ir.config_parameter'].sudo().get_param(
            'baseer_report_engine.tobacco_fee_accounts', '').strip())
        candidates = self.env['account.account'].with_context(active_test=False).search([('company_ids', 'in', company.id)])
        return accounts | candidates.filtered(lambda a: a.code == '201021' or a.code in tokens or str(a.id) in tokens)

    @api.model
    def _vat_period_domain(self, options, account_ids, states):
        domain = (Domain('company_id', '=', self.env.company.id)
                  & Domain('date', '>=', options['date_from']) & Domain('date', '<=', options['date_to'])
                  & Domain('parent_state', 'in', states) & Domain('account_id', 'in', account_ids))
        if options['journal_ids']:
            domain &= Domain('journal_id', 'in', options['journal_ids'])
        return domain

    @api.model
    def _vat_accounts(self, tags):
        vat_tags = list({tag for key, ids in tags.items() if key.endswith('.tax') for tag in ids})
        reps = self.env['account.tax.repartition.line'].search([('company_id', '=', self.env.company.id),
            ('repartition_type', '=', 'tax'), ('tag_ids', 'in', vat_tags)])
        return (reps.account_id - self._vat_tobacco_accounts()).ids

    @api.model
    def _vat_domain(self, options):
        if len(self.env.companies) != 1 or self.env.company.account_fiscal_country_id.code != 'SA':
            raise ValidationError(_('Select one Saudi company for the VAT report.'))
        domain = (Domain('company_id', '=', self.env.company.id)
                  & Domain('date', '>=', options['date_from'])
                  & Domain('date', '<=', options['date_to'])
                  & Domain('parent_state', 'in', ['posted'] if options['posted_only'] else ['posted', 'draft'])
                  & self.env['account.move.line']._get_tax_exigible_domain()
                  & Domain('account_id', 'not in', self._vat_tobacco_accounts().ids))
        if options['journal_ids']:
            domain &= Domain('journal_id', 'in', options['journal_ids'])
        return domain

    @api.model
    def _vat_values(self, options):
        definition = self.env.ref('l10n_sa.tax_report_vat_filing')
        domain = self._vat_domain(options)
        values, sources, tags_by_key = {}, {}, {}
        currency = self.env.company.currency_id
        quantum = Decimal('1').scaleb(-currency.decimal_places)
        lines = definition.line_ids.filtered(lambda l: l.code and re.fullmatch(r'sa_(?:[1-9]|1[0-6])', l.code)).sorted(lambda l: int(l.code[3:]))
        if len(lines) != 16:
            raise ValidationError(_('The Saudi VAT report must define all 16 boxes.'))
        for line in lines:
            for expr in line.expression_ids.filtered(lambda e: e.label in ('base', 'tax')):
                key = '%s.%s' % (line.code, expr.label)
                if expr.engine == 'tax_tags':
                    if not re.fullmatch(r'-?\d+\([BT]\)', expr.formula):
                        raise ValidationError(_('Unsupported Saudi VAT expression.'))
                    tags = self.env['account.account.tag']._get_tax_tags(expr.formula, self.env.company.account_fiscal_country_id.id)
                    if not tags:
                        raise ValidationError(_('Missing Saudi VAT tax tag.'))
                    group = self.env['account.move.line']._read_group(domain & Domain('tax_tag_ids', 'in', tags.ids), [], ['balance:sum'])
                    amount = Decimal(str((group[0][0] if group else 0) or 0))
                    # Odoo 19 tags have no tax_negate; the localization formula
                    # carries the sign, including for refunds and reversals.
                    amount *= -1 if expr.formula.startswith('-') else 1
                    sources[key] = [key]
                    tags_by_key[key] = tags.ids
                elif expr.engine == 'aggregation':
                    formula = expr.formula.replace(' ', '')
                    parts = re.findall(r'[+-]?sa_\d+\.(?:base|tax)', formula)
                    if not parts or ''.join(parts) != formula:
                        raise ValidationError(_('Unsupported Saudi VAT expression.'))
                    amount = sum(((-1 if part.startswith('-') else 1) * values[part.lstrip('+-')] for part in parts), Decimal(0))
                    sources[key] = [source for part in parts for source in sources[part.lstrip('+-')]]
                else:
                    raise ValidationError(_('Unsupported Saudi VAT expression.'))
                values[key] = amount.quantize(quantum, rounding=ROUND_HALF_UP)
        return lines, values, sources, tags_by_key

    @api.model
    def _vat_tax_groups(self, options, lines, tags):
        """Allocate each tagged balance once; preserve an audit bucket for ambiguous lines."""
        groups = {}
        Tax = self.env['account.tax'].with_context(active_test=False)
        all_taxes = Tax.search([('company_id', '=', self.env.company.id), ('type_tax_use', 'in', ['sale', 'purchase'])])
        for line in lines:
            number = int(line.code[3:])
            if number not in (*range(1, 6), *range(7, 12)):
                continue
            section = 'sale' if number < 7 else 'purchase'
            for expr in line.expression_ids.filtered(lambda e: e.engine == 'tax_tags' and e.label in ('base', 'tax')):
                tag_ids = tags.get(line.code + '.' + expr.label, [])
                candidates = all_taxes.filtered(lambda t: t.type_tax_use == section and bool(
                    (t.invoice_repartition_line_ids | t.refund_repartition_line_ids).tag_ids & self.env['account.account.tag'].browse(tag_ids)))
                for aml in self.env['account.move.line'].search(self._vat_domain(options) & Domain('tax_tag_ids', 'in', tag_ids)):
                    linked = (aml.tax_line_id | aml.tax_ids) & candidates
                    tax = linked if len(linked) == 1 else (candidates if not linked and len(candidates) == 1 else Tax)
                    key = (section, tax.id or 0)
                    bucket = groups.setdefault(key, {'tax': tax, 'base': Decimal(0), 'tax_amount': Decimal(0), 'base_ids': set(), 'tax_ids': set()})
                    column = 'base' if expr.label == 'base' else 'tax_amount'
                    bucket[column] += Decimal(str(aml.balance)) * (-1 if expr.formula.startswith('-') else 1)
                    bucket[expr.label + '_ids'].add(aml.id)
        return groups

    @api.model
    def get_report(self, report_code, options=None, with_accounts=False):
        if report_code != 'saudi_vat':
            return super().get_report(report_code, options, with_accounts=with_accounts)
        self._check_report_access()
        report = self._definition(report_code)
        raw = options if options is not None else self.env.context.get('baseer_options') or {}
        normalized = self._normalize_options(report, raw)
        lines, values, sources, tags = self._vat_values(normalized)
        payload = self._build(report, normalized)
        payload['report']['report_kind'] = 'vat'
        columns = [{'key': key, 'kind': 'period', 'label': label} for key, label in [('base', _('Base')), ('tax', _('Tax'))]]
        payload['columns'] = columns
        currency = self.env.company.currency_id
        rows = []
        def row(code, name, base=None, tax=None, display='line', drill=False):
            amounts = []
            for col, value in zip(columns, (base, tax)):
                item = self._serialize_amount(col, value, currency, drill and value is not None)
                if value is None:
                    item.update(value=None, display='—', drill=False)
                amounts.append(item)
            rows.append({'code': code, 'name': name, 'level': 1, 'display': display, 'foldable': False, 'has_accounts': False, 'accounts': [], 'amounts': amounts})
        if normalized['tax_grouping'] == 'tax':
            groups = self._vat_tax_groups(normalized, lines, tags)
            for section, title, total in [('sale', _('Sales'), 'sa_6'), ('purchase', _('Purchases'), 'sa_12')]:
                row('tax_section_' + section, title, display='section')
                for (kind, tax_id), bucket in sorted(groups.items(), key=lambda item: (item[0][0], item[1]['tax'].name or '')):
                    if kind == section:
                        row('tax_%s_%s' % (section, tax_id), bucket['tax'].name or _('Unassigned tax'), bucket['base'], bucket['tax_amount'], drill=True)
                row('tax_total_' + section, _('Total %s') % title, values.get(total + '.base'), values.get(total + '.tax'), display='total')
        for line in lines if normalized['tax_grouping'] == 'grid' else []:
            if line.code in ('sa_1', 'sa_7', 'sa_13'):
                name = {'sa_1': _('VAT on Sales'), 'sa_7': _('VAT on Purchases'), 'sa_13': _('Net VAT')}[line.code]
                row('section_' + line.code, name, display='section')
            row(line.code, line.name, values.get(line.code + '.base'), values.get(line.code + '.tax'), 'total' if line.code in ('sa_6', 'sa_12', 'sa_13', 'sa_16') else 'line', True)
        account_ids = self._vat_accounts(tags)
        period = self._vat_period_domain(normalized, account_ids, ['posted'] if normalized['posted_only'] else ['posted', 'draft'])
        def amount(domain):
            group = self.env['account.move.line']._read_group(domain, [], ['balance:sum'])
            return -Decimal(str((group[0][0] if group else 0) or 0))
        movement = amount(period)
        net = values.get('sa_16.tax', Decimal(0))
        row('reconciliation', _('Reconciliation with VAT accounts'), display='section')
        row('vat_net', _('Net VAT due'), tax=net)
        row('vat_movement', _('VAT account movement'), tax=movement, drill=True)
        row('vat_difference', _('Difference'), tax=net - movement, display='total')
        causes = [
            ('vat_untagged', _('VAT account entries without tax tags'), period & Domain('tax_tag_ids', '=', False)),
            ('vat_pending', _('Cash-basis pending'), period & ~self.env['account.move.line']._get_tax_exigible_domain()),
        ]
        if normalized['posted_only']:
            causes.append(('vat_draft', _('Draft VAT account entries'), self._vat_period_domain(normalized, account_ids, ['draft'])))
        for code, label, domain in causes:
            row(code, label, tax=amount(domain), drill=True)
        untagged = self.env['account.move.line'].search_count(causes[0][2])
        if untagged:
            payload['notes'].append(_('VAT account entries without tax tags: %s') % untagged)
        payload['lines'] = rows
        return payload

    @api.model
    def export_xlsx(self, report_code, options=None):
        result = super().export_xlsx(report_code, options)
        if report_code == 'saudi_vat':
            workbook = load_workbook(io.BytesIO(base64.b64decode(result['content'])))
            sheet = workbook.active
            for cells in sheet.iter_rows(min_col=1, max_col=1):
                cell = cells[0]
                if isinstance(cell.value, str) and len(cell.value) > 50:
                    alignment = copy(cell.alignment)
                    alignment.wrap_text = True
                    cell.alignment = alignment
                    sheet.row_dimensions[cell.row].height = 30
            sheet.sheet_properties.pageSetUpPr.fitToPage = True
            sheet.page_setup.fitToWidth = 1
            sheet.page_setup.fitToHeight = 0
            sheet.page_setup.orientation = 'landscape'
            sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
            output = io.BytesIO()
            workbook.save(output)
            result['content'] = base64.b64encode(output.getvalue()).decode()
        return result

    @api.model
    def get_move_line_action(self, report_code, options, line_code, column_key, account_id=False, company_id=False):
        if report_code != 'saudi_vat':
            return super().get_move_line_action(report_code, options, line_code, column_key, account_id, company_id)
        self._check_report_access()
        normalized = self._normalize_options(self._definition(report_code), options or {})
        lines, values, sources, tags = self._vat_values(normalized)
        if line_code in ('vat_movement', 'vat_untagged', 'vat_pending', 'vat_draft') and column_key == 'tax':
            states = ['draft'] if line_code == 'vat_draft' else (['posted'] if normalized['posted_only'] else ['posted', 'draft'])
            domain = self._vat_period_domain(normalized, self._vat_accounts(tags), states)
            if line_code == 'vat_untagged':
                domain &= Domain('tax_tag_ids', '=', False)
            elif line_code == 'vat_pending':
                domain &= ~self.env['account.move.line']._get_tax_exigible_domain()
            return {'type': 'ir.actions.act_window', 'name': _('VAT journal items'), 'res_model': 'account.move.line', 'view_mode': 'list,form', 'views': [(False, 'list'), (False, 'form')], 'domain': list(domain)}
        match = re.fullmatch(r'tax_(sale|purchase)_(\d+)', line_code)
        if match and column_key in ('base', 'tax'):
            groups = self._vat_tax_groups(normalized, lines, tags)
            bucket = groups.get((match.group(1), int(match.group(2))))
            if not bucket:
                raise ValidationError(_('Choose a VAT box and column.'))
            return {'type': 'ir.actions.act_window', 'name': _('VAT journal items'), 'res_model': 'account.move.line', 'view_mode': 'list,form', 'views': [(False, 'list'), (False, 'form')], 'domain': [('id', 'in', list(bucket[column_key + '_ids']))]}
        if column_key not in ('base', 'tax') or line_code not in lines.mapped('code'):
            raise ValidationError(_('Choose a VAT box and column.'))
        key = line_code + '.' + column_key
        if key not in sources:
            raise ValidationError(_('Choose a VAT box and column.'))
        tag_ids = list({tag for source in sources[key] for tag in tags[source]})
        domain = self._vat_domain(normalized) & Domain('tax_tag_ids', 'in', tag_ids)
        return {'type': 'ir.actions.act_window', 'name': _('VAT journal items'), 'res_model': 'account.move.line', 'view_mode': 'list,form', 'views': [(False, 'list'), (False, 'form')], 'domain': list(domain)}
