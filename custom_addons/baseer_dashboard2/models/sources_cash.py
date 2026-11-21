from .service import request_memo
from collections import defaultdict

from odoo import models, _
from odoo.exceptions import UserError



class DashboardCash(models.AbstractModel):
    _inherit = 'baseer.dashboard2.service'

    @request_memo
    def _cash_out(self, ids, start, end, split=False):
        buckets = defaultdict(lambda: {'items': defaultdict(float), 'sources': defaultdict(float), 'total': 0.0})
        for cid in ids:
            ctx = dict(allowed_company_ids=[cid])
            company = self.env['res.company'].browse(cid)
            settings = self.env['baseer.dashboard2.settings'].with_context(**ctx).search([('company_id', '=', cid)], limit=1)
            accounts = self.env['account.account'].with_context(**ctx).with_company(company).search([('company_ids', 'in', [cid]), '|', ('account_type', '=', 'asset_cash'), ('code', 'in', ('101090', '105090'))])
            if settings:
                accounts |= settings.liquidity_account_ids | settings.liquidity_ids.mapped('account_id')
            liquidity = set(accounts.ids)
            bank_accounts = set(self.env['account.journal'].with_context(**ctx).search([('company_id', '=', cid), ('type', '=', 'bank')]).mapped('default_account_id').ids)
            categories = self.env['baseer.dashboard2.category'].with_context(**ctx).search([])
            tax_lines = self.env['account.tax.repartition.line'].with_context(**ctx).search([('account_id', '!=', False), ('tax_id.company_id', '=', cid)])
            tax_ids = set(tax_lines.filtered(lambda r: any(term in ((r.tax_id.name or '') + ' ' + (r.tax_id.with_context(lang='en_US').name or '')).lower()
                                                         for term in ('vat', 'value added', 'القيمة المضافة'))).mapped('account_id').ids)
            # Saudi chart VAT control accounts, including the ZATCA settlement payable.
            vat_codes = {'100103', '101060', '104041', '104043', '201017', '201030', '202003'}
            resets = set(self._reset_move_ids([cid], end, start))
            paid = self.env['account.move.line'].with_context(**ctx).search([('company_id', '=', cid), ('parent_state', '=', 'posted'), ('date', '>=', start), ('date', '<=', end), ('account_id', 'in', list(liquidity)), ('credit', '>', 0), ('move_id', 'not in', list(resets))], limit=200001)
            if len(paid) > 200000:
                raise UserError(_('The selected period contains more than 200,000 outflow lines.'))
            # Prime the entire reconciliation graph in batches before classifying individual lines.
            counterparts = paid.mapped('move_id.line_ids')
            partials = counterparts.mapped('matched_debit_ids') | counterparts.mapped('matched_credit_ids')
            reconciled = partials.mapped('debit_move_id') | partials.mapped('credit_move_id')
            bill_lines = reconciled.mapped('move_id.line_ids')
            (counterparts | bill_lines).fetch(['balance', 'account_id'])
            bill_lines.mapped('account_id')
            counterparts.mapped('account_id')
            rows_by_account = {row.account_id.id: row for row in settings.liquidity_ids} if settings else {}
            def source_label(row):
                parts = [part.strip() for part in (row.label or row.account_id.with_context(lang='ar_001').name or '').split('|')]
                label = next((part for part in parts if any('\u0600' <= c <= '\u06ff' for c in part)), parts[0])
                if label.startswith('L '):
                    label = label[2:].strip()
                return label if label.startswith('عهدة') else 'عهدة ' + label
            for row in rows_by_account.values():
                if row.kind == 'custody':
                    for offset in range((end.year - start.year) * 12 + end.month - start.month + 1):
                        month_index = start.year * 12 + start.month - 1 + offset
                        year, month = divmod(month_index, 12)
                        buckets['%04d-%02d' % (year, month + 1)]['sources'][source_label(row)] += 0
            account_details = {}
            def details(account):
                if account.id not in account_details:
                    account = account.with_company(company)
                    account_details[account.id] = (account.code or '', account.account_type, self._category(account, categories))
                return account_details[account.id]
            def classify(line):
                account = line.account_id
                code, account_type, account_category = details(account)
                if code in vat_codes or account.id in tax_ids:
                    return {'vat_paid': 1.0}
                if code == '201090':
                    return {'salaries': 1.0}
                if account_type == 'liability_payable' or code == '102014' or line.matched_debit_ids or line.matched_credit_ids:
                    matched = (line.matched_debit_ids | line.matched_credit_ids)
                    other = (matched.mapped('debit_move_id') | matched.mapped('credit_move_id')) - line
                    weights = defaultdict(float)
                    for counterpart in other.mapped('move_id').line_ids:
                        acc_code, acc_type, acc_category = details(counterpart.account_id)
                        category = 'salaries' if acc_code == '201090' else acc_category if (acc_type or '').startswith('expense') else False
                        if category:
                            weights['purchases' if category == 'food_cost' else category] += abs(counterpart.balance)
                    # Supplier bills retain their gross payment, including input VAT.
                    # A settlement with no expense lines can instead target VAT controls.
                    if not weights and any(details(x.account_id)[0] in vat_codes or x.account_id.id in tax_ids for x in other.mapped('move_id').line_ids):
                        return {'vat_paid': 1.0}
                    return weights or {'purchases' if account_type == 'liability_payable' else 'other': 1.0}
                category = account_category
                return {('purchases' if category == 'food_cost' else category or 'other'): 1.0}
            # A move can contain multiple paid liquidity lines. Classify each
            # counterpart once and reuse the same ordered counterparts for it.
            others_by_move = defaultdict(list)
            for row in counterparts.read(['move_id', 'account_id', 'balance'], load=None):
                if row['account_id'] not in liquidity:
                    others_by_move[row['move_id']].append(row)
            classified = {}
            for line in paid.read(['move_id', 'account_id', 'credit', 'date'], load=None):
                other = others_by_move[line['move_id']]
                if not other:
                    continue
                weights = defaultdict(float)
                for counterpart in other:
                    if counterpart['id'] not in classified:
                        classified[counterpart['id']] = classify(counterparts.browse(counterpart['id']))
                    parts = classified[counterpart['id']]
                    denominator = sum(parts.values())
                    for key, weight in parts.items():
                        weights[key] += abs(counterpart['balance']) * weight / denominator if denominator else 0
                denominator = sum(weights.values())
                included = line['credit'] * (denominator - weights.get('vat_paid', 0)) / denominator if denominator else 0
                if not included:
                    continue
                bucket = buckets[line['date'].strftime('%Y-%m')]
                bucket['total'] += included
                for key, weight in weights.items():
                    if key != 'vat_paid':
                        bucket['items'][key] += line['credit'] * weight / denominator if denominator else 0
                row = rows_by_account.get(line['account_id'])
                kind = row.kind if row else ('bank' if line['account_id'] in bank_accounts else 'cash')
                label = (row.label or self.env['account.account'].browse(line['account_id']).with_context(lang='ar_001').name or '').split('|')[0].strip() if row else ''
                if label.startswith('L '):
                    label = label[2:].strip()
                if kind == 'custody':
                    source = source_label(row)
                elif row and row.label:
                    source = row.label
                else:
                    source = {'bank': 'bank', 'cash': 'cash', 'app': 'حساب تطبيق'}[kind]
                bucket['sources'][source] += included
        def finish(bucket):
            total = round(bucket['total'], 2)
            def rounded_rows(rows):
                result = {k: round(v, 2) for k, v in rows.items()}
                if result:
                    key = max(result, key=lambda k: abs(result[k]))
                    result[key] = round(result[key] + total - sum(result.values()), 2)
                return result
            return {'available': True, 'unconfigured_company_ids': [], 'total': total,
                    'items': rounded_rows(bucket['items']), 'sources': rounded_rows(bucket['sources'])}
        if split:
            return {key: finish(value) for key, value in buckets.items()}
        combined = {'total': 0.0, 'items': defaultdict(float), 'sources': defaultdict(float)}
        for bucket in buckets.values():
            combined['total'] += bucket['total']
            for field in ('items', 'sources'):
                for key, value in bucket[field].items():
                    combined[field][key] += value
        return finish(combined)

    @request_memo
    def _sales_vat(self, ids, start, end):
        ctx = dict(allowed_company_ids=ids)
        sales_days, _, _, _ = self._sales_days(ids, start, end)
        sessions = self.env['pos.session'].with_context(**ctx).search_read([
            ('company_id', 'in', ids), ('move_id.state', '=', 'posted'),
            ('move_id.date', '>=', start), ('move_id.date', '<=', end)], ['move_id', 'config_id'], load=None)
        settings = self.env['baseer.dashboard2.settings'].with_context(**ctx).search([('company_id', 'in', ids)])
        summary_ids = set(settings.mapped('summary_pos_config_ids').ids)
        configs = self.env['pos.config'].with_context(**dict(ctx, active_test=False)).search([('company_id', 'in', ids)])
        summary_ids.update(config.id for config in configs if any(word in (config.name or '').casefold() for word in ('ملخص المبيعات', 'sales summaries', 'ملخصات')))
        session_move_ids = [s['move_id'] for s in sessions if s['move_id'] and (not s['config_id'] or s['config_id'] not in summary_ids)]
        orders = self.env['pos.order'].with_context(**ctx).search_read([
            ('company_id', 'in', ids), ('account_move.state', '=', 'posted'),
            ('account_move.date', '>=', start), ('account_move.date', '<=', end)], ['account_move', 'config_id'], limit=200001, load=None)
        if len(orders) > 200000:
            raise UserError(_('The selected period contains more than 200,000 POS orders.'))
        pos_moves = set(session_move_ids + [o['account_move'] for o in orders if o['account_move'] and (not o['config_id'] or o['config_id'] not in summary_ids)])
        rows = self.env['account.move.line'].with_context(**ctx)._read_group([
            ('company_id', 'in', ids), ('parent_state', '=', 'posted'), ('date', '>=', start), ('date', '<=', end),
            ('account_id.account_type', '=', 'liability_current'), ('tax_line_id', '!=', False), ('move_id', 'not in', self._reset_move_ids(ids, end, start)),
            '|', '|', ('move_id.ref', 'ilike', 'NOORIX-SALES'), ('move_id.reversed_entry_id.ref', 'ilike', 'NOORIX-SALES'), ('move_id', 'in', list(pos_moves))],
            ['company_id', 'date:day', 'move_id'], ['credit:sum', 'debit:sum'])
        amount = sum(day.get('sales_vat', 0) for day in sales_days.values() if day['source'] in ('summary', 'mixed'))
        for company, day, move, credit, debit in rows:
            source = sales_days.get((company.id, day), {}).get('source')
            if (source in ('pos', 'mixed') and move.id in session_move_ids):
                amount += (credit or 0) - (debit or 0)
        return {'available': True, 'value': round(amount, 2)}

    @request_memo
    def _unpaid_bills(self, ids, end):
        return self._unpaid_bills_batch(ids, (end,))[end]

    def _unpaid_bills_batch(self, ids, ends):
        if not ends:
            return {}
        ctx = dict(allowed_company_ids=ids)
        bills = self.env['account.move'].with_context(**ctx).search([
            ('company_id', 'in', ids), ('state', '=', 'posted'), ('move_type', 'in', ['in_invoice', 'in_refund']),
            ('invoice_date', '<=', max(ends))])
        bill_info = {row['id']: row['invoice_date'] for row in bills.read(['invoice_date'], load=None)}
        all_lines = bills.line_ids
        line_rows = all_lines.read(['move_id', 'account_id', 'balance'], load=None)
        payable_ids = set(self.env['account.account'].with_context(**ctx).search([('account_type', '=', 'liability_payable')]).ids)
        bill_rows = [(row['id'], row['move_id'], bill_info[row['move_id']], row['balance'])
                     for row in line_rows if row['account_id'] in payable_ids]
        line_ids = [row[0] for row in bill_rows]
        partials = self.env['account.partial.reconcile'].with_context(**ctx).search_read([
            ('max_date', '<=', max(ends)), '|', ('debit_move_id', 'in', line_ids), ('credit_move_id', 'in', line_ids)],
            ['max_date', 'debit_move_id', 'credit_move_id', 'amount'], load=None)
        related_ids = {row[field] for row in partials for field in ('debit_move_id', 'credit_move_id')}
        move_by_line = {row['id']: row['move_id'] for row in self.env['account.move.line'].with_context(**ctx).browse(related_ids).read(['move_id'], load=None)}
        partial_rows = [(row['max_date'], row['debit_move_id'], row['credit_move_id'],
                         move_by_line[row['debit_move_id']], move_by_line[row['credit_move_id']], row['amount'])
                        for row in partials]
        result = {}
        for end in ends:
            resets = set(self._reset_move_ids(ids, end))
            selected = [(line_id, balance) for line_id, move_id, invoice_date, balance in bill_rows
                        if invoice_date <= end and move_id not in resets]
            line_ids = {line_id for line_id, _balance in selected}
            remaining = sum(-balance for _line_id, balance in selected)
            for max_date, debit_id, credit_id, debit_move, credit_move, amount in partial_rows:
                if max_date > end or debit_move in resets or credit_move in resets:
                    continue
                if credit_id in line_ids:
                    remaining -= amount
                if debit_id in line_ids:
                    remaining += amount
            result[end] = {'available': True, 'value': round(remaining, 2), 'label': 'فواتير غير مسددة — نهاية الفترة'}
        return result
