from .service import request_memo, raw_rows
from collections import defaultdict

from odoo import models, _
from odoo.exceptions import UserError



class DashboardCash(models.AbstractModel):
    _inherit = 'baseer.dashboard2.service'

    @request_memo
    def _cash_out(self, ids, start, end, split=False):
        buckets = defaultdict(lambda: {'items': defaultdict(float), 'sources': defaultdict(float), 'total': 0.0})
        trace = self.env.context.get('_bd2_cash_trace')
        def trace_part(month, field, key, line, amount):
            if trace is not None:
                trace.setdefault(month, {}).setdefault(field, {}).setdefault(key, {})[line['id']] = (line['credit'], amount)
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
            line_model = self.env['account.move.line'].with_context(**ctx)
            paid = raw_rows(line_model, [('company_id', '=', cid), ('parent_state', '=', 'posted'), ('date', '>=', start), ('date', '<=', end), ('account_id', 'in', list(liquidity)), ('credit', '>', 0), ('move_id', 'not in', list(resets))], ['move_id', 'account_id', 'credit', 'date'], limit=200001)
            if len(paid) > 200000:
                raise UserError(_('The selected period contains more than 200,000 outflow lines.'))
            move_ids = list(dict.fromkeys(row['move_id'] for row in paid))
            counterparts = raw_rows(line_model, [('move_id', 'in', move_ids)], ['move_id', 'account_id', 'balance'])
            counterpart_ids = [row['id'] for row in counterparts]
            partials = raw_rows(self.env['account.partial.reconcile'].with_context(**ctx), [
                '|', ('debit_move_id', 'in', counterpart_ids), ('credit_move_id', 'in', counterpart_ids)],
                ['debit_move_id', 'credit_move_id'])
            debit_matches, credit_matches = defaultdict(list), defaultdict(list)
            for partial in partials:
                debit_matches[partial['credit_move_id']].append(partial)
                credit_matches[partial['debit_move_id']].append(partial)
            related_ids = {p[field] for p in partials for field in ('debit_move_id', 'credit_move_id')}
            related = raw_rows(line_model, [('id', 'in', list(related_ids))], ['move_id'])
            move_by_line = {row['id']: row['move_id'] for row in related}
            bill_lines = raw_rows(line_model, [('move_id', 'in', list(set(move_by_line.values())))], ['move_id', 'account_id', 'balance'])
            lines_by_move = defaultdict(list)
            for row in bill_lines:
                lines_by_move[row['move_id']].append(row)
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
            account_records = self.env['account.account'].with_context(**ctx).browse(list({row['account_id'] for row in counterparts + bill_lines})).with_company(company)
            account_records.fetch(['code', 'account_type'])
            account_by_id = {account.id: account for account in account_records}
            def details(account_id):
                if account_id not in account_details:
                    account = account_by_id[account_id]
                    account_details[account_id] = (account.code or '', account.account_type, self._category(account, categories))
                return account_details[account_id]
            def classify(line):
                account_id = line['account_id']
                code, account_type, account_category = details(account_id)
                if code in vat_codes or account_id in tax_ids:
                    return {'vat_paid': 1.0}
                if code == '201090':
                    return {'salaries': 1.0}
                matched = debit_matches[line['id']] + credit_matches[line['id']]
                if account_type == 'liability_payable' or code == '102014' or matched:
                    # mapped(debit_move_id) | mapped(credit_move_id), excluding this line.
                    other_ids = list(dict.fromkeys(p[field] for field in ('debit_move_id', 'credit_move_id') for p in matched if p[field] != line['id']))
                    other_moves = list(dict.fromkeys(move_by_line[x] for x in other_ids if x in move_by_line))
                    other_lines = [row for move_id in other_moves for row in lines_by_move[move_id]]
                    weights = defaultdict(float)
                    for counterpart in other_lines:
                        acc_code, acc_type, acc_category = details(counterpart['account_id'])
                        category = 'salaries' if acc_code == '201090' else acc_category if (acc_type or '').startswith('expense') else False
                        if category:
                            weights['purchases' if category == 'food_cost' else category] += abs(counterpart['balance'])
                    if not weights and any(details(x['account_id'])[0] in vat_codes or x['account_id'] in tax_ids for x in other_lines):
                        return {'vat_paid': 1.0}
                    return weights or {'purchases' if account_type == 'liability_payable' else 'other': 1.0}
                return {('purchases' if account_category == 'food_cost' else account_category or 'other'): 1.0}
            # A move can contain multiple paid liquidity lines. Classify each
            # counterpart once and reuse the same ordered counterparts for it.
            others_by_move = defaultdict(list)
            for row in counterparts:
                if row['account_id'] not in liquidity:
                    others_by_move[row['move_id']].append(row)
            classified = {}
            for line in paid:
                other = others_by_move[line['move_id']]
                if not other:
                    continue
                weights = defaultdict(float)
                for counterpart in other:
                    if counterpart['id'] not in classified:
                        classified[counterpart['id']] = classify(counterpart)
                    parts = classified[counterpart['id']]
                    denominator = sum(parts.values())
                    for key, weight in parts.items():
                        weights[key] += abs(counterpart['balance']) * weight / denominator if denominator else 0
                denominator = sum(weights.values())
                included = line['credit'] * (denominator - weights.get('vat_paid', 0)) / denominator if denominator else 0
                if not included:
                    continue
                bucket = buckets[line['date'].strftime('%Y-%m')]
                month = line['date'].strftime('%Y-%m')
                bucket['total'] += included
                trace_part(month, 'total', 'total', line, included)
                for key, weight in weights.items():
                    if key != 'vat_paid':
                        bucket['items'][key] += line['credit'] * weight / denominator if denominator else 0
                        trace_part(month, 'items', key, line, line['credit'] * weight / denominator if denominator else 0)
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
                trace_part(month, 'sources', source, line, included)
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
        sessions = raw_rows(self.env['pos.session'].with_context(**ctx), [
            ('company_id', 'in', ids), ('move_id.state', '=', 'posted'),
            ('move_id.date', '>=', start), ('move_id.date', '<=', end)], ['move_id', 'config_id'])
        settings = self.env['baseer.dashboard2.settings'].with_context(**ctx).search([('company_id', 'in', ids)])
        summary_ids = set(settings.mapped('summary_pos_config_ids').ids)
        configs = self.env['pos.config'].with_context(**dict(ctx, active_test=False)).search([('company_id', 'in', ids)])
        summary_ids.update(config.id for config in configs if any(word in (config.name or '').casefold() for word in ('ملخص المبيعات', 'sales summaries', 'ملخصات')))
        session_move_ids = [s['move_id'] for s in sessions if s['move_id'] and (not s['config_id'] or s['config_id'] not in summary_ids)]
        orders = raw_rows(self.env['pos.order'].with_context(**ctx), [
            ('company_id', 'in', ids), ('account_move.state', '=', 'posted'),
            ('account_move.date', '>=', start), ('account_move.date', '<=', end)], ['account_move', 'config_id'], limit=200001)
        if len(orders) > 200000:
            raise UserError(_('The selected period contains more than 200,000 POS orders.'))
        pos_moves = set(session_move_ids + [o['account_move'] for o in orders if o['account_move'] and (not o['config_id'] or o['config_id'] not in summary_ids)])
        domain = [
            ('company_id', 'in', ids), ('parent_state', '=', 'posted'), ('date', '>=', start), ('date', '<=', end),
            ('account_id.account_type', '=', 'liability_current'), ('tax_line_id', '!=', False), ('move_id', 'not in', self._reset_move_ids(ids, end, start)),
            '|', '|', ('move_id.ref', 'ilike', 'NOORIX-SALES'), ('move_id.reversed_entry_id.ref', 'ilike', 'NOORIX-SALES'), ('move_id', 'in', list(pos_moves))]
        rows = self.env['account.move.line'].with_context(**ctx)._read_group(domain,
            ['company_id', 'date:day', 'move_id'], ['credit:sum', 'debit:sum'])
        amount = sum(day.get('sales_vat', 0) for day in sales_days.values() if day['source'] in ('summary', 'mixed'))
        for company, day, move, credit, debit in rows:
            source = sales_days.get((company.id, day), {}).get('source')
            if (source in ('pos', 'mixed') and move.id in session_move_ids):
                amount += (credit or 0) - (debit or 0)
        trace = self.env.context.get('_bd2_vat_trace')
        if trace is not None:
            for line in raw_rows(self.env['account.move.line'].with_context(**ctx), domain, ['company_id', 'date', 'move_id']):
                source = sales_days.get((line['company_id'], line['date']), {}).get('source')
                if source in ('pos', 'mixed') and line['move_id'] in session_move_ids:
                    trace.add(line['id'])
        return {'available': True, 'value': round(amount, 2)}

    @request_memo
    def _unpaid_bills(self, ids, end):
        return self._unpaid_bills_batch(ids, (end,))[end]

    def _unpaid_bills_batch(self, ids, ends):
        if not ends:
            return {}
        ctx = dict(allowed_company_ids=ids)
        bills = raw_rows(self.env['account.move'].with_context(**ctx), [
            ('company_id', 'in', ids), ('state', '=', 'posted'), ('move_type', 'in', ['in_invoice', 'in_refund']),
            ('invoice_date', '<=', max(ends))], ['invoice_date'])
        bill_info = {row['id']: row['invoice_date'] for row in bills}
        lines = raw_rows(self.env['account.move.line'].with_context(**ctx), [('move_id', 'in', list(bill_info))], ['move_id', 'account_id', 'balance'])
        lines_by_move = defaultdict(list)
        for row in lines:
            lines_by_move[row['move_id']].append(row)
        line_rows = [row for bill in bills for row in lines_by_move[bill['id']]]
        payable_ids = set(self.env['account.account'].with_context(**ctx).search([('account_type', '=', 'liability_payable')]).ids)
        bill_rows = [(row['id'], row['move_id'], bill_info[row['move_id']], row['balance'])
                     for row in line_rows if row['account_id'] in payable_ids]
        line_ids = [row[0] for row in bill_rows]
        partials = raw_rows(self.env['account.partial.reconcile'].with_context(**ctx), [
            ('max_date', '<=', max(ends)), '|', ('debit_move_id', 'in', line_ids), ('credit_move_id', 'in', line_ids)],
            ['max_date', 'debit_move_id', 'credit_move_id', 'amount'])
        related_ids = {row[field] for row in partials for field in ('debit_move_id', 'credit_move_id')}
        move_by_line = {row['id']: row['move_id'] for row in raw_rows(self.env['account.move.line'].with_context(**ctx), [('id', 'in', list(related_ids))], ['move_id'])}
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
