from collections import defaultdict
from datetime import datetime, time, timedelta

import pytz

from odoo import fields, models, _
from odoo.exceptions import UserError

from .configuration import ACCOUNT_DEFAULTS


class DashboardSales(models.AbstractModel):
    _inherit = 'baseer.dashboard2.service'

    def _channel_for(self, label, channels, field):
        label = (label or '').casefold()
        for channel in channels:
            if any(token.strip().casefold() in label for token in (channel[field] or '').split(',') if token.strip()):
                return channel
        return {'key': 'other', 'kind': 'hall', 'name': 'أخرى', 'color_token': False, 'commission_rate': 0}

    def _sales_days(self, ids, start, end):
        """Select revenue by cutover; retain qualifying real POS orders for metrics."""
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
        real_sessions = sessions.filtered(lambda session: session.config_id.id not in summary_ids)
        real_session_moves = set(real_sessions.mapped('move_id').ids)
        real_order_moves = set(self.env['pos.order'].with_context(**context).search([
            ('company_id', 'in', ids), ('account_move', 'in', list(move_map)),
            ('config_id', 'not in', list(summary_ids))]).mapped('account_move').ids) if move_map else set()
        session_keys = {session.id: (session.company_id.id, session.move_id.date) for session in real_sessions}
        posted_days = set(session_keys.values())
        posted_orders = self.env['pos.order'].with_context(**context).search_read([
            ('session_id', 'in', list(session_keys)), ('state', 'in', ('paid', 'done', 'invoiced'))],
            ['company_id', 'session_id', 'amount_total'], limit=200001) if session_keys else []
        if len(posted_orders) > 200000:
            raise UserError(_('The selected period contains more than 200,000 POS orders.'))
        order_days = {order['id']: session_keys[order['session_id'][0]] for order in posted_orders
                      if abs(order['amount_total']) > thresholds.get(order['company_id'][0], 1.5)}
        posted_real_days = set(order_days.values())
        posted_channels = defaultdict(lambda: defaultdict(float))
        if order_days:
            groups = self.env['pos.payment'].with_context(**context)._read_group(
                [('pos_order_id', 'in', list(order_days)), ('company_id', 'in', ids)],
                ['pos_order_id', 'payment_method_id'], ['amount:sum'])
            for order, method, amount in groups:
                key = order_days[order.id]
                channel = mapped.get((key[0], 'pos_method', method.id)) or self._channel_for(method.name, channels, 'pos_method_keywords')
                posted_channels[key][channel['key']] += amount
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
                if move_id in real_session_moves or move_id in real_order_moves:
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
        overrides = self.env['baseer.dashboard2.source.override'].with_context(**context).search([
            ('company_id', 'in', ids), ('date_from', '<=', end), ('date_to', '>=', start)])
        for key in set(summary_days) | posted_days | set(pos_days):
            override = overrides.filtered(lambda row: row.company_id.id == key[0] and row.date_from <= key[1] <= row.date_to)
            mode = override.source if override else 'auto'
            has_summary = key in summary_days
            has_pos = key in posted_days
            use_summary = has_summary and mode != 'pos'
            use_pos = has_pos and mode != 'summary'
            source = 'mixed' if use_summary and use_pos else 'summary' if use_summary else 'pos' if use_pos else False
            day = {'source': source, 'channels': defaultdict(float), 'customers': None,
                   'pos_gross': 0.0, 'sales_vat': 0.0, 'sales_missing': not bool(source),
                   'both_sources': has_summary and key in posted_real_days, 'source_mode': mode,
                   'has_summary': has_summary}
            if use_summary:
                day['channels'].update(summary_days[key]['channels'])
                day['sales_vat'] = summary_days[key]['sales_vat']
            if use_pos:
                for channel, amount in posted_channels[key].items():
                    day['channels'][channel] += amount
            if key in real_days:
                day['customers'] = pos_days[key]['customers']
                day['pos_gross'] = pos_days[key]['pos_gross']
            days[key] = day
        for key, weekday, hour, sign, amount in order_hours:
            hours[(weekday, hour)]['orders'] += sign
            hours[(weekday, hour)]['gross'] += amount
        reset_ids = self._reset_move_ids(ids, end)
        liquidity_ids = set((settings.mapped('liquidity_account_ids') | settings.mapped('liquidity_ids.account_id')).ids)
        app_maps = maps.filtered(lambda m: m.source == 'account' and m.kind == 'app'
                                 and (m.account_id.account_type == 'asset_receivable' or
                                      (m.account_id.with_company(m.company_id).code in ACCOUNT_DEFAULTS
                                       and m.channel_id.key in ('hunger', 'keeta', 'jahez')
                                       and ACCOUNT_DEFAULTS[m.account_id.with_company(m.company_id).code] == m.channel_id.key))
                                 and m.account_id.id not in liquidity_ids)
        account_channel = {(m.company_id.id, m.account_id.id): m.channel_id.key for m in app_maps}
        starts = {s.company_id.id: s.app_balance_start_date for s in settings}
        balances = defaultdict(float)
        cumulative = defaultdict(float)
        rows = self.env['account.move.line'].with_context(**context)._read_group([
            ('company_id', 'in', ids), ('parent_state', '=', 'posted'), ('account_id', 'in', app_maps.mapped('account_id').ids),
            ('date', '<=', end), ('move_id', 'not in', reset_ids)], ['company_id', 'account_id', 'date:day'], ['balance:sum'])
        for company, account, day, amount in rows:
            key = (company.id, account_channel.get((company.id, account.id)))
            if key[1]:
                cumulative[key] += amount or 0
                if not starts.get(company.id) or day >= starts[company.id]:
                    balances[key] += amount or 0
        breakdown = defaultdict(lambda: {'value': 0.0, 'cumulative': 0.0})
        app_keys = {c['key'] for c in channels if c['kind'] == 'app'}
        for cid in ids:
            for key in app_keys:
                gross = sum(day['channels'].get(key, 0) for (company_id, _), day in days.items() if company_id == cid)
                breakdown[key]['value'] += min(max(balances[(cid, key)], 0), max(gross, 0))
                breakdown[key]['cumulative'] += max(cumulative[(cid, key)], 0)
        available = all(not starts.get(cid) or end >= starts[cid] for cid in ids)
        unreceived = {'available': available, 'value': round(sum(v['value'] for v in breakdown.values()), 2) if available else None,
                      'label': 'حتى نهاية الفترة' if available else 'غير متوفر — قيد المراجعة',
                      'breakdown': [{'key': key, 'name': next((c['name'] for c in channels if c['key'] == key), key),
                                     'value': round(value['value'], 2), 'cumulative': round(value['cumulative'], 2)}
                                    for key, value in breakdown.items()]}
        return days, channels, unreceived, hours

    def _cancelled_session_warnings(self, ids, start, end, summary_days=None):
        ctx = dict(allowed_company_ids=ids, active_test=False)
        settings = self.env['baseer.dashboard2.settings'].with_context(**ctx).search([('company_id', 'in', ids)])
        thresholds = {s.company_id.id: s.min_order_amount for s in settings}
        summary_ids = set(settings.mapped('summary_pos_config_ids').ids)
        # A wide UTC window accommodates every company timezone; filter local dates below.
        orders = self.env['pos.order'].with_context(**ctx).search_read([
            ('company_id', 'in', ids), ('session_id.move_id.state', '=', 'cancel'),
            ('date_order', '>=', datetime.combine(start - timedelta(days=1), time.min)),
            ('date_order', '<', datetime.combine(end + timedelta(days=2), time.min)),
        ], ['company_id', 'session_id', 'date_order', 'amount_total'])
        sessions = self.env['pos.session'].with_context(**ctx).browse({o['session_id'][0] for o in orders})
        sessions = sessions.filtered(lambda session: session.config_id.id not in summary_ids and not any(
            word in (session.config_id.name or '').casefold() for word in ('ملخص المبيعات', 'sales summaries', 'ملخصات')))
        if not sessions:
            return []
        if summary_days is None:
            days = self._sales_days(ids, start, end)[0]
            summary_days = {key for key, day in days.items() if day['has_summary']}
        refs = {ref for session in sessions for ref in (session.name, session.move_id.ref) if ref}
        posted = self.env['account.move'].with_context(**ctx).search([
            ('company_id', 'in', ids), ('state', '=', 'posted'), ('ref', 'in', list(refs))]) if refs else self.env['account.move']
        replacements = {(m.company_id.id, m.ref) for m in posted}
        by_id = {s.id: s for s in sessions}
        grouped = defaultdict(lambda: [0.0, 0])
        for order in orders:
            session = by_id.get(order['session_id'][0])
            cid = order['company_id'][0]
            if not session or order['amount_total'] <= thresholds.get(cid, 1.5):
                continue
            tz = pytz.timezone(session.company_id.partner_id.tz or self.env.user.tz or 'Asia/Riyadh')
            day = fields.Datetime.to_datetime(order['date_order']).replace(tzinfo=pytz.UTC).astimezone(tz).date()
            if not start <= day <= end or (cid, day) in summary_days or any(
                (cid, ref) in replacements for ref in (session.name, session.move_id.ref) if ref):
                continue
            grouped[(session.id, day)][0] += order['amount_total']
            grouped[(session.id, day)][1] += 1
        return [{'date': str(day), 'company_id': by_id[sid].company_id.id,
                 'label': 'جلسة إقفال ملغاة لم تُعد: %s — مفقود %s (%s طلب)' % (
                     by_id[sid].name.rsplit('/', 1)[-1], format(amount, ',.0f'), count), 'session_id': sid}
                for (sid, day), (amount, count) in sorted(grouped.items())]

    def _sales_summary(self, ids, start, end):
        days, channels, unreceived, hours = self._sales_days(ids, start, end)
        totals = defaultdict(float)
        for day in days.values():
            for key, amount in day['channels'].items():
                totals[key] += amount
        pos_days = [v for v in days.values() if v['source'] in ('pos', 'mixed')]
        summary_days = [v for v in days.values() if v['source'] in ('summary', 'mixed')]
        customer_days = [v for v in days.values() if v['customers'] is not None]
        orders = sum(v['customers'] for v in customer_days)
        pos_gross = sum(v['pos_gross'] for v in customer_days)
        gross = sum(totals.values())
        app_keys = {c['key'] for c in channels if c['kind'] == 'app'}
        apps = sum(v for k, v in totals.items() if k in app_keys)
        return {'available': True, 'warnings': [{'date': str(day), 'company_id': cid, 'label': 'يوم بمصدرين مرحّلين: نوركس + جلسة نقاط بيع — تم الجمع' if data['source_mode'] == 'auto' else 'يوم بمصدرين مرحّلين: نوركس + جلسة نقاط بيع — طُبّق استثناء المصدر'} for (cid, day), data in sorted(days.items()) if data.get('both_sources')] + self._cancelled_session_warnings(ids, start, end, {key for key, day in days.items() if day['has_summary']}), 'gross': round(gross, 2), 'source_counts': {'pos': len(pos_days), 'summary': len(summary_days)},
                'channel_names': {c['key']: c['name'] for c in channels}, 'channels': {k: round(v, 2) for k, v in totals.items()},
                'apps': round(apps, 2), 'apps_pct': round(apps / gross * 100, 2) if gross else None,
                'apps_unreceived': unreceived,
                'customers': {'available': bool(customer_days), 'reason': False if customer_days else 'no_pos_days',
                              'partial': bool(customer_days and len(customer_days) < len(days)), 'covered_days': len(customer_days),
                              'value': orders if customer_days else None, 'avg_ticket': round(pos_gross / orders, 2) if orders else None}}, days, channels, hours
