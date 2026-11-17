"""Saudi return based on the installed localization's public report data."""
import re
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
            if raw.get('comparison') or raw.get('analytic_account_ids') or raw.get('group_by'):
                raise ValidationError(_('Comparison, analytic filtering and tax grouping are not available for this report.'))
        return super()._normalize_options(report, raw)

    @api.model
    def _vat_domain(self, options):
        if len(self.env.companies) != 1 or self.env.company.account_fiscal_country_id.code != 'SA':
            raise ValidationError(_('Select one Saudi company for the VAT report.'))
        domain = (Domain('company_id', '=', self.env.company.id)
                  & Domain('date', '>=', options['date_from'])
                  & Domain('date', '<=', options['date_to'])
                  & Domain('parent_state', 'in', ['posted'] if options['posted_only'] else ['posted', 'draft'])
                  & self.env['account.move.line']._get_tax_exigible_domain())
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
        for line in lines:
            if line.code in ('sa_1', 'sa_7', 'sa_13'):
                name = {'sa_1': _('VAT on Sales'), 'sa_7': _('VAT on Purchases'), 'sa_13': _('Net VAT')}[line.code]
                row('section_' + line.code, name, display='section')
            row(line.code, line.name, values.get(line.code + '.base'), values.get(line.code + '.tax'), 'total' if line.code in ('sa_6', 'sa_12', 'sa_13', 'sa_16') else 'line', True)
        vat_tags = list({tag for key, ids in tags.items() if key.endswith('.tax') for tag in ids})
        reps = self.env['account.tax.repartition.line'].search([('company_id', '=', self.env.company.id), ('repartition_type', '=', 'tax'), ('tag_ids', 'in', vat_tags)])
        account_ids = reps.account_id.ids
        period = (Domain('company_id', '=', self.env.company.id)
                  & Domain('date', '>=', normalized['date_from'])
                  & Domain('date', '<=', normalized['date_to'])
                  & Domain('parent_state', 'in', ['posted'] if normalized['posted_only'] else ['posted', 'draft'])
                  & Domain('account_id', 'in', account_ids))
        if normalized['journal_ids']:
            period &= Domain('journal_id', 'in', normalized['journal_ids'])
        movement_group = self.env['account.move.line']._read_group(period, [], ['balance:sum'])
        movement = -Decimal(str((movement_group[0][0] if movement_group else 0) or 0))
        net = values.get('sa_16.tax', Decimal(0))
        row('reconciliation', _('Reconciliation with VAT accounts'), display='section')
        row('vat_net', _('Net VAT due'), tax=net)
        row('vat_movement', _('VAT account movement'), tax=movement, drill=True)
        row('vat_difference', _('Difference'), tax=net - movement, display='total')
        untagged = self.env['account.move.line'].search_count(period & Domain('tax_tag_ids', '=', False))
        if untagged:
            payload['notes'].append(_('VAT account entries without tax tags: %s') % untagged)
        payload['lines'] = rows
        return payload

    @api.model
    def get_move_line_action(self, report_code, options, line_code, column_key, account_id=False, company_id=False):
        if report_code != 'saudi_vat':
            return super().get_move_line_action(report_code, options, line_code, column_key, account_id, company_id)
        self._check_report_access()
        normalized = self._normalize_options(self._definition(report_code), options or {})
        lines, values, sources, tags = self._vat_values(normalized)
        if line_code == 'vat_movement' and column_key == 'tax':
            vat_tags = list({tag for key, ids in tags.items() if key.endswith('.tax') for tag in ids})
            reps = self.env['account.tax.repartition.line'].search([('company_id', '=', self.env.company.id), ('repartition_type', '=', 'tax'), ('tag_ids', 'in', vat_tags)])
            domain = [('company_id', '=', self.env.company.id), ('date', '>=', normalized['date_from']), ('date', '<=', normalized['date_to']), ('parent_state', 'in', ['posted'] if normalized['posted_only'] else ['posted', 'draft']), ('account_id', 'in', reps.account_id.ids)]
            if normalized['journal_ids']:
                domain.append(('journal_id', 'in', normalized['journal_ids']))
            return {'type': 'ir.actions.act_window', 'name': _('VAT journal items'), 'res_model': 'account.move.line', 'view_mode': 'list,form', 'views': [(False, 'list'), (False, 'form')], 'domain': domain}
        if column_key not in ('base', 'tax') or line_code not in lines.mapped('code'):
            raise ValidationError(_('Choose a VAT box and column.'))
        key = line_code + '.' + column_key
        if key not in sources:
            raise ValidationError(_('Choose a VAT box and column.'))
        tag_ids = list({tag for source in sources[key] for tag in tags[source]})
        domain = self._vat_domain(normalized) & Domain('tax_tag_ids', 'in', tag_ids)
        return {'type': 'ir.actions.act_window', 'name': _('VAT journal items'), 'res_model': 'account.move.line', 'view_mode': 'list,form', 'views': [(False, 'list'), (False, 'form')], 'domain': list(domain)}
