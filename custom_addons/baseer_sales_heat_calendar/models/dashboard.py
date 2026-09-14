import calendar
from datetime import date, timedelta
from decimal import Decimal

from odoo import _, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.addons.baseer_pos_summary.models.common import active_company, money
from .occasion import HEAT_CALENDAR_MANAGER_GROUP


ZERO = Decimal('0.00')
MAX_HEAT_DAYS = 366
BASELINE_WEEKS = 8
BASELINE_MINIMUM = 3


def _money_display(value):
    return f'{money(value):,.2f}' if value is not None else '—'


def _integer_display(value):
    return f'{int(value):,}' if value is not None else '—'


def _median(values):
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return money((ordered[middle - 1] + ordered[middle]) / Decimal('2'))


class SalesHeatCalendarDashboard(models.Model):
    _inherit = 'spreadsheet.dashboard'

    baseer_dashboard_kind = fields.Selection(
        selection_add=[('sales_heat_calendar', 'Heat calendar')],
        # The base dashboard field has no default.  Cascading removes only
        # dashboards of this added type if this isolated add-on is uninstalled.
        ondelete={'sales_heat_calendar': 'cascade'},
    )

    def _heat_month_bounds(self, raw_month):
        if raw_month in (None, False):
            current = fields.Date.context_today(self.with_context(tz='Asia/Riyadh'))
            return current.replace(day=1), current.replace(day=calendar.monthrange(current.year, current.month)[1])
        if not isinstance(raw_month, str) or len(raw_month) != 7:
            raise ValidationError(_('Choose a valid calendar month.'))
        try:
            year, month = (int(part) for part in raw_month.split('-', 1))
            first = date(year, month, 1)
        except (TypeError, ValueError):
            raise ValidationError(_('Choose a valid calendar month.')) from None
        return first, first.replace(day=calendar.monthrange(first.year, first.month)[1])

    def _heat_target_for_day(self, targets, business_date):
        candidates = [target for target in targets if target.year in (0, business_date.year)
                      and target.month in (0, business_date.month)
                      and target.weekday in (-1, business_date.weekday())]
        if not candidates:
            return None

        def specificity(target):
            return ((target.year == business_date.year) * 4
                    + (target.month == business_date.month) * 2
                    + (target.weekday == business_date.weekday()))
        return max(candidates, key=lambda target: (specificity(target), target.id))

    def _heat_occasions(self, company, first, last):
        Occasion = self.env['baseer.official.occasion']
        Occasion.check_access('read')
        records = Occasion.search([
            ('active', '=', True),
            ('status', '!=', 'cancelled'),
            ('date_from', '<=', last),
            ('date_to', '>=', first),
            '|', ('company_ids', '=', False), ('company_ids', 'in', [company.id]),
        ])
        by_day = {}
        arabic = (self.env.lang or '').lower().startswith('ar')
        for record in records:
            cursor = max(first, record.date_from)
            end = min(last, record.date_to)
            while cursor <= end:
                by_day.setdefault(cursor, []).append({
                    'name': record.name if arabic else record.name_en,
                    'code': record.code,
                    'occasion_type': record.occasion_type,
                    'kind_label': (_('Official holiday') if record.occasion_type == 'official_holiday'
                                   else _('Occasion')),
                    'status': record.status,
                    'source_label': record.source_label,
                    'source_url': record.source_url if (record.source_url or '').startswith('https://') else False,
                })
                cursor += timedelta(days=1)
        return by_day

    def _heat_day_breakdowns(self, company, first, last):
        """Detail only approved daily-summary source records, never invoices."""
        Summary = self.env['baseer.pos.summary']
        records = Summary.search([
            ('company_id', '=', company.id), ('state', '=', 'approved'),
            ('business_date', '>=', first), ('business_date', '<=', last),
        ], order='business_date, period_scope, id')
        period_labels = dict(Summary._fields['period_scope']._description_selection(self.env))
        by_day = {}
        for record in records:
            by_day.setdefault(record.business_date, []).append({
                'period': period_labels.get(record.period_scope, record.period_scope),
                'configuration': record.config_id.display_name,
                'sales_display': _money_display(money(Decimal(str(record.amount_gross)))),
                'customers_display': _integer_display(record.customer_count),
            })
        return by_day

    def _heat_grid(self, first, rows):
        by_date = {row['business_date']: row for row in rows}
        # Saudi business week starts on Saturday.  Python Monday=0, Saturday=5.
        offset = (first.weekday() - 5) % 7
        cells = [None] * offset + [by_date[first + timedelta(days=index)] for index in range(len(rows))]
        cells += [None] * ((7 - len(cells) % 7) % 7)
        return [cells[index:index + 7] for index in range(0, len(cells), 7)]

    def get_baseer_heat_calendar(self, month=None):
        """Return a month of heat data without copying or changing sales data."""
        self.ensure_one()
        self.check_access('read')
        if self.baseer_dashboard_kind != 'sales_heat_calendar' or not self.is_published:
            raise AccessError(_('This heat calendar is not available.'))
        if not self.env.user.has_group('point_of_sale.group_pos_user') or (
                self.group_ids and not (self.group_ids & self.env.user.all_group_ids)):
            raise AccessError(_('You do not have access to this heat calendar.'))
        company = self.env.company
        if self.company_ids and company not in self.company_ids:
            raise AccessError(_('Switch to a company enabled for this heat calendar.'))
        active_company(self, company)
        first, last = self._heat_month_bounds(month)
        if (last - first).days + 1 > MAX_HEAT_DAYS:
            raise ValidationError(_('Choose a calendar range of at most 366 days.'))

        Report = self.env['baseer.pos.daily.report']
        Summary = self.env['baseer.pos.summary']
        Target = self.env['baseer.heat.calendar.target']
        Report.check_access('read')
        Summary.check_access('read')
        Target.check_access('read')

        # `date.min` accepts a valid ISO month such as 0001-01, but it cannot
        # be moved eight weeks backwards.  Keep that edge request a harmless
        # calendar with no historical baseline instead of leaking an internal
        # OverflowError through the RPC route.
        earliest_history = date.min + timedelta(weeks=BASELINE_WEEKS)
        history_first = (
            first - timedelta(weeks=BASELINE_WEEKS)
            if first >= earliest_history else date.min
        )
        all_rows = Report._aggregate_days(company, history_first, last)['days']
        month_rows = [row for row in all_rows if first <= row['business_date'] <= last]
        complete_rows = [row for row in month_rows if row['status'] == 'complete']
        weekday_names = (
            (5, _('Saturday')), (6, _('Sunday')), (0, _('Monday')), (1, _('Tuesday')),
            (2, _('Wednesday')), (3, _('Thursday')), (4, _('Friday')),
        )
        weekday_sales = {weekday: [] for weekday, _name in weekday_names}
        for row in complete_rows:
            weekday_sales[row['business_date'].weekday()].append(
                money(Decimal(str(row['sales'])))
            )
        weekday_headers = []
        for weekday, name in weekday_names:
            sales = weekday_sales[weekday]
            average = money(sum(sales, ZERO) / Decimal(len(sales))) if sales else None
            weekday_headers.append({
                'name': name,
                'average_display': _money_display(average),
                'has_average': average is not None,
            })
        occasions_by_day = self._heat_occasions(company, history_first, last)
        breakdowns_by_day = self._heat_day_breakdowns(company, first, last)
        targets = Target.search([
            ('company_id', '=', company.id), ('active', '=', True),
            ('year', 'in', [0, first.year]), ('month', 'in', [0, first.month]),
        ])

        prepared = []
        for raw in month_rows:
            business_date = raw['business_date']
            status = raw['status']
            sales = money(Decimal(str(raw['sales'])))
            customers = int(raw['customers'])
            target = self._heat_target_for_day(targets, business_date)
            candidates = []
            cursor = (
                business_date - timedelta(weeks=BASELINE_WEEKS)
                if business_date >= earliest_history else date.min
            )
            while cursor < business_date:
                candidate = next((row for row in all_rows if row['business_date'] == cursor), None)
                if (candidate and candidate['status'] == 'complete' and not candidate['closure_ids']
                        and not occasions_by_day.get(cursor) and cursor.weekday() == business_date.weekday()):
                    candidates.append(money(Decimal(str(candidate['sales']))))
                cursor += timedelta(days=1)
            baseline = _median(candidates) if len(candidates) >= BASELINE_MINIMUM else None
            basis = money(Decimal(str(target.target_amount))) if target else baseline
            basis_kind = 'target' if target else ('baseline' if baseline is not None else 'none')
            ratio = money(sales * Decimal('100') / basis) if status == 'complete' and basis and basis > ZERO else None
            if ratio is None:
                heat_level = 'neutral'
                heat_label = _('No performance evaluation')
            elif ratio < Decimal('80'):
                heat_level, heat_label = 'low', _('Below expectation')
            elif ratio < Decimal('100'):
                heat_level, heat_label = 'watch', _('Near expectation')
            elif ratio < Decimal('120'):
                heat_level, heat_label = 'good', _('On target')
            else:
                heat_level, heat_label = 'high', _('Above expectation')

            status_label = {
                'complete': _('Complete'),
                'incomplete': _('Incomplete'),
                'closed': _('Closed'),
                'missing': _('No entry'),
            }[status]
            partial_closure = status == 'complete' and bool(raw['closure_ids'])
            occasion_names = ', '.join(
                _('%(kind)s: %(name)s', kind=event['kind_label'], name=event['name'])
                for event in occasions_by_day.get(business_date, [])
            )
            source_action = self._baseer_source_action(company, business_date, business_date)
            aria = _('%(date)s: %(sales)s; %(customers)s customers; %(status)s',
                     date=business_date.strftime('%d/%m/%Y'), sales=_money_display(sales),
                     customers=_integer_display(customers), status=status_label)
            if occasion_names:
                aria += _('; occasion: %s', occasion_names)
            prepared.append({
                'business_date': business_date,
                'date': business_date.isoformat(),
                'day': business_date.day,
                'date_display': business_date.strftime('%d/%m/%Y'),
                'weekday': business_date.weekday(),
                'sales_display': _money_display(sales) if raw['has_sales'] else '—',
                'customers_display': _integer_display(customers) if raw['has_sales'] else '—',
                'status': status,
                'status_label': status_label,
                'partial_closure': partial_closure,
                'partial_closure_label': _('Partially closed') if partial_closure else '',
                'has_sales': bool(raw['has_sales']),
                'heat_level': heat_level if status == 'complete' else 'neutral',
                'heat_label': heat_label if status == 'complete' else status_label,
                'basis_kind': basis_kind,
                'basis_display': _money_display(basis),
                'baseline_sample_count': len(candidates),
                'ratio_display': f'{ratio:,.1f}%' if ratio is not None else '—',
                'occasions': occasions_by_day.get(business_date, []),
                'occasion_label': occasion_names,
                'shift_breakdown': breakdowns_by_day.get(business_date, []),
                'source_action': source_action if raw['has_sales'] else None,
                'aria_label': aria,
            })

        return {
            'company': {'id': company.id, 'name': company.name, 'currency': company.currency_id.name},
            # ``strftime('%Y')`` is not zero-padded for years below 1000 on
            # every supported platform.  Keep the RPC contract a strict
            # ``YYYY-MM`` value, so the browser can safely request it again.
            'month': f'{first.year:04d}-{first.month:02d}',
            'month_label': first.strftime('%m/%Y'),
            'weeks': self._heat_grid(first, prepared),
            'can_manage_occasions': (self.env.user.has_group('base.group_system')
                                      or self.env.user.has_group(HEAT_CALENDAR_MANAGER_GROUP)),
            'weekdays': weekday_headers,
            'labels': {
                'sales': _('Sales including VAT'),
                'customers': _('Recorded customers'),
                'basis_target': _('Daily target'),
                'basis_baseline': _('Reference median'),
                'basis_none': _('No target or reference'),
                'baseline_sample': _('Comparable days'),
                'weekday_average': _('Average'),
                'occasion': _('Occasion'),
                'shift': _('Shift'),
                'configuration': _('Sales configuration'),
                'estimated': _('Estimated'),
                'confirmed': _('Confirmed'),
            },
        }
