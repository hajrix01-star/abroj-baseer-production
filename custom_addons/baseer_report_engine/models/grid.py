"""Grouped journal-item reports. Fiscal carry-forward is a grid layout policy."""
from decimal import Decimal
from calendar import monthrange

from odoo.tools.misc import format_date

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

from .definition import _or_domains
from .engine import _zeros

PL_TYPES = ('income', 'income_other', 'expense', 'expense_other',
            'expense_depreciation', 'expense_direct_cost')


class BaseerGridEngine(models.AbstractModel):
    _inherit = 'baseer.report.engine'

    @api.model
    def _grid_balances(self, options, groupby, scopes):
        """Aggregate each scope under ORM record rules, using statement conversion.

        Analytic filters deliberately use the statement engine's per-line weighted
        aggregation; without them each scope is one grouped query.
        """
        if not isinstance(groupby, tuple) or 'company_id' not in groupby:
            raise ValidationError(_('The report options are not valid.'))
        return {key: self._aggregate(self._base_domain(options) + domain, date,
                                     options['analytic_account_ids'], groupby=groupby)
                for key, domain, date in scopes}

    @api.model
    def _grid_layout(self, periods, grid_columns):
        """Expand declarative column tokens into visible columns and groups."""
        columns, groups = [], []
        tokens = [token.strip() for token in grid_columns.split(',') if token.strip()]
        labels = {'initial': _('Initial Balance'), 'end': _('End Balance')}
        figures = {'initial': ('balance', _('Balance')), 'end': ('balance', _('Balance')),
                   'period_debit': ('debit', _('Debit')), 'period_credit': ('credit', _('Credit'))}
        if not tokens or any(token not in figures for token in tokens):
            raise ValidationError(_('The report options are not valid.'))
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token.startswith('period_'):
                period_tokens = []
                while index < len(tokens) and tokens[index].startswith('period_'):
                    period_tokens.append(tokens[index])
                    index += 1
                for period in periods:
                    start, end = period['_start'], period['_end']
                    label = (format_date(self.env, end, date_format='MMM y')
                             if start.day == 1 and start.year == end.year and start.month == end.month
                             and end.day == monthrange(end.year, end.month)[1] else period['label'])
                    groups.append({'label': label, 'colspan': len(period_tokens), 'kind': 'period', 'period_key': period['key']})
                    for item in period_tokens:
                        figure, label = figures[item]
                        columns.append({'key': period['key'] + '_' + figure, 'kind': 'period',
                                        'label': label, 'figure': figure, 'period_key': period['key']})
            else:
                figure, label = figures[token]
                columns.append({'key': token, 'kind': token, 'label': label, 'figure': figure})
                groups.append({'label': labels[token], 'colspan': 1, 'kind': token, 'period_key': False})
                index += 1
        return columns, groups

    @api.model
    def _grid_prior_domain(self, first):
        return _or_domains([[('company_id', '=', company.id),
                             ('date', '<', company.compute_fiscalyear_dates(first)['date_from'])]
                            for company in self.env.companies]) + [('account_id.account_type', 'in', PL_TYPES)]

    @api.model
    def _grid_earnings_accounts(self):
        accounts = self.env['account.account']
        return {company.id: accounts.with_company(company).with_context(active_test=True).search([
            *accounts._check_company_domain(company), ('account_type', '=', 'equity_unaffected'),
        ], limit=1) for company in self.env.companies}

    @api.model
    def _grid_carry_forward(self, balances, prior, earnings):
        """Move prior fiscal years' P&L balances to each company's earnings row.

        Keep the source aggregates untouched so another report layout can reuse
        them for period movements as well as opening and closing balances.
        """
        adjusted = {key: dict(value) for key, value in balances.items()}
        for (account_id, company_id), values in prior.items():
            adjusted[(account_id, company_id)]['balance'] -= values['balance']
            account = earnings[company_id]
            key = (account.id if account else 0, company_id)
            adjusted.setdefault(key, _zeros())['balance'] += values['balance']
        return adjusted

    @api.model
    def _build_grid(self, report, options):
        periods = options['columns']
        first, last = periods[0]['_start'], periods[-1]['_end']
        columns, groups = self._grid_layout(periods, report.grid_columns)
        scopes = [('initial', [('date', '<', first)], first),
                  ('prior', self._grid_prior_domain(first), first),
                  ('prior_end', self._grid_prior_domain(first), last)]
        scopes += [(p['key'], [('date', '>=', p['_start']), ('date', '<=', p['_end'])], p['_end']) for p in periods]
        # This scope also retains accounts with offsetting activity outside the displayed periods.
        scopes.append(('end', [('date', '<=', last)], last))
        groupby = tuple(field.strip() for field in report.grid_groupby.split(',') if field.strip())
        if groupby == ('account',):  # Compatibility with existing definitions.
            groupby = ('account_id', 'company_id')
        if groupby != ('account_id', 'company_id'):
            raise ValidationError(_('The report options are not valid.'))
        sums = self._grid_balances(options, groupby, scopes)
        earnings = self._grid_earnings_accounts()
        adjusted = {
            scope: self._grid_carry_forward(sums[scope], sums[prior], earnings)
            for scope, prior in (('initial', 'prior'), ('end', 'prior_end'))
        }
        keys = set(adjusted['end']) | set(adjusted['initial'])
        accounts = self.env['account.account'].with_context(active_test=False).browse(list({key[0] for key in keys if key[0]})).exists()
        by_id = {a.id: a for a in accounts}
        currency = self.env.company.currency_id
        rows = []
        totals = {c['key']: Decimal('0') for c in columns}
        for account_id, company_id in keys:
            account = by_id.get(account_id)
            if account_id and not account:
                continue
            company = self.env['res.company'].browse(company_id)
            if account:
                account = account.with_company(company)
            values = {'initial': adjusted['initial'].get((account_id, company_id), _zeros())['balance']}
            for period in periods:
                bucket = sums[period['key']].get((account_id, company_id), _zeros())
                for figure in ('debit', 'credit'):
                    values[period['key'] + '_' + figure] = bucket[figure]
            values['end'] = adjusted['end'].get((account_id, company_id), _zeros())['balance']
            if options['hide_zero'] and all(currency.is_zero(float(v)) for v in values.values()):
                continue
            for key, value in values.items():
                totals[key] += value
            rows.append({'id': account_id, 'account_id': account_id, 'company_id': company_id,
                         'company_name': company.name, 'account_code': account.code or '' if account else '',
                         'account_name': account.name or '' if account else _('Undistributed Profits/Losses'), 'code': 'account_%s_%s' % (account_id, company_id),
                         'name': ('%s %s' % (account.code or '', account.name or '')).strip() if account else _('Undistributed Profits/Losses'),
                         'level': 0, 'display': 'line', 'foldable': False, 'has_accounts': False,
                         'accounts': [], 'amounts': [self._serialize_amount(c, values[c['key']], currency, True) for c in columns]})
        counts = {}
        for row in rows:
            counts[row['name']] = counts.get(row['name'], 0) + 1
        for row in rows:
            if counts[row['name']] > 1:
                row['name'] += ' — ' + row['company_name']
                row['account_name'] += ' — ' + row['company_name']
        rows.sort(key=lambda r: (r['account_code'], r['account_id'], r['company_id']))
        rows.append({'code': 'total', 'name': _('Total'), 'level': 0, 'display': 'total',
                     'foldable': False, 'has_accounts': False, 'accounts': [],
                     'amounts': [self._serialize_amount(c, totals[c['key']], currency, False) for c in columns]})
        # Reuse the statement envelope without invoking its computation.
        return {'report': {'code': report.code, 'name': report.name, 'date_mode': report.date_mode, 'report_kind': report.report_kind},
                'companies': [{'id': c.id, 'name': c.display_name, 'currency': c.currency_id.name} for c in self.env.companies],
                'currency': {'id': currency.id, 'code': currency.name or '', 'symbol': currency.symbol or '', 'position': currency.position, 'decimals': currency.decimal_places},
                'options': {k: v for k, v in options.items() if k != 'columns'},
                'columns': columns, 'column_groups': groups, 'lines': rows, 'notes': self._notes(report, options),
                'generated_at': fields.Datetime.context_timestamp(self, fields.Datetime.now()).strftime('%Y-%m-%d %H:%M')}

    @api.model
    def _grid_move_line_action(self, report, options, line_code, column_key, account_id, company_id):
        if type(account_id) is not int or type(company_id) is not int or company_id not in self.env.companies.ids or line_code != 'account_%s_%s' % (account_id, company_id):
            raise AccessError(_('Choose an account from this line.'))
        company = self.env['res.company'].browse(company_id)
        account = self.env['account.account'].with_context(active_test=False).browse(account_id).exists()
        if account_id and not account:
            raise AccessError(_('Choose an account from this line.'))
        if account:
            account.check_access('read')
        if (account and company not in account.company_ids) or (not account and (account_id != 0 or self._grid_earnings_accounts().get(company_id))):
            raise AccessError(_('Choose an account from this line.'))
        periods = options['columns']
        columns, _groups = self._grid_layout(periods, report.grid_columns)
        column = next((c for c in columns if c['key'] == column_key), None)
        if column_key == 'range':
            column = {'kind': 'range'}
        if not column:
            raise ValidationError(_('Open a period column to see journal items.'))
        first = periods[0]['_start']
        fiscal = company.compute_fiscalyear_dates(first)['date_from']
        own = [('account_id', '=', account.id)] if account else [('id', '=', 0)]
        if column['kind'] == 'range':
            domain = own + [('date', '>=', first), ('date', '<=', periods[-1]['_end'])]
        elif column['kind'] == 'period':
            period = next(p for p in periods if p['key'] == column['period_key'])
            own += [('date', '>=', period['_start']), ('date', '<=', period['_end'])]
            domain = own
        else:
            before = own + [('date', '<', first)]
            if account and account.account_type in PL_TYPES:
                before += [('date', '>=', fiscal)]
            parts = [before]
            if not account or account == self._grid_earnings_accounts().get(company_id):
                parts.append([('account_id.account_type', 'in', PL_TYPES), ('date', '<', fiscal)])
            if column['kind'] == 'end':
                parts.append(own + [('date', '>=', first), ('date', '<=', periods[-1]['_end'])])
            domain = _or_domains(parts)
        domain = self._base_domain(options) + [('company_id', '=', company_id)] + domain
        return {'type': 'ir.actions.act_window', 'name': _('Journal Items – %s') % (account.name if account else _('Undistributed Profits/Losses')),
                'res_model': 'account.move.line', 'view_mode': 'list,form',
                'views': [(False, 'list'), (False, 'form')], 'target': 'current',
                'domain': self._public_domain(domain)}
