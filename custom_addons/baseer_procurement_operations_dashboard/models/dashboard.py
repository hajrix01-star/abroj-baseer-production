"""Read-only operational measures for the procurement-request workflow."""
from datetime import date, datetime, time, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import SQL


MAX_PERIOD_DAYS = 366
MAX_QUEUE_ROWS = 20
MAX_DIMENSION_ROWS = 6
RIYADH = pytz.timezone('Asia/Riyadh')
PENDING_STATES = ('draft', 'sent', 'received')
VISIBLE_STATES = ('draft', 'sent', 'received', 'purchased')


def _day_bounds(first, last):
    """Return UTC-naive storage bounds for Riyadh calendar dates."""
    start = RIYADH.localize(datetime.combine(first, time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
    end = RIYADH.localize(datetime.combine(last + timedelta(days=1), time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
    return start, end


class ProcurementOperationsDashboard(models.Model):
    _inherit = 'spreadsheet.dashboard'

    baseer_dashboard_kind = fields.Selection(
        selection_add=[('procurement_operations', 'Procurement operations')],
        ondelete={'procurement_operations': 'cascade'},
    )

    def _baseer_procurement_period(self, raw):
        """Accept only bounded values emitted by the native dashboard picker."""
        today = fields.Date.context_today(self.with_context(tz='Asia/Riyadh'))
        if raw in (None, False):
            return today - timedelta(days=89), today
        if not isinstance(raw, dict):
            raise ValidationError(_('Choose a valid dashboard date filter.'))
        kind = raw.get('type')
        try:
            if kind == 'range' and set(raw) == {'type', 'from', 'to'}:
                first, last = fields.Date.to_date(raw['from']), fields.Date.to_date(raw['to'])
            elif kind == 'relative' and set(raw) == {'type', 'period'}:
                period = raw['period']
                lengths = {
                    'today': 1, 'yesterday': 1, 'last_7_days': 7,
                    'last_30_days': 30, 'last_90_days': 90,
                }
                if period in lengths:
                    last = today - timedelta(days=1) if period == 'yesterday' else today
                    first = last - timedelta(days=lengths[period] - 1)
                elif period == 'month_to_date':
                    first, last = today.replace(day=1), today
                elif period == 'last_month':
                    first = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
                    last = today.replace(day=1) - timedelta(days=1)
                elif period == 'year_to_date':
                    first, last = today.replace(month=1, day=1), today
                else:
                    raise ValueError
            elif kind == 'month' and set(raw) == {'type', 'month', 'year'}:
                first = date(int(raw['year']), int(raw['month']), 1)
                next_month = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
                last = next_month - timedelta(days=1)
            elif kind == 'quarter' and set(raw) == {'type', 'quarter', 'year'}:
                first = date(int(raw['year']), (int(raw['quarter']) - 1) * 3 + 1, 1)
                next_quarter = date(first.year + (first.month + 2) // 12, ((first.month + 2) % 12) + 1, 1)
                last = next_quarter - timedelta(days=1)
            elif kind == 'year' and set(raw) == {'type', 'year'}:
                first, last = date(int(raw['year']), 1, 1), date(int(raw['year']), 12, 31)
            else:
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            raise ValidationError(_('Choose a valid dashboard date filter.')) from None
        if not first or not last or first > last or (last - first).days + 1 > MAX_PERIOD_DAYS:
            raise ValidationError(_('Choose a date range of at most 366 days.'))
        return first, last

    def _baseer_procurement_assert_access(self):
        self.ensure_one()
        self.check_access('read')
        self.check_access_rule('read')
        if self.baseer_dashboard_kind != 'procurement_operations' or not self.is_published:
            raise AccessError(_('This procurement operations dashboard is not available.'))
        if self.company_ids and self.env.company not in self.company_ids:
            raise AccessError(_('This dashboard is not available for the active company.'))
        user = self.env.user
        authorized = user.has_group('baseer_procurement_requests.group_procurement_manager') or user.has_group(
            'baseer_procurement_requests.group_procurement_cashier'
        )
        if not authorized or (self.group_ids and not (self.group_ids & user.all_group_ids)):
            raise AccessError(_('Procurement manager or cashier access is required.'))
        self.env['baseer.procurement.request'].check_access('read')

    def _baseer_procurement_domain(self, first, last, date_field):
        start, end = _day_bounds(first, last)
        return [
            ('company_id', '=', self.env.company.id),
            (date_field, '>=', fields.Datetime.to_string(start)),
            (date_field, '<', fields.Datetime.to_string(end)),
        ]

    @staticmethod
    def _read_group_counts(Request, domain, field):
        rows = Request.formatted_read_group(domain, [field], ['__count'])
        return {row.get(field): row.get('__count', 0) for row in rows}

    def _baseer_procurement_timeline(self, Request, domain, date_column, states=False):
        """Use the ACL/record-rule constrained ORM query as the SQL source."""
        query = Request._search(domain)
        Request.flush_model(['request_date', 'actual_confirmed_at', 'state'])
        columns = "COUNT(*)"
        if states:
            columns = ", ".join([
                "COUNT(*) FILTER (WHERE state = 'draft')",
                "COUNT(*) FILTER (WHERE state = 'sent')",
                "COUNT(*) FILTER (WHERE state = 'received')",
                "COUNT(*) FILTER (WHERE state = 'purchased')",
            ])
        local_day = "(%s AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Riyadh')::date" % date_column
        self.env.cr.execute(SQL("""
            SELECT %s, %s
              FROM baseer_procurement_request
             WHERE id IN (%s)
             GROUP BY %s
             ORDER BY %s
             LIMIT %s
        """ % (local_day, columns, '%s', local_day, local_day, MAX_PERIOD_DAYS), query.select()))
        rows = []
        for row in self.env.cr.fetchall():
            day = row[0]
            item = {'key': day.isoformat(), 'label': day.isoformat(), 'count': int(row[1])}
            if states:
                item['states'] = dict(zip(VISIBLE_STATES, (int(value) for value in row[1:])))
            rows.append(item)
        return rows

    def _baseer_procurement_dimensions(self, Request, domain):
        route_labels = dict(Request._fields['purchase_route']._description_selection(self.env))
        routes = self._read_group_counts(Request, domain, 'purchase_route')
        route_rows = [
            {'key': key, 'label': route_labels.get(key, key), 'count': int(value)}
            for key, value in routes.items() if key
        ]
        route_rows.sort(key=lambda row: (-row['count'], row['label'].casefold()))

        warehouse_rows = []
        for row in Request.formatted_read_group(domain, ['warehouse_id'], ['__count']):
            warehouse = row.get('warehouse_id')
            key, label = (warehouse if isinstance(warehouse, tuple) else (False, _('No warehouse')))
            warehouse_rows.append({'key': key or False, 'label': label or _('No warehouse'), 'count': int(row.get('__count', 0))})
        warehouse_rows.sort(key=lambda row: (-row['count'], row['label'].casefold(), row['key'] or 0))
        if len(warehouse_rows) > MAX_DIMENSION_ROWS:
            other = sum(row['count'] for row in warehouse_rows[MAX_DIMENSION_ROWS:])
            warehouse_rows = warehouse_rows[:MAX_DIMENSION_ROWS] + [{'key': 'other', 'label': _('Other'), 'count': other}]
        return {'routes': route_rows, 'warehouses': warehouse_rows}

    def _baseer_procurement_queue(self, Request, cohort_domain):
        records = Request.search(cohort_domain + [('state', 'in', PENDING_STATES)], order='request_date asc, id asc', limit=MAX_QUEUE_ROWS)
        labels = dict(Request._fields['state']._description_selection(self.env))
        rows = []
        for record in records:
            rows.append({
                'id': record.id,
                'name': record.name,
                'state': record.state,
                'state_label': labels.get(record.state, record.state),
                'request_date': fields.Datetime.to_string(record.request_date),
                'warehouse': record.warehouse_id.display_name or '',
            })
        return rows

    @api.readonly
    def get_baseer_procurement_operations_metrics(self, filters=None):
        """Return bounded operational aggregates; never read financial documents."""
        self._baseer_procurement_assert_access()
        if filters is not None and (not isinstance(filters, dict) or set(filters) != {'native'}):
            raise ValidationError(_('Choose valid dashboard filters.'))
        first, last = self._baseer_procurement_period((filters or {}).get('native'))
        Request = self.env['baseer.procurement.request']
        cohort_domain = self._baseer_procurement_domain(first, last, 'request_date') + [('state', 'in', VISIBLE_STATES)]
        counts = self._read_group_counts(Request, cohort_domain, 'state')
        # An operational alert only: it neither changes the request nor asserts
        # any supplier, invoice, payment, or accounting delay.
        overdue_before, _unused = _day_bounds(
            fields.Date.context_today(self.with_context(tz='Asia/Riyadh')) - timedelta(days=3),
            fields.Date.context_today(self.with_context(tz='Asia/Riyadh')) - timedelta(days=3),
        )
        aged_pending = Request.search_count([
            ('company_id', '=', self.env.company.id), ('state', 'in', PENDING_STATES),
            ('request_date', '<', fields.Datetime.to_string(overdue_before)),
        ])
        completed_domain = self._baseer_procurement_domain(first, last, 'actual_confirmed_at') + [('state', '=', 'purchased')]
        source_action = {
            'type': 'ir.actions.act_window',
            'name': _('Procurement requests'),
            'res_model': 'baseer.procurement.request',
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': cohort_domain,
            'context': {'create': False, 'allowed_company_ids': [self.env.company.id]},
        }
        return {
            'company': {'id': self.env.company.id, 'name': self.env.company.name},
            'filters': {'date_from': first.isoformat(), 'date_to': last.isoformat()},
            'cards': {
                'total': {'value': sum(int(counts.get(state, 0)) for state in VISIBLE_STATES), 'display': f"{sum(int(counts.get(state, 0)) for state in VISIBLE_STATES):,}"},
                **{state: {'value': int(counts.get(state, 0)), 'display': f"{int(counts.get(state, 0)):,}"} for state in VISIBLE_STATES},
                'aged_pending': {'value': aged_pending, 'display': f"{aged_pending:,}"},
            },
            'cohort_timeline': self._baseer_procurement_timeline(Request, cohort_domain, 'request_date', states=True),
            'completion_timeline': self._baseer_procurement_timeline(Request, completed_domain, 'actual_confirmed_at'),
            'dimensions': self._baseer_procurement_dimensions(Request, cohort_domain),
            'pending_queue': self._baseer_procurement_queue(Request, cohort_domain),
            'source_action': source_action,
        }
