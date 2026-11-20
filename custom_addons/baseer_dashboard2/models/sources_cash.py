from collections import defaultdict

from odoo import models, _
from odoo.exceptions import UserError



class DashboardCash(models.AbstractModel):
    _inherit = 'baseer.dashboard2.service'

    def _cash_out(self, ids, start, end):
        items, sources, total = defaultdict(float), defaultdict(float), 0.0
        vat_visibility = {}
        unconfigured = []
        for cid in ids:
            ctx = dict(allowed_company_ids=[cid])
            company = self.env['res.company'].browse(cid)
            settings = self.env['baseer.dashboard2.settings'].with_context(**ctx).search([('company_id', '=', cid)], limit=1)
            vat_visibility[str(cid)] = settings.show_vat_paid_line if settings else True
            journals = settings.outflow_journal_ids - settings.excluded_journal_ids if settings else self.env['account.journal']
            wallet_maps = self.env['baseer.dashboard2.channel.map'].with_context(**ctx).search([('company_id', '=', cid), ('source', '=', 'journal'), ('kind', '=', 'app')])
            journals -= wallet_maps.mapped('journal_id')
            wallet_accounts = self.env['baseer.dashboard2.channel.map'].with_context(**ctx).search([('company_id', '=', cid), ('source', '=', 'account'), ('kind', '=', 'app')]).mapped('account_id')
            journals -= journals.filtered(lambda journal: journal.default_account_id in wallet_accounts)
            if not journals:
                unconfigured.append(cid)
            liquidity = set(journals.mapped('default_account_id').ids)
            liquidity.update(self.env['account.account'].with_context(**ctx).search([('company_ids', 'in', [cid]), ('account_type', '=', 'asset_cash')]).ids)
            custody = settings.custody_journal_ids & journals if settings else self.env['account.journal']
            methods = self.env['account.payment.method.line'].with_context(**ctx).search([('journal_id.company_id', '=', cid)])
            outstanding = set(methods.mapped('payment_account_id').ids)
            for name in ('account_journal_payment_credit_account_id', 'account_journal_payment_debit_account_id'):
                if name in company._fields and company[name]:
                    outstanding.add(company[name].id)
            tax_ids = set(self.env['account.tax.repartition.line'].with_context(**ctx).search([('account_id', '!=', False), ('tax_id.company_id', '=', cid)]).mapped('account_id').ids)
            line_model = self.env['account.move.line'].with_context(**ctx)
            paid = line_model.search_read([('company_id', '=', cid), ('parent_state', '=', 'posted'), ('date', '>=', start), ('date', '<=', end), ('journal_id', 'in', journals.ids), ('account_id', 'in', list(liquidity)), ('credit', '>', 0)], ['move_id', 'journal_id', 'credit'], limit=200001)
            if len(paid) > 200000:
                raise UserError(_('The selected period contains more than 200,000 outflow lines.'))
            move_ids = list({row['move_id'][0] for row in paid})
            if not move_ids:
                continue
            counterparts = line_model.search_read([('company_id', '=', cid), ('move_id', 'in', move_ids)], ['move_id', 'account_id', 'debit', 'credit', 'tax_repartition_line_id', 'matched_debit_ids', 'matched_credit_ids'], limit=200001)
            if len(counterparts) > 200000:
                raise UserError(_('The selected period contains more than 200,000 outflow counterpart lines.'))
            by_move = defaultdict(list)
            for row in counterparts:
                by_move[row['move_id'][0]].append(row)
            partial_ids = {pid for row in counterparts if row['account_id'][0] in outstanding for pid in row['matched_debit_ids'] + row['matched_credit_ids']}
            partials = self.env['account.partial.reconcile'].with_context(**ctx).search_read([('id', 'in', list(partial_ids)), ('company_id', '=', cid)], ['debit_move_id', 'credit_move_id']) if partial_ids else []
            other_line_ids = {p[side][0] for p in partials for side in ('debit_move_id', 'credit_move_id') if p[side]} - {r['id'] for r in counterparts}
            other_lines = line_model.search_read([('company_id', '=', cid), ('id', 'in', list(other_line_ids))], ['move_id']) if other_line_ids else []
            matched_moves = {r['move_id'][0] for r in other_lines}
            matched_rows = line_model.search_read([('company_id', '=', cid), ('move_id', 'in', list(matched_moves))], ['move_id', 'account_id', 'debit', 'credit', 'tax_repartition_line_id']) if matched_moves else []
            for row in matched_rows:
                by_move[row['move_id'][0]].append(row)
            line_to_move = {r['id']: r['move_id'][0] for r in counterparts + other_lines}
            related = defaultdict(set)
            for p in partials:
                a, b = p['debit_move_id'][0], p['credit_move_id'][0]
                if a in line_to_move and b in line_to_move:
                    related[a].add(line_to_move[b])
                    related[b].add(line_to_move[a])
            all_account_ids = {r['account_id'][0] for rows in by_move.values() for r in rows}
            accounts = {a.id: a for a in self.env['account.account'].with_context(**ctx).browse(list(all_account_ids)).exists()}
            categories = self.env['baseer.dashboard2.category'].with_context(**ctx).search([])
            for paid_line in paid:
                move_lines = by_move[paid_line['move_id'][0]]
                other = [r for r in move_lines if r['account_id'][0] not in liquidity and r['account_id'][0] != company.transfer_account_id.id]
                if not other:
                    continue
                weighted = defaultdict(float)
                for row in other:
                    aid = row['account_id'][0]
                    weight = abs(row['debit'] - row['credit'])
                    if aid in outstanding:
                        matches = [r for mid in related[row['id']] for r in by_move[mid] if r['account_id'][0] not in outstanding and r['account_id'][0] not in liquidity]
                        sums = defaultdict(float)
                        for match in matches:
                            acc = accounts[match['account_id'][0]]
                            key = 'purchases' if acc.account_type == 'liability_payable' else self._category(acc, categories) or 'other'
                            sums[key] += abs(match['debit'] - match['credit'])
                        denominator = sum(sums.values())
                        for key, amount in (sums.items() if denominator else [('other', 1)]):
                            weighted[key] += weight * amount / (denominator or 1)
                    else:
                        acc = accounts[aid]
                        key = 'purchases' if acc.account_type == 'liability_payable' else 'vat_paid' if aid in tax_ids or row['tax_repartition_line_id'] else self._category(acc, categories) or 'other'
                        weighted[key] += weight
                denominator = sum(weighted.values())
                amount = paid_line['credit']
                total += amount
                for key, weight in weighted.items():
                    items[key] += amount * weight / denominator if denominator else 0
                journal = journals.filtered(lambda j: j.id == paid_line['journal_id'][0])
                source = ('عهدة ' + journal.name) if journal in custody else 'bank' if journal.type == 'bank' else 'cash'
                sources[source] += amount
        return {'available': not bool(unconfigured), 'unconfigured_company_ids': unconfigured, 'total': round(total, 2), 'items': {k: round(v, 2) for k, v in items.items()}, 'sources': {k: round(v, 2) for k, v in sources.items()}, 'show_vat_paid_line': any(vat_visibility.values()), 'vat_visibility_by_company': vat_visibility}

    def _sales_vat(self, ids, start, end):
        ctx = dict(allowed_company_ids=ids)
        sales_days, _, _, _ = self._sales_days(ids, start, end)
        sessions = self.env['pos.session'].with_context(**ctx).search_read([
            ('company_id', 'in', ids), ('move_id.state', '=', 'posted'),
            ('move_id.date', '>=', start), ('move_id.date', '<=', end)], ['move_id'])
        session_move_ids = [s['move_id'][0] for s in sessions if s['move_id']]
        orders = self.env['pos.order'].with_context(**ctx).search_read([
            ('company_id', 'in', ids), ('account_move.state', '=', 'posted'),
            ('account_move.date', '>=', start), ('account_move.date', '<=', end)], ['account_move'], limit=200001)
        if len(orders) > 200000:
            raise UserError(_('The selected period contains more than 200,000 POS orders.'))
        pos_moves = set(session_move_ids + [o['account_move'][0] for o in orders if o['account_move']])
        rows = self.env['account.move.line'].with_context(**ctx)._read_group([
            ('company_id', 'in', ids), ('parent_state', '=', 'posted'), ('date', '>=', start), ('date', '<=', end),
            ('account_id.account_type', '=', 'liability_current'), ('tax_line_id', '!=', False),
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
        lines = bills.line_ids.filtered(lambda line: line.account_id.account_type == 'liability_payable')
        partials = self.env['account.partial.reconcile'].with_context(**ctx).search([
            ('max_date', '<=', end), '|', ('debit_move_id', 'in', lines.ids), ('credit_move_id', 'in', lines.ids)])
        remaining = sum(-line.balance for line in lines)
        line_ids = set(lines.ids)
        for partial in partials:
            if partial.credit_move_id.id in line_ids:
                remaining -= partial.amount
            if partial.debit_move_id.id in line_ids:
                remaining += partial.amount
        return {'available': True, 'value': round(remaining, 2), 'label': 'فواتير غير مسددة — نهاية الفترة'}
