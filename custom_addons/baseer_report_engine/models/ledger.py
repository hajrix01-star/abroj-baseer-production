"""Ledger layout over the shared account-grid fiscal carry-forward policy."""
from decimal import Decimal

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools.misc import format_date, format_amount
from odoo.tools import SQL

from .engine import _analytic_share, _zeros


class BaseerLedgerEngine(models.AbstractModel):
    _inherit = 'baseer.report.engine'

    _gl_page_size = 80
    _gl_unfold_all_page_size = 20

    @api.model
    def _ledger_columns(self, options):
        labels = [('date', _('Date')), ('partner', _('Partner')), ('currency', _('Currency')),
                  ('debit', _('Debit')), ('credit', _('Credit')), ('balance', _('Balance'))]
        return [{'key': key, 'label': label, 'kind': 'ledger', 'figure': key} for key, label in labels]

    @api.model
    def _ledger_data(self, report, options):
        first, last = options['columns'][0]['_start'], options['columns'][0]['_end']
        scopes = [('initial', [('date', '<', first)], last),
                  ('prior', self._grid_prior_domain(first), last),
                  ('period', [('date', '>=', first), ('date', '<=', last)], last)]
        sums = self._grid_balances(options, ('account_id', 'company_id'), scopes)
        opening = {key: dict(value) for key, value in sums['initial'].items()}
        earnings = self._grid_earnings_accounts()
        for key, prior in sums['prior'].items():
            for figure in ('debit', 'credit', 'balance'):
                opening[key][figure] -= prior[figure]
            target = (earnings[key[1]].id or 0, key[1])
            bucket = opening.setdefault(target, _zeros())
            # Preserve gross debit and credit for the cumulative drill domain.
            for figure in ('debit', 'credit', 'balance'):
                bucket[figure] += prior[figure]
        return opening, sums['period']

    @api.model
    def _ledger_amounts(self, values, drill=False):
        currency = self.env.company.currency_id
        return [self._serialize_amount({'key': key, 'kind': 'ledger'}, values.get(key, 0), currency, drill)
                for key in ('debit', 'credit', 'balance')]

    @api.model
    def _build_ledger(self, report, options, raw, ledger_data=None):
        # Grid supplies names, ordering, disambiguation and the exact closing balance.
        grid = self._build_grid(report, dict(options, hide_zero=False))
        opening, period = ledger_data or self._ledger_data(report, options)
        rows = []
        totals = _zeros()
        for row in grid['lines'][:-1]:
            key = (row['account_id'], row['company_id'])
            initial, movement = opening.get(key, _zeros()), period.get(key, _zeros())
            values = {k: initial[k] + movement[k] for k in ('debit', 'credit')}
            values['balance'] = Decimal(row['amounts'][-1]['value'])
            if all(self.env.company.currency_id.is_zero(float(values[k])) for k in values) and not any(initial.values()) and not any(movement.values()):
                continue
            for k in values:
                totals[k] += values[k]
            row.update(foldable=True, has_accounts=True, amounts=self._ledger_amounts(values, True))
            rows.append(row)
        rows.append({'code': 'total', 'name': _('Total General Ledger'), 'level': 0, 'display': 'total',
                     'foldable': False, 'has_accounts': False, 'amounts': self._ledger_amounts(totals)})
        grid['lines'] = rows
        grid['columns'] = self._ledger_columns(options)
        layout_columns, groups = self._grid_layout(options['columns'][:1], 'period_debit,period_credit')
        grid['column_groups'] = [dict(groups[0], colspan=6)]
        unfolded = raw.get('unfolded_accounts', [])
        unfold_all = raw.get('unfold_all', False)
        if type(unfold_all) is not bool or not isinstance(unfolded, list) or any(
            not isinstance(pair, (list, tuple)) or len(pair) != 2 or any(type(x) is not int for x in pair) for pair in unfolded
        ):
            raise ValidationError(_('The report options are not valid.'))
        selected = [row for row in rows[:-1] if unfold_all or [row['account_id'], row['company_id']] in unfolded]
        if selected:
            limit = None if self.env.context.get('baseer_gl_export') else self._ledger_limit(None)
            if unfold_all and limit is not None:
                limit = min(limit, self._gl_unfold_all_page_size)
            pages = self._ledger_pages(options, selected, opening, 0, limit)
            for row in selected:
                row['ledger'] = pages[(row['account_id'], row['company_id'])]
        grid['options'].update(unfold_all=unfold_all, unfolded_accounts=unfolded)
        return grid

    @api.model
    def _ledger_limit(self, limit):
        size = self.env.context.get('baseer_gl_page_size', self._gl_page_size)
        if type(size) is not int or size < 1 or (limit is not None and (type(limit) is not int or limit < 1)):
            raise ValidationError(_('The report options are not valid.'))
        return min(size, limit) if limit is not None else size

    @api.model
    def _ledger_convert(self, amount, company, on_date):
        source, target = company.currency_id, self.env.company.currency_id
        if not source or source == target:
            return amount
        rate = source._get_conversion_rate(source, target, company, on_date)
        return amount * Decimal(str(rate))

    @api.model
    def _ledger_pages(self, options, accounts, opening, offset, limit):
        first, last = options['columns'][0]['_start'], options['columns'][0]['_end']
        keys = {(row['account_id'], row['company_id']) for row in accounts}
        domain = self._base_domain(options) + [('date', '>=', first), ('date', '<=', last),
                 ('account_id', 'in', [key[0] for key in keys if key[0]]),
                 ('company_id', 'in', list({key[1] for key in keys}))]
        model = self.env['account.move.line']
        # _search applies record rules before ranking lines within each account.
        model.flush_model(['date', 'move_name', 'account_id', 'company_id', 'balance', 'analytic_distribution'])
        query = model._search(domain)
        ranked = query.select(SQL('account_move_line.id'), SQL('account_move_line.account_id'),
            SQL('account_move_line.company_id'), SQL('ROW_NUMBER() OVER (PARTITION BY account_move_line.account_id, account_move_line.company_id ORDER BY account_move_line.date, account_move_line.move_name, account_move_line.id) AS rn'),
            SQL('COUNT(*) OVER (PARTITION BY account_move_line.account_id, account_move_line.company_id) AS total'))
        upper = offset + limit if limit is not None else 2147483647
        result_rows = self.env.execute_query(SQL('SELECT id, account_id, company_id, total FROM (%s) AS ranked WHERE rn > %s AND rn <= %s ORDER BY rn', ranked, offset, upper))
        previous_balances = {}
        if offset:
            share = SQL('1')
            if options['analytic_account_ids']:
                share = SQL("""COALESCE((SELECT LEAST(100, GREATEST(0, SUM(value::numeric))) / 100
                    FROM jsonb_each_text(account_move_line.analytic_distribution)
                    WHERE CASE WHEN key ~ '^\\s*[+-]?[0-9]+\\s*$' THEN key::numeric = ANY(%s) ELSE FALSE END
                      AND value ~ '^\\s*[+-]?([0-9]+(\\.[0-9]*)?|\\.[0-9]+)([eE][+-]?[0-9]+)?\\s*$'), 0)""",
                    options['analytic_account_ids'])
            previous = query.select(SQL('account_move_line.account_id'), SQL('account_move_line.company_id'),
                SQL('account_move_line.balance * (%s) AS weighted_balance', share),
                SQL('ROW_NUMBER() OVER (PARTITION BY account_move_line.account_id, account_move_line.company_id ORDER BY account_move_line.date, account_move_line.move_name, account_move_line.id) AS rn'))
            previous_balances = {(account_id, company_id): self._ledger_convert(Decimal(str(balance or 0)), self.env['res.company'].browse(company_id), last)
                for account_id, company_id, balance in self.env.execute_query(SQL(
                    'SELECT account_id, company_id, SUM(weighted_balance) FROM (%s) AS ranked WHERE rn <= %s GROUP BY account_id, company_id', previous, offset))}
        ids, counts = [], {}
        for line_id, account_id, company_id, count in result_rows:
            ids.append(line_id)
            counts[(account_id, company_id)] = count
        lines = model.search_fetch([('id', 'in', ids)],
            ['date', 'move_id', 'move_name', 'name', 'partner_id', 'currency_id', 'company_id',
             'account_id', 'amount_currency', 'debit', 'credit', 'balance', 'analytic_distribution'],
            order='date, move_name, id') if ids else model.browse()
        grouped = {key: [] for key in keys}
        for line in lines:
            key = (line.account_id.id, line.company_id.id)
            if key in grouped:
                grouped[key].append(line)
        result = {}
        formatted_dates = {}
        for account in accounts:
            key = (account['account_id'], account['company_id'])
            initial = opening.get(key, _zeros())
            running = initial['balance'] + previous_balances.get(key, Decimal(0))
            rows = []
            if offset == 0 and (initial['debit'] or initial['credit']):
                rows.append({'type': 'initial', 'name': _('Initial Balance'), 'amounts': self._ledger_amounts(initial)})
            items = grouped[key]
            for line in items:
                share = _analytic_share(line.analytic_distribution, set(options['analytic_account_ids'])) if options['analytic_account_ids'] else Decimal(1)
                values = {figure: self._ledger_convert(Decimal(str(line[figure] or 0)) * share, line.company_id, last)
                          for figure in ('debit', 'credit', 'balance')}
                running += values['balance']
                values['balance'] = running
                name = line.move_name or line.move_id.name or ''
                if line.name and line.name != name:
                    name += ' ' + line.name
                if line.date not in formatted_dates:
                    formatted_dates[line.date] = (format_date(self.env, line.date), fields.Date.to_string(line.date))
                date, date_raw = formatted_dates[line.date]
                rows.append({'type': 'item', 'id': line.id, 'name': name, 'date': date, 'date_raw': date_raw,
                             'partner': line.partner_id.display_name or '',
                             'currency': format_amount(self.env, line.amount_currency * float(share), line.currency_id) if line.currency_id and line.currency_id != line.company_id.currency_id else '',
                             'amounts': self._ledger_amounts(values)})
            has_more = limit is not None and offset + limit < counts.get(key, 0)
            if not has_more:
                rows.append({'type': 'total', 'name': _('Total %s') % account['name'], 'amounts': account['amounts']})
            result[key] = {'rows': rows, 'has_more': has_more, 'next_offset': offset + limit if has_more else False}
        return result

    @api.model
    def get_ledger_lines(self, report_code, options, account_id, company_id, offset=0, limit=None):
        self._check_report_access()
        report = self._definition(report_code)
        if report.report_kind != 'ledger' or type(offset) is not int or offset < 0:
            raise ValidationError(_('The report options are not valid.'))
        normalized = self._normalize_options(report, options or {})
        # This validates account membership and access, including synthetic earnings.
        self._grid_move_line_action(report, normalized, 'account_%s_%s' % (account_id, company_id), 'end', account_id, company_id)
        ledger_data = self._ledger_data(report, normalized)
        payload = self._build_ledger(report, normalized, {}, ledger_data)
        row = next((r for r in payload['lines'][:-1] if (r['account_id'], r['company_id']) == (account_id, company_id)), None)
        if not row:
            raise AccessError(_('Choose an account from this line.'))
        opening, _period = ledger_data
        return self._ledger_pages(normalized, [row], opening, offset, self._ledger_limit(limit))[(account_id, company_id)]

    @api.model
    def get_move_action(self, move_line_id):
        self._check_report_access()
        if type(move_line_id) is not int or move_line_id <= 0:
            raise AccessError(_('Choose an account from this line.'))
        line = self.env['account.move.line'].browse(move_line_id).exists()
        if not line:
            raise AccessError(_('Choose an account from this line.'))
        line.check_access('read')
        line.move_id.check_access('read')
        return {'type': 'ir.actions.act_window', 'name': _('View Journal Entry'), 'res_model': 'account.move',
                'view_mode': 'form', 'views': [(False, 'form')], 'res_id': line.move_id.id, 'target': 'current'}

    @api.model
    def get_general_ledger_action(self, report_code, options, account_id, company_id):
        self._check_report_access()
        report = self._definition(report_code)
        normalized = self._normalize_options(report, options or {})
        self._grid_move_line_action(report, normalized, 'account_%s_%s' % (account_id, company_id), 'end', account_id, company_id)
        action = self.env.ref('baseer_report_engine.action_general_ledger').read()[0]
        keys = ('preset', 'date_from', 'date_to', 'anchor_date', 'journal_ids', 'analytic_account_ids', 'posted_only')
        initial = {key: normalized[key] for key in keys if key in normalized}
        initial['unfolded_accounts'] = [[account_id, company_id]]
        action['context'] = {'report_code': 'general_ledger', 'baseer_options': initial}
        return action
