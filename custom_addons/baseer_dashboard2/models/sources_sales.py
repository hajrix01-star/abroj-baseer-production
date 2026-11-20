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
        arabic_lang = 'ar_001' if self.env['res.lang']._get_data(code='ar_001').code else self.env.lang
        channels = self.env['baseer.dashboard2.channel'].with_context(**dict(context, lang=arabic_lang)).search_read([], ['name', 'key', 'kind', 'color_token', 'line_keywords', 'pos_method_keywords', 'commission_rate'], order='sequence,id')
        defaults = {'cash': 'cash,نقد,نقدي,كاش', 'card': 'bank,card,mada,مدى,شبكة,بنك',
                    'keeta': 'keeta,كيتا', 'hunger': 'hunger,هنقر,هنجر', 'jahez': 'jahez,جاهز'}
        for channel in channels:
            if '|' in channel['name']:
                parts = [part.strip() for part in channel['name'].split('|')]
                channel['name'] = next((part for part in parts if any('\u0600' <= c <= '\u06ff' for c in part)), parts[0])
            for field in ('line_keywords', 'pos_method_keywords'):
                channel[field] = (channel[field] or '') + ',' + defaults.get(channel['key'], '')
        maps = self.env['baseer.dashboard2.channel.map'].with_context(**context).search([('company_id', 'in', ids)])
        channel_by_id = {c['id']: c for c in channels}
        mapped = {(m.company_id.id, m.source, (m.pos_payment_method_id if m.source == 'pos_method' else m.account_id if m.source == 'account' else m.journal_id).id): channel_by_id[m.channel_id.id] for m in maps if m.channel_id.id in channel_by_id}
        settings = self.env['baseer.dashboard2.settings'].with_context(**context).search([('company_id', 'in', ids)])
        thresholds = {s.company_id.id: s.min_order_amount for s in settings}
        configs = self.env['pos.config'].with_context(**dict(context, active_test=False)).search([('company_id', 'in', ids)])
        summary_ids = set(settings.mapped('summary_pos_config_ids').ids)
        summary_ids.update(c.id for c in configs if any(word in (c.name or '').casefold() for word in ('ملخص المبيعات', 'sales summaries', 'ملخصات')))
        cutovers = {s.company_id.id: s.pos_cutover_date for s in settings if s.pos_cutover_date}
        for cid in ids:
            if cid not in cutovers:
                candidates = self.env['pos.order'].with_context(**context).search([
                    ('company_id', '=', cid), ('state', 'in', ('paid', 'done', 'invoiced')),
                    ('config_id', 'not in', list(summary_ids)), '|', ('amount_total', '>', thresholds.get(cid, 1.5)),
                    ('amount_total', '<', -thresholds.get(cid, 1.5))], order='date_order asc', limit=1)
                if candidates:
                    cutovers[cid] = fields.Datetime.to_datetime(candidates.date_order).replace(tzinfo=pytz.UTC).astimezone(tz).date()
        orders = self.env['pos.order'].with_context(**context).search_read([
            ('company_id', 'in', ids), ('state', 'in', ('paid', 'done', 'invoiced')),
            ('date_order', '>=', utc_start), ('date_order', '<', utc_end)],
            ['company_id', 'date_order', 'amount_total', 'config_id'], limit=200001)
        if len(orders) > 200000:
            raise UserError(_('The selected period contains more than 200,000 POS orders.'))
        days = {}
        pos_days = {}
        real_days = set()
        order_hours = []
        order_days = {}
        hours = defaultdict(lambda: {'orders': 0, 'gross': 0.0})
        for order in orders:
            local = fields.Datetime.to_datetime(order['date_order']).replace(tzinfo=pytz.UTC).astimezone(tz)
            key = (order['company_id'][0], local.date())
            if order['config_id'] and order['config_id'][0] in summary_ids:
                continue
            day = pos_days.setdefault(key, {'source': 'pos', 'channels': defaultdict(float), 'customers': 0, 'pos_gross': 0.0})
            sign = 1 if order['amount_total'] > 0 else -1 if order['amount_total'] < 0 else 0
            if abs(order['amount_total']) > thresholds.get(key[0], 1.5):
                day['customers'] += sign
                day['pos_gross'] += order['amount_total']
                real_days.add(key)
                order_hours.append((key, local.weekday(), local.hour, sign, order['amount_total']))
            order_days[order['id']] = key
        if order_days:
            payment = self.env['pos.payment'].with_context(**context)
            groups = payment._read_group([('pos_order_id', 'in', list(order_days)), ('company_id', 'in', ids)], ['pos_order_id', 'payment_method_id'], ['amount:sum'])
            for order, method, amount in groups:
                channel = mapped.get((order_days[order.id][0], 'pos_method', method.id)) or self._channel_for(method.name, channels, 'pos_method_keywords')
                pos_days[order_days[order.id]]['channels'][channel['key']] += amount
        moves = self.env['account.move'].with_context(**context)
        move_rows = moves.search_read([
            ('company_id', 'in', ids), ('state', '=', 'posted'), ('move_type', '=', 'entry'),
            ('date', '>=', start), ('date', '<=', end)],
            ['company_id', 'date', 'reversed_entry_id', 'ref'], limit=200001)
        if len(move_rows) > 200000:
            raise UserError(_('The selected period contains more than 200,000 entries.'))
        move_map = {m['id']: m for m in move_rows}
        receivable_ids = defaultdict(set)
        sessions = self.env['pos.session'].with_context(**context).search([('company_id', 'in', ids), ('move_id', 'in', list(move_map))]) if move_map else self.env['pos.session']
        real_session_moves = {session.move_id.id for session in sessions if session.config_id.id not in summary_ids}
        if move_map:
            line_rows = self.env['account.move.line'].with_context(**context).search_read(
                [('company_id', 'in', ids), ('move_id', 'in', list(move_map))],
                ['move_id', 'name', 'account_id', 'debit', 'credit', 'tax_line_id'], limit=200001)
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
                move = move_map[move_id]
                if move_id in real_session_moves and 'NOORIX-SALES' not in (move['ref'] or '').upper():
                    continue
                company = self.env['res.company'].browse(move['company_id'][0])
                kinds = {line['account_id'][0]: self._category(
                    by_account[line['account_id'][0]].with_company(company), categories) for line in lines}
                if any(by_account[line['account_id'][0]].with_company(company).code == '999999' for line in lines):
                    continue
                if 'revenue' not in kinds.values():
                    continue
                key = (company.id, fields.Date.to_date(move['date']))
                day = days.setdefault(key, {'source': 'summary', 'channels': defaultdict(float),
                                            'customers': None, 'pos_gross': 0.0, 'sales_vat': 0.0})
                reverse = bool(move['reversed_entry_id'])
                for line in lines:
                    if kinds[line['account_id'][0]] in ('revenue', 'other_income'):
                        continue
                    amount = line['debit'] - line['credit']
                    if (reverse and line['credit'] > 0) or (not reverse and line['debit'] > 0):
                        channel = mapped.get((company.id, 'account', line['account_id'][0])) or self._channel_for(line['name'], channels, 'line_keywords')
                        day['channels'][channel['key']] += amount
                        if channel['kind'] == 'app':
                            receivable_ids[key[0]].add(line['account_id'][0])
                    elif (line['tax_line_id'] or by_account[line['account_id'][0]].account_type == 'liability_current') and ((reverse and line['debit'] > 0) or (not reverse and line['credit'] > 0)):
                        day['sales_vat'] -= amount
        summary_days = days
        days = {}
        for key in set(summary_days) | set(pos_days):
            use_pos = key[0] in cutovers and key[1] >= cutovers[key[0]]
            selected = pos_days.get(key) if use_pos else summary_days.get(key)
            if selected:
                selected['both_sources'] = key in real_days and key in summary_days
                days[key] = selected
        for key, weekday, hour, sign, amount in order_hours:
            if key in days and days[key]['source'] == 'pos':
                hours[(weekday, hour)]['orders'] += sign
                hours[(weekday, hour)]['gross'] += amount
        reset_ids = self._reset_move_ids(ids, end)
        unreceived = 0.0
        for cid in ids:
            accounts = maps.filtered(lambda m: m.company_id.id == cid and m.source == 'account' and m.kind == 'app').mapped('account_id').ids
            rows = self.env['account.move.line'].with_context(allowed_company_ids=[cid])._read_group([
                ('company_id', '=', cid), ('parent_state', '=', 'posted'), ('account_id', 'in', accounts),
                ('date', '<=', end), ('move_id', 'not in', reset_ids)], [], ['balance:sum'])
            balance = rows[0][0] or 0.0 if rows else 0.0
            app_keys = {c['key'] for c in channels if c['kind'] == 'app'}
            gross = sum(amount for (company_id, _day), day in days.items() if company_id == cid for key, amount in day['channels'].items() if key in app_keys)
            unreceived += min(max(balance, 0.0), max(gross, 0.0))
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
        reset_end = self._reset_move_ids(ids, end, end)
        reset_label = 'غير متوفر — إعادة ضبط أرصدة %s' % end.strftime('%d/%m')
        return {'available': True, 'warnings': [{'date': str(day), 'company_id': cid, 'label': 'يوم فيه نقاط بيع وملخص نوركس معاً — راجع'} for (cid, day), data in sorted(days.items()) if data.get('both_sources')], 'gross': round(gross, 2), 'source_counts': {'pos': len(pos_days), 'summary': len(summary_days)},
                'channel_names': {c['key']: c['name'] for c in channels}, 'channels': {k: round(v, 2) for k, v in totals.items()},
                'apps': round(apps, 2), 'apps_pct': round(apps / gross * 100, 2) if gross else None,
                'apps_unreceived': {'available': not bool(reset_end), 'value': None if reset_end else unreceived, 'label': reset_label if reset_end else 'حتى نهاية الفترة'},
                'customers': {'available': bool(pos_days), 'reason': False if pos_days else 'no_pos_days',
                              'partial': bool(pos_days and summary_days), 'covered_days': len(pos_days),
                              'value': orders if pos_days else None, 'avg_ticket': round(pos_gross / orders, 2) if orders else None}}, days, channels, hours
