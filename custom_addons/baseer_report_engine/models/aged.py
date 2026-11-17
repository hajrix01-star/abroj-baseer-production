"""As-of open-item aging, using the partner ledger's filters and conventions."""
from collections import defaultdict
from decimal import Decimal

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools.misc import format_date
from odoo.tools import SQL

from .engine import _analytic_share
from .ledger import _item_labels


class BaseerAgedEngine(models.AbstractModel):
    _inherit = 'baseer.report.engine'

    @api.model
    def _aged_entries(self, options, line_ids=None):
        date = fields.Date.to_date(options['date_to'])
        unfiltered = dict(options, partner_ids=[], partner_category_ids=[], unreconciled=False)
        lines = self.env['account.move.line'].search(
            self._base_domain(options) + self._partner_domain(unfiltered) + [('date', '<=', date)] + ([('id', 'in', line_ids)] if line_ids is not None else []),
            order='date, move_name, id')
        partials = self.env['account.partial.reconcile'].search([
            '|', ('debit_move_id', 'in', lines.ids), ('credit_move_id', 'in', lines.ids)]) if lines else self.env['account.partial.reconcile']
        by_line = defaultdict(list)
        for partial in partials:
            by_line[partial.debit_move_id.id].append((partial, partial.credit_move_id))
            by_line[partial.credit_move_id.id].append((partial, partial.debit_move_id))
        attribution = defaultdict(dict)
        for line in lines.filtered(lambda l: not l.partner_id):
            for partial, other in by_line[line.id]:
                if other.partner_id and partial.max_date > date:
                    pid = other.partner_id.id
                    attribution[line.id][pid] = attribution[line.id].get(pid, Decimal(0)) + Decimal(str(partial.amount))
        selected = self._selected_attribution_partners(options, attribution)
        selected_direct = set(lines.partner_id.ids)
        if options['partner_ids']:
            selected_direct &= set(options['partner_ids'])
        if options['partner_category_ids'] and selected_direct:
            selected_direct = set(self.env['res.partner'].search([('id', 'in', list(selected_direct)), ('category_id', 'in', options['partner_category_ids'])]).ids)
        entries = []
        for line in lines:
            balance = Decimal(str(line.balance))
            settled = sum((Decimal(str(p.amount)) for p, _other in by_line[line.id] if p.max_date <= date), Decimal(0))
            residual = balance - settled * (1 if balance > 0 else -1)
            if line.company_currency_id.is_zero(float(residual)):
                continue
            share = _analytic_share(line.analytic_distribution, set(options['analytic_account_ids'])) if options['analytic_account_ids'] else Decimal(1)
            allocations = {}
            if line.partner_id:
                if line.partner_id.id in selected_direct:
                    allocations[line.partner_id.id] = residual
            else:
                remaining = abs(residual)
                for pid, amount in attribution[line.id].items():
                    portion = min(remaining, amount)
                    remaining -= portion
                    if pid in selected:
                        allocations[pid] = portion if residual > 0 else -portion
                if remaining and not options['partner_ids'] and not options['partner_category_ids']:
                    allocations[0] = remaining if residual > 0 else -remaining
            aging_date = (line.date_maturity if options['aging_basis'] == 'due_date' else line.move_id.invoice_date) or line.date
            days = (date - aging_date).days
            bucket = 0 if days <= 0 else min(5, (days - 1) // options['period_length'] + 1)
            for pid, amount in allocations.items():
                # Credit balances on payable accounts represent money owed to vendors.
                value = self._ledger_convert(amount * share * (-1 if options['aged_payable'] else 1), line.company_id, date)
                entries.append((pid, line, bucket, value))
        return entries

    @api.model
    def _aged_allocated_sql(self, options):
        """Open allocations before partner filtering, including future attribution."""
        date = fields.Date.to_date(options['date_to'])
        unfiltered = dict(options, partner_ids=[], partner_category_ids=[], unreconciled=False)
        model = self.env['account.move.line']
        model.flush_model(['date', 'move_name', 'balance', 'partner_id', 'company_id',
                           'date_maturity', 'move_id', 'analytic_distribution'])
        self.env['account.move'].flush_model(['invoice_date'])
        self.env['account.partial.reconcile'].flush_model(['debit_move_id', 'credit_move_id', 'amount', 'max_date'])
        query = model._search(self._base_domain(options) + self._partner_domain(unfiltered) + [('date', '<=', date)])
        candidates = query.select(SQL('account_move_line.id'), SQL('account_move_line.date'),
            SQL('account_move_line.move_name'), SQL('account_move_line.partner_id'),
            SQL('account_move_line.balance'), SQL('account_move_line.company_id'),
            SQL('account_move_line.date_maturity'), SQL('account_move_line.move_id'),
            SQL('account_move_line.analytic_distribution'))
        return SQL("""
            WITH candidates AS (%s), partials AS (
                SELECT debit_move_id AS line_id, credit_move_id AS other_id, amount, max_date, id FROM account_partial_reconcile
                UNION ALL
                SELECT credit_move_id, debit_move_id, amount, max_date, id FROM account_partial_reconcile
            ), settled AS (
                SELECT p.line_id, SUM(p.amount) AS amount FROM partials p
                JOIN candidates c ON c.id = p.line_id WHERE p.max_date <= %s GROUP BY p.line_id
            ), open_lines AS (
                SELECT c.*, c.balance - SIGN(c.balance) * COALESCE(s.amount, 0) AS residual, currency.rounding
                FROM candidates c LEFT JOIN settled s ON s.line_id = c.id
                JOIN res_company company ON company.id = c.company_id
                JOIN res_currency currency ON currency.id = company.currency_id
            ), future AS (
                SELECT p.line_id, other.partner_id, SUM(p.amount) AS amount, MIN(p.id) AS first_id
                FROM partials p JOIN open_lines c ON c.id = p.line_id
                JOIN account_move_line other ON other.id = p.other_id
                WHERE c.partner_id IS NULL AND p.max_date > %s AND other.partner_id IS NOT NULL
                GROUP BY p.line_id, other.partner_id
            ), portions AS (
                SELECT f.*, COALESCE(SUM(f.amount) OVER (PARTITION BY f.line_id ORDER BY f.first_id, f.partner_id
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS prior FROM future f
            ), allocated AS (
                SELECT c.*, c.partner_id AS pid, c.residual AS amount FROM open_lines c
                 WHERE c.partner_id IS NOT NULL AND ABS(c.residual) >= c.rounding / 2
                UNION ALL
                SELECT c.*, p.partner_id, SIGN(c.residual) * LEAST(p.amount, ABS(c.residual) - p.prior)
                  FROM open_lines c JOIN portions p ON p.line_id = c.id
                 WHERE ABS(c.residual) >= c.rounding / 2 AND ABS(c.residual) > p.prior
                UNION ALL
                SELECT c.*, 0, SIGN(c.residual) * (ABS(c.residual) - COALESCE(f.amount, 0))
                  FROM open_lines c LEFT JOIN (SELECT line_id, SUM(amount) AS amount FROM future GROUP BY line_id) f ON f.line_id = c.id
                 WHERE c.partner_id IS NULL AND ABS(c.residual) >= c.rounding / 2
                   AND ABS(c.residual) > COALESCE(f.amount, 0)
            )
        """, candidates, date, date)

    @api.model
    def _aged_selected_keys(self, options):
        if not options['partner_ids'] and not options['partner_category_ids']:
            return None
        domain = []
        if options['partner_ids']:
            domain.append(('id', 'in', options['partner_ids']))
        if options['partner_category_ids']:
            domain.append(('category_id', 'in', options['partner_category_ids']))
        return self.env['res.partner'].search(domain).ids

    @api.model
    def _aged_grouped(self, options):
        date = fields.Date.to_date(options['date_to'])
        keys = self._aged_selected_keys(options)
        basis = SQL('COALESCE(a.date_maturity, a.date)') if options['aging_basis'] == 'due_date' else SQL('COALESCE(move.invoice_date, a.date)')
        analytic = options['analytic_account_ids']
        share = SQL("""COALESCE((SELECT LEAST(100, GREATEST(0, SUM(value::numeric))) / 100
                    FROM jsonb_each_text(a.analytic_distribution) j(key, value)
                    WHERE CASE WHEN btrim(key) ~ '^[+-]?[0-9]+$' THEN btrim(key)::numeric = ANY(%s) ELSE FALSE END), 0)""", analytic) if analytic else SQL('1')
        result = self.env.execute_query(SQL("""
            %s, values_by_line AS (
                SELECT a.pid, a.company_id, a.amount * (%s) AS amount,
                       CASE WHEN %s - (%s) <= 0 THEN 0 ELSE LEAST(5, ((%s - (%s) - 1) / %s) + 1) END AS bucket
                  FROM allocated a JOIN account_move move ON move.id = a.move_id
                 WHERE %s
            ) SELECT pid, company_id, bucket, SUM(amount) FROM values_by_line GROUP BY pid, company_id, bucket
        """, self._aged_allocated_sql(options), share, date, basis, date, basis, options['period_length'],
            SQL('a.pid = ANY(%s)', keys) if keys is not None else SQL('TRUE')))
        grouped = defaultdict(lambda: [Decimal(0)] * 7)
        companies = self.env['res.company'].browse(list({row[1] for row in result}))
        for pid, company_id, bucket, amount in result:
            value = self._ledger_convert(Decimal(str(amount)) * (-1 if options['aged_payable'] else 1), companies.browse(company_id), date)
            grouped[pid][bucket] += value
            grouped[pid][6] += value
        return grouped

    @api.model
    def _aged_amounts(self, values, drill=False):
        return [self._serialize_amount({'key': key, 'kind': 'ledger'}, value, self.env.company.currency_id, drill)
                for key, value in zip(('at_date', 'period1', 'period2', 'period3', 'period4', 'older', 'total'), values)]

    @api.model
    def _build_aged(self, report, options):
        grouped = self._aged_grouped(options)
        partners = self.env['res.partner'].browse([pid for pid in grouped if pid]).exists()
        names = {partner.id: partner.display_name for partner in partners}
        rows = [{'code': 'header', 'name': report.name, 'level': 0, 'display': 'section', 'foldable': False, 'has_accounts': False, 'amounts': self._aged_amounts([0] * 7)}]
        totals = [Decimal(0)] * 7
        for pid in sorted(grouped, key=lambda x: (not bool(x), names.get(x, '').casefold(), x)):
            values = grouped[pid]
            totals = [a + b for a, b in zip(totals, values)]
            rows.append({'id': pid, 'partner_id': pid, 'code': 'partner_%s' % pid, 'name': names.get(pid) or _('Unknown Partner'), 'level': 0, 'display': 'line', 'foldable': True, 'has_accounts': True, 'amounts': self._aged_amounts(values, True)})
        total_name = _('Total Aged Payable') if options['aged_payable'] else _('Total Aged Receivable')
        rows.append({'code': 'total', 'name': total_name, 'level': 0, 'display': 'total', 'foldable': False, 'has_accounts': False, 'amounts': self._aged_amounts(totals)})
        payload = self._build(report, options)
        payload['report']['report_kind'] = 'aged'
        payload['lines'] = rows
        n = options['period_length']
        labels = [_('Invoice Date'), _('At Date')] + ['%s-%s' % (1 + i*n, (i+1)*n) for i in range(4)] + [_('Older'), _('Total')]
        keys = ['invoice_date', 'at_date', 'period1', 'period2', 'period3', 'period4', 'older', 'total']
        payload['columns'] = [{'key': k, 'label': v, 'kind': 'ledger', 'figure': k} for k, v in zip(keys, labels)]
        payload['column_groups'] = [{'label': options['columns'][0]['label'], 'colspan': 8, 'kind': 'period', 'period_key': 'c0'}]
        payload['options']['account_filter_label'] = ', '.join(dict(self._partner_type_labels())[k] for k in options['account_types'])
        return payload

    @api.model
    def _aged_items_batch(self, options, partner_keys, limit):
        available = set(self._aged_grouped(options))
        keys = available if partner_keys is None else set(partner_keys)
        if not keys <= available:
            raise AccessError(_('Choose an account from this line.'))
        if not keys:
            return {}
        partners = self.env['res.partner'].browse([key for key in keys if key]).exists()
        partners.check_access('read')
        ranked = self.env.execute_query(SQL("""
            %s, ranked AS (
                SELECT id, pid, ROW_NUMBER() OVER (PARTITION BY pid ORDER BY date, move_name, id) AS rn,
                       COUNT(*) OVER (PARTITION BY pid) AS total
                  FROM allocated WHERE pid = ANY(%s)
            ) SELECT id, pid, total FROM ranked WHERE rn <= %s ORDER BY pid, rn
        """, self._aged_allocated_sql(options), list(keys), limit if limit is not None else 2147483647))
        entries = self._aged_entries(options, list({row[0] for row in ranked})) if ranked else []
        by_key = defaultdict(dict)
        for pid, line, bucket, value in entries:
            move, detail, name = _item_labels(line.move_name or line.move_id.name, line.name)
            values = [Decimal(0)] * 7
            values[bucket] = values[6] = value
            by_key[pid][line.id] = {'type': 'item', 'id': line.id, 'name': name, 'move_label': move,
                'detail_label': detail, 'invoice_date': format_date(self.env, line.move_id.invoice_date) if line.move_id.invoice_date else '',
                'amounts': self._aged_amounts(values)}
        result = {key: {'initial': False, 'items': [], 'has_more': False, 'next_offset': False} for key in keys}
        for line_id, key, count in ranked:
            result[key]['items'].append(by_key[key][line_id])
            if limit is not None and count > limit:
                result[key].update(has_more=True, next_offset=limit)
        return result

    @api.model
    def _aged_page(self, options, partner_id, offset, limit):
        if type(partner_id) is not int or partner_id < 0:
            raise AccessError(_('Choose an account from this line.'))
        date = fields.Date.to_date(options['date_to'])
        unfiltered = dict(options, partner_ids=[], partner_category_ids=[], unreconciled=False)
        model = self.env['account.move.line']
        model.flush_model(['date', 'move_name', 'balance', 'partner_id', 'company_id'])
        self.env['account.partial.reconcile'].flush_model(['debit_move_id', 'credit_move_id', 'amount', 'max_date'])
        query = model._search(self._base_domain(options) + self._partner_domain(unfiltered) + [('date', '<=', date)])
        candidates = query.select(SQL('account_move_line.id'), SQL('account_move_line.date'),
                                  SQL('account_move_line.move_name'), SQL('account_move_line.partner_id'),
                                  SQL('account_move_line.balance'), SQL('account_move_line.company_id'))
        # Compute settlement once per line, then allocate future reconciliations of
        # partner-less lines in partial-reconcile order, exactly as in the report.
        ranked = SQL("""
            WITH candidates AS (%s), partials AS (
                SELECT debit_move_id AS line_id, credit_move_id AS other_id, amount, max_date, id FROM account_partial_reconcile
                UNION ALL
                SELECT credit_move_id, debit_move_id, amount, max_date, id FROM account_partial_reconcile
            ), settled AS (
                SELECT p.line_id, SUM(p.amount) AS amount FROM partials p
                JOIN candidates c ON c.id = p.line_id WHERE p.max_date <= %s GROUP BY p.line_id
            ), open_lines AS (
                SELECT c.*, c.balance - SIGN(c.balance) * COALESCE(s.amount, 0) AS residual, currency.rounding
                FROM candidates c LEFT JOIN settled s ON s.line_id = c.id
                JOIN res_company company ON company.id = c.company_id
                JOIN res_currency currency ON currency.id = company.currency_id
            ), future AS (
                SELECT p.line_id, other.partner_id, SUM(p.amount) AS amount, MIN(p.id) AS first_id
                FROM partials p JOIN open_lines c ON c.id = p.line_id
                JOIN account_move_line other ON other.id = p.other_id
                WHERE c.partner_id IS NULL AND p.max_date > %s AND other.partner_id IS NOT NULL
                GROUP BY p.line_id, other.partner_id
            ), portions AS (
                SELECT f.*, COALESCE(SUM(f.amount) OVER (PARTITION BY f.line_id ORDER BY f.first_id, f.partner_id
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS prior
                FROM future f
            ), allocated AS (
                SELECT c.id, c.date, c.move_name, c.partner_id AS pid FROM open_lines c WHERE c.partner_id IS NOT NULL AND ABS(c.residual) >= c.rounding / 2
                UNION ALL
                SELECT c.id, c.date, c.move_name, p.partner_id FROM open_lines c JOIN portions p ON p.line_id = c.id
                WHERE ABS(c.residual) >= c.rounding / 2 AND ABS(c.residual) > p.prior
                UNION ALL
                SELECT c.id, c.date, c.move_name, 0 FROM open_lines c
                WHERE c.partner_id IS NULL AND ABS(c.residual) >= c.rounding / 2
                AND ABS(c.residual) > COALESCE((SELECT SUM(f.amount) FROM future f WHERE f.line_id = c.id), 0)
            ), numbered AS (
                SELECT id, ROW_NUMBER() OVER (ORDER BY date, move_name, id) AS rn, COUNT(*) OVER () AS total
                FROM allocated WHERE pid = %s
            ) SELECT id, total FROM numbered WHERE rn > %s AND rn <= %s ORDER BY rn
        """, candidates, date, date, partner_id, offset, offset + limit if limit is not None else 2147483647)
        if partner_id and (options['partner_ids'] or options['partner_category_ids']):
            domain = [('id', '=', partner_id)]
            if options['partner_ids']:
                domain += [('id', 'in', options['partner_ids'])]
            if options['partner_category_ids']:
                domain += [('category_id', 'in', options['partner_category_ids'])]
            if not self.env['res.partner'].search_count(domain):
                raise AccessError(_('Choose an account from this line.'))
        if not partner_id and (options['partner_ids'] or options['partner_category_ids']):
            raise AccessError(_('Choose an account from this line.'))
        selected = self.env.execute_query(ranked)
        if not selected and not offset:
            raise AccessError(_('Choose an account from this line.'))
        entries = [entry for entry in self._aged_entries(options, [row[0] for row in selected]) if entry[0] == partner_id]
        rows = []
        for _pid, line, bucket, value in entries:
            move, detail, name = _item_labels(line.move_name or line.move_id.name, line.name)
            values = [Decimal(0)] * 7
            values[bucket] = values[6] = value
            rows.append({'type': 'item', 'id': line.id, 'name': name, 'move_label': move, 'detail_label': detail,
                         'invoice_date': format_date(self.env, line.move_id.invoice_date) if line.move_id.invoice_date else '',
                         'amounts': self._aged_amounts(values)})
        more = bool(limit is not None and selected and selected[0][1] > offset + limit)
        return {'rows': rows, 'has_more': more, 'next_offset': offset + limit if more else False}

    @api.model
    def _aged_action(self, options, line_code, column_key, partner_id):
        if partner_id is False:
            partner_id = 0
        keys = ('at_date', 'period1', 'period2', 'period3', 'period4', 'older')
        if type(partner_id) is not int or partner_id < 0 or line_code != 'partner_%s' % partner_id or column_key not in keys + ('total', 'end'):
            raise ValidationError(_('The report options are not valid.'))
        entries = self._aged_entries(options)
        if not any(pid == partner_id for pid, _line, _bucket, _value in entries):
            raise AccessError(_('Choose an account from this line.'))
        ids = [line.id for pid, line, bucket, _value in entries if pid == partner_id and (column_key in ('total', 'end') or bucket == keys.index(column_key))]
        return {'type': 'ir.actions.act_window', 'name': _('Journal Items'), 'res_model': 'account.move.line',
                'view_mode': 'list,form', 'views': [(False, 'list'), (False, 'form')], 'target': 'current', 'domain': [('id', 'in', ids)]}
