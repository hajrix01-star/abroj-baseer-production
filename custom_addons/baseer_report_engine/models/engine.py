"""Compute a declarative report from account.move.line for the active companies."""

import ast

from datetime import timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools.misc import format_date

from .definition import _or_domains
from .formula import FormulaError, evaluate_formula, referenced_codes


UNITS = ('month', 'quarter', 'year')
ACCOUNTING_GROUPS = (
    'account.group_account_readonly',
    'account.group_account_user',
    'account.group_account_manager',
)


class BaseerReportEngine(models.AbstractModel):
    _name = 'baseer.report.engine'
    _description = 'Baseer Report Engine'

    @api.model
    def get_bootstrap(self, report_code):
        self._check_report_access()
        report = self._definition(report_code)
        result = {
            'report': {
                'code': report.code,
                'name': report.name,
                'date_mode': report.date_mode,
            },
            'presets': [{'key': key, 'label': label} for key, label in self._preset_labels()],
            'units': [{'key': key, 'label': label} for key, label in self._unit_labels()],
            'journals': self._journal_options(),
            'analytic_accounts': self._analytic_options(),
            'analytic_enabled': self.env['account.analytic.account'].has_access('read'),
            'labels': self._labels(),
            'defaults': dict(self._default_options(), preset=report.default_preset or ('today' if report.date_mode == 'as_of' else 'this_year'), comparison_unit='month' if report.date_mode == 'as_of' or report.report_kind in ('account_grid', 'ledger') else 'year'),
        }
        if report.report_kind in ('partner_ledger', 'aged'):
            result['account_types'] = [{'key': key, 'label': label} for key, label in self._partner_type_labels()]
            result['defaults'].update(account_types=['receivable', 'payable'], partner_ids=[], partner_category_ids=[], unreconciled=False)
        if report.report_kind == 'aged':
            result['account_types'] = [item for item in result['account_types'] if ('payable' in item['key']) == (report.code == 'aged_payable')]
            result['defaults'].update(account_types=['payable' if report.code == 'aged_payable' else 'receivable'], aging_basis='due_date', period_length=30)
            result['aging_labels'] = {'due_date': _('Based on Due Date'), 'invoice_date': _('Based on Invoice Date'), 'days': _('%s Days')}
        return result

    @api.model
    def get_report(self, report_code, options=None, with_accounts=False):
        self._check_report_access()
        report = self._definition(report_code)
        if options is None:
            options = self.env.context.get('baseer_options') or {}
        normalized = self._normalize_options(report, options or {})
        payload = (self._build_grid(report, normalized) if report.report_kind == 'account_grid'
                   else self._build_ledger(report, normalized, options or {}) if report.report_kind == 'ledger'
                   else self._build_partner_ledger(report, normalized, options or {}) if report.report_kind == 'partner_ledger'
                   else self._build_aged(report, normalized) if report.report_kind == 'aged'
                   else self._build(report, normalized, with_accounts=with_accounts))
        payload['has_draft_entries'] = bool(normalized['posted_only'] and self.env['account.move.line'].search_count(self._draft_domain(normalized), limit=1))
        return payload

    @api.model
    def _draft_domain(self, options):
        return [('company_id', 'in', self.env.companies.ids),
                ('parent_state', '=', 'draft'), ('date', '<=', options['date_to'])]

    @api.model
    def get_draft_entries_action(self, report_code, options):
        self._check_report_access()
        normalized = self._normalize_options(self._definition(report_code), options or {})
        lines = self.env['account.move.line'].search(self._draft_domain(normalized))
        return {'type': 'ir.actions.act_window', 'name': _('Unposted Journal Entries'),
                'res_model': 'account.move', 'view_mode': 'list,form',
                'views': [(False, 'list'), (False, 'form')], 'target': 'current',
                'domain': [('id', 'in', lines.move_id.ids)]}

    @api.model
    def get_line_accounts(self, report_code, options, line_code):
        return self.get_lines_accounts(report_code, options, [line_code])[0]

    @api.model
    def get_lines_accounts(self, report_code, options, line_codes):
        self._check_report_access()
        report = self._definition(report_code)
        normalized = self._normalize_options(report, options or {})
        if not isinstance(line_codes, list) or any(not isinstance(code, str) for code in line_codes):
            raise ValidationError(_('Choose a report line that lists accounts.'))
        lines = {line.code: line for line in report.line_ids}
        accounts = self.env['account.account'].with_context(active_test=False).search([
            ('company_ids', 'in', self.env.companies.ids),
        ])
        columns = normalized['columns']
        periods = [column for column in columns if column['kind'] == 'period']
        cache = {}
        result = []
        for code in line_codes:
            line = lines.get(code)
            if not line or not any(expr.engine != 'formula' for expr in line.expression_ids):
                raise ValidationError(_('Choose a report line that lists accounts.'))
            result.append({'line_code': code, 'accounts': self._account_rows(
                line, periods, columns, normalized, accounts, cache, self.env.company.currency_id,
            )})
        return result

    @api.model
    def get_move_line_action(self, report_code, options, line_code, column_key, account_id=False, company_id=False):
        self._check_report_access()
        report = self._definition(report_code)
        normalized = self._normalize_options(report, options or {})
        if report.report_kind == 'aged':
            return self._aged_action(normalized, line_code, column_key, account_id)
        if report.report_kind == 'partner_ledger':
            return self._partner_move_line_action(normalized, line_code, account_id)
        if report.report_kind in ('account_grid', 'ledger'):
            if report.report_kind == 'ledger':
                column_key = 'end'
            return self._grid_move_line_action(report, normalized, line_code, column_key, account_id, company_id)
        line = report.line_ids.filtered(lambda item: item.code == line_code)[:1]
        if not line:
            raise ValidationError(_('Choose a line from this report.'))
        column = next((item for item in normalized['columns'] if item['key'] == column_key), None)
        if not column or column['kind'] != 'period':
            raise ValidationError(_('Open a period column to see journal items.'))
        account = self.env['account.account']
        if account_id:
            if type(account_id) is not int or account_id <= 0:
                raise ValidationError(_('Choose an account from this line.'))
            account = self.env['account.account'].browse(account_id)
            account.check_access('read')
            if not account.exists():
                raise AccessError(_('Choose an account from this line.'))
        if company_id and (not account or type(company_id) is not int or company_id not in self.env.companies.ids):
            raise AccessError(_('Choose an account from this line.'))
        domain = self._drill_domain(report, line, column, normalized, account, company_id)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Journal Items – %s') % line.name,
            'res_model': 'account.move.line',
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'target': 'current',
            'domain': self._public_domain(domain),
        }

    @api.model
    def _default_options(self):
        return {
            'preset': 'this_month',
            'comparison': 0,
            'comparison_unit': 'month',
            'comparison_mode': 'previous',
            'posted_only': True,
            'hide_zero': False,
            'journal_ids': [],
            'analytic_account_ids': [],
        }

    @api.model
    def _normalize_options(self, report, raw):
        if not isinstance(raw, dict):
            raise ValidationError(_('The report options are not valid.'))
        preset = raw.get('preset') or (report.default_preset if report.report_kind in ('partner_ledger', 'aged') else 'this_month') or 'this_month'
        if preset not in dict(self._preset_labels()):
            raise ValidationError(_('Choose a valid period.'))
        comparison = raw.get('comparison', 0)
        if type(comparison) is not int or comparison < 0 or comparison > 12:
            raise ValidationError(_('Comparison accepts 0 to 12 previous periods.'))
        unit = raw.get('comparison_unit') or 'month'
        if unit not in UNITS:
            raise ValidationError(_('Choose a month, quarter or year comparison.'))
        comparison_mode = raw.get('comparison_mode', 'previous')
        if comparison_mode not in ('previous', 'year'):
            raise ValidationError(_('The report options are not valid.'))
        posted_only = raw.get('posted_only', True)
        hide_zero = raw.get('hide_zero', False)
        if type(posted_only) is not bool or type(hide_zero) is not bool:
            raise ValidationError(_('The report options are not valid.'))
        direction = raw.get('direction', 0)
        if type(direction) is not int or direction not in (-1, 0, 1):
            raise ValidationError(_('The report options are not valid.'))
        journal_ids = self._id_list(raw.get('journal_ids', []), _('journals'))
        analytic_ids = self._id_list(raw.get('analytic_account_ids', []), _('analytic accounts'))
        self._check_journals(journal_ids)
        self._check_analytics(analytic_ids)
        anchor = self._optional_date(raw.get('anchor_date')) or fields.Date.context_today(self)
        if preset == 'custom':
            if report.date_mode == 'as_of':
                as_of = self._required_date(raw.get('as_of'), _('the as-of date'))
                if direction:
                    as_of = _shift_date(as_of, direction, unit)
                start, end = as_of, as_of
            else:
                start = self._required_date(raw.get('date_from'), _('the start date'))
                end = self._required_date(raw.get('date_to'), _('the end date'))
                if start > end:
                    raise ValidationError(_('The start date must be on or before the end date.'))
                if direction:
                    start = _shift_date(start, direction, unit)
                    end = _shift_date(end, direction, unit)
            anchor = end
        else:
            if direction:
                _start, _end, unit = self._preset_bounds(self.env.company, preset, anchor)
                anchor = _shift_date(anchor, direction, unit)
            start, end, unit = self._preset_bounds(self.env.company, preset, anchor)
        columns = self._columns(report, start, end, comparison, 'year' if comparison_mode == 'year' else unit)
        result = {
            'preset': preset,
            'as_of': fields.Date.to_string(end) if report.date_mode == 'as_of' else False,
            'date_from': fields.Date.to_string(start),
            'date_to': fields.Date.to_string(end),
            'anchor_date': fields.Date.to_string(anchor),
            'comparison': comparison,
            'comparison_unit': unit,
            'comparison_mode': comparison_mode,
            'posted_only': posted_only,
            'hide_zero': hide_zero,
            'journal_ids': journal_ids,
            'analytic_account_ids': analytic_ids,
            'date_mode': report.date_mode,
            'columns': columns,
        }
        if report.report_kind in ('partner_ledger', 'aged'):
            if report.report_kind == 'aged':
                raw = dict(raw)
                raw.setdefault('account_types', ['payable' if report.code == 'aged_payable' else 'receivable'])
            self._normalize_partner_options(raw, result)
            if report.report_kind == 'aged':
                basis, length = raw.get('aging_basis', 'due_date'), raw.get('period_length', 30)
                if basis not in ('due_date', 'invoice_date') or type(length) is not int or length <= 0 or any(('payable' in item) != (report.code == 'aged_payable') for item in result['account_types']):
                    raise ValidationError(_('The report options are not valid.'))
                result.update(aging_basis=basis, period_length=length, aged_payable=report.code == 'aged_payable')
        return result

    @api.model
    def _columns(self, report, start, end, comparison, unit):
        columns = [self._period_column(report, 'c0', start, end)]
        for offset in range(1, comparison + 1):
            columns.append(self._period_column(
                report, 'c%s' % offset,
                _shift_date(start, -offset, unit),
                _shift_date(end, -offset, unit),
            ))
        if report.report_kind == 'account_grid':
            return list(reversed(columns))
        if comparison:
            columns.append({'key': 'variation', 'kind': 'variation', 'label': _('Variation')})
            columns.append({'key': 'variation_percent', 'kind': 'variation_percent', 'label': '%'})
        return columns

    @api.model
    def _period_column(self, report, key, start, end):
        fiscal_start = self.env.company.compute_fiscalyear_dates(end)['date_from']
        if report.date_mode == 'as_of':
            label = _('As of %s') % format_date(self.env, end)
            date_from = False
            column_start = None
        else:
            label = _('From %s to %s') % (format_date(self.env, start), format_date(self.env, end))
            date_from = fields.Date.to_string(start)
            column_start = start
        return {
            'key': key,
            'kind': 'period',
            'label': label,
            'date_from': date_from,
            'date_to': fields.Date.to_string(end),
            'fiscal_start': fields.Date.to_string(fiscal_start),
            '_start': column_start,
            '_end': end,
            '_fiscal_start': fiscal_start,
        }

    @api.model
    def _preset_bounds(self, company, preset, anchor):
        if preset == 'today':
            return anchor, anchor, 'month'
        if preset == 'this_month':
            return (*_month_bounds(anchor), 'month')
        if preset == 'last_month':
            return (*_month_bounds(anchor.replace(day=1) - timedelta(days=1)), 'month')
        if preset == 'this_quarter':
            return (*_quarter_bounds(company, anchor), 'quarter')
        if preset == 'last_quarter':
            start, _end = _quarter_bounds(company, anchor)
            return (*_quarter_bounds(company, start - timedelta(days=1)), 'quarter')
        if preset in ('this_year', 'last_year'):
            bounds = company.compute_fiscalyear_dates(anchor)
            if preset == 'last_year':
                bounds = company.compute_fiscalyear_dates(bounds['date_from'] - timedelta(days=1))
            return bounds['date_from'], bounds['date_to'], 'year'
        raise ValidationError(_('Choose a valid period.'))

    @api.model
    def _build(self, report, options, with_accounts=False):
        currency = self.env.company.currency_id
        lines = report.line_ids
        order = self._computation_order(lines)
        accounts = self.env['account.account'].with_context(active_test=False).search([
            ('company_ids', 'in', self.env.companies.ids),
        ])
        cache = {}
        values = {line.code: {} for line in lines}
        period_columns = [column for column in options['columns'] if column['kind'] == 'period']
        for column in period_columns:
            for code, amount in self._column_values(
                report, order, column, options, accounts, cache,
            ).items():
                values[code][column['key']] = amount
        if any(column['kind'] == 'variation' for column in options['columns']):
            for amounts in values.values():
                _fill_variation(amounts)
        visible = self._visible_codes(lines, values, period_columns, options, currency)
        display_lines = []
        for line, level, is_total in self._display_order(lines):
            if line.code not in visible:
                continue
            has_accounts = any(expression.engine != 'formula' for expression in line.expression_ids)
            account_rows = []
            if with_accounts and has_accounts:
                account_rows = self._account_rows(
                    line, period_columns, options['columns'], options, accounts, cache, currency,
                )
            row = self._serialize_line(
                line, level, values[line.code], options['columns'], currency, has_accounts, account_rows,
            )
            if is_total:
                row.update(code='%s__total' % line.code, source_code=line.code,
                           name=_('Total %s') % line.name, display='total',
                           foldable=False, has_accounts=False, accounts=[])
            elif line.child_ids and line.show_total:
                row['hide_amounts'] = True
            display_lines.append(row)
        return {
            'report': {'code': report.code, 'name': report.name, 'date_mode': report.date_mode},
            'companies': [
                {'id': company.id, 'name': company.display_name, 'currency': company.currency_id.name} for company in self.env.companies
            ],
            'currency': {
                'id': currency.id,
                'code': currency.name or '',
                'symbol': currency.symbol or '',
                'decimals': currency.decimal_places,
            },
            'options': {key: value for key, value in options.items() if key != 'columns'},
            'columns': [
                {key: value for key, value in column.items() if not key.startswith('_')}
                for column in options['columns']
            ],
            'lines': display_lines,
            'notes': self._notes(report, options),
            'generated_at': fields.Datetime.context_timestamp(
                self, fields.Datetime.now(),
            ).strftime('%Y-%m-%d %H:%M'),
        }

    @api.model
    def _column_values(self, report, order, column, options, accounts, cache):
        values = {}
        for line in order:
            formula = line.expression_ids.filtered(lambda item: item.engine == 'formula')[:1]
            if formula:
                try:
                    values[line.code] = evaluate_formula(formula.formula, values)
                except FormulaError as error:
                    raise ValidationError(self._formula_message(error)) from error
                continue
            if line.expression_ids:
                total = Decimal('0')
                for expression in line.expression_ids:
                    total += self._expression_amount(
                        report, expression, column, options, accounts, cache,
                    )
                values[line.code] = total
                continue
            values[line.code] = sum(
                (values[child.code] for child in line.child_ids), Decimal('0'),
            )
        return values

    @api.model
    def _expression_amount(self, report, expression, column, options, accounts, cache):
        sign = Decimal(expression.sign)
        if expression.engine == 'domain':
            totals = self._scope_totals(
                report, column, expression.date_scope, options, cache, expression._domain_list(),
            )
            amount = sum((row[expression.figure] for row in totals.values()), Decimal('0'))
            return sign * amount
        totals = self._scope_totals(report, column, expression.date_scope, options, cache)
        amount = Decimal('0')
        by_id = {account.id: account for account in accounts}
        for (account_id, company_id), row in totals.items():
            account = by_id.get(account_id)
            if account and expression._matches_account(account.with_company(self.env['res.company'].browse(company_id))):
                amount += row[expression.figure]
        return sign * amount

    @api.model
    def _scope_totals(self, report, column, scope, options, cache, extra_domain=None):
        key = (column['key'], scope, repr(extra_domain or []))
        if key not in cache:
            domain = self._base_domain(options) + self._date_domain(report, column, scope)
            if extra_domain:
                domain = domain + list(extra_domain)
            cache[key] = self._aggregate(domain, column['_end'], options['analytic_account_ids'])
        return cache[key]

    @api.model
    def _aggregate(self, domain, on_date, analytic_ids, groupby=('account_id', 'company_id')):
        totals = {}
        if analytic_ids:
            selected = set(analytic_ids)
            lines = self.env['account.move.line'].search(domain)
            for values in lines.read([
                *groupby, 'company_id', 'debit', 'credit', 'balance', 'analytic_distribution',
            ]):
                share = _analytic_share(values.get('analytic_distribution'), selected)
                if share == 0 or not values['company_id']:
                    continue
                company = self.env['res.company'].browse(values['company_id'][0])
                key = tuple(values[field][0] if values.get(field) else False for field in groupby)
                bucket = totals.setdefault(key, _zeros())
                for figure in ('balance', 'debit', 'credit'):
                    amount = Decimal(str(values[figure] or 0)) * share
                    bucket[figure] += self._convert(amount, company, on_date)
            return totals
        rows = self.env['account.move.line']._read_group(
            domain, list(groupby), ['balance:sum', 'debit:sum', 'credit:sum'],
        )
        for row in rows:
            groups, (balance, debit, credit) = row[:-3], row[-3:]
            company = groups[groupby.index('company_id')]
            key = tuple(value.id if value else False for value in groups)
            bucket = totals.setdefault(key, _zeros())
            for figure, amount in (
                ('balance', balance), ('debit', debit), ('credit', credit),
            ):
                bucket[figure] += self._convert(amount, company, on_date)
        return totals

    @api.model
    def _convert(self, amount, company, on_date):
        amount = Decimal(str(amount or 0))
        target = self.env.company.currency_id
        source = company.currency_id
        if not source or source == target:
            return amount
        return Decimal(str(source._convert(float(amount), target, company, on_date)))

    @api.model
    def _base_domain(self, options):
        states = ['posted'] if options['posted_only'] else ['posted', 'draft']
        domain = [
            ('company_id', 'in', self.env.companies.ids),
            ('parent_state', 'in', states),
            ('account_id', '!=', False),
        ]
        if options['journal_ids']:
            domain.append(('journal_id', 'in', options['journal_ids']))
        if options['analytic_account_ids']:
            domain.append(('analytic_distribution', 'in', options['analytic_account_ids']))
        return domain

    @api.model
    def _date_domain(self, report, column, scope):
        date_to = column['_end']
        if scope == 'to_date' or (scope == 'report' and report.date_mode == 'as_of'):
            return [('date', '<=', date_to)]
        if scope == 'report':
            return [('date', '>=', column['_start']), ('date', '<=', date_to)]
        fiscal_start = column['_fiscal_start']
        if scope == 'from_fiscalyear':
            return [('date', '>=', fiscal_start), ('date', '<=', date_to)]
        if scope == 'before_fiscalyear':
            return [('date', '<', fiscal_start)]
        raise ValidationError(_('The date scope %s is not supported.') % scope)

    @api.model
    def _account_rows(self, line, period_columns, columns, options, accounts, cache, currency):
        expressions = line.expression_ids.filtered(lambda item: item.engine != 'formula')
        rows = []
        pairs = [(account.with_company(company), company) for account in accounts
                 for company in self.env.companies if company in account.company_ids]
        for account, company in sorted(pairs, key=lambda pair: (pair[0].code or '', pair[0].id, pair[1].id)):
            amounts = {}
            used = False
            for column in period_columns:
                total = Decimal('0')
                for expression in expressions:
                    if expression.engine == 'domain':
                        totals = self._scope_totals(
                            line.report_id, column, expression.date_scope, options, cache,
                            expression._domain_list(),
                        )
                    elif expression._matches_account(account):
                        totals = self._scope_totals(
                            line.report_id, column, expression.date_scope, options, cache,
                        )
                    else:
                        continue
                    row = totals.get((account.id, company.id))
                    if not row:
                        continue
                    total += Decimal(expression.sign) * row[expression.figure]
                    used = True
                amounts[column['key']] = total
            if not used:
                continue
            if options['hide_zero'] and all(
                currency.is_zero(float(amounts[column['key']])) for column in period_columns
            ):
                continue
            _fill_variation(amounts, columns)
            rows.append({
                'id': account.id,
                'company_id': company.id,
                'company_name': company.name,
                'code': account.code or '',
                'name': account.name or '',
                'amounts': [
                    self._serialize_amount(
                        column, amounts.get(column['key']), currency, drill=column['kind'] == 'period',
                    )
                    for column in columns
                ],
            })
        if len(self.env.companies) > 1:
            counts = {}
            for row in rows:
                key = (row['code'], row['name'])
                counts[key] = counts.get(key, 0) + 1
            for row in rows:
                if counts[(row['code'], row['name'])] > 1:
                    row['name'] += ' — ' + row['company_name']
        return rows

    @api.model
    def _drill_domain(self, report, line, column, options, account, company_id=False):
        parts = []
        for expression in self._drill_expressions(line):
            if account and expression.engine != 'domain' and not expression._matches_account(account.with_company(self.env['res.company'].browse(company_id)) if company_id else account):
                continue
            if account and expression.engine == 'domain':
                probe = (
                    self._base_domain(options)
                    + self._date_domain(report, column, expression.date_scope)
                    + expression._domain_list()
                    + [('account_id', '=', account.id)]
                )
                if not any(key[0] == account.id and (not company_id or key[1] == company_id) for key in self._aggregate(probe, column['_end'], options['analytic_account_ids'])):
                    continue
                account_domain = expression._domain_list() + [('account_id', '=', account.id)]
            elif account:
                account_domain = [('account_id', '=', account.id)]
            else:
                account_domain = expression._account_domain()
            parts.append(
                self._base_domain(options)
                + self._date_domain(report, column, expression.date_scope)
                + account_domain
                + ([('company_id', '=', company_id)] if company_id else [])
            )
        if not parts:
            raise AccessError(_('This amount has no journal items to open.'))
        return _or_domains(parts)

    @api.model
    def _drill_expressions(self, line):
        by_code = {item.code: item for item in line.report_id.line_ids}
        empty = self.env['baseer.report.expression']

        def resolve(current, visited):
            if current.code in visited:
                return None
            visited = visited | {current.code}
            formula = current.expression_ids.filtered(lambda item: item.engine == 'formula')[:1]
            if formula:
                try:
                    tree = ast.parse(formula.formula, mode='eval').body
                except SyntaxError:
                    return None

                def names(node):
                    if isinstance(node, ast.Name):
                        return [node.id]
                    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                        left, right = names(node.left), names(node.right)
                        return left + right if left is not None and right is not None else None
                    return None

                codes = names(tree)
                if not codes or len(codes) != len(set(codes)):
                    return None
                children = [by_code.get(code) for code in codes]
            elif current.expression_ids:
                return current.expression_ids
            else:
                children = list(current.child_ids)
            result = empty
            for child in children:
                if not child:
                    return None
                expressions = resolve(child, visited)
                if expressions is None or set(result.ids) & set(expressions.ids):
                    return None
                result |= expressions
            return result

        expressions = resolve(line, set())
        if not expressions or len(set(expressions.mapped('sign'))) != 1 or any(
            expression.figure != 'balance' for expression in expressions
        ):
            return empty
        return expressions

    @api.model
    def _serialize_line(self, line, level, amounts, columns, currency, has_accounts, account_rows):
        return {
            'id': line.id,
            'code': line.code,
            'name': line.name,
            'level': level,
            'parent_code': line.parent_id.code or False,
            'foldable': line.foldable,
            'display': line.display,
            'has_accounts': has_accounts,
            'amounts': [
                self._serialize_amount(
                    column, amounts.get(column['key']), currency,
                    drill=column['kind'] == 'period' and bool(self._drill_expressions(line)),
                )
                for column in columns
            ],
            'accounts': account_rows,
        }

    @api.model
    def _serialize_amount(self, column, amount, currency, drill):
        if column['kind'] == 'variation_percent':
            if amount is None:
                return {
                    'key': column['key'], 'value': None, 'display': '—',
                    'negative': False, 'zero': True, 'drill': False,
                }
            quant = Decimal(amount).quantize(Decimal('0.01'))
            text = f'{abs(quant):,.2f}%'
            return {
                'key': column['key'],
                'value': f'{quant:.2f}',
                'display': ('-' + text) if quant < 0 else text,
                'negative': quant < 0,
                'zero': quant == 0,
                'drill': False,
            }
        quant = _quantize(amount or Decimal('0'), currency)
        digits = currency.decimal_places
        text = f'{abs(quant):,.{digits}f}'
        return {
            'key': column['key'],
            'value': f'{quant:.{digits}f}',
            'display': ('-' + text) if quant < 0 else text,
            'negative': quant < 0,
            'zero': quant == 0,
            'drill': drill,
        }

    @api.model
    def _grouped_children(self, lines):
        grouped = {}
        for line in lines:
            grouped.setdefault(line.parent_id.id or 0, []).append(line.id)
        model = self.env['baseer.report.line']
        return {
            parent_id: model.browse(ids).sorted(key=lambda item: (item.sequence, item.id))
            for parent_id, ids in grouped.items()
        }

    @api.model
    def _visible_codes(self, lines, values, period_columns, options, currency):
        children = self._grouped_children(lines)

        def own_zero(line):
            return all(
                currency.is_zero(float(values[line.code].get(column['key'], 0)))
                for column in period_columns
            )

        visible = set()

        def walk(line):
            # Visit every child. any() would stop at the first visible child.
            child_visible = False
            for child in children.get(line.id, ()):
                if walk(child):
                    child_visible = True
            show = (
                not options['hide_zero'] or not line.hideable or not own_zero(line) or child_visible
            )
            if show:
                visible.add(line.code)
            return show

        for root in children.get(0, []):
            walk(root)
        return visible

    @api.model
    def _display_order(self, lines):
        children = self._grouped_children(lines)
        ordered = []

        def walk(parent_id, level):
            for line in children.get(parent_id, []):
                ordered.append((line, level, False))
                walk(line.id, level + 1)
                if line.child_ids and line.show_total:
                    ordered.append((line, level, True))

        walk(0, 0)
        return ordered

    @api.model
    def _computation_order(self, lines):
        by_code = {line.code: line for line in lines}
        dependencies = {}
        for line in lines:
            formula = line.expression_ids.filtered(lambda item: item.engine == 'formula')[:1]
            if formula:
                try:
                    dependencies[line.code] = referenced_codes(formula.formula)
                except FormulaError as error:
                    raise ValidationError(self._formula_message(error)) from error
            elif not line.expression_ids:
                dependencies[line.code] = [child.code for child in line.child_ids]
            else:
                dependencies[line.code] = []
        order = []
        visiting, visited = set(), set()
        cycle_message = _('The formula for %s refers to itself.')
        unknown_message = _('The formula refers to an unknown line %s.')

        def visit(code):
            if code in visited:
                return
            if code in visiting:
                raise ValidationError(cycle_message % code)
            if code not in by_code:
                raise ValidationError(unknown_message % code)
            visiting.add(code)
            for dependency in dependencies[code]:
                visit(dependency)
            visiting.remove(code)
            visited.add(code)
            order.append(by_code[code])

        for code in by_code:
            visit(code)
        return order

    @api.model
    def _notes(self, report, options):
        notes = [
            _('Posted entries only.') if options['posted_only'] else _('Posted and draft entries.'),
        ]
        if report.date_mode == 'as_of':
            notes.append(_(
                'Balances are cumulative from the beginning of the books through the selected date.'
            ))
        else:
            notes.append(_('Amounts cover the selected dates.'))
        if options['journal_ids']:
            notes.append(_('Selected journals only.'))
        if options['analytic_account_ids']:
            notes.append(_('Amounts are weighted by the selected analytic distribution.'))
        notes.append(_('Companies follow the ones active in this session.'))
        return notes

    @api.model
    def _formula_message(self, error):
        if error.code == 'unknown':
            return _('The formula refers to an unknown line %s.') % (error.detail or '')
        if error.code == 'division':
            return _('The formula divides by zero.')
        return _('The formula is not valid.')

    @api.model
    def _labels(self):
        return {
            'account_filter': _('Account:'),
            'partners': _('Partners'),
            'partner_categories': _('Partner Categories'),
            'unreconciled_entries': _('Unreconciled Entries'),
            'trade_partners': _('Trade Partners'),
            'partner': _('Partner'),
            'balance': _('Balance'),
            'initial_balance': _('Initial Balance'),
            'end_balance': _('End Balance'),
            'debit': _('Debit'),
            'credit': _('Credit'),
            'total': _('Total'),
            'search': _('Search...'),
            'general_ledger': _('General Ledger'),
            'journal_items': _('Journal Items'),
            'view_journal_entry': _('View Journal Entry'),
            'load_more': _('Load more...'),
            'unfold_line': _('Unfold'),
            'fold_line': _('Fold'),
            'total_format': _('Total %s'),
            'end_month': _('End of Month'),
            'end_quarter': _('End of Quarter'),
            'end_year': _('End of Year'),
            'specific_date': _('Specific Date'),
            'custom_dates': _('Custom Dates'),
            'posted_entries': _('Posted Entries'),
            'posted_draft_entries': _('Posted & Draft Entries'),
            'analytic': _('Analytic'),
            'in_currency': _('In'),
            'banner_before': _('There are'),
            'banner_link': _('unposted Journal Entries'),
            'banner_after': _('prior or included in this period.'),
            'hide_lines_zero': _('Hide lines at 0'),
            'journal_count': _('Journals'),
            'apply': _('Apply'),
            'no_comparison': _('No Comparison'),
            'same_last_year': _('Same Period Last Year'),
            'number_periods': _('Number of periods'),
            'draft_entries': _('Draft Entries'),
            'options': _('Options'),
            'unfold_all': _('Unfold All'),
            'fold_all': _('Fold All'),
            'pdf': _('PDF'),
            'xlsx': _('XLSX'),
            'period': _('Period'),
            'as_of': _('As of'),
            'from': _('From'),
            'to': _('To'),
            'comparison': _('Comparison'),
            'comparison_unit': _('Comparison period'),
            'posted_only': _('Posted entries only'),
            'hide_zero': _('Hide zero lines'),
            'journals': _('Journals'),
            'all_journals': _('All Journals'),
            'analytics': _('Analytic accounts'),
            'all_analytics': _('All analytic accounts'),
            'loading': _('Loading the report…'),
            'error': _(
                'The report could not be loaded. Check the dates and your access, then try again.'
            ),
            'empty': _('No lines to display.'),
            'accounts_empty': _('No accounts on this line.'),
            'previous': _('Previous Period'),
            'next': _('Next period'),
            'unfold': _('Show details'),
            'fold': _('Hide details'),
            'drill': _('View journal items'),
            'companies': _('Companies'),
        }

    @api.model
    def _preset_labels(self):
        return (
            ('today', _('Today')),
            ('this_month', _('This month')),
            ('this_quarter', _('This quarter')),
            ('this_year', _('This year')),
            ('last_month', _('Last month')),
            ('last_quarter', _('Last quarter')),
            ('last_year', _('Last year')),
            ('custom', _('Custom')),
        )

    @api.model
    def _unit_labels(self):
        return (
            ('month', _('Month')),
            ('quarter', _('Quarter')),
            ('year', _('Year')),
        )

    @api.model
    def _check_report_access(self):
        if not self.env.companies or not any(
            self.env.user.has_group(xmlid) for xmlid in ACCOUNTING_GROUPS
        ):
            raise AccessError(_('You need accounting access to open this report.'))

    @api.model
    def _definition(self, report_code):
        if not isinstance(report_code, str) or not report_code:
            raise ValidationError(_('Choose a report.'))
        report = self.env['baseer.report.definition'].search([('code', '=', report_code)], limit=1)
        if not report:
            raise AccessError(_('This report is not available.'))
        return report

    @api.model
    def _id_list(self, value, label):
        if not isinstance(value, list) or any(type(item) is not int or item <= 0 for item in value):
            raise ValidationError(_('The selected %s are not valid.') % label)
        if len(value) > 200:
            raise ValidationError(_('Select at most 200 %s.') % label)
        return list(dict.fromkeys(value))

    @api.model
    def _check_journals(self, journal_ids):
        if not journal_ids:
            return
        journals = self.env['account.journal'].browse(journal_ids)
        journals.check_access('read')
        if len(journals.exists()) != len(set(journal_ids)) or any(
            journal.company_id not in self.env.companies for journal in journals
        ):
            raise AccessError(_('Select journals from the active companies.'))

    @api.model
    def _check_analytics(self, analytic_ids):
        if not analytic_ids:
            return
        accounts = self.env['account.analytic.account'].browse(analytic_ids)
        accounts.check_access('read')
        if len(accounts.exists()) != len(set(analytic_ids)) or any(
            account.company_id and account.company_id not in self.env.companies for account in accounts
        ):
            raise AccessError(_('Select analytic accounts from the active companies.'))

    @api.model
    def _journal_options(self):
        journals = self.env['account.journal'].search([
            ('company_id', 'in', self.env.companies.ids),
        ])
        return [
            {'id': journal.id, 'name': journal.display_name, 'code': journal.code or '', 'type': dict(journal._fields['type']._description_selection(self.env)).get(journal.type, '')}
            for journal in journals
        ]

    @api.model
    def _analytic_options(self):
        model = self.env['account.analytic.account']
        if not model.has_access('read'):
            return []
        accounts = model.search([
            '|', ('company_id', '=', False), ('company_id', 'in', self.env.companies.ids),
        ])
        return [{'id': account.id, 'name': account.display_name} for account in accounts]

    @api.model
    def _optional_date(self, value):
        if not value:
            return None
        return self._required_date(value, _('the date'))

    @api.model
    def _required_date(self, value, label):
        if hasattr(value, 'year') and not isinstance(value, str):
            return value
        try:
            parsed = fields.Date.to_date(value)
        except (TypeError, ValueError):
            parsed = None
        if not parsed:
            raise ValidationError(_('Enter a valid date for %s.') % label)
        return parsed

    @api.model
    def _public_domain(self, domain):
        public = []
        for term in domain:
            if isinstance(term, (list, tuple)) and len(term) == 3 and hasattr(term[2], 'isoformat'):
                public.append((term[0], term[1], term[2].isoformat()))
            else:
                public.append(term)
        return public


def _zeros():
    return {'balance': Decimal('0'), 'debit': Decimal('0'), 'credit': Decimal('0')}


def _quantize(amount, currency):
    digits = currency.decimal_places
    return Decimal(str(currency.round(float(amount)))).quantize(Decimal('1').scaleb(-digits))


def _fill_variation(amounts, columns=None):
    if columns is not None and not any(column['kind'] == 'variation' for column in columns):
        return
    if 'c0' not in amounts:
        return
    current = amounts.get('c0', Decimal('0'))
    previous = amounts.get('c1', Decimal('0'))
    amounts['variation'] = current - previous
    amounts['variation_percent'] = None if previous == 0 else (
        (current - previous) / abs(previous) * Decimal('100')
    )


def _month_bounds(day):
    return day.replace(day=1), day + relativedelta(day=31)


def _quarter_bounds(company, day):
    fiscal_start = company.compute_fiscalyear_dates(day)['date_from']
    for index in range(4):
        start = fiscal_start + relativedelta(months=3 * index)
        end = fiscal_start + relativedelta(months=3 * (index + 1), days=-1)
        if start <= day <= end:
            return start, end
    bounds = company.compute_fiscalyear_dates(day)
    return bounds['date_from'], bounds['date_to']


def _shift_date(day, steps, unit):
    months = {'month': 1, 'quarter': 3, 'year': 12}[unit] * steps
    shifted = day + relativedelta(months=months)
    if day == day + relativedelta(day=31):
        shifted = shifted + relativedelta(day=31)
    return shifted


def _analytic_share(distribution, selected_ids):
    if not distribution:
        return Decimal('0')
    total = Decimal('0')
    for key, value in distribution.items():
        try:
            if int(key) in selected_ids:
                total += Decimal(str(value))
        except (TypeError, ValueError, ArithmeticError):
            continue
    if total <= 0:
        return Decimal('0')
    if total > 100:
        total = Decimal('100')
    return total / Decimal('100')
