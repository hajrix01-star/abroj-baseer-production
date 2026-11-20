from collections import defaultdict

from odoo import models, _
from odoo.exceptions import UserError



class DashboardCash(models.AbstractModel):
    _inherit = 'baseer.dashboard2.service'

    def _cash_out(self, ids, start, end):
        items, sources = defaultdict(float), defaultdict(float)
        total = 0.0
        vat_visibility = {}
        for cid in ids:
            ctx = dict(allowed_company_ids=[cid])
            company = self.env['res.company'].browse(cid)
            settings = self.env['baseer.dashboard2.settings'].with_context(**ctx).search([('company_id', '=', cid)], limit=1)
            vat_visibility[str(cid)] = settings.show_vat_paid_line if settings else True
            accounts = self.env['account.account'].with_context(**ctx).with_company(company).search([('company_ids', 'in', [cid]), '|', ('account_type', '=', 'asset_cash'), ('code', 'in', ('101090', '105090'))])
            if settings:
                accounts |= settings.liquidity_account_ids | settings.liquidity_ids.mapped('account_id')
            liquidity = set(accounts.ids)
            bank_accounts = set(self.env['account.journal'].with_context(**ctx).search([('company_id', '=', cid), ('type', '=', 'bank')]).mapped('default_account_id').ids)
            categories = self.env['baseer.dashboard2.category'].with_context(**ctx).search([])
            tax_ids = set(self.env['account.tax.repartition.line'].with_context(**ctx).search([('account_id', '!=', False), ('tax_id.company_id', '=', cid)]).mapped('account_id').ids)
            resets = set(self._reset_move_ids([cid], end, start))
            paid = self.env['account.move.line'].with_context(**ctx).search([('company_id', '=', cid), ('parent_state', '=', 'posted'), ('date', '>=', start), ('date', '<=', end), ('account_id', 'in', list(liquidity)), ('credit', '>', 0), ('move_id', 'not in', list(resets))], limit=200001)
            if len(paid) > 200000:
                raise UserError(_('The selected period contains more than 200,000 outflow lines.'))
            def classify(line):
                account = line.account_id.with_company(company)
                code = account.code or ''
                if code == '201090':
                    return {'salaries': 1.0}
                if account.account_type == 'liability_payable' or code == '102014' or line.matched_debit_ids or line.matched_credit_ids:
                    matched = (line.matched_debit_ids | line.matched_credit_ids)
                    other = (matched.mapped('debit_move_id') | matched.mapped('credit_move_id')) - line
                    weights = defaultdict(float)
                    for counterpart in other.mapped('move_id').line_ids:
                        acc = counterpart.account_id.with_company(company)
                        category = 'salaries' if acc.code == '201090' else self._category(acc, categories) if (acc.account_type or '').startswith('expense') else False
                        if category:
                            weights['purchases' if category == 'food_cost' else category] += abs(counterpart.balance)
                    return weights or {'purchases' if account.account_type == 'liability_payable' else 'other': 1.0}
                if line.tax_repartition_line_id or account.id in tax_ids:
                    return {'vat_paid': 1.0}
                category = self._category(account, categories)
                return {('purchases' if category == 'food_cost' else category or 'other'): 1.0}
            for line in paid:
                other = line.move_id.line_ids.filtered(lambda l: l.account_id.id not in liquidity)
                if not other:
                    continue
                weights = defaultdict(float)
                for counterpart in other:
                    parts = classify(counterpart)
                    denominator = sum(parts.values())
                    for key, weight in parts.items():
                        weights[key] += abs(counterpart.balance) * weight / denominator if denominator else 0
                denominator = sum(weights.values())
                total += line.credit
                for key, weight in weights.items():
                    items[key] += line.credit * weight / denominator if denominator else 0
                row = settings.liquidity_ids.filtered(lambda r: r.account_id == line.account_id)[:1] if settings else False
                kind = row.kind if row else ('bank' if line.account_id.id in bank_accounts else 'cash')
                label = (row.label or line.account_id.with_context(lang='ar_001').name or '').split('|')[0].strip() if row else ''
                if label.startswith('L '):
                    label = label[2:].strip()
                if kind == 'custody':
                    source = label if label.startswith('عهدة') else 'عهدة ' + label
                elif row and row.label:
                    source = row.label
                else:
                    source = {'bank': 'bank', 'cash': 'cash', 'app': 'حساب تطبيق'}[kind]
                sources[source] += line.credit
        return {'available': True, 'unconfigured_company_ids': [], 'total': round(total, 2), 'items': {k: round(v, 2) for k, v in items.items()}, 'sources': {k: round(v, 2) for k, v in sources.items()}, 'show_vat_paid_line': any(vat_visibility.values()), 'vat_visibility_by_company': vat_visibility}

    def _sales_vat(self, ids, start, end):
        ctx = dict(allowed_company_ids=ids)
        sales_days, _, _, _ = self._sales_days(ids, start, end)
        sessions = self.env['pos.session'].with_context(**ctx).search_read([
            ('company_id', 'in', ids), ('move_id.state', '=', 'posted'),
            ('move_id.date', '>=', start), ('move_id.date', '<=', end)], ['move_id', 'config_id'])
        settings = self.env['baseer.dashboard2.settings'].with_context(**ctx).search([('company_id', 'in', ids)])
        summary_ids = set(settings.mapped('summary_pos_config_ids').ids)
        configs = self.env['pos.config'].with_context(**dict(ctx, active_test=False)).search([('company_id', 'in', ids)])
        summary_ids.update(config.id for config in configs if any(word in (config.name or '').casefold() for word in ('ملخص المبيعات', 'sales summaries', 'ملخصات')))
        session_move_ids = [s['move_id'][0] for s in sessions if s['move_id'] and (not s['config_id'] or s['config_id'][0] not in summary_ids)]
        orders = self.env['pos.order'].with_context(**ctx).search_read([
            ('company_id', 'in', ids), ('account_move.state', '=', 'posted'),
            ('account_move.date', '>=', start), ('account_move.date', '<=', end)], ['account_move', 'config_id'], limit=200001)
        if len(orders) > 200000:
            raise UserError(_('The selected period contains more than 200,000 POS orders.'))
        pos_moves = set(session_move_ids + [o['account_move'][0] for o in orders if o['account_move'] and (not o['config_id'] or o['config_id'][0] not in summary_ids)])
        rows = self.env['account.move.line'].with_context(**ctx)._read_group([
            ('company_id', 'in', ids), ('parent_state', '=', 'posted'), ('date', '>=', start), ('date', '<=', end),
            ('account_id.account_type', '=', 'liability_current'), ('tax_line_id', '!=', False), ('move_id', 'not in', self._reset_move_ids(ids, end, start)),
            '|', '|', ('move_id.ref', 'ilike', 'NOORIX-SALES'), ('move_id.reversed_entry_id.ref', 'ilike', 'NOORIX-SALES'), ('move_id', 'in', list(pos_moves))],
            ['company_id', 'date:day', 'move_id'], ['credit:sum', 'debit:sum'])
        amount = sum(day.get('sales_vat', 0) for day in sales_days.values() if day['source'] == 'summary')
        for company, day, move, credit, debit in rows:
            source = sales_days.get((company.id, day), {}).get('source')
            if (source == 'pos' and move.id in pos_moves):
                amount += (credit or 0) - (debit or 0)
        return {'available': True, 'value': round(amount, 2)}

    def _unpaid_bills(self, ids, end):
        ctx = dict(allowed_company_ids=ids)
        bills = self.env['account.move'].with_context(**ctx).search([
            ('company_id', 'in', ids), ('state', '=', 'posted'), ('move_type', 'in', ['in_invoice', 'in_refund']),
            ('invoice_date', '<=', end)])
        resets = set(self._reset_move_ids(ids, end))
        bills = bills.filtered(lambda move: move.id not in resets)
        lines = bills.line_ids.filtered(lambda line: line.account_id.account_type == 'liability_payable')
        partials = self.env['account.partial.reconcile'].with_context(**ctx).search([
            ('max_date', '<=', end), '|', ('debit_move_id', 'in', lines.ids), ('credit_move_id', 'in', lines.ids)])
        remaining = sum(-line.balance for line in lines)
        line_ids = set(lines.ids)
        for partial in partials:
            if partial.debit_move_id.move_id.id in resets or partial.credit_move_id.move_id.id in resets:
                continue
            if partial.credit_move_id.id in line_ids:
                remaining -= partial.amount
            if partial.debit_move_id.id in line_ids:
                remaining += partial.amount
        return {'available': True, 'value': round(remaining, 2), 'label': 'فواتير غير مسددة — نهاية الفترة'}
