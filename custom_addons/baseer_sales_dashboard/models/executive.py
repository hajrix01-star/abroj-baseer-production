"""Read-only POS command center, grouped by the session's Riyadh opening day."""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import SQL
from odoo.addons.baseer_pos_summary.models.common import money, ZERO
from .dashboard import _card, _display
from .report_names import report_name


RIYADH = ZoneInfo('Asia/Riyadh')
MAX_DAYS = 366
MAX_ORDERS = 100000
SESSION_PAGE_SIZE = 50
POS_STATES = ('paid', 'done', 'invoiced')


def _validate_company_ids(company_ids, permitted):
    if (not isinstance(company_ids, list) or not 1 <= len(company_ids) <= 3
            or any(type(identifier) is not int or identifier <= 0 for identifier in company_ids)
            or len(set(company_ids)) != len(company_ids)):
        raise ValidationError(_('Choose between one and three distinct companies per request.'))
    if not set(company_ids).issubset(set(permitted)):
        raise AccessError(_('One or more selected companies are not available.'))


def _utc_at(day, hour):
    return datetime.combine(day, time(hour), RIYADH).astimezone(timezone.utc).replace(tzinfo=None)


def _resolve_period(preset, date_from, date_to, now):
    """Dates select session opening days; only contributing states imply closure."""
    local = now.replace(tzinfo=timezone.utc).astimezone(RIYADH)
    today = local.date()
    if preset != 'custom' and (date_from is not None or date_to is not None):
        raise ValidationError(_('Custom dates require the custom period.'))
    if preset == 'last_complete_day':
        first = last = today - timedelta(days=1)
    elif preset == 'current_day':
        first = last = today
    elif preset == 'this_month':
        first, last = today.replace(day=1), today
    elif preset == 'last_month':
        last = today.replace(day=1) - timedelta(days=1)
        first = last.replace(day=1)
    elif preset == 'last_30_days':
        last, first = today, today - timedelta(days=29)
    elif preset == 'custom':
        try:
            if any(not isinstance(raw, str) or len(raw) != 10 for raw in (date_from, date_to)):
                raise ValueError
            first, last = date.fromisoformat(date_from), date.fromisoformat(date_to)
            if first.isoformat() != date_from or last.isoformat() != date_to:
                raise ValueError
        except (TypeError, ValueError):
            raise ValidationError(_('Choose valid start and end dates.')) from None
    else:
        raise ValidationError(_('Choose a valid command center period.'))
    if first > last:
        raise ValidationError(_('The start date must be on or before the end date.'))
    if last > today:
        raise ValidationError(_('Future session opening days are not available.'))
    if (last - first).days + 1 > MAX_DAYS:
        raise ValidationError(_('Choose a period of at most 366 days; no dates have been omitted.'))
    return {'preset': preset, 'from': first.isoformat(), 'to': last.isoformat(),
            'status': 'selected', 'timezone': 'Asia/Riyadh', 'day_basis': 'session_start',
            'as_of': local.strftime('%Y-%m-%d %H:%M:%S')}


class ExecutiveDashboard(models.Model):
    _inherit = 'spreadsheet.dashboard'

    baseer_dashboard_kind = fields.Selection(
        selection_add=[('executive_center', 'Command center')],
        ondelete={'executive_center': 'set null'},
    )

    def _baseer_executive_access(self):
        self.ensure_one()
        self.check_access('read')
        if self.baseer_dashboard_kind not in ('sales_summary', 'executive_center') or not self.is_published:
            raise AccessError(_('This sales dashboard is not available.'))
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(_('Point of Sale access is required to view POS sales.'))
        for name in ('pos.order', 'pos.session'):
            self.env[name].check_access('read')

    def _baseer_executive_allowed(self):
        assigned = self.env.user.company_ids
        scoped = self.with_context({'allowed_company_ids': assigned.ids, 'lang': self.env.lang, 'tz': 'Asia/Riyadh'})
        scoped._baseer_executive_access()
        companies = scoped.env['res.company'].search([('id', 'in', assigned.ids)], order='id')
        if scoped.company_ids:
            companies &= scoped.company_ids
        return companies

    def _baseer_executive_scope(self, identifier):
        scoped = self.with_context({'allowed_company_ids': [identifier],
                                   'lang': self.env.lang, 'tz': 'Asia/Riyadh'})
        scoped._baseer_executive_access()
        return scoped

    @api.readonly
    def get_baseer_executive_companies(self):
        companies = self._baseer_executive_allowed()
        return {'companies': [{'id': company.id, 'name': report_name(company.name, self.env.lang),
                               'currency': company.currency_id.name} for company in companies],
                'user_id': self.env.uid, 'db': self.env.cr.dbname}

    @api.readonly
    def get_baseer_executive_cards(self, company_ids, period='last_complete_day', date_from=None, date_to=None):
        companies = self._baseer_executive_allowed()
        _validate_company_ids(company_ids, companies.ids)
        now = fields.Datetime.to_datetime(fields.Datetime.now())
        selected = _resolve_period(period, date_from, date_to, now)
        cards = []
        for identifier in company_ids:
            company = companies.filtered(lambda item: item.id == identifier)
            cards.append(self._baseer_executive_scope(identifier)._baseer_executive_card(company, selected, now))
        return {'cards': cards, 'period': selected}

    @api.readonly
    def get_baseer_executive_sessions(self, company_id, period='last_complete_day', date_from=None, date_to=None, page=1):
        companies = self._baseer_executive_allowed()
        _validate_company_ids([company_id], companies.ids)
        if type(page) is not int or page < 1:
            raise ValidationError(_('Choose a valid session page.'))
        now = fields.Datetime.to_datetime(fields.Datetime.now())
        selected = _resolve_period(period, date_from, date_to, now)
        scoped = self._baseer_executive_scope(company_id)
        if (companies.filtered(lambda item: item.id == company_id).currency_id.name != 'SAR'
                or not scoped._baseer_executive_currency_supported(selected, now)):
            raise ValidationError(_('This command center supports SAR companies only.'))
        scoped._baseer_executive_capacity(selected, now)
        result = scoped._baseer_executive_session_page(selected, now, page)
        result['period'] = selected
        return result

    def _baseer_executive_change(self, current, previous, available):
        result = self._baseer_comparison(current, previous, available)
        result['amount_display'] = '—'
        if result['available']:
            delta = money(Decimal(current['value']) - Decimal(previous['value']))
            result['amount_display'] = ('+' if delta > ZERO else '') + _display(delta)
        return result

    def _baseer_executive_source(self):
        """Intersect both POS models' actual record rules; never trust client scope."""
        sessions = self.env['pos.session']._search([('company_id', '=', self.env.company.id)])
        return [('company_id', '=', self.env.company.id), ('state', 'in', POS_STATES),
                ('session_id.company_id', '=', self.env.company.id),
                ('session_id', 'in', sessions)]

    def _baseer_executive_domain(self, period, now):
        source = self._baseer_executive_source()
        if self.env['pos.order'].search_count(source + [
                ('session_id.start_at', '=', False), ('date_order', '<=', now)], limit=1):
            raise ValidationError(_('A confirmed POS order has no session opening time; its operating day cannot be determined.'))
        first, last = date.fromisoformat(period['from']), date.fromisoformat(period['to'])
        return source + [('session_id.start_at', '>=', _utc_at(first, 0)),
                         ('session_id.start_at', '<', _utc_at(last + timedelta(days=1), 0)),
                         ('session_id.start_at', '<=', now), ('date_order', '<=', now)]

    def _baseer_executive_capacity(self, period, now):
        domain = self._baseer_executive_domain(period, now)
        if self.env['pos.order'].search_count(domain, limit=MAX_ORDERS + 1) > MAX_ORDERS:
            raise ValidationError(_('This period exceeds 100,000 POS orders. Choose a shorter period; no records have been omitted.'))

    def _baseer_executive_currency_supported(self, period, now):
        """A SAR company can have a foreign-currency POS journal/configuration.

        Inspect the same visible session-day source before summing anything.
        Refuse the whole card rather than silently drop or convert those orders.
        """
        domain = self._baseer_executive_domain(period, now) + [
            ('config_id.currency_id', '!=', self.env.ref('base.SAR').id)]
        return not self.env['pos.order'].search_count(domain, limit=1)

    def _baseer_executive_query(self, period, now):
        return self.env['pos.order']._search(self._baseer_executive_domain(period, now))

    def _baseer_executive_session_stamp(self):
        self.env['pos.session'].flush_model(['start_at', 'state'])
        return SQL('(SELECT s.start_at FROM pos_session s WHERE s.id = %s)',
                   SQL.identifier('pos_order', 'session_id'))

    def _baseer_executive_open_session(self):
        self.env['pos.session'].flush_model(['state'])
        return SQL("(SELECT s.state != 'closed' FROM pos_session s WHERE s.id = %s)",
                   SQL.identifier('pos_order', 'session_id'))

    def _baseer_executive_amount(self):
        orders = self.env['pos.order']
        # Odoo's PostgreSQL numeric decoder returns float. Serialize the exact
        # SQL decimal result as text before it reaches that decoder.
        return SQL('CAST(COALESCE(SUM(CAST(%s AS NUMERIC)), 0) AS TEXT)',
                   SQL.identifier(orders._table, 'amount_total', to_flush=orders._fields['amount_total']))

    def _baseer_executive_days(self, period, now):
        query = self._baseer_executive_query(period, now)
        stamp = self._baseer_executive_session_stamp()
        business_day = SQL("CAST(%s AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Riyadh' AS DATE)", stamp)
        query.groupby = business_day
        return {day: {'sales': Decimal(total), 'count': count, 'status': 'current' if opened else 'complete'}
                for day, total, count, opened in self.env.execute_query(query.select(
                    business_day, self._baseer_executive_amount(), SQL('COUNT(*)'),
                    SQL('BOOL_OR(%s)', self._baseer_executive_open_session())))}

    def _baseer_executive_session_page(self, period, now, page=1):
        query = self._baseer_executive_query(period, now)
        session = SQL.identifier('pos_order', 'session_id')
        total = self.env.execute_query(query.select(SQL('COUNT(DISTINCT %s)', session)))[0][0]
        if type(page) is not int or page < 1 or page > max(1, (total + SESSION_PAGE_SIZE - 1) // SESSION_PAGE_SIZE):
            raise ValidationError(_('Choose a valid session page.'))
        query.groupby = session
        query.order = session
        query.limit = SESSION_PAGE_SIZE
        query.offset = (page - 1) * SESSION_PAGE_SIZE
        grouped = self.env.execute_query(query.select(session, self._baseer_executive_amount(), SQL('COUNT(*)')))
        sessions = self.env['pos.session'].browse([row[0] for row in grouped])
        sessions.check_access('read')
        by_id = {item.id: item for item in sessions}
        rows = [{'session_id': identifier, 'name': report_name(by_id[identifier].name, self.env.lang),
                 'pos_name': report_name(by_id[identifier].config_id.name, self.env.lang),
                 'opening_day': by_id[identifier].start_at.replace(tzinfo=timezone.utc).astimezone(RIYADH).date().isoformat(),
                 'state': by_id[identifier].state, 'order_count': count, 'sales': _card(amount)}
                for identifier, amount, count in grouped]
        return {'rows': rows, 'total': total, 'page': page, 'page_size': SESSION_PAGE_SIZE,
                'has_next': page * SESSION_PAGE_SIZE < total}

    def _baseer_executive_latest(self, now):
        orders = self.env['pos.order']
        query = orders._search(self._baseer_executive_source() + [('date_order', '<=', now)])
        stamp = SQL.identifier(orders._table, 'date_order', to_flush=orders._fields['date_order'])
        latest = self.env.execute_query(query.select(SQL('MAX(%s)', stamp)))[0][0]
        return latest.replace(tzinfo=timezone.utc).astimezone(RIYADH).strftime('%Y-%m-%d %H:%M:%S') if latest else None

    def _baseer_executive_card(self, company, period, now):
        if company.currency_id.name != 'SAR' or not self._baseer_executive_currency_supported(period, now):
            empty = _card(None, False)
            return {'company': {'id': company.id, 'name': report_name(company.name, self.env.lang),
                                'currency': company.currency_id.name},
                    'available': False, 'reason': 'unsupported_currency', 'date': period['to'],
                    'period': dict(period), 'daily': dict(empty), 'total': dict(empty),
                    'daily_change': self._baseer_executive_change(empty, empty, False),
                    'order_count': 0, 'session_count': 0, 'timeline': [],
                    'sessions': {'rows': [], 'total': 0, 'page': 1,
                                 'page_size': SESSION_PAGE_SIZE, 'has_next': False},
                    'outside_hours': {'count': 0, 'total': dict(empty)}, 'latest_sale_at': None}
        self._baseer_executive_capacity(period, now)
        days = self._baseer_executive_days(period, now)
        first, last = date.fromisoformat(period['from']), date.fromisoformat(period['to'])
        total = sum((item['sales'] for item in days.values()), ZERO)
        order_count = sum(item['count'] for item in days.values())
        daily = days.get(last, {'sales': ZERO, 'count': 0})
        card_period = dict(period, status='current' if any(item['status'] == 'current' for item in days.values()) else 'complete')
        empty = _card(None, False)
        unavailable_change = self._baseer_executive_change(empty, empty, False)
        prior = days.get(last - timedelta(days=1))
        if daily.get('status') == 'complete' and daily['count'] and prior is None:
            previous = dict(period, **{'from': (last - timedelta(days=1)).isoformat(),
                                      'to': (last - timedelta(days=1)).isoformat()})
            if self._baseer_executive_currency_supported(previous, now):
                self._baseer_executive_capacity(previous, now)
                prior = self._baseer_executive_days(previous, now).get(last - timedelta(days=1))
        change = self._baseer_executive_change(_card(daily['sales']), _card(prior['sales']), True) \
            if daily.get('status') == 'complete' and daily['count'] and prior and prior['count'] and prior['status'] == 'complete' else unavailable_change
        chart_start = max(first, last - timedelta(days=13))
        chart = []
        day = chart_start
        peak = max((abs(item['sales']) for day, item in days.items() if chart_start <= day <= last), default=ZERO)
        while day <= last:
            item = days.get(day, {'sales': ZERO, 'count': 0})
            value = _card(item['sales'])
            chart.append({'date': day.isoformat(), 'label': str(day.day),
                          'status': item['status'] if item['count'] else 'no_orders',
                          'value': value['value'], 'display': value['display'],
                          'change': dict(unavailable_change), 'order_count': item['count'],
                          'bar_height': str(money(abs(item['sales']) / peak * Decimal(100))) if peak else '0.00'})
            day += timedelta(days=1)
        sessions = self._baseer_executive_session_page(period, now)
        return {'company': {'id': company.id, 'name': report_name(company.name, self.env.lang),
                            'currency': company.currency_id.name},
                'available': True, 'reason': None if order_count else 'no_sales',
                'date': last.isoformat(), 'period': card_period, 'daily': _card(daily['sales']),
                'daily_change': change, 'total': _card(total), 'order_count': order_count,
                'session_count': sessions['total'], 'timeline': chart, 'sessions': sessions,
                'outside_hours': {'count': 0, 'total': _card(ZERO)},
                'latest_sale_at': self._baseer_executive_latest(now)}
