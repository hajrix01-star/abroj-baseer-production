"""Ledger layout over the shared account-grid fiscal carry-forward policy."""
from decimal import Decimal

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools.misc import format_date, format_amount
from odoo.tools import SQL

from .engine import _analytic_share, _zeros


def _item_labels(move_name, line_name):
    move = move_name or ''
    detail = (line_name or '').replace(move, '') if move else (line_name or '')
    detail = detail.strip(' -–—/|:')
    return move, detail, ' '.join(part for part in (move, detail) if part)


class BaseerLedgerEngine(models.AbstractModel):
    _inherit = 'baseer.report.engine'

    _gl_page_size = 80

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
    def _ledger_partner_data(self, options, partner_domain):
        """Aggregate partner activity after converting each company's amounts.

        Receivable and payable accounts do not use the profit-and-loss
        fiscal-year carry-forward adjustment.
        """
        first, last = options['columns'][0]['_start'], options['columns'][0]['_end']
        scopes = [('initial', [('date', '<', first)], last),
                  ('period', [('date', '>=', first), ('date', '<=', last)], last)]
        grouped = self._grid_balances(options, ('partner_id', 'company_id'), scopes, partner_domain)
        result = {}
        for scope, companies in grouped.items():
            partners = result[scope] = {}
            for (partner_id, _company_id), values in companies.items():
                bucket = partners.setdefault(partner_id or 0, _zeros())
                for figure in ('debit', 'credit', 'balance'):
                    bucket[figure] += values[figure]
        if 'account_types' in options:
            if options['analytic_account_ids']:
                allocations = self._partner_allocations(options)
                selected = self._selected_attribution_partners(options, allocations)
                attributed = []
                for line in self.env['account.move.line'].browse(list(allocations)):
                    scope = 'initial' if line.date < first else 'period'
                    share = _analytic_share(line.analytic_distribution, set(options['analytic_account_ids']))
                    for partner_id, amount in allocations[line.id].items():
                        attributed.append((scope, partner_id, line.company_id, line.balance > 0, amount * share))
            else:
                attributed = self._partner_attribution_sums(options, first)
                selected = self._selected_attribution_partners(options, {0: {row[1]: 0 for row in attributed}})
            for scope, partner_id, company, is_debit, amount in attributed:
                value = self._convert(amount, company, last)
                values = {'debit': value if is_debit else Decimal(0),
                          'credit': Decimal(0) if is_debit else value,
                          'balance': value if is_debit else -value}
                if not options['partner_ids'] and not options['partner_category_ids']:
                    bucket = result[scope].setdefault(0, _zeros())
                    for figure in bucket:
                        bucket[figure] -= values[figure]
                if partner_id in selected:
                    bucket = result[scope].setdefault(partner_id, _zeros())
                    for figure in bucket:
                        bucket[figure] += values[figure]
            for partners in result.values():
                if 0 in partners and all(self.env.company.currency_id.is_zero(float(v)) for v in partners[0].values()):
                    del partners[0]
        return result['initial'], result['period']

    @api.model
    def _partner_attribution_sums(self, options, first):
        unfiltered = dict(options, partner_ids=[], partner_category_ids=[])
        domain = self._base_domain(options) + self._partner_domain(unfiltered) + [
            ('partner_id', '=', False), ('date', '<=', options['date_to'])]
        model = self.env['account.move.line']
        model.flush_model(['partner_id', 'date', 'balance', 'company_id'])
        self.env['account.partial.reconcile'].flush_model(['debit_move_id', 'credit_move_id', 'amount'])
        source = model._search(domain).select(SQL('account_move_line.id'), SQL('account_move_line.date'),
                                               SQL('account_move_line.balance'), SQL('account_move_line.company_id'))
        rows = self.env.execute_query(SQL("""
            SELECT source.date < %s, other.partner_id, source.company_id,
                   source.balance > 0, SUM(partial.amount)
              FROM (%s) source
              JOIN account_partial_reconcile partial
                ON partial.debit_move_id = source.id OR partial.credit_move_id = source.id
              JOIN account_move_line other ON other.id = CASE
                WHEN partial.debit_move_id = source.id THEN partial.credit_move_id
                ELSE partial.debit_move_id END
             WHERE other.partner_id IS NOT NULL
             GROUP BY 1, 2, 3, 4
        """, first, source))
        companies = self.env['res.company'].browse({row[2] for row in rows})
        company_by_id = {company.id: company for company in companies}
        return [('initial' if initial else 'period', partner_id, company_by_id[company_id], is_debit, Decimal(str(amount)))
                for initial, partner_id, company_id, is_debit, amount in rows]

    @api.model
    def _partner_allocations(self, options):
        unfiltered = dict(options, partner_ids=[], partner_category_ids=[])
        domain = self._base_domain(options) + self._partner_domain(unfiltered) + [
            ('partner_id', '=', False), ('date', '<=', options['date_to'])]
        model = self.env['account.move.line']
        model.flush_model(['partner_id', 'date', 'balance'])
        self.env['account.partial.reconcile'].flush_model(['debit_move_id', 'credit_move_id', 'amount'])
        source = model._search(domain).select(SQL('account_move_line.id'))
        rows = self.env.execute_query(SQL("""
            SELECT source.id, other.partner_id, SUM(partial.amount)
              FROM (%s) source
              JOIN account_partial_reconcile partial
                ON partial.debit_move_id = source.id OR partial.credit_move_id = source.id
              JOIN account_move_line other ON other.id = CASE
                WHEN partial.debit_move_id = source.id THEN partial.credit_move_id
                ELSE partial.debit_move_id END
             WHERE other.partner_id IS NOT NULL
             GROUP BY source.id, other.partner_id
        """, source))
        result = {}
        for line_id, partner_id, amount in rows:
            result.setdefault(line_id, {})[partner_id] = Decimal(str(amount))
        return result

    @api.model
    def _selected_attribution_partners(self, options, allocations):
        ids = {partner for partners in allocations.values() for partner in partners}
        if options['partner_ids']:
            ids &= set(options['partner_ids'])
        if ids and options['partner_category_ids']:
            ids = set(self.env['res.partner'].search([('id', 'in', list(ids)),
                ('category_id', 'in', options['partner_category_ids'])]).ids)
        return ids

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
            pages = self._ledger_pages(options, selected, opening, 0, None if self.env.context.get('baseer_gl_export') else self._ledger_limit(None))
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
        model.flush_model(['date', 'move_name', 'account_id', 'company_id'])
        query = model._search(domain)
        ranked = query.select(SQL('account_move_line.id'), SQL('account_move_line.account_id'),
            SQL('account_move_line.company_id'), SQL('ROW_NUMBER() OVER (PARTITION BY account_move_line.account_id, account_move_line.company_id ORDER BY account_move_line.date, account_move_line.move_name, account_move_line.id) AS rn'),
            SQL('COUNT(*) OVER (PARTITION BY account_move_line.account_id, account_move_line.company_id) AS total'))
        upper = offset + limit if limit is not None else 2147483647
        result_rows = self.env.execute_query(SQL('SELECT id, account_id, company_id, total FROM (%s) AS ranked WHERE rn > %s AND rn <= %s ORDER BY rn', ranked, offset, upper))
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
        for account in accounts:
            key = (account['account_id'], account['company_id'])
            initial = opening.get(key, _zeros())
            running = initial['balance']
            rows = []
            if offset == 0 and (initial['debit'] or initial['credit']):
                rows.append({'type': 'initial', 'name': _('Initial Balance'), 'amounts': self._ledger_amounts(initial)})
            items = grouped[key]
            if offset and key[0]:
                previous = model.search(domain + [('account_id', '=', key[0]), ('company_id', '=', key[1])], order='date, move_name, id', limit=offset)
                for prior_line in previous:
                    share = _analytic_share(prior_line.analytic_distribution, set(options['analytic_account_ids'])) if options['analytic_account_ids'] else Decimal(1)
                    running += self._ledger_convert(Decimal(str(prior_line.balance or 0)) * share, prior_line.company_id, last)
            for line in items:
                share = _analytic_share(line.analytic_distribution, set(options['analytic_account_ids'])) if options['analytic_account_ids'] else Decimal(1)
                values = {figure: self._ledger_convert(Decimal(str(line[figure] or 0)) * share, line.company_id, last)
                          for figure in ('debit', 'credit', 'balance')}
                running += values['balance']
                values['balance'] = running
                _move, _detail, name = _item_labels(line.move_name or line.move_id.name, line.name)
                rows.append({'type': 'item', 'id': line.id, 'name': name, 'date': format_date(self.env, line.date), 'date_raw': fields.Date.to_string(line.date),
                             'partner': line.partner_id.display_name or '',
                             'currency': format_amount(self.env, line.amount_currency * float(share), line.currency_id) if line.currency_id and line.currency_id != line.company_id.currency_id else '',
                             'amounts': self._ledger_amounts(values)})
            has_more = limit is not None and offset + limit < counts.get(key, 0)
            if not has_more:
                rows.append({'type': 'total', 'name': _('Total %s') % account['name'], 'amounts': account['amounts']})
            result[key] = {'rows': rows, 'has_more': has_more, 'next_offset': offset + limit if has_more else False}
        return result

    @api.model
    def get_ledger_lines(self, report_code, options, account_id, company_id=False, offset=0, limit=None):
        self._check_report_access()
        report = self._definition(report_code)
        if report.report_kind not in ('ledger', 'partner_ledger') or type(offset) is not int or offset < 0:
            raise ValidationError(_('The report options are not valid.'))
        normalized = self._normalize_options(report, options or {})
        if report.report_kind == 'partner_ledger':
            partner_id = account_id if account_id is not False else 0
            self._partner_move_line_action(normalized, 'partner_%s' % partner_id, partner_id)
            payload = self._build_partner_ledger(report, normalized, {})
            row = next ( (r for r in payload['lines'][:-1] if r['partner_id'] == partner_id), None)
            if not row:
                raise AccessError(_('Choose an account from this line.'))
            opening, _period = self._ledger_partner_data(normalized, self._partner_domain(normalized))
            return self._partner_page(normalized, row, opening, offset, self._ledger_limit(limit))
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
    def _normalize_partner_options(self, raw, options):
        names = ('receivable', 'non_trade_receivable', 'payable', 'non_trade_payable')
        selected = raw.get('account_types', ['receivable', 'payable'])
        if not isinstance(selected, list) or not selected or any(type(x) is not str or x not in names for x in selected):
            raise ValidationError(_('The report options are not valid.'))
        options['account_types'] = list(dict.fromkeys(selected))
        for key, model_name in (('partner_ids', 'res.partner'), ('partner_category_ids', 'res.partner.category')):
            ids = self._id_list(raw.get(key, []), key)
            records = self.env[model_name].browse(ids)
            records.check_access('read')
            if len(records.exists()) != len(ids):
                raise AccessError(_('The report options are not valid.'))
            options[key] = ids
        options['unreconciled'] = raw.get('unreconciled', False)
        if type(options['unreconciled']) is not bool:
            raise ValidationError(_('The report options are not valid.'))

    @api.model
    def _partner_domain(self, options):
        from .definition import _or_domains
        mapping = {'receivable': ('asset_receivable', False), 'non_trade_receivable': ('asset_receivable', True),
                   'payable': ('liability_payable', False), 'non_trade_payable': ('liability_payable', True)}
        domain = _or_domains([[('account_id.account_type', '=', mapping[k][0]), ('account_id.non_trade', '=', mapping[k][1])]
                              for k in options['account_types']])
        if options['partner_ids']:
            domain += [('partner_id', 'in', options['partner_ids'])]
        if options['partner_category_ids']:
            domain += [('partner_id.category_id', 'in', options['partner_category_ids'])]
        if options['unreconciled']:
            domain += [('amount_residual', '!=', 0)]
        return domain

    @api.model
    def _build_partner_ledger(self, report, options, raw):
        domain = self._partner_domain(options)
        opening, period = self._ledger_partner_data(options, domain)
        ids = set(opening) | set(period)
        partners = self.env['res.partner'].browse([x for x in ids if x]).exists()
        names = {p.id: p.display_name for p in partners}
        rows, totals = [], _zeros()
        for partner_id in sorted(ids, key=lambda x: (not bool(x), names.get(x, '').casefold(), x)):
            initial, movement = opening.get(partner_id, _zeros()), period.get(partner_id, _zeros())
            values = {k: initial[k] + movement[k] for k in totals}
            for k in totals:
                totals[k] += values[k]
            rows.append({'id': partner_id, 'partner_id': partner_id, 'code': 'partner_%s' % partner_id,
                         'name': names.get(partner_id) or _('Unknown Partner'), 'level': 0, 'display': 'line',
                         'foldable': True, 'has_accounts': True, 'accounts': [], 'amounts': self._ledger_amounts(values, True)})
        rows.append({'code': 'total', 'name': _('Total'), 'level': 0, 'display': 'total', 'foldable': False,
                     'has_accounts': False, 'accounts': [], 'amounts': self._ledger_amounts(totals)})
        payload = self._build(report, options)
        payload['report']['report_kind'] = report.report_kind
        payload['lines'] = rows
        labels = [('journal', _('Journal')), ('account', _('Account')), ('invoice_date', _('Invoice Date')),
                  ('due_date', _('Due Date')), ('matching', _('Matching')), ('debit', _('Debit')),
                  ('credit', _('Credit')), ('amount_currency', _('Amount Currency')), ('balance', _('Balance'))]
        payload['columns'] = [{'key': k, 'label': v, 'kind': 'ledger', 'figure': k} for k, v in labels]
        payload['column_groups'] = [{'label': options['columns'][0]['label'], 'colspan': 9, 'kind': 'period', 'period_key': 'c0'}]
        payload['options']['account_filter_label'] = (_('Trade Partners') if set(options['account_types']) == {'receivable', 'payable'}
            else ', '.join(dict(self._partner_type_labels())[k] for k in options['account_types']))
        return payload

    @api.model
    def _partner_type_labels(self):
        return [('receivable', _('Receivable')), ('non_trade_receivable', _('Non Trade Receivable')),
                ('payable', _('Payable')), ('non_trade_payable', _('Non Trade Payable'))]

    @api.model
    def _partner_move_line_action(self, options, line_code, partner_id):
        if partner_id is False:
            partner_id = 0
        if type(partner_id) is not int or partner_id < 0 or line_code != 'partner_%s' % partner_id:
            raise AccessError(_('Choose an account from this line.'))
        if partner_id:
            partner = self.env['res.partner'].browse(partner_id).exists()
            if not partner:
                raise AccessError(_('Choose an account from this line.'))
            partner.check_access('read')
        allocations = self._partner_allocations(options)
        selected = self._selected_attribution_partners(options, allocations)
        ids = [line_id for line_id, partners in allocations.items() if partner_id in partners and partner_id in selected]
        unfiltered = dict(options, partner_ids=[], partner_category_ids=[])
        partner_domain = self._partner_domain(unfiltered if ids else options)
        fully_allocated = []
        if not partner_id:
            for line in self.env['account.move.line'].browse(list(allocations)):
                if line.company_currency_id.is_zero(abs(line.balance) - float(sum(allocations[line.id].values()))):
                    fully_allocated.append(line.id)
        domain = self._base_domain(options) + partner_domain + ['|', ('partner_id', '=', partner_id or False), ('id', 'in', ids), ('id', 'not in', fully_allocated), ('date', '<=', options['date_to'])]
        return {'type': 'ir.actions.act_window', 'name': _('Journal Items'), 'res_model': 'account.move.line',
                'view_mode': 'list,form', 'views': [(False, 'list'), (False, 'form')], 'target': 'current',
                'domain': self._public_domain(domain)}

    @api.model
    def get_partner_action(self, partner_id):
        self._check_report_access()
        if type(partner_id) is not int or partner_id <= 0:
            raise AccessError(_('Choose an account from this line.'))
        partner = self.env['res.partner'].browse(partner_id).exists()
        if not partner:
            raise AccessError(_('Choose an account from this line.'))
        partner.check_access('read')
        return {'type': 'ir.actions.act_window', 'name': _('Partner'), 'res_model': 'res.partner',
                'view_mode': 'form', 'views': [(False, 'form')], 'res_id': partner_id, 'target': 'current'}

    @api.model
    def _partner_page(self, options, row, opening, offset, limit):
        first, last = options['columns'][0]['_start'], options['columns'][0]['_end']
        allocations = self._partner_allocations(options)
        partner_id = row['partner_id']
        selected_partners = self._selected_attribution_partners(options, allocations)
        ids = [line_id for line_id, partners in allocations.items() if partner_id in partners and partner_id in selected_partners]
        fully_allocated = []
        if not partner_id:
            for line in self.env['account.move.line'].browse(list(allocations)):
                if line.company_currency_id.is_zero(abs(line.balance) - float(sum(allocations[line.id].values()))):
                    fully_allocated.append(line.id)
        unfiltered = dict(options, partner_ids=[], partner_category_ids=[])
        domain = self._base_domain(options) + self._partner_domain(unfiltered if ids else options) + [
            '|', ('partner_id', '=', partner_id or False), ('id', 'in', ids), ('id', 'not in', fully_allocated),
            ('date', '>=', first), ('date', '<=', last)]
        model = self.env['account.move.line']
        model.flush_model(['date', 'move_name', 'partner_id'])
        query = model._search(domain)
        ranked = query.select(SQL('account_move_line.id'),
            SQL('ROW_NUMBER() OVER (ORDER BY account_move_line.date, account_move_line.move_name, account_move_line.id) AS rn'),
            SQL('COUNT(*) OVER () AS total'))
        selected = self.env.execute_query(SQL('SELECT id, total FROM (%s) AS ranked WHERE rn > %s AND rn <= %s ORDER BY rn',
                                              ranked, offset, offset + limit if limit is not None else 9223372036854775807))
        lines = model.search([('id', 'in', [item[0] for item in selected])], order='date, move_name, id')
        previous = model.search(domain, order='date, move_name, id', limit=offset) if offset else model.browse()
        initial = opening.get(row['partner_id'], _zeros())
        running = initial['balance']
        result = []
        if not offset and (initial['debit'] or initial['credit']):
            result.append({'type': 'initial', 'name': _('Initial Balance'), 'amounts': self._ledger_amounts(initial)})
        for index, line in enumerate(previous | lines):
            share = _analytic_share(line.analytic_distribution, set(options['analytic_account_ids'])) if options['analytic_account_ids'] else Decimal(1)
            if not line.partner_id and line.id in allocations:
                amount = (allocations[line.id].get(partner_id, Decimal(0)) if partner_id else
                          Decimal(str(abs(line.balance))) - sum(allocations[line.id].values()))
                share *= amount / Decimal(str(abs(line.balance))) if line.balance else Decimal(0)
            values = {k: self._ledger_convert(Decimal(str(line[k] or 0)) * share, line.company_id, last) for k in ('debit', 'credit', 'balance')}
            running += values['balance']
            if index < offset:
                continue
            values['balance'] = running
            move_label, detail_label, name = _item_labels(line.move_name or line.move_id.name, line.name)
            result.append({'type': 'item', 'id': line.id, 'name': name, 'move_label': move_label,
                           'detail_label': detail_label, 'journal': line.journal_id.code or '',
                           'account': line.account_id.with_company(line.company_id).code or '',
                           'invoice_date': format_date(self.env, line.move_id.invoice_date) if line.move_id.invoice_date else '',
                           'invoice_date_raw': fields.Date.to_string(line.move_id.invoice_date),
                           'due_date': format_date(self.env, line.date_maturity) if line.date_maturity else '',
                           'due_date_raw': fields.Date.to_string(line.date_maturity),
                           'overdue': bool(line.date_maturity and line.date_maturity < fields.Date.context_today(self) and line.amount_residual),
                           'matching': line.matching_number or '',
                           'amount_currency': format_amount(self.env, line.amount_currency * float(share), line.currency_id) if line.currency_id and line.currency_id != line.company_id.currency_id else '',
                           'amounts': self._ledger_amounts(values)})
        has_more = bool(limit is not None and selected and selected[0][1] > offset + limit)
        if not has_more:
            result.append({'type': 'total', 'name': _('Total %s') % row['name'], 'amounts': row['amounts']})
        return {'rows': result, 'has_more': has_more, 'next_offset': offset + limit if has_more else False}

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
