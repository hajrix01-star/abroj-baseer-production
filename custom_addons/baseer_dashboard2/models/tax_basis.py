"""Tax-inclusive dashboard amounts from posted journal-entry tax lines."""
from collections import defaultdict
import re

from odoo import models
from odoo.tools import SQL

from .service import request_memo, food_ratio, raw_rows
from .tax_math import allocate_tax


class DashboardTaxBasis(models.AbstractModel):
    _inherit = 'baseer.dashboard2.service'

    @request_memo
    def _tax_window(self, ids, start, end):
        """Read a complete request window; match bases in the same move only."""
        lines = self.env['account.move.line'].with_context(allowed_company_ids=ids)
        excluded = self._reset_move_ids(ids, end, start) + self.env['res.company'].browse(ids).mapped('account_opening_move_id').ids
        taxes = raw_rows(lines, [('company_id', 'in', ids), ('parent_state', '=', 'posted'),
                                ('date', '>=', start), ('date', '<=', end),
                                ('tax_line_id', '!=', False), ('move_id', 'not in', excluded),
                                ('move_id.ref', '!=', 'Opening Entry')],
                         ['date', 'company_id', 'account_id', 'tax_line_id', 'move_id', 'balance'])
        if not taxes:
            return []
        moves = list({line['move_id'] for line in taxes})
        base_fields = ['id', 'move_id', 'account_id', 'balance']
        for field in base_fields:
            lines._check_field_access(lines._fields[field], 'read')
        lines.flush_model(base_fields)
        query = lines._search([('move_id', 'in', moves), ('tax_ids', '!=', False)], order=lines._order)
        # Keep the ORM's access rules while fetching base values and tax links
        # together, so the full window requires only one base-link query.
        columns = [SQL.identifier(query.table, field) for field in base_fields]
        columns.append(SQL('(SELECT array_agg(account_tax_id ORDER BY account_tax_id) '
                           'FROM account_move_line_account_tax_rel '
                           'WHERE account_move_line_id = %s) AS tax_ids',
                           SQL.identifier(query.table, 'id')))
        bases = self.env.execute_query_dict(query.select(*columns))
        by_id = {base['id']: base for base in bases}
        by_move_tax = defaultdict(list)
        for base in bases:
            for tax_id in base['tax_ids'] or ():
                by_move_tax[(base['move_id'], tax_id)].append((base['id'], base['balance']))
        tax_records = lines.env['account.tax'].browse(list({line['tax_line_id'] for line in taxes}))
        tax_records.fetch(['type_tax_use', 'name', 'tax_group_id', 'amount_type', 'amount'])
        tax_records.mapped('tax_group_id').fetch(['name'])
        metadata = {}
        for tax in tax_records:
            name = ' '.join((tax.name or '', tax.with_context(lang='en_US').name or '')).upper()
            group = ' '.join((tax.tax_group_id.name or '', tax.tax_group_id.with_context(lang='en_US').name or '')).upper()
            excluded_tax = bool(re.search(r'\bR\s*C\b|\bWH\b|WITHHOLD', name) or 'WITHHOLD' in group or (tax.amount_type == 'division' and tax.amount < 0))
            metadata[tax.id] = (tax.type_tax_use, excluded_tax)
        codes = {}
        for cid, aid in {(line['company_id'], line['account_id']) for line in taxes}:
            codes[(cid, aid)] = lines.env['account.account'].browse(aid).with_company(lines.env['res.company'].browse(cid)).code or ''
        entries = []
        for line in taxes:
            cid, account_id, tax_id = line['company_id'], line['account_id'], line['tax_line_id']
            code = codes[(cid, account_id)]
            use, excluded_tax = metadata[tax_id]
            if use == 'sale' and code in ('201017', '201021'):
                entries.append((line['date'], cid, 'output_vat' if code == '201017' else 'tobacco_fee', 0, -line['balance'], line['id']))
            elif use == 'purchase' and code in ('104041', '104043') and not excluded_tax:
                allocations = allocate_tax(line['balance'], by_move_tax[(line['move_id'], tax_id)])
                if allocations is None:
                    entries.append((line['date'], cid, 'unallocated_input_vat', 0, line['balance'], line['id']))
                else:
                    entries.extend((line['date'], cid, 'input_vat', by_id[base_id]['account_id'], float(amount), line['id']) for base_id, amount in allocations)
        return entries

    @request_memo
    def _tax_basis(self, ids, start, end):
        window = self.env.context.get('_bd2_tax_window') or (start, end)
        first, last = min(window[0], start), max(window[1], end)
        totals = {'output_vat': 0.0, 'tobacco_fee': 0.0, 'unallocated_input_vat': 0.0}
        accounts = defaultdict(float)
        unallocated_lines = 0
        scope = self.env.context.get('_bd2_tax_companies') or ids
        # Entries are immutable tuples; reuse this private request-local snapshot
        # instead of deep-copying the entire window for every monthly bucket.
        cache = self.env.context.get('_bd2_request_cache')
        key = ('_bd2_tax_entries', tuple(scope), first, last)
        if cache is not None:
            if key not in cache:
                cache[key] = tuple(self._tax_window(scope, first, last))
            entries = cache[key]
        else:
            entries = self._tax_window(scope, first, last)
        for day, cid, kind, account_id, amount, _line_id in entries:
            if cid in ids and start <= day <= end:
                if kind == 'input_vat':
                    accounts[(cid, account_id)] += amount
                else:
                    totals[kind] += amount
                    if kind == 'unallocated_input_vat':
                        unallocated_lines += 1
        totals = {key: round(value, 2) for key, value in totals.items()}
        totals['accounts'] = {key: round(value, 2) for key, value in accounts.items()}
        totals['input_vat'] = round(sum(accounts.values()), 2)
        totals['unallocated_input_vat_lines'] = unallocated_lines
        totals['vat_payable'] = round(totals['output_vat'] - totals['input_vat'], 2)
        return totals

    @request_memo
    def _accounting_gross(self, ids, start, end, data=None):
        data = data if data is not None else self._accounting(ids, start, end)
        tax = self._tax_basis(ids, start, end)
        categories = self.env['baseer.dashboard2.category'].with_context(allowed_company_ids=ids).search([])
        for (cid, account_id), amount in tax['accounts'].items():
            account = self.env['account.account'].browse(account_id).with_company(self.env['res.company'].browse(cid))
            key = self._category(account, categories)
            if key:
                data['categories'][key] = round(data['categories'].get(key, 0) + amount, 2)
            for row in data.get('accounts', []):
                if row['company_id'] == cid and row['account_id'] == account_id:
                    row['amount'] = round(row['amount'] + amount, 2)
                    break
        net_sales = data['sales_net']
        sales = round(net_sales + tax['output_vat'] + tax['tobacco_fee'], 2)
        cat = data['categories']
        cat['revenue'] = sales
        gross = round(sales - cat.get('food_cost', 0), 2)
        operating = round(gross - sum(cat.get(k, 0) for k in ('salaries', 'rent', 'utilities', 'marketing', 'commissions', 'other_opex', 'depreciation', 'non_operating')), 2)
        net = round(operating + cat.get('other_income', 0) - cat.get('zakat_tax', 0), 2)
        # Inclusive break-even = net break-even × the actual gross/net sales ratio.
        breakeven = round(data['breakeven'] * sales / net_sales, 2) if data['breakeven'] is not None and net_sales else None
        data.update(sales_net=sales, gross_profit=gross, operating_profit=operating, net_profit=net,
                    breakeven=breakeven, safety_margin=round(sales - breakeven, 2) if breakeven is not None else None,
                    ratios={'food_pct': food_ratio(cat.get('food_cost', 0), sales),
                            'salaries_pct': round(cat.get('salaries', 0) / sales * 100, 2) if sales else None,
                            'prime_pct': round((cat.get('food_cost', 0) + cat.get('salaries', 0)) / sales * 100, 2) if sales else None,
                            'net_margin_pct': round(net / sales * 100, 2) if sales else None},
                    basis='inclusive', tax={**{k: v for k, v in tax.items() if k != 'accounts'}, 'sales_net_pre_tax': net_sales})
        if tax['unallocated_input_vat_lines']:
            data['warnings'] = ['unallocated_input_vat']
        return data
