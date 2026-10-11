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


def _count_card(value, available=True):
    return {'value': value if available else None,
            'display': str(value) if available else '—', 'available': available}


def _averages(total, sale_count, customers, customer_available):
    return {'sale_order_count': sale_count,
            'customer_count': _count_card(customers, customer_available),
            'average_order': _card(Decimal(total) / Decimal(sale_count)) if sale_count else _card(None, False),
            'average_customer': _card(Decimal(total) / Decimal(customers))
                if customer_available and customers else _card(None, False)}


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
        # Cancellation statistics now read other states too. The same budget
        # must bound those visible orders, not only the financial sale subset.
        domain = [term for term in self._baseer_executive_domain(period, now)
                  if term != ('state', 'in', POS_STATES)]
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

    def _baseer_executive_visible_session_domain(self, period, now):
        first, last = date.fromisoformat(period['from']), date.fromisoformat(period['to'])
        return [('company_id', '=', self.env.company.id),
                ('start_at', '>=', _utc_at(first, 0)),
                ('start_at', '<', _utc_at(last + timedelta(days=1), 0)),
                ('start_at', '<=', now)]

    def _baseer_executive_metric_columns(self):
        orders = self.env['pos.order']
        amount = SQL.identifier(orders._table, 'amount_total', to_flush=orders._fields['amount_total'])
        # Negative totals are refunds even on installations without is_refund.
        sale = SQL('%s >= 0', amount)
        refund = orders._fields.get('is_refund')
        if refund and refund.store and refund.column_type:
            sale = SQL('%s AND NOT COALESCE(%s, FALSE)', sale,
                       SQL.identifier(orders._table, 'is_refund', to_flush=refund))
        customer = orders._fields.get('customer_count')
        if customer and customer.store and customer.column_type:
            number = SQL.identifier(orders._table, 'customer_count', to_flush=customer)
            return (SQL('COUNT(*) FILTER (WHERE %s)', sale),
                    SQL('CAST(COALESCE(SUM(%s) FILTER (WHERE %s AND %s > 0), 0) AS TEXT)', number, sale, number),
                    SQL('COUNT(*) FILTER (WHERE %s AND COALESCE(%s, 0) <= 0)', sale, number), True)
        return SQL('COUNT(*) FILTER (WHERE %s)', sale), SQL("'0'"), SQL('COUNT(*) FILTER (WHERE %s)', sale), False

    def _baseer_executive_group_metrics(self, period, now, group):
        query = self._baseer_executive_query(period, now)
        query.groupby = group
        sale_count, customers, missing, supported = self._baseer_executive_metric_columns()
        return {key: {'sales': Decimal(total), 'count': count,
                      'sale_count': sales, 'customers': int(Decimal(customer_total)),
                      'customer_available': supported and not absent,
                      'status': 'current' if opened else 'complete'}
                for key, total, count, sales, customer_total, absent, opened in self.env.execute_query(query.select(
                    group, self._baseer_executive_amount(), SQL('COUNT(*)'), sale_count, customers, missing,
                    SQL('BOOL_OR(%s)', self._baseer_executive_open_session())))}

    def _baseer_executive_empty_metrics(self):
        return {'sales': ZERO, 'count': 0, 'sale_count': 0, 'customers': 0,
                'customer_available': self._baseer_executive_metric_columns()[3],
                'session_count': 0, 'status': 'no_orders'}

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
        stamp = self._baseer_executive_session_stamp()
        business_day = SQL("CAST(%s AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Riyadh' AS DATE)", stamp)
        result = self._baseer_executive_group_metrics(period, now, business_day)
        sessions = self.env['pos.session']
        query = sessions._search(self._baseer_executive_visible_session_domain(period, now))
        session_day = SQL("CAST(%s AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Riyadh' AS DATE)",
                          SQL.identifier(sessions._table, 'start_at', to_flush=sessions._fields['start_at']))
        query.groupby = session_day
        state = SQL.identifier(sessions._table, 'state', to_flush=sessions._fields['state'])
        for day, count, opened in self.env.execute_query(query.select(session_day, SQL('COUNT(*)'), SQL("BOOL_OR(%s != 'closed')", state))):
            item = result.setdefault(day, self._baseer_executive_empty_metrics())
            item.update(session_count=count, status='current' if opened else 'complete')
        return result

    def _baseer_executive_audit_counts(self, model_name, sessions, orders):
        if model_name not in self.env.registry:
            return None
        model = self.env[model_name]
        try:
            model.check_access('read')
            query = model._search([('company_id', '=', self.env.company.id),
                                   ('session_id', 'in', sessions.ids), ('order_id', 'in', orders)])
            session = SQL.identifier(model._table, 'session_id', to_flush=model._fields['session_id'])
            query.groupby = session
            return dict(self.env.execute_query(query.select(session, SQL('COUNT(*)'))))
        except AccessError:
            return None

    def _baseer_executive_session_page(self, period, now, page=1):
        session_model = self.env['pos.session']
        domain = self._baseer_executive_visible_session_domain(period, now)
        total = session_model.search_count(domain)
        if type(page) is not int or page < 1 or page > max(1, (total + SESSION_PAGE_SIZE - 1) // SESSION_PAGE_SIZE):
            raise ValidationError(_('Choose a valid session page.'))
        sessions = session_model.search(domain, order='start_at desc, id desc',
                                       limit=SESSION_PAGE_SIZE, offset=(page - 1) * SESSION_PAGE_SIZE)
        sessions.check_access('read')
        session = SQL.identifier('pos_order', 'session_id')
        grouped = self._baseer_executive_group_metrics(period, now, session)
        order_domain = [('company_id', '=', self.env.company.id),
                        ('session_id.company_id', '=', self.env.company.id),
                        ('session_id', 'in', sessions.ids), ('date_order', '<=', now)]
        visible_orders = self.env['pos.order']._search(order_domain)
        cancelled_query = self.env['pos.order']._search(order_domain + [('state', '=', 'cancel')])
        cancelled_query.groupby = session
        cancelled = dict(self.env.execute_query(cancelled_query.select(session, SQL('COUNT(*)'))))
        item_cancellations = self._baseer_executive_audit_counts('baseer.pos.protected_item_cancellation', sessions, visible_orders)
        substitutions = self._baseer_executive_audit_counts('baseer.pos.substitution', sessions, visible_orders)
        rows = []
        for item in sessions:
            metrics = grouped.get(item.id, self._baseer_executive_empty_metrics())
            rows.append({'session_id': item.id, 'name': report_name(item.name, self.env.lang),
                         'pos_name': report_name(item.config_id.name, self.env.lang),
                         'opening_day': item.start_at.replace(tzinfo=timezone.utc).astimezone(RIYADH).date().isoformat(),
                         'state': item.state, 'order_count': metrics['count'], 'sales': _card(metrics['sales']),
                         **_averages(metrics['sales'], metrics['sale_count'], metrics['customers'], metrics['customer_available']),
                         'cancelled_orders': cancelled.get(item.id, 0),
                         'item_cancellations': _count_card(item_cancellations.get(item.id, 0) if item_cancellations is not None else 0, item_cancellations is not None),
                         'substitutions': _count_card(substitutions.get(item.id, 0) if substitutions is not None else 0, substitutions is not None)})
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
                    'order_count': 0, 'session_count': 0, 'timeline': [], 'days': [],
                    **_averages(ZERO, 0, 0, False),
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
        # Session rows and optional audit models are fetched only when a day is
        # expanded. Card totals come from the complete bounded day projection.
        session_total = sum(item.get('session_count', 0) for item in days.values())
        sessions = {'rows': [], 'total': session_total, 'page': 1,
                    'page_size': SESSION_PAGE_SIZE, 'has_next': False}
        complete_days = []
        day = first
        while day <= last:
            item = days.get(day, self._baseer_executive_empty_metrics())
            complete_days.append({'date': day.isoformat(), 'sales': _card(item['sales']),
                                  'order_count': item['count'], 'session_count': item.get('session_count', 0),
                                  'status': item['status'],
                                  **_averages(item['sales'], item['sale_count'], item['customers'], item['customer_available'])})
            day += timedelta(days=1)
        complete_days.reverse()
        summary = _averages(total, sum(item['sale_count'] for item in days.values()),
                            sum(item['customers'] for item in days.values()),
                            self._baseer_executive_metric_columns()[3]
                            and all(item['customer_available'] for item in days.values()))
        return {'company': {'id': company.id, 'name': report_name(company.name, self.env.lang),
                            'currency': company.currency_id.name},
                'available': True, 'reason': None if order_count else 'no_sales',
                'date': last.isoformat(), 'period': card_period, 'daily': _card(daily['sales']),
                'daily_change': change, 'total': _card(total), 'order_count': order_count,
                'session_count': session_total, 'timeline': chart, 'sessions': sessions,
                'days': complete_days, **summary,
                'outside_hours': {'count': 0, 'total': _card(ZERO)},
                'latest_sale_at': self._baseer_executive_latest(now)}
