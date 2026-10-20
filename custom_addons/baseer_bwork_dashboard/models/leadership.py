"""Read-only C1 bridge over the existing financial authorities.

Only amounts and daily aggregates leave this boundary. There is no business or
target mutation, arbitrary model/action entry point, or report sudo here.
"""
from datetime import date, timedelta
from decimal import Decimal

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.fields import Domain

from ..contracts import (
    MAX_COMPANIES, MAX_SOURCE_ROWS, ZERO, amount, change, merge_ranges,
    month_end, month_start, ratio,
)

REPORTS = {
    'sales': ('baseer_sales_dashboard.dashboard_sales_summary', 'sales_summary'),
    'heat': ('baseer_sales_heat_calendar.dashboard_sales_heat_calendar', 'sales_heat_calendar'),
    'spending': ('baseer_purchase_expense_dashboard.dashboard_supplier_bills', 'supplier_bills'),
}


class LeadershipService(models.AbstractModel):
    _inherit = 'baseer.bwork.service'

    @api.model
    def _v2_bootstrap(self):
        result = super()._v2_bootstrap()
        result['capabilities']['leadership_version'] = 1
        return result

    def _leadership_user(self):
        user = self._require_user()
        if not user._bwork_effective_permissions().get('dashboard_view'):
            raise AccessError(self.env._('BWork dashboard access is not enabled.'))
        return user

    def _leadership_companies(self, company_id=None):
        user = self._leadership_user()
        companies = user.company_ids.sorted('id')
        if company_id is not None:
            companies = companies.filtered(lambda company: company.id == company_id)
            if not companies:
                raise AccessError(self.env._('This company is not authorized.'))
        if not companies or len(companies) > MAX_COMPANIES:
            raise ValidationError(self.env._('Select one company; all-company reporting supports at most 10 companies.'))
        companies.check_access('read')
        return companies

    def _leadership_reports(self, company):
        scoped = self.with_context({
            'allowed_company_ids': [company.id], 'lang': self.env.lang,
            'tz': 'Asia/Riyadh',
        })
        reports = {}
        for key, (xmlid, kind) in REPORTS.items():
            dashboard = scoped.env.ref(xmlid)
            dashboard.check_access('read')
            if (not dashboard.is_published or dashboard.baseer_dashboard_kind != kind
                    or (dashboard.company_ids and company not in dashboard.company_ids)
                    or (dashboard.group_ids and not (dashboard.group_ids & scoped.env.user.all_group_ids))):
                raise AccessError(self.env._('A required dashboard is not available for this company.'))
            reports[key] = dashboard
        if not scoped.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(self.env._('Point of Sale report access is required.'))
        reports['sales']._baseer_unified_access()
        reports['spending']._baseer_purchase_assert_access()
        for model in ('baseer.pos.daily.report', 'baseer.pos.closure',
                      'baseer.pos.summary.allocation', 'pos.payment',
                      'baseer.heat.calendar.target', 'baseer.official.occasion'):
            scoped.env[model].check_access('read')
        return scoped, reports

    @api.model
    def _leadership_options(self):
        user = self._require_user()
        if not user._bwork_effective_permissions().get('dashboard_view'):
            return {'api_version': 2, 'leadership_version': 1, 'can_view': False,
                    'companies': [], 'max_companies': MAX_COMPANIES}
        # Options preserve the complete native company scope; never shrink it
        # to companies that happen to have readable sources or goals.
        companies = user.company_ids.sorted('id')
        companies.check_access('read')
        for company in companies:
            self._leadership_reports(company)
        return {'api_version': 2, 'leadership_version': 1, 'can_view': True,
                'companies': self._leadership_company_rows(companies),
                'max_companies': MAX_COMPANIES}

    @staticmethod
    def _leadership_company_rows(companies):
        return [{'id': company.id, 'name': company.name} for company in companies]

    def _leadership_plan(self, selection, today):
        selected = (selection['first'], selection['last'])
        current_first = today.replace(day=1)
        previous_first = month_start(current_first, -1)
        # Same number of completed calendar dates in both months. Extra dates
        # in a longer current month cannot be compared with nonexistent dates.
        comparable_count = today.day - 1
        previous_count = min(comparable_count, month_end(previous_first).day)
        current_last = current_first + timedelta(days=comparable_count - 1)
        previous_last = previous_first + timedelta(days=previous_count - 1)
        current = (current_first, current_last) if comparable_count else None
        previous = (previous_first, previous_last) if previous_count else None
        monetary = [selected] + ([current, previous] if current else [])
        # Public canonical RPC reads its own preceding comparison period too.
        sales_ranges = list(monetary)
        for first, last in monetary:
            prior_last = first - timedelta(days=1)
            sales_ranges.append((prior_last - (last - first), prior_last))
        calendar_first = selection['calendar_first']
        heat_months = {calendar_first, month_start(calendar_first, -1),
                       current_first, previous_first}
        earliest = date.min + timedelta(weeks=8)
        for first in heat_months:
            sales_ranges.append((first - timedelta(weeks=8) if first >= earliest else date.min,
                                 month_end(first)))
        return {'selected': selected, 'current': current, 'previous': previous,
                'current_first': current_first, 'previous_first': previous_first,
                'comparable_count': comparable_count, 'equal_periods': comparable_count == previous_count,
                'heat_months': sorted(heat_months),
                'sales_ranges': merge_ranges(sales_ranges),
                'spending_ranges': merge_ranges(monetary)}

    def _leadership_preflight(self, per_company, plan):
        """One request budget across companies and disjoint interval unions.

        Invoice base domain deliberately counts a conservative superset before
        canonical reversal ancestry is traversed. Its own ancestry/payment and
        heat session guards remain additional fail-closed limits.
        """
        remaining = MAX_SOURCE_ROWS
        for company, scoped, reports in per_company:
            sales, spending = reports['sales'], reports['spending']
            ranges = plan['sales_ranges']
            domains = {
                'baseer.pos.summary': [[
                    ('company_id', '=', company.id),
                    ('business_date', '>=', first), ('business_date', '<=', last),
                ] for first, last in ranges],
                'baseer.pos.closure': [[
                    ('company_id', '=', company.id), ('date_from', '<=', last),
                    ('date_to', '>=', first),
                ] for first, last in ranges],
                'pos.order': [sales._baseer_unified_pos_domain(
                    company, first, last, include_bridges=True) for first, last in ranges],
                'account.move': [sales._baseer_unified_invoice_base_domain(
                    company, first, last) for first, last in ranges] + [
                    spending._baseer_purchase_domain(company, first, last)
                    for first, last in plan['spending_ranges']],
                'baseer.pos.summary.allocation': [[
                    ('company_id', '=', company.id),
                    ('summary_id.business_date', '>=', first),
                    ('summary_id.business_date', '<=', last),
                ] for first, last in ranges],
                'pos.payment': [
                    [('pos_order_id.' + field, operator, value) for field, operator, value
                     in sales._baseer_unified_pos_domain(company, first, last, include_bridges=True)]
                    for first, last in ranges],
            }
            for model, parts in domains.items():
                source = scoped.env[model]
                source.check_access('read')
                count = source.search_count(Domain.OR(parts), limit=remaining + 1)
                remaining -= count
                if remaining < 0:
                    raise ValidationError(self.env._(
                        'This dashboard exceeds 100,000 source rows across the requested companies and periods; no rows have been omitted.'))
        # All budget counts finish before any public report materializes data.
        for company, _scoped, reports in per_company:
            reports['sales']._baseer_check_capacity(company, plan['sales_ranges'])

    @staticmethod
    def _leadership_sales(dashboard, bounds):
        first, last = bounds
        result = dashboard.get_baseer_sales_metrics(filters={'native': {
            'type': 'range', 'from': first.isoformat(), 'to': last.isoformat(),
        }})
        return Decimal(result['cards']['sales']['value'])

    @staticmethod
    def _leadership_spending(dashboard, company, bounds):
        first, last = bounds
        domain = dashboard._baseer_purchase_domain(company, first, last)
        return dashboard._baseer_purchase_totals(domain, company.currency_id)[0]

    def _leadership_calendar(self, month, heat_payloads, today, weekdays=False):
        """Aggregate money exactly; withhold evaluation for mixed coverage/goals."""
        company_days = [
            {row['date']: row for week in payload['weeks'] for row in week if row}
            for payload in heat_payloads
        ]
        rows = []
        cursor, last = month, month_end(month)
        while cursor <= last:
            key = cursor.isoformat()
            parts = [days[key] for days in company_days]
            complete = cursor < today and all(row['status'] == 'complete' for row in parts)
            known = any(row['has_sales'] for row in parts)
            sales = sum((Decimal(row['sales_value']) for row in parts
                         if row['sales_value'] is not None), ZERO) if known else None
            explicit = all(row['target_value'] is not None for row in parts)
            target = sum((Decimal(row['target_value']) for row in parts), ZERO) if explicit else None
            if len(parts) == 1:
                basis_kind = parts[0]['basis_kind']
                basis = Decimal(parts[0]['basis_value']) if parts[0]['basis_value'] is not None else None
            else:
                basis_kind, basis = ('target', target) if explicit else ('none', None)
            performance = ratio(sales, basis) if complete and sales is not None and basis and basis > ZERO else amount(None)
            value = Decimal(performance['value']) if performance['available'] else None
            heat = ('low' if value < 80 else 'watch' if value < 100 else
                    'good' if value < 120 else 'high') if value is not None else 'neutral'
            statuses = {row['status'] for row in parts}
            status = ('complete' if complete else next(iter(statuses))
                      if len(statuses) == 1 else 'incomplete')
            label = {'complete': self.env._('Complete'), 'incomplete': self.env._('Incomplete'),
                     'closed': self.env._('Closed'), 'missing': self.env._('No entry'),
                     'conflict': self.env._('Conflicting daily sources')}.get(status, self.env._('Incomplete'))
            coverage = self.env._('Complete in every requested company') if complete else self.env._('Missing or incomplete company coverage')
            if len(parts) == 1:
                coverage = parts[0]['status_label']
            rows.append({'date': key, 'day': cursor.day, 'weekday': cursor.weekday(),
                         'sales': amount(sales), 'status': status, 'status_label': label,
                         'has_sales': known, 'target': amount(target), 'basis': amount(basis),
                         'basis_kind': basis_kind, 'ratio': performance, 'heat_level': heat,
                         'coverage_label': coverage})
            cursor += timedelta(days=1)
        result = {'month': month.isoformat()[:7], 'label': month.strftime('%m/%Y'),
                  'week_start': 5, 'days': rows}
        if weekdays:
            names = [self.env._('Monday'), self.env._('Tuesday'), self.env._('Wednesday'),
                     self.env._('Thursday'), self.env._('Friday'), self.env._('Saturday'),
                     self.env._('Sunday')]
            result['weekdays'] = []
            for weekday, name in enumerate(names):
                samples = [Decimal(row['sales']['value']) for row in rows
                           if row['weekday'] == weekday and row['status'] == 'complete'
                           and row['sales']['available'] and Decimal(row['sales']['value']) > ZERO]
                result['weekdays'].append({'weekday': weekday, 'name': name,
                    'average': amount(sum(samples, ZERO) / Decimal(len(samples)) if samples else None),
                    'sample_count': len(samples)})
        return result

    @staticmethod
    def _leadership_observations(calendar_payload, bounds):
        if not bounds:
            return [], False
        first, last = bounds
        rows = [row for row in calendar_payload['days'] if first.isoformat() <= row['date'] <= last.isoformat()]
        samples = [Decimal(row['sales']['value']) for row in rows
                   if row['status'] == 'complete' and row['sales']['available']]
        return samples, len(samples) == (last - first).days + 1

    def _leadership_reconcile(self, calendars, bounds, headline):
        """Validate public headline against central heat; never substitute it.

        All recorded money counts, including current/future incomplete records.
        Missing sales contribute zero only to this identity, never to averages.
        """
        by_date = {row['date']: row for payload in calendars.values() for row in payload['days']}
        cursor, last = bounds
        total = ZERO
        while cursor <= last:
            row = by_date.get(cursor.isoformat())
            if row is None:
                raise ValidationError(self.env._('The central sales calendar does not cover the requested headline dates.'))
            if row['sales']['available']:
                total += Decimal(row['sales']['value'])
            cursor += timedelta(days=1)
        if total != headline:
            raise ValidationError(self.env._(
                'The central calendar and canonical sales headline disagree; the report is unavailable and no source data was changed.'))

    @api.model
    def _leadership(self, selection, as_of=None):
        companies = self._leadership_companies(selection['company_id'])
        as_of = fields.Datetime.to_datetime(as_of or fields.Datetime.now())
        today = fields.Date.context_today(self.with_context(tz='Asia/Riyadh'), timestamp=as_of)
        plan = self._leadership_plan(selection, today)
        per_company = []
        for company in companies:
            scoped, reports = self._leadership_reports(company)
            per_company.append((company, scoped, reports))
        self._leadership_preflight(per_company, plan)
        totals = {key: ZERO for key in ('sales', 'spending', 'current_sales',
                                      'current_spending', 'previous_sales', 'previous_spending')}
        heat = {month: [] for month in plan['heat_months']}
        for company, _scoped, reports in per_company:
            for prefix, bounds in (('', plan['selected']), ('current_', plan['current']),
                                   ('previous_', plan['previous'])):
                if bounds:
                    totals[prefix + 'sales'] += self._leadership_sales(reports['sales'], bounds)
                    totals[prefix + 'spending'] += self._leadership_spending(reports['spending'], company, bounds)
            for month in heat:
                heat[month].append(reports['heat'].get_baseer_heat_calendar(month=month.isoformat()[:7]))
        calendars = {month: self._leadership_calendar(month, values, today,
                        weekdays=month == selection['calendar_first']) for month, values in heat.items()}
        for prefix, bounds in (('', plan['selected']), ('current_', plan['current']),
                               ('previous_', plan['previous'])):
            if bounds:
                self._leadership_reconcile(calendars, bounds, totals[prefix + 'sales'])
        current_calendar = calendars[plan['current_first']]
        previous_calendar = calendars[plan['previous_first']]
        observations, complete = self._leadership_observations(current_calendar, plan['current'])
        previous_observations, previous_complete = self._leadership_observations(previous_calendar, plan['previous'])
        average = sum(observations, ZERO) / Decimal(len(observations)) if observations else None
        previous_average = sum(previous_observations, ZERO) / Decimal(len(previous_observations)) if previous_observations else None
        sales, spending = totals['sales'], totals['spending']
        difference = sales - spending
        current_sales, previous_sales = totals['current_sales'], totals['previous_sales']
        comparison_available = bool(plan['current'] and complete and previous_complete and plan['equal_periods'])
        first, last = plan['current'] or (plan['current_first'], plan['current_first'])
        prior_first, prior_last = plan['previous'] or (plan['previous_first'], plan['previous_first'])
        if plan['current']:
            comparison_label = self.env._(
                '%(first)s–%(last)s compared with %(prior_first)s–%(prior_last)s; completed dates only. Forecast is an estimate: complete-day mean × calendar days, minimum 7 complete days and no coverage gaps.',
                first=first.isoformat(), last=last.isoformat(), prior_first=prior_first.isoformat(), prior_last=prior_last.isoformat())
        else:
            comparison_label = self.env._('No completed dates in the current month; comparison and forecast unavailable.')
        if not plan['equal_periods']:
            comparison_label += ' ' + self.env._('Change unavailable: the previous month has fewer calendar dates.')
        current = {
            'month': plan['current_first'].isoformat()[:7], 'from': first.isoformat(), 'to': last.isoformat(),
            'sales': amount(current_sales if plan['current'] else None),
            'daily_average': amount(average),
            'forecast': amount(average * Decimal(month_end(today).day)
                               if complete and len(observations) >= 7 else None),
            'sales_change': change(current_sales, previous_sales, comparison_available),
            'spending_change': change(totals['current_spending'], totals['previous_spending'], comparison_available),
            'difference_change': change(current_sales - totals['current_spending'],
                                        previous_sales - totals['previous_spending'], comparison_available),
            'completed_days': len(observations), 'previous_sales': amount(previous_sales if plan['previous'] else None),
            'previous_daily_average': amount(previous_average), 'comparison_label': comparison_label,
        }
        return {
            'api_version': 2, 'leadership_version': 1, 'source': 'sales_summary',
            'companies': self._leadership_company_rows(companies), 'company_id': selection['company_id'],
            'currency': 'SAR', 'as_of': as_of.isoformat(timespec='seconds') + 'Z',
            'filters': {'month': selection['month'], 'period': selection['period'],
                        'from': selection['first'].isoformat(), 'to': selection['last'].isoformat()},
            'overview': {'sales': amount(sales), 'spending': amount(spending), 'difference': amount(difference),
                         'spending_ratio': ratio(spending, sales), 'difference_ratio': ratio(difference, sales),
                         'spending_scope': self.env._('Posted supplier bills less supplier credits, gross including VAT, company currency only. Sales less supplier bills is a difference, not profit or cash flow.'),
                         'current_month': current},
            'calendar': calendars[selection['calendar_first']],
            'previous_calendar': calendars[month_start(selection['calendar_first'], -1)],
        }
