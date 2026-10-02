import json
import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP

import pytz

from odoo import _, api, fields, models, tools
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import SQL

from .report_query import REPORT_QUERY


class CancellationFollowupReport(models.Model):
    _name = 'baseer.pos.cancellation.report'
    _description = 'Baseer POS Cancellation Follow-up'
    _auto = False
    _order = 'event_at desc, id desc'

    company_id = fields.Many2one('res.company', readonly=True)
    order_id = fields.Many2one('pos.order', readonly=True)
    order_identity = fields.Integer(readonly=True)
    order_reference = fields.Char(readonly=True)
    pos_config_id = fields.Many2one('pos.config', readonly=True)
    session_id = fields.Many2one('pos.session', readonly=True)
    cashier_id = fields.Many2one('res.users', readonly=True)
    event_at = fields.Datetime(readonly=True)
    event_type = fields.Selection([
        ('substitution', 'Substitution'), ('item_cancel', 'Item cancellation'),
        ('order_cancel', 'Order cancellation'), ('quantity_reduce', 'Quantity reduction'),
    ], readonly=True)
    source_model = fields.Char(readonly=True)
    source_record_id = fields.Integer(readonly=True)
    operation_key = fields.Char(readonly=True)
    source_name = fields.Char(readonly=True)
    replacement_names = fields.Char(readonly=True)
    quantity = fields.Float(readonly=True)
    gross_amount = fields.Monetary(readonly=True, currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', readonly=True)
    reason_code = fields.Char(readonly=True)
    reason_note = fields.Char(readonly=True)
    same_order_review = fields.Boolean(readonly=True)
    replacement_cancelled = fields.Boolean(readonly=True)
    sequence_uncertain = fields.Boolean(readonly=True)
    data_gap = fields.Boolean(readonly=True)
    prior_substitution_id = fields.Many2one('baseer.pos.substitution', readonly=True)
    prior_substitution_at = fields.Datetime(readonly=True)
    prior_source_name = fields.Char(readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(SQL('CREATE VIEW %s AS %s', SQL.identifier(self._table), SQL(REPORT_QUERY)))

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError(_('This report is read-only.'))

    def write(self, vals):
        raise AccessError(_('This report is read-only.'))

    def unlink(self):
        raise AccessError(_('This report is read-only.'))

    def _assert_report_access(self):
        if not (self.env.user.has_group('point_of_sale.group_pos_manager')
                or self.env.user.has_group('base.group_system')):
            raise AccessError(_('Only a POS manager can view this report.'))
        self.check_access('read')

    @staticmethod
    def _number(value, decimals=0):
        value = Decimal(str(value or 0)).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
        return format(value, f'.{decimals}f')

    def _clock(self, value):
        if not isinstance(value, str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', value):
            raise ValidationError(_('Enter a valid shift time (HH:mm).'))
        return int(value[:2]) * 60 + int(value[3:])

    def _integer(self, value, default, minimum, maximum):
        if value is False or value is None or value == '':
            return default
        if isinstance(value, bool) or not isinstance(value, (int, str)) or not re.fullmatch(r'[0-9]+', str(value)):
            raise ValidationError(_('The report filter is invalid.'))
        parsed = int(value)
        if not minimum <= parsed <= maximum:
            raise ValidationError(_('The report filter is invalid.'))
        return parsed

    def _normalize_filters(self, raw):
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ValidationError(_('The report filter is invalid.'))
        zone_name = self.env.context.get('tz') or self.env.user.tz or 'Asia/Riyadh'
        try:
            zone = pytz.timezone(zone_name)
        except (pytz.UnknownTimeZoneError, AttributeError):
            raise ValidationError(_('The report timezone is invalid.')) from None
        today = datetime.now(zone).date()
        preset = raw.get('preset', 'today')
        try:
            for key in ('day', 'month'):
                if key in raw and raw[key] is not None and raw[key] is not False and not isinstance(raw[key], str):
                    raise ValueError()
            selected_day = date.fromisoformat(raw.get('day') or today.isoformat())
            month = raw.get('month') or today.strftime('%Y-%m')
            if not isinstance(month, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}', month):
                raise ValueError()
            first_month = date.fromisoformat(month + '-01')
            if preset == 'today':
                start = datetime.combine(today, time.min)
                end = start + timedelta(days=1)
            elif preset == 'day':
                start = datetime.combine(selected_day, time.min)
                end = start + timedelta(days=1)
            elif preset == 'month':
                start = datetime.combine(first_month, time.min)
                end = datetime(first_month.year + (first_month.month == 12), first_month.month % 12 + 1, 1)
            elif preset == 'custom':
                if any(not isinstance(raw.get(key), str)
                       or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}', raw[key])
                       for key in ('date_from', 'date_to')):
                    raise ValueError()
                start, end = [datetime.fromisoformat(raw[key]) for key in ('date_from', 'date_to')]
            else:
                raise ValueError()
            if not start < end or end - start > timedelta(days=366):
                raise ValueError()
            utc_start, utc_end = [zone.localize(value, is_dst=None).astimezone(pytz.UTC).replace(tzinfo=None)
                                  for value in (start, end)]
        except (ValueError, TypeError, OverflowError, pytz.InvalidTimeError):
            raise ValidationError(_('Choose a valid period of up to 366 days.')) from None
        morning, evening = raw.get('morning_start', '06:00'), raw.get('evening_start', '18:00')
        m, e = self._clock(morning), self._clock(evening)
        if m == e:
            raise ValidationError(_('Morning and evening must start at different times.'))
        shift, event_type = raw.get('shift', 'all'), raw.get('event_type', 'all')
        if shift not in ('all', 'morning', 'evening') or event_type not in (
                'all', 'substitution', 'item_cancel', 'order_cancel', 'quantity_reduce'):
            raise ValidationError(_('The report filter is invalid.'))
        review_only = raw.get('review_only', False)
        if not isinstance(review_only, bool):
            raise ValidationError(_('The report filter is invalid.'))
        normalized = dict(
            preset=preset, day=selected_day.isoformat(), month=month,
            date_from=start.strftime('%Y-%m-%dT%H:%M'), date_to=end.strftime('%Y-%m-%dT%H:%M'),
            timezone=zone_name, morning_start=morning, evening_start=evening,
            shift=shift, event_type=event_type, review_only=review_only,
            pos_config_id=self._integer(raw.get('pos_config_id'), False, 1, 2147483647),
            cashier_id=self._integer(raw.get('cashier_id'), False, 1, 2147483647),
            offset=self._integer(raw.get('offset'), 0, 0, 10000000),
            limit=self._integer(raw.get('limit'), 50, 1, 100),
            group_offset=self._integer(raw.get('group_offset'), 0, 0, 10000000),
            group_limit=self._integer(raw.get('group_limit'), 50, 1, 100),
        )
        return normalized, utc_start, utc_end, m, e, zone

    def _report_domain(self, normalized, start, end):
        domain = [('company_id', 'in', self.env.companies.ids), ('event_at', '>=', start), ('event_at', '<', end)]
        for name in ('pos_config_id', 'cashier_id'):
            if normalized[name]:
                domain.append((name, '=', normalized[name]))
        if normalized['event_type'] != 'all':
            domain.append(('event_type', '=', normalized['event_type']))
        if normalized['review_only']:
            domain += ['|', '|', ('same_order_review', '=', True), ('sequence_uncertain', '=', True), ('data_gap', '=', True)]
        return domain

    def _scoped_query(self, domain, filters, morning, evening):
        # ORM supplies ACL and record-rule WHERE conditions before any aggregation.
        query = self._search(domain)
        minute = SQL('(extract(hour FROM local_time)::int * 60 + extract(minute FROM local_time)::int)')
        clock_condition = SQL('%s >= %s AND %s < %s', minute, morning, minute, evening) if morning < evening else SQL(
            '(%s >= %s OR %s < %s)', minute, morning, minute, evening)
        localized = SQL('SELECT e.*, timezone(%s, e.event_at AT TIME ZONE %s) AS local_time FROM (%s) e',
                        filters['timezone'], 'UTC', query.select(SQL('%s.*', SQL.identifier(self._table))))
        shifted = SQL("SELECT e.*, CASE WHEN %s THEN 'morning' ELSE 'evening' END AS shift FROM (%s) e",
                      clock_condition, localized)
        if filters['shift'] == 'all':
            return shifted
        return SQL('SELECT * FROM (%s) e WHERE shift = %s', shifted, filters['shift'])

    def _rows(self, statement):
        self.env.cr.execute(statement)
        return self.env.cr.dictfetchall()

    def _names(self, model, ids):
        return {record.id: record.display_name for record in self.env[model].browse(sorted(set(ids))).exists()}

    def _report_data(self, scoped, offset, limit, group_offset=0, group_limit=50):
        # Evaluate the permission-filtered audit projection once per request.
        # JSON text preserves exact numeric values through Decimal decoding.
        result = self._rows(SQL("""
            WITH scoped AS MATERIALIZED (%s), summary AS (
                SELECT count(*) AS details, count(DISTINCT operation_key) AS operations,
                    count(DISTINCT operation_key) FILTER (WHERE event_type='substitution') AS substitutions,
                    count(DISTINCT operation_key) FILTER (WHERE event_type IN ('item_cancel','order_cancel')) AS cancellations,
                    count(DISTINCT operation_key) FILTER (WHERE event_type='quantity_reduce') AS reductions,
                    count(DISTINCT (company_id,order_identity)) FILTER (WHERE same_order_review) AS review_orders,
                    count(DISTINCT operation_key) FILTER (WHERE replacement_cancelled) AS replacement_cancellations,
                    count(*) FILTER (WHERE data_gap) AS gaps,
                    sum(quantity) FILTER (WHERE event_type='substitution') AS substituted_quantity,
                    sum(quantity) FILTER (WHERE event_type IN ('item_cancel','order_cancel')) AS cancelled_quantity
                FROM scoped
            ), session_groups AS (
                SELECT local_time::date::text AS date, company_id, pos_config_id, session_id,
                    max(event_at) AS latest_event_at, count(*) AS detail_count,
                    count(DISTINCT operation_key) AS operations,
                    count(DISTINCT operation_key) FILTER (WHERE event_type='substitution') AS substitutions,
                    count(DISTINCT operation_key) FILTER (WHERE event_type IN ('item_cancel','order_cancel')) AS cancellations,
                    count(DISTINCT operation_key) FILTER (WHERE event_type='quantity_reduce') AS reductions
                FROM scoped GROUP BY local_time::date,company_id,pos_config_id,session_id
            ), session_metric_base AS MATERIALIZED (
                SELECT local_time::date::text AS date,company_id,pos_config_id,session_id,
                    CASE WHEN event_type='substitution' THEN 'substitution'
                         WHEN event_type='quantity_reduce' THEN 'reduction' ELSE 'cancellation' END AS key,
                    count(DISTINCT operation_key) AS operations,sum(quantity) AS quantity,
                    count(*) FILTER (WHERE quantity IS NULL) AS quantity_missing,
                    count(*) FILTER (WHERE gross_amount IS NULL OR currency_id IS NULL) AS missing_amounts
                FROM scoped GROUP BY 1,2,3,4,5
            ), session_amount_base AS MATERIALIZED (
                SELECT local_time::date::text AS date,company_id,pos_config_id,session_id,
                    CASE WHEN event_type='substitution' THEN 'substitution'
                         WHEN event_type='quantity_reduce' THEN 'reduction' ELSE 'cancellation' END AS key,
                    currency_id,sum(gross_amount) AS amount,count(*) AS known_rows
                FROM scoped WHERE gross_amount IS NOT NULL AND currency_id IS NOT NULL
                GROUP BY 1,2,3,4,5,6
            ), session_summary AS (SELECT count(*) AS total FROM session_groups)
            SELECT to_json(session_summary.total)::text AS group_total,
                (SELECT COALESCE(json_agg(r),'[]')::text FROM (
                    SELECT g.*,(SELECT COALESCE(json_agg(m),'[]') FROM (
                        SELECT b.key,b.operations,b.quantity,b.quantity_missing,b.missing_amounts,
                            (SELECT COALESCE(json_agg(a),'[]') FROM (
                                SELECT a.currency_id,a.amount,a.known_rows FROM session_amount_base a
                                WHERE a.date=b.date AND a.company_id=b.company_id AND a.key=b.key
                                    AND a.pos_config_id IS NOT DISTINCT FROM b.pos_config_id
                                    AND a.session_id IS NOT DISTINCT FROM b.session_id
                                ORDER BY a.currency_id
                            ) a) AS amounts
                        FROM session_metric_base b
                        WHERE b.date=g.date AND b.company_id=g.company_id
                            AND b.pos_config_id IS NOT DISTINCT FROM g.pos_config_id
                            AND b.session_id IS NOT DISTINCT FROM g.session_id
                    ) m) AS raw_metrics FROM session_groups g
                    ORDER BY date DESC,latest_event_at DESC,company_id,pos_config_id NULLS LAST,session_id NULLS LAST
                    LIMIT %s OFFSET CASE WHEN %s >= session_summary.total
                        THEN greatest(0,(session_summary.total-1)/%s*%s) ELSE %s END
                ) r) AS session_groups,
                row_to_json(summary)::text AS summary,
                (SELECT COALESCE(json_agg(r),'[]')::text FROM (
                    SELECT COALESCE(reason_code,'') AS key,count(DISTINCT operation_key) AS count
                    FROM scoped WHERE event_type IN ('item_cancel','order_cancel')
                    GROUP BY COALESCE(reason_code,'') ORDER BY count DESC,key
                ) r) AS reasons,
                (SELECT COALESCE(json_agg(r),'[]')::text FROM (
                    SELECT shift AS key,count(DISTINCT operation_key) AS count
                    FROM scoped GROUP BY shift ORDER BY shift
                ) r) AS shifts,
                (SELECT COALESCE(json_agg(r),'[]')::text FROM (
                    SELECT local_time::date::text AS key,count(DISTINCT operation_key) AS count,
                        count(DISTINCT operation_key) FILTER (WHERE event_type='substitution') AS substitutions,
                        count(DISTINCT operation_key) FILTER (WHERE event_type IN ('item_cancel','order_cancel')) AS cancellations
                    FROM scoped GROUP BY local_time::date ORDER BY local_time::date
                ) r) AS timeline,
                (SELECT COALESCE(json_agg(r),'[]')::text FROM (
                    SELECT grouping(cashier_id) AS by_register,
                        CASE WHEN grouping(cashier_id)=0 THEN cashier_id ELSE pos_config_id END AS key,
                        count(DISTINCT operation_key) FILTER (WHERE event_type='substitution') AS substitutions,
                        count(DISTINCT operation_key) FILTER (WHERE event_type IN ('item_cancel','order_cancel')) AS cancellations,
                        count(DISTINCT (company_id,order_identity)) FILTER (WHERE same_order_review) AS reviews
                    FROM scoped GROUP BY GROUPING SETS ((cashier_id),(pos_config_id))
                    ORDER BY by_register,key NULLS LAST
                ) r) AS groups,
                (SELECT COALESCE(json_agg(r),'[]')::text FROM (
                    SELECT * FROM scoped ORDER BY event_at DESC,id DESC LIMIT %s OFFSET
                        CASE WHEN %s >= summary.details
                            THEN greatest(0, (summary.details-1)/%s*%s) ELSE %s END
                ) r) AS details
            FROM summary CROSS JOIN session_summary
        """, scoped, group_limit, group_offset, group_limit, group_limit, group_offset,
            limit, offset, limit, limit, offset))[0]
        return self._decode_data(result)

    @staticmethod
    def _decode_data(result):
        data = {key: json.loads(value, parse_float=Decimal) for key, value in result.items()}
        for row in data['details']:
            for name in ('event_at', 'local_time', 'prior_substitution_at'):
                if row[name]:
                    row[name] = datetime.fromisoformat(row[name])
        return data

    @api.model
    def get_report(self, filters=None):
        self._assert_report_access()
        normalized, start, end, morning, evening, zone = self._normalize_filters(filters)
        scoped = self._scoped_query(self._report_domain(normalized, start, end), normalized, morning, evening)
        data = self._report_data(scoped, normalized['offset'], normalized['limit'],
                                 normalized['group_offset'], normalized['group_limit'])
        summary = data['summary']
        number = self._number
        def percentage(value, total):
            return number(Decimal(value or 0) * 100 / Decimal(total or 1), 2)
        operations = summary['operations']
        kpis = [
            dict(key='substitutions', label=_('Substitution operations'), value=number(summary['substitutions']),
                 note=_('%s%% of documented operations') % percentage(summary['substitutions'], operations)),
            dict(key='cancellations', label=_('Cancellation operations'), value=number(summary['cancellations']),
                 note=_('%s%% of documented operations') % percentage(summary['cancellations'], operations)),
            dict(key='reductions', label=_('Quantity reduction operations'), value=number(summary['reductions']), note=_('Separate from complete item cancellations')),
            dict(key='review_orders', label=_('Orders to review'), value=number(summary['review_orders']), note=_('Substitution followed by cancellation in the same order')),
            dict(key='replacement_cancellations', label=_('Replacement cancellation operations'), value=number(summary['replacement_cancellations']), note=_('Matched by recorded replacement line identifier')),
            dict(key='substituted_quantity', label=_('Substituted item quantity'), value=number(summary['substituted_quantity'], 2), note=_('Recorded POS units across products')),
            dict(key='cancelled_quantity', label=_('Cancelled item quantity'), value=number(summary['cancelled_quantity'], 2), note=_('Known quantities only; incomplete snapshots are excluded')),
        ]
        reasons = data['reasons']
        reason_labels = self._reason_labels()
        for row in reasons:
            row.update(label=reason_labels.get(row['key'], _('Reason not recorded')),
                       percentage=percentage(row['count'], summary['cancellations']),
                       bar_width=percentage(row['count'], summary['cancellations']), count=number(row['count']))
        shifts = data['shifts']
        for row in shifts:
            row.update(label=_('Morning') if row['key'] == 'morning' else _('Evening'),
                       percentage=percentage(row['count'], operations), bar_width=percentage(row['count'], operations), count=number(row['count']))
        timeline = data['timeline']
        maximum = max((row['count'] for row in timeline), default=1)
        for row in timeline:
            row.update(label=row['key'], bar_width=percentage(row['count'], maximum),
                       count=number(row['count']), substitutions=number(row['substitutions']), cancellations=number(row['cancellations']))
        groups = {}
        for by_register, model, key in [(0, 'res.users', 'cashiers'), (1, 'pos.config', 'registers')]:
            grouped = [row for row in data['groups'] if row['by_register'] == by_register]
            names = self._names(model, [row['key'] for row in grouped if row['key']])
            for row in grouped:
                row.update(key=row['key'] or 'unknown', label=names.get(row['key'], _('Not recorded')),
                           substitutions=number(row['substitutions']), cancellations=number(row['cancellations']), reviews=number(row['reviews']))
            groups[key] = [{name: value for name, value in row.items() if name != 'by_register'} for row in grouped]
        total = summary['details']
        offset, limit = normalized['offset'], normalized['limit']
        if offset >= total:
            offset = max(0, (total - 1) // limit * limit)
            normalized['offset'] = offset
        details = self._format_details(data['details'], zone)
        session_days, group_pagination = self._format_session_days(data, normalized)
        # Options use only accessible audit rows in the active companies.
        option_rows = self._read_group([('company_id', 'in', self.env.companies.ids)], ['pos_config_id', 'cashier_id'])
        register_ids = {register.id for register, cashier in option_rows if register}
        cashier_ids = {cashier.id for register, cashier in option_rows if cashier}
        options = {
            'registers': [dict(id=key, name=name) for key, name in self._names('pos.config', register_ids).items()],
            'cashiers': [dict(id=key, name=name) for key, name in self._names('res.users', cashier_ids).items()],
        }
        return dict(
            filters=normalized, kpis=kpis, reasons=reasons, shifts=shifts, timeline=timeline,
            details=details, pagination=dict(offset=offset, limit=limit, total=total), options=options,
            session_days=session_days, group_pagination=group_pagination,
            coverage_note=_('Only stored audit events are covered. Ordinary unaudited deletions are not included. '
                            'Quantities are POS units. Session amounts cover only audit rows with a recorded amount and currency. '
                            'Cancellation reason percentages use '
                            'documented cancellation operations; an operation with multiple reasons can appear in several groups. '
                            'Source rows with incomplete data: %s.') % number(summary['gaps']),
            **groups,
        )

    def _reason_labels(self):
        return {
            'customer_cancelled': _('Customer cancelled'), 'wrong_order': _('Wrong order'),
            'duplicate_order': _('Duplicate order'), 'unavailable_item': _('Item unavailable'),
            'staff_error': _('Staff error'), 'other': _('Other'), '': _('Reason not recorded'),
        }

    def _format_details(self, details, zone):
        number = self._number
        reason_labels = self._reason_labels()
        cashier_names = self._names('res.users', [row['cashier_id'] for row in details if row['cashier_id']])
        register_names = self._names('pos.config', [row['pos_config_id'] for row in details if row['pos_config_id']])
        event_labels = {'substitution': _('Substitution'), 'item_cancel': _('Item cancellation'),
                        'order_cancel': _('Order cancellation'), 'quantity_reduce': _('Quantity reduction')}
        for row in details:
            review = []
            if row['replacement_cancelled']:
                review.append(_('Recorded replacement cancelled'))
            elif row['same_order_review']:
                review.append(_('Same-order cancellation after substitution'))
            if row['sequence_uncertain']:
                review.append(_('Equal timestamps: sequence uncertain'))
            if row['data_gap']:
                review.append(_('Incomplete source data'))
            reason = reason_labels.get(row['reason_code'], _('Reason not recorded'))
            row.update(
                event_at=row['local_time'].strftime('%Y-%m-%d %H:%M:%S'),
                event_label=event_labels[row['event_type']],
                cashier_name=cashier_names.get(row['cashier_id'], _('Not recorded')),
                pos_name=register_names.get(row['pos_config_id'], _('Not recorded')),
                source_name=row['source_name'] or _('Not recorded'), replacement_names=row['replacement_names'] or '',
                quantity=number(row['quantity'], 2) if row['quantity'] is not None else _('Not recorded'),
                reason=(reason + ': ' + row['reason_note']) if row['reason_note'] else reason,
                review_label=' · '.join(review), review_context='',
            )
            if row['prior_substitution_at']:
                local_prior = pytz.UTC.localize(row['prior_substitution_at']).astimezone(zone)
                row['review_context'] = _('Prior substitution: %s · %s') % (
                    local_prior.strftime('%Y-%m-%d %H:%M:%S'), row['prior_source_name'] or _('Not recorded'))
            # JSON-RPC must not carry raw datetime/numeric values from SQL.
            row.pop('local_time', None)
            row.pop('prior_substitution_at', None)
            row.pop('gross_amount', None)
        return details

    @staticmethod
    def _page_offset(offset, limit, total):
        return max(0, (total - 1) // limit * limit) if offset >= total else offset

    def _format_session_days(self, data, normalized):
        rows = data['session_groups']
        session_names = self._names('pos.session', [row['session_id'] for row in rows if row['session_id']])
        register_names = self._names('pos.config', [row['pos_config_id'] for row in rows if row['pos_config_id']])
        currency_ids = {amount['currency_id'] for row in rows for metric in row['raw_metrics']
                        for amount in metric['amounts']}
        currencies = self.env['res.currency'].with_context(active_test=False).search([('id', 'in', sorted(currency_ids))])
        currency_names = {currency.id: currency.name for currency in currencies}
        days = {}
        for row in rows:
            row.pop('latest_event_at', None)
            row['session_id'] = row['session_id'] or False
            row['pos_config_id'] = row['pos_config_id'] or False
            row['key'] = '%s:%s:%s:%s' % (
                row['date'], row['company_id'], row['pos_config_id'] or 'unknown', row['session_id'] or 'unknown')
            session_name = (session_names.get(row['session_id']) or '').strip()
            row['session_name'] = (
                (session_name if session_name and session_name != '/' else _('Session %s') % self._number(row['session_id']))
                if row['session_id'] else _('Session not recorded')
            )
            row['pos_name'] = register_names.get(row['pos_config_id'], _('Not recorded'))
            row['metrics'] = self._format_session_metrics(row.pop('raw_metrics'), currency_names)
            for name in ('operations', 'substitutions', 'cancellations', 'reductions'):
                row[name] = self._number(row[name])
            day = days.setdefault(row['date'], dict(key=row['date'], date=row['date'], groups=[]))
            day['groups'].append(row)
        total, limit = data['group_total'], normalized['group_limit']
        offset = self._page_offset(normalized['group_offset'], limit, total)
        normalized['group_offset'] = offset
        return list(days.values()), dict(offset=offset, limit=limit, total=total)

    def _format_session_metrics(self, raw_metrics, currency_names):
        by_key = {metric['key']: metric for metric in raw_metrics}
        metrics = []
        for key in ('substitution', 'cancellation', 'reduction'):
            raw = by_key.get(key, {})
            operations = raw.get('operations', 0)
            quantity_missing = raw.get('quantity_missing', 0)
            missing_amounts = raw.get('missing_amounts', 0)
            amounts = []
            for amount in raw.get('amounts', []):
                currency = currency_names.get(amount['currency_id'])
                if currency:
                    amounts.append(dict(currency_id=amount['currency_id'], currency=currency,
                                        amount=self._number(amount['amount'], 2)))
                else:
                    # A recorded numeric value without an accessible currency is incomplete evidence.
                    missing_amounts += amount['known_rows']
            amounts.sort(key=lambda amount: (amount['currency'], amount['currency_id']))
            quantity = raw.get('quantity')
            metrics.append(dict(
                key=key, operations=self._number(operations), has_operations=bool(operations),
                quantity=(_('Not recorded') if quantity is None and operations else self._number(quantity, 2)),
                quantity_missing=self._number(quantity_missing), has_quantity_missing=bool(quantity_missing),
                amounts=amounts, missing_amounts=self._number(missing_amounts), has_missing_amounts=bool(missing_amounts),
            ))
        return metrics

    def _validate_session_group(self, group):
        if not isinstance(group, dict):
            raise ValidationError(_('The report session group is invalid.'))
        day = group.get('date')
        try:
            if not isinstance(day, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', day):
                raise ValueError()
            date.fromisoformat(day)
        except (ValueError, TypeError):
            raise ValidationError(_('The report session group is invalid.')) from None
        result = dict(date=day)
        for name in ('company_id', 'pos_config_id', 'session_id'):
            value = group.get(name)
            if value is False and name != 'company_id':
                result[name] = False
            elif type(value) is int and 1 <= value <= 2147483647:
                result[name] = value
            else:
                raise ValidationError(_('The report session group is invalid.'))
        if result['company_id'] not in self.env.companies.ids:
            raise AccessError(_('The report session company is not accessible.'))
        return result

    @api.model
    def get_session_details(self, filters, group, offset=0, limit=50):
        self._assert_report_access()
        selected = self._validate_session_group(group)
        normalized, start, end, morning, evening, zone = self._normalize_filters(filters)
        offset = self._integer(offset, 0, 0, 10000000)
        limit = self._integer(limit, 50, 1, 100)
        domain = self._report_domain(normalized, start, end)
        domain += [(name, '=', selected[name]) for name in ('company_id', 'pos_config_id', 'session_id')]
        scoped = self._scoped_query(domain, normalized, morning, evening)
        scoped = SQL('SELECT * FROM (%s) e WHERE local_time::date = %s::date', scoped, selected['date'])
        result = self._rows(SQL("""
            WITH scoped AS MATERIALIZED (%s), summary AS (SELECT count(*) AS total FROM scoped)
            SELECT row_to_json(summary)::text AS summary,
                (SELECT COALESCE(json_agg(r),'[]')::text FROM (
                    SELECT * FROM scoped ORDER BY event_at DESC,id DESC LIMIT %s OFFSET
                        CASE WHEN %s >= summary.total
                            THEN greatest(0,(summary.total-1)/%s*%s) ELSE %s END
                ) r) AS details
            FROM summary
        """, scoped, limit, offset, limit, limit, offset))[0]
        data = self._decode_data(result)
        total = data['summary']['total']
        offset = self._page_offset(offset, limit, total)
        return dict(details=self._format_details(data['details'], zone),
                    pagination=dict(offset=offset, limit=limit, total=total))
