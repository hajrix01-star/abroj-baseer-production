from collections import defaultdict
from datetime import datetime, time, timedelta

import pytz

from odoo import fields, models, _
from odoo.exceptions import UserError


class DashboardSales(models.AbstractModel):
    _inherit = 'baseer.dashboard2.service'

    def _channel_for(self, label, channels, field):
        label = (label or '').casefold()
        for channel in channels:
            if any(token.strip().casefold() in label for token in (channel[field] or '').split(',') if token.strip()):
                return channel
        return {'key': 'other', 'kind': 'hall', 'name': 'أخرى', 'color_token': False, 'commission_rate': 0}

    def _sales_days(self, ids, start, end):
        """Select POS per company/day; use posted sales summaries when that day has no POS."""
        context = dict(allowed_company_ids=ids, tz=self.env.user.tz or 'Asia/Riyadh')
        tz = pytz.timezone(context['tz'])
        utc_start = tz.localize(datetime.combine(start, time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
        utc_end = tz.localize(datetime.combine(end + timedelta(days=1), time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
        channels = self.env['baseer.dashboard2.channel'].with_context(**context).search_read([], ['name', 'key', 'kind', 'color_token', 'line_keywords', 'pos_method_keywords', 'commission_rate'], order='sequence,id')
        defaults = {'cash': 'cash,نقد,نقدي,كاش', 'card': 'bank,card,mada,مدى,شبكة,بنك',
                    'keeta': 'keeta,كيتا', 'hunger': 'hunger,هنقر,هنجر', 'jahez': 'jahez,جاهز'}
        for channel in channels:
            for field in ('line_keywords', 'pos_method_keywords'):
                channel[field] = (channel[field] or '') + ',' + defaults.get(channel['key'], '')
        orders = self.env['pos.order'].with_context(**context).search_read([
            ('company_id', 'in', ids), ('state', 'in', ('paid', 'done', 'invoiced')),
            ('date_order', '>=', utc_start), ('date_order', '<', utc_end)],
            ['company_id', 'date_order', 'amount_total'], limit=200001)
        if len(orders) > 200000:
            raise UserError(_('The selected period contains more than 200,000 POS orders.'))
        days = {}
        order_days = {}
        hours = defaultdict(lambda: {'orders': 0, 'gross': 0.0})
        for order in orders:
            local = fields.Datetime.to_datetime(order['date_order']).replace(tzinfo=pytz.UTC).astimezone(tz)
            key = (order['company_id'][0], local.date())
            day = days.setdefault(key, {'source': 'pos', 'channels': defaultdict(float), 'customers': 0, 'pos_gross': 0.0})
            sign = 1 if order['amount_total'] > 0 else -1 if order['amount_total'] < 0 else 0
            day['customers'] += sign
            day['pos_gross'] += order['amount_total']
            hours[(local.weekday(), local.hour)]['orders'] += sign
            hours[(local.weekday(), local.hour)]['gross'] += order['amount_total']
            order_days[order['id']] = key
        if order_days:
            payment = self.env['pos.payment'].with_context(**context)
            groups = payment._read_group([('pos_order_id', 'in', list(order_days)), ('company_id', 'in', ids)], ['pos_order_id', 'payment_method_id'], ['amount:sum'])
            for order, method, amount in groups:
                channel = self._channel_for(method.name, channels, 'pos_method_keywords')
                days[order_days[order.id]]['channels'][channel['key']] += amount
        moves = self.env['account.move'].with_context(**context)
        move_rows = moves.search_read([
            ('company_id', 'in', ids), ('state', '=', 'posted'), ('move_type', '=', 'entry'),
            ('date', '>=', start), ('date', '<=', end)],
            ['company_id', 'date', 'reversed_entry_id'], limit=200001)
        if len(move_rows) > 200000:
            raise UserError(_('The selected period contains more than 200,000 entries.'))
        move_map = {m['id']: m for m in move_rows}
        receivable_ids = defaultdict(set)
        if move_map:
            sessions = self.env['pos.session'].with_context(**context).search_read(
                [('move_id', 'in', list(move_map))], ['move_id'])
            pos_orders = self.env['pos.order'].with_context(**context).search_read(
                [('account_move', 'in', list(move_map))], ['account_move'])
            excluded = {row['move_id'][0] for row in sessions if row['move_id']}
            excluded.update(row['account_move'][0] for row in pos_orders if row['account_move'])
            line_rows = self.env['account.move.line'].with_context(**context).search_read(
                [('company_id', 'in', ids), ('move_id', 'in', list(move_map))],
                ['move_id', 'name', 'account_id', 'debit', 'credit'], limit=200001)
            if len(line_rows) > 200000:
                raise UserError(_('The selected period contains more than 200,000 entry lines.'))
            categories = self.env['baseer.dashboard2.category'].with_context(**context).search([])
            accounts = self.env['account.account'].with_context(**context).browse(
                list({line['account_id'][0] for line in line_rows}))
            by_account = {account.id: account for account in accounts}
            by_move = defaultdict(list)
            for line in line_rows:
                by_move[line['move_id'][0]].append(line)
            for move_id, lines in by_move.items():
                if move_id in excluded:
                    continue
                move = move_map[move_id]
                company = self.env['res.company'].browse(move['company_id'][0])
                kinds = {line['account_id'][0]: self._category(
                    by_account[line['account_id'][0]].with_company(company), categories) for line in lines}
                if 'revenue' not in kinds.values():
                    continue
                key = (company.id, fields.Date.to_date(move['date']))
                if key in days and days[key]['source'] == 'pos':
                    continue
                day = days.setdefault(key, {'source': 'summary', 'channels': defaultdict(float),
                                            'customers': None, 'pos_gross': 0.0, 'sales_vat': 0.0})
                reverse = bool(move['reversed_entry_id'])
                for line in lines:
                    if kinds[line['account_id'][0]] in ('revenue', 'other_income'):
                        continue
                    amount = line['debit'] - line['credit']
                    if (reverse and line['credit'] > 0) or (not reverse and line['debit'] > 0):
                        channel = self._channel_for(line['name'], channels, 'line_keywords')
                        day['channels'][channel['key']] += amount
                        if channel['kind'] == 'app':
                            receivable_ids[key[0]].add(line['account_id'][0])
                    elif (reverse and line['debit'] > 0) or (not reverse and line['credit'] > 0):
                        day['sales_vat'] -= amount
        app_methods = self.env['pos.payment.method'].with_context(**context).search_read([('company_id', 'in', ids)], ['name', 'company_id', 'receivable_account_id'])
        for method in app_methods:
            if method['receivable_account_id'] and self._channel_for(method['name'], channels, 'pos_method_keywords')['kind'] == 'app':
                receivable_ids[method['company_id'][0]].add(method['receivable_account_id'][0])
        unreceived = 0.0
        for cid, accounts in receivable_ids.items():
            rows = self.env['account.move.line'].with_context(allowed_company_ids=[cid])._read_group([
                ('company_id', '=', cid), ('parent_state', '=', 'posted'), ('account_id', 'in', list(accounts)),
                ('date', '>=', start), ('date', '<=', end), ('debit', '>', 0)], [], ['amount_residual:sum'])
            unreceived += (rows[0][0] or 0.0) if rows else 0.0
        return days, channels, round(unreceived, 2), hours

    def _sales_summary(self, ids, start, end):
        days, channels, unreceived, hours = self._sales_days(ids, start, end)
        totals = defaultdict(float)
        for day in days.values():
            for key, amount in day['channels'].items():
                totals[key] += amount
        pos_days = [v for v in days.values() if v['source'] == 'pos']
        summary_days = [v for v in days.values() if v['source'] == 'summary']
        orders = sum(v['customers'] for v in pos_days)
        pos_gross = sum(v['pos_gross'] for v in pos_days)
        gross = sum(totals.values())
        app_keys = {c['key'] for c in channels if c['kind'] == 'app'}
        apps = sum(v for k, v in totals.items() if k in app_keys)
        return {'available': True, 'gross': round(gross, 2), 'source_counts': {'pos': len(pos_days), 'summary': len(summary_days)},
                'channel_names': {c['key']: c['name'] for c in channels}, 'channels': {k: round(v, 2) for k, v in totals.items()},
                'apps': round(apps, 2), 'apps_pct': round(apps / gross * 100, 2) if gross else None,
                'apps_unreceived': {'available': True, 'value': unreceived, 'label': 'حتى اليوم'},
                'customers': {'available': bool(pos_days), 'reason': False if pos_days else 'no_pos_days',
                              'partial': bool(pos_days and summary_days), 'covered_days': len(pos_days),
                              'value': orders if pos_days else None, 'avg_ticket': round(pos_gross / orders, 2) if orders else None}}, days, channels, hours
