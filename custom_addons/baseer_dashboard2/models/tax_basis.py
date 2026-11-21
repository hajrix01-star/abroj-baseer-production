"""Tax-inclusive dashboard amounts from posted journal-entry tax lines."""
from collections import defaultdict
import re

from odoo import models

from .service import request_memo, food_ratio
from .tax_math import allocate_tax


class DashboardTaxBasis(models.AbstractModel):
    _inherit = 'baseer.dashboard2.service'

    @request_memo
    def _tax_window(self, ids, start, end):
        """Read a complete request window; match bases in the same move only."""
        lines = self.env['account.move.line'].with_context(allowed_company_ids=ids)
        excluded = self._reset_move_ids(ids, end, start) + self.env['res.company'].browse(ids).mapped('account_opening_move_id').ids
        taxes = lines.search([('company_id', 'in', ids), ('parent_state', '=', 'posted'),
                              ('date', '>=', start), ('date', '<=', end),
                              ('tax_line_id', '!=', False), ('move_id', 'not in', excluded),
                              ('move_id.ref', '!=', 'Opening Entry')])
        bases = lines.search([('move_id', 'in', taxes.mapped('move_id').ids), ('tax_ids', '!=', False)])
        by_move_tax = defaultdict(list)
        for base in bases:
            for tax in base.tax_ids:
                by_move_tax[(base.move_id.id, tax.id)].append((base.id, base.balance))
        base_accounts = {base.id: base.account_id.id for base in bases}
        entries = []
        for line in taxes:
            company = line.company_id
            code = line.account_id.with_company(company).code or ''
            tax = line.tax_line_id
            if tax.type_tax_use == 'sale' and code in ('201017', '201021'):
                entries.append((line.date, company.id, 'output_vat' if code == '201017' else 'tobacco_fee', 0, -line.balance))
            elif tax.type_tax_use == 'purchase' and code in ('104041', '104043'):
                name = ' '.join((tax.name or '', tax.with_context(lang='en_US').name or '')).upper()
                group = ' '.join((tax.tax_group_id.name or '', tax.tax_group_id.with_context(lang='en_US').name or '')).upper()
                if re.search(r'\bR\s*C\b|\bWH\b|WITHHOLD', name) or 'WITHHOLD' in group or (tax.amount_type == 'division' and tax.amount < 0):
                    continue
                allocations = allocate_tax(line.balance, by_move_tax[(line.move_id.id, tax.id)])
                if allocations is None:
                    entries.append((line.date, company.id, 'unallocated_input_vat', 0, line.balance))
                else:
                    entries.extend((line.date, company.id, 'input_vat', base_accounts[base_id], float(amount)) for base_id, amount in allocations)
        return entries

    @request_memo
    def _tax_basis(self, ids, start, end):
        window = self.env.context.get('_bd2_tax_window') or (start, end)
        first, last = min(window[0], start), max(window[1], end)
        totals = {'output_vat': 0.0, 'tobacco_fee': 0.0, 'unallocated_input_vat': 0.0}
        accounts = defaultdict(float)
        unallocated_lines = 0
        scope = self.env.context.get('_bd2_tax_companies') or ids
        for day, cid, kind, account_id, amount in self._tax_window(scope, first, last):
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
