from .service import request_memo, raw_rows
from collections import defaultdict
from datetime import datetime, time, timedelta

import pytz

from odoo import fields, models, _
from odoo.exceptions import UserError
from odoo.osv import expression

from .configuration import ACCOUNT_DEFAULTS


class DashboardSales(models.AbstractModel):
    _inherit = 'baseer.dashboard2.service'

    def _channel_for(self, label, channels, field):
        label = (label or '').casefold()
        for channel in channels:
            if any(token.strip().casefold() in label for token in (channel[field] or '').split(',') if token.strip()):
                return channel
        return {'key': 'other', 'kind': 'hall', 'name': 'أخرى', 'color_token': False, 'commission_rate': 0}

    def _summary_config_ids(self, ids):
        """POS configs that only carry daily sales summaries (not real tickets)."""
        context = {'allowed_company_ids': ids, 'active_test': False}
        settings = self.env['baseer.dashboard2.settings'].with_context(**context).search([('company_id', 'in', ids)])
        configs = self.env['pos.config'].with_context(**context).search([('company_id', 'in', ids)])
        summary_ids = set(settings.mapped('summary_pos_config_ids').ids)
        summary_ids.update(c.id for c in configs if any(word in (c.name or '').casefold() for word in ('ملخص المبيعات', 'sales summaries', 'ملخصات')))
        return summary_ids

    def _riyadh_window(self, start, end):
        """UTC bounds of the Riyadh calendar days start..end (inclusive)."""
        tz = pytz.timezone('Asia/Riyadh')
        return (tz.localize(datetime.combine(start, time.min)).astimezone(pytz.UTC).replace(tzinfo=None),
                tz.localize(datetime.combine(end + timedelta(days=1), time.min)).astimezone(pytz.UTC).replace(tzinfo=None))

    def _session_day_domain(self, first, last):
        """POS orders whose session was opened on Riyadh day first..last.

        A session without an opening time (never opened through the POS) falls back to the order time.
        """
        utc_first, utc_end = self._riyadh_window(first, last)
        return ['|',
                '&', ('session_id.start_at', '>=', utc_first), ('session_id.start_at', '<', utc_end),
                '&', ('session_id.start_at', '=', False), '&', ('date_order', '>=', utc_first), ('date_order', '<', utc_end)]

    @request_memo
    def _posted_pos_sessions(self, ids, start, end):
        """Real POS sessions with a posted closing entry, keyed by their opening day (Asia/Riyadh).

        Returns {session_id: (company_id, day, move_id)}. The day is the Riyadh calendar day of
        pos.session.start_at, so a shift closed after midnight stays entirely on the day it opened.
        Sessions without start_at fall back to the closing entry date.
        """
        tz = pytz.timezone('Asia/Riyadh')
        utc_start, utc_end = self._riyadh_window(start, end)
        summary_ids = self._summary_config_ids(ids)
        sessions = self.env['pos.session'].with_context(allowed_company_ids=ids, tz='Asia/Riyadh').search([
            ('company_id', 'in', ids), ('move_id.state', '=', 'posted'), ('config_id', 'not in', list(summary_ids)),
            '|',
            '&', ('start_at', '>=', utc_start), ('start_at', '<', utc_end),
            '&', ('start_at', '=', False), '&', ('move_id.date', '>=', start), ('move_id.date', '<=', end)])
        result = {}
        for session in sessions:
            if session.start_at:
                day = session.start_at.replace(tzinfo=pytz.UTC).astimezone(tz).date()
            else:
                day = session.move_id.date
            result[session.id] = (session.company_id.id, day, session.move_id.id)
        return result

    def _has_pos_session_closings(self, ids, start, end):
        """True when a real POS session has its closing entry posted in start..end (by entry date)."""
        summary_ids = self._summary_config_ids(ids)
        return bool(self.env['pos.session'].with_context(allowed_company_ids=ids).search_count([
            ('company_id', 'in', ids), ('move_id.state', '=', 'posted'), ('config_id', 'not in', list(summary_ids)),
            ('move_id.date', '>=', start), ('move_id.date', '<=', end)]))

    def _customer_orders_domain(self, ids, start, end):
        context = {'allowed_company_ids': ids, 'active_test': False}
        settings = self.env['baseer.dashboard2.settings'].with_context(**context).search([('company_id', 'in', ids)])
        by_company = {s.company_id.id: s for s in settings}
        summary_ids = self._summary_config_ids(ids)
        branches = []
        for cid in ids:
            setting = by_company.get(cid)
            first = max(start, setting.pos_cutover_date) if setting and setting.pos_cutover_date else start
            if first > end:
                continue
            threshold = setting.min_order_amount if setting else 1.5
            branches.append(expression.AND([[('company_id', '=', cid)], self._session_day_domain(first, end),
                                             expression.OR([[('amount_total', '>', threshold)], [('amount_total', '<', -threshold)]])]))
        return expression.AND([[('company_id', 'in', ids), ('state', 'in', ('paid', 'done', 'invoiced')),
                                ('config_id', 'not in', list(summary_ids))],
                               expression.OR(branches) if branches else [('id', '=', 0)]])

    def _customer_hour_domain(self, ids, start, end, weekday, hour):
        tz = pytz.timezone('Asia/Riyadh')
        intervals = []
        # An overnight shift opened on `end` has tickets on the next clock day; the order domain keeps them.
        day = start
        while day <= end + timedelta(days=1):
            if day.weekday() == weekday:
                local_start = tz.localize(datetime.combine(day, time(hour)))
                first = local_start.astimezone(pytz.UTC).replace(tzinfo=None)
                last = (local_start + timedelta(hours=1)).astimezone(pytz.UTC).replace(tzinfo=None)
                intervals.append([('date_order', '>=', first), ('date_order', '<', last)])
            day += timedelta(days=1)
        return expression.AND([self._customer_orders_domain(ids, start, end), expression.OR(intervals) if intervals else [('id', '=', 0)]])

    @request_memo
    def _sales_days(self, ids, start, end):
        """Select revenue by cutover; retain qualifying real POS orders for metrics."""
        context = dict(allowed_company_ids=ids, tz='Asia/Riyadh')
        tz = pytz.timezone(context['tz'])
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
        # Tickets belong to the day their POS session was opened (Asia/Riyadh), not to their own clock day.
        orders = raw_rows(self.env['pos.order'].with_context(**context), [
            ('company_id', 'in', ids), ('state', 'in', ('paid', 'done', 'invoiced'))] + self._session_day_domain(start, end),
            ['company_id', 'date_order', 'amount_total', 'config_id', 'session_id'], limit=200001)
        session_open = {row['id']: row['start_at'] for row in raw_rows(
            self.env['pos.session'].with_context(**context), [('id', 'in', list({o['session_id'] for o in orders if o['session_id']}))],
            ['start_at'])} if orders else {}
        qualifying_ids = set(self.env['pos.order'].with_context(**context).search(self._customer_orders_domain(ids, start, end)).ids)
        if len(orders) > 200000:
            raise UserError(_('The selected period contains more than 200,000 POS orders.'))
        days = {}
        summary_line_ids = defaultdict(lambda: defaultdict(list))
        summary_vat_ids = defaultdict(list)
        pos_days = {}
        real_days = set()
        order_hours = []
        hours = defaultdict(lambda: {'orders': 0, 'gross': 0.0})
        for order in orders:
            local = fields.Datetime.to_datetime(order['date_order']).replace(tzinfo=pytz.UTC).astimezone(tz)
            opened = session_open.get(order['session_id'])
            key = (order['company_id'], fields.Datetime.to_datetime(opened).replace(tzinfo=pytz.UTC).astimezone(tz).date() if opened else local.date())
            if order['config_id'] and order['config_id'] in summary_ids:
                continue
            day = pos_days.setdefault(key, {'source': 'pos', 'channels': defaultdict(float), 'customers': 0, 'pos_gross': 0.0})
            sign = 1 if order['amount_total'] > 0 else -1 if order['amount_total'] < 0 else 0
            if order['id'] in qualifying_ids:
                day['customers'] += sign
                day['pos_gross'] += order['amount_total']
                real_days.add(key)
                order_hours.append((key, local.weekday(), local.hour, sign, order['amount_total']))
        moves = self.env['account.move'].with_context(**context)
        move_rows = raw_rows(moves, [
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
        real_order_moves = {row['account_move'] for row in raw_rows(self.env['pos.order'].with_context(**context), [
            ('company_id', 'in', ids), ('account_move', 'in', list(move_map)),
            ('config_id', 'not in', list(summary_ids))], ['account_move']) if row['account_move']} if move_map else set()
        # Sales of a posted session land entirely on the day it was opened, even when it closed after midnight.
        dated_sessions = self._posted_pos_sessions(ids, start, end)
        session_keys = {session_id: (company_id, day) for session_id, (company_id, day, _move_id) in dated_sessions.items()}
        posted_days = set(session_keys.values())
        posted_orders = raw_rows(self.env['pos.order'].with_context(**context), [
            ('session_id', 'in', list(session_keys)), ('state', 'in', ('paid', 'done', 'invoiced'))],
            ['company_id', 'session_id', 'amount_total'], limit=200001) if session_keys else []
        if len(posted_orders) > 200000:
            raise UserError(_('The selected period contains more than 200,000 POS orders.'))
        order_days = {order['id']: session_keys[order['session_id']] for order in posted_orders
                      if abs(order['amount_total']) > thresholds.get(order['company_id'], 1.5)}
        posted_real_days = set(order_days.values())
        posted_channels = defaultdict(lambda: defaultdict(float))
        pos_payment_ids = defaultdict(lambda: defaultdict(list))
        if order_days:
            payment_domain = [('pos_order_id', 'in', list(order_days)), ('company_id', 'in', ids)]
            groups = self.env['pos.payment'].with_context(**context)._read_group(
                payment_domain,
                ['pos_order_id', 'payment_method_id'], ['amount:sum'])
            for order, method, amount in groups:
                key = order_days[order.id]
                channel = mapped.get((key[0], 'pos_method', method.id)) or self._channel_for(method.name, channels, 'pos_method_keywords')
                posted_channels[key][channel['key']] += amount
            if self.env.context.get('_bd2_pos_trace') is not None:
                payment_rows = raw_rows(self.env['pos.payment'].with_context(**context), payment_domain,
                                        ['pos_order_id', 'payment_method_id'])
                methods = self.env['pos.payment.method'].with_context(**context).browse({p['payment_method_id'] for p in payment_rows})
                names = {m.id: m.name for m in methods}
                for payment in payment_rows:
                    key = order_days[payment['pos_order_id']]
                    method_id = payment['payment_method_id']
                    channel = mapped.get((key[0], 'pos_method', method_id)) or self._channel_for(names.get(method_id), channels, 'pos_method_keywords')
                    pos_payment_ids[key][channel['key']].append(payment['id'])
        if move_map:
            line_rows = raw_rows(self.env['account.move.line'].with_context(**context),
                [('company_id', 'in', ids), ('move_id', 'in', list(move_map))],
                ['move_id', 'name', 'account_id', 'debit', 'credit', 'tax_line_id'], limit=200001)
            if len(line_rows) > 200000:
                raise UserError(_('The selected period contains more than 200,000 entry lines.'))
            categories = self.env['baseer.dashboard2.category'].with_context(**context).search([])
            accounts = self.env['account.account'].with_context(**context).browse(
                list({line['account_id'] for line in line_rows}))
            by_account = {account.id: account for account in accounts}
            by_move = defaultdict(list)
            for line in line_rows:
                by_move[line['move_id']].append(line)
            account_info = {}
            for move_id, lines in by_move.items():
                move = move_map[move_id]
                if move_id in real_session_moves or move_id in real_order_moves:
                    continue
                company = self.env['res.company'].browse(move['company_id'])
                account_ids = {line['account_id'] for line in lines}
                for account_id in account_ids:
                    info_key = (company.id, account_id)
                    if info_key not in account_info:
                        account = by_account[account_id].with_company(company)
                        account_info[info_key] = (self._category(account, categories), account.code == '999999')
                kinds = {account_id: account_info[(company.id, account_id)][0] for account_id in account_ids}
                if any(account_info[(company.id, account_id)][1] for account_id in account_ids):
                    continue
                if 'revenue' not in kinds.values():
                    continue
                key = (company.id, fields.Date.to_date(move['date']))
                day = days.setdefault(key, {'source': 'summary', 'channels': defaultdict(float),
                                            'customers': None, 'pos_gross': 0.0, 'sales_vat': 0.0})
                reverse = bool(move['reversed_entry_id'])
                for line in lines:
                    if kinds[line['account_id']] in ('revenue', 'other_income'):
                        continue
                    amount = line['debit'] - line['credit']
                    if (reverse and line['credit'] > 0) or (not reverse and line['debit'] > 0):
                        channel = mapped.get((company.id, 'account', line['account_id'])) or self._channel_for(line['name'], channels, 'line_keywords')
                        day['channels'][channel['key']] += amount
                        summary_line_ids[key][channel['key']].append(line['id'])
                        if channel['kind'] == 'app':
                            receivable_ids[key[0]].add(line['account_id'])
                    elif (line['tax_line_id'] or by_account[line['account_id']].account_type == 'liability_current') and ((reverse and line['debit'] > 0) or (not reverse and line['credit'] > 0)):
                        day['sales_vat'] -= amount
                        summary_vat_ids[key].append(line['id'])
        summary_days = days
        days = {}
        overrides = self.env['baseer.dashboard2.source.override'].with_context(**context).search([
            ('company_id', 'in', ids), ('date_from', '<=', end), ('date_to', '>=', start)])
        overrides_by_company = defaultdict(list)
        for row in overrides:
            overrides_by_company[row.company_id.id].append((row.date_from, row.date_to, row.source))
        for key in set(summary_days) | posted_days | set(pos_days):
            matches = [source for date_from, date_to, source in overrides_by_company[key[0]] if date_from <= key[1] <= date_to]
            if len(matches) > 1:
                raise ValueError('Expected singleton: baseer.dashboard2.source.override')
            mode = matches[0] if matches else 'auto'
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
                trace = self.env.context.get('_bd2_sales_trace')
                if trace is not None:
                    trace[key] = dict(summary_line_ids[key])
                vat_trace = self.env.context.get('_bd2_vat_trace')
                if vat_trace is not None:
                    vat_trace.update(summary_vat_ids[key])
            if use_pos:
                for channel, amount in posted_channels[key].items():
                    day['channels'][channel] += amount
                trace = self.env.context.get('_bd2_pos_trace')
                if trace is not None:
                    trace[key] = dict(pos_payment_ids[key])
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
                      'label': 'حتى نهاية الفترة' if available else 'غير متوفر',
                      'breakdown': [{'key': key, 'name': next((c['name'] for c in channels if c['key'] == key), key),
                                     'value': round(value['value'], 2), 'cumulative': round(value['cumulative'], 2)}
                                    for key, value in breakdown.items()] if available else []}
        return days, channels, unreceived, hours

    def _cancelled_session_warnings(self, ids, start, end, summary_days=None):
        ctx = dict(allowed_company_ids=ids, active_test=False)
        settings = self.env['baseer.dashboard2.settings'].with_context(**ctx).search([('company_id', 'in', ids)])
        thresholds = {s.company_id.id: s.min_order_amount for s in settings}
        cutovers = {s.company_id.id: s.pos_cutover_date for s in settings if s.pos_cutover_date}
        starts = {s.company_id.id: s.app_balance_start_date for s in settings}
        summary_ids = set(settings.mapped('summary_pos_config_ids').ids)
        # A wide UTC window accommodates every company timezone; filter local dates below.
        orders = raw_rows(self.env['pos.order'].with_context(**ctx), [
            ('company_id', 'in', ids), ('session_id.move_id.state', '=', 'cancel'),
            ('date_order', '>=', datetime.combine(start - timedelta(days=1), time.min)),
            ('date_order', '<', datetime.combine(end + timedelta(days=2), time.min)),
        ], ['company_id', 'session_id', 'date_order', 'amount_total'])
        sessions = self.env['pos.session'].with_context(**ctx).browse({o['session_id'] for o in orders})
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
            session = by_id.get(order['session_id'])
            cid = order['company_id']
            if not session or order['amount_total'] <= thresholds.get(cid, 1.5):
                continue
            tz = pytz.timezone(session.company_id.partner_id.tz or self.env.user.tz or 'Asia/Riyadh')
            day = fields.Datetime.to_datetime(order['date_order']).replace(tzinfo=pytz.UTC).astimezone(tz).date()
            if not start <= day <= end or (starts.get(cid) and day < starts[cid]) or (cid, day) in summary_days or any(
                (cid, ref) in replacements for ref in (session.name, session.move_id.ref) if ref):
                continue
            grouped[(session.id, day)][0] += order['amount_total']
            grouped[(session.id, day)][1] += 1
        return [{'date': str(day), 'company_id': by_id[sid].company_id.id,
                 'label': 'جلسة إقفال ملغاة لم تُعد: %s — مفقود %s (%s طلب)' % (
                     by_id[sid].name.rsplit('/', 1)[-1], format(amount, ',.0f'), count), 'session_id': sid}
                for (sid, day), (amount, count) in sorted(grouped.items())]

    @request_memo
    def _tooltip_sales_months(self, ids, start, end):
        """Reuse the existing day/source selection once for all comparison months."""
        days, channels, _unreceived, _hours = self._sales_days(ids, start, end)
        app_keys = {c['key'] for c in channels if c['kind'] == 'app'}
        groups = defaultdict(list)
        for (_company, day), value in days.items():
            groups[day.strftime('%Y-%m')].append(value)
        result = {}
        for month, rows in groups.items():
            totals = defaultdict(float)
            for row in rows:
                for key, amount in row['channels'].items():
                    totals[key] += amount
            gross = sum(totals.values())
            apps = sum(v for k, v in totals.items() if k in app_keys)
            customer_days = [row for row in rows if row['customers'] is not None]
            orders = sum(row['customers'] for row in customer_days)
            pos_gross = sum(row['pos_gross'] for row in customer_days)
            has_sales = any(row['source'] in ('pos', 'summary', 'mixed') for row in rows)
            result[month] = {'gross': round(gross, 2) if has_sales else None,
                             'apps': round(apps, 2) if has_sales else None,
                             'apps_pct': round(apps / gross * 100, 2) if gross else None,
                             'channels': {k: round(v, 2) for k, v in totals.items()},
                             'customers': {'value': orders if customer_days else None,
                                           'avg_ticket': round(pos_gross / orders, 2) if orders else None}}
        return result

    @request_memo
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
        settings = self.env['baseer.dashboard2.settings'].with_context(allowed_company_ids=ids).search([('company_id', 'in', ids)])
        starts = {s.company_id.id: s.app_balance_start_date for s in settings}
        cutover = settings.pos_cutover_date if len(ids) == 1 and len(settings) == 1 else False
        return {'available': True, 'warnings': [{'date': str(day), 'company_id': cid, 'label': 'يوم بمصدرين مرحّلين: نوركس + جلسة نقاط بيع — تم الجمع' if data['source_mode'] == 'auto' else 'يوم بمصدرين مرحّلين: نوركس + جلسة نقاط بيع — طُبّق استثناء المصدر'} for (cid, day), data in sorted(days.items()) if data.get('both_sources') and (not starts.get(cid) or day >= starts[cid])] + self._cancelled_session_warnings(ids, start, end, {key for key, day in days.items() if day['has_summary']}), 'gross': round(gross, 2), 'source_counts': {'pos': len(pos_days), 'summary': len(summary_days)},
                'channel_names': {c['key']: c['name'] for c in channels}, 'channels': {k: round(v, 2) for k, v in totals.items()},
                'apps': round(apps, 2), 'apps_pct': round(apps / gross * 100, 2) if gross else None,
                'apps_unreceived': unreceived,
                'customers': {'available': bool(customer_days), 'reason': False if customer_days else 'no_pos_days',
                              'cutover_date': fields.Date.to_string(cutover) if cutover and start <= cutover <= end else False,
                              'partial': bool(customer_days and len(customer_days) < len(days)), 'covered_days': len(customer_days),
                              'value': orders if customer_days else None, 'avg_ticket': round(pos_gross / orders, 2) if orders else None}}, days, channels, hours
