"""Read-only executive cards; native POS daily reporting remains the authority."""
import calendar
from datetime import timedelta
from decimal import Decimal

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError
from odoo.addons.baseer_pos_summary.models.common import clean_context, money, ZERO
from .dashboard import _card, _display
from .report_names import report_name


def _validate_company_ids(company_ids, permitted):
    if (not isinstance(company_ids, list) or not 1 <= len(company_ids) <= 3
            or any(type(identifier) is not int or identifier <= 0 for identifier in company_ids)
            or len(set(company_ids)) != len(company_ids)):
        raise ValidationError(_('Choose between one and three distinct companies per request.'))
    if not set(company_ids).issubset(set(permitted)):
        raise AccessError(_('One or more selected companies are not available.'))


def _coverage(data):
    result = {key: data['totals'][key] for key in (
        'operating_days', 'closed_days', 'incomplete_days', 'missing_days')}
    result['days'] = len(data['days'])
    return result


def _covered(data):
    return bool(data['days']) and not (
        data['totals']['incomplete_days'] or data['totals']['missing_days'])


def _forecast(data, remaining_days, full_month_closed):
    totals = data['totals']
    available = _covered(data) and not full_month_closed and totals['operating_days'] > 0
    value = (totals['recorded_sales'] + totals['complete_sales']
             / Decimal(totals['operating_days']) * Decimal(remaining_days)) if available else None
    return _card(value, available)


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
            raise AccessError(_('Point of Sale access is required to view sales summaries.'))
        for name in ('baseer.pos.daily.report', 'baseer.pos.summary',
                     'baseer.pos.closure', 'baseer.pos.summary.allocation'):
            self.env[name].check_access('read')

    def _baseer_executive_allowed(self):
        # User assignments, never client-supplied allowed_company_ids, own this limit.
        assigned = self.env.user.company_ids
        scoped = self.with_context({'allowed_company_ids': assigned.ids, 'lang': self.env.lang, 'tz': 'Asia/Riyadh'})
        scoped._baseer_executive_access()
        companies = scoped.env['res.company'].search([('id', 'in', assigned.ids)], order='id')
        if scoped.company_ids:
            companies &= scoped.company_ids
        return companies

    @api.readonly
    def get_baseer_executive_companies(self):
        companies = self._baseer_executive_allowed()
        return {'companies': [{'id': company.id, 'name': report_name(company.display_name, self.env.lang),
                               'currency': company.currency_id.name} for company in companies],
                'user_id': self.env.uid, 'db': self.env.cr.dbname}

    @api.readonly
    def get_baseer_executive_cards(self, company_ids):
        companies = self._baseer_executive_allowed()
        _validate_company_ids(company_ids, companies.ids)
        cards = []
        # Validate the whole batch before reading any financial data.
        for identifier in company_ids:
            company = companies.filtered(lambda item: item.id == identifier)
            scoped = self.with_context({'allowed_company_ids': [identifier],
                                       'lang': self.env.lang, 'tz': 'Asia/Riyadh'})
            scoped._baseer_executive_access()
            if company.currency_id.name == 'SAR':
                scoped = clean_context(scoped, scoped.env['res.company'].browse(identifier))
            cards.append(scoped._baseer_executive_card(company))
        return {'cards': cards}

    def _baseer_executive_change(self, current, previous, available):
        result = self._baseer_comparison(current, previous, available)
        result['amount_display'] = '—'
        if result['available']:
            delta = money(Decimal(current['value']) - Decimal(previous['value']))
            result['amount_display'] = ('+' if delta > ZERO else '') + _display(delta)
        return result

    def _baseer_executive_card(self, company):
        empty = _card(None, False)
        unavailable_change = self._baseer_executive_change(empty, empty, False)
        result = {
            'company': {'id': company.id, 'name': report_name(company.display_name, self.env.lang), 'currency': company.currency_id.name},
            'available': False, 'reason': 'no_complete_day', 'date': None, 'daily': dict(empty),
            'daily_change': dict(unavailable_change), 'timeline': [],
            'month_to_date': dict(empty), 'daily_average': dict(empty),
            'customer_average': dict(empty), 'forecast': dict(empty),
            'period_change': dict(unavailable_change),
            'coverage': dict(operating_days=0, closed_days=0, incomplete_days=0, missing_days=0, days=0),
            'payments': {'rows': [], 'coverage': {'complete': False}}, 'previous_period': None,
        }
        # Native external summaries support SAR only. Do not fail other cards,
        # convert currencies, or imply that an unsupported company's sales are zero.
        if company.currency_id.name != 'SAR':
            result['reason'] = 'unsupported_currency'
            return result
        today = fields.Date.context_today(self.with_context(tz='Asia/Riyadh'))
        last = today - timedelta(days=1)
        first = last - timedelta(days=365)
        self._baseer_check_capacity(company, [(first, last)])
        history = self._baseer_aggregate_period(company, first, last)
        completed = [day for day in history['days'] if day['status'] == 'complete']
        if not completed:
            return result
        latest = completed[-1]
        cutoff = latest['business_date']
        month_first = cutoff.replace(day=1)
        month_last = cutoff.replace(day=calendar.monthrange(cutoff.year, cutoff.month)[1])
        previous_last = month_first - timedelta(days=1)
        previous_first = previous_last - (cutoff - month_first)
        chart_first = cutoff - timedelta(days=14)
        self._baseer_check_capacity(company, [(month_first, month_last), (first, last),
                                              (previous_first, previous_last), (chart_first, cutoff)])
        current = self._baseer_metrics(company, month_first, cutoff)
        previous = self._baseer_metrics(company, previous_first, previous_last)
        full_month = self._baseer_aggregate_period(company, month_first, month_last)
        chart = self._baseer_aggregate_period(company, chart_first, cutoff)['days']
        for prior, day in zip(chart, chart[1:]):
            # Keep prior days available for daily comparisons, not visible bars.
            if day['business_date'] < today.replace(day=1):
                continue
            value = _card(day['sales'], day['has_sales'])
            prior_value = _card(prior['sales'], prior['has_sales'])
            result['timeline'].append({
                'date': day['date_label'], 'label': str(day['business_date'].day),
                'status': day['status'], 'value': value['value'], 'display': value['display'],
                'change': self._baseer_executive_change(value, prior_value,
                    day['status'] == 'complete' and prior['status'] == 'complete'),
            })
        daily = _card(latest['sales'])
        prior = chart[-2]
        totals = current['data']['totals']
        result.update(
            available=True, reason=None, date=cutoff.isoformat(), daily=daily,
            daily_change=self._baseer_executive_change(daily, _card(prior['sales'], prior['has_sales']),
                                                      prior['status'] == 'complete'),
            month_to_date=current['cards']['sales'], daily_average=current['cards']['daily_sales'],
            customer_average=current['cards']['daily_customers'],
            forecast=_forecast(current['data'], (month_last - cutoff).days,
                               full_month['totals']['closed_days'] > 0),
            period_change=self._baseer_executive_change(current['cards']['sales'], previous['cards']['sales'],
                _covered(current['data']) and _covered(previous['data'])
                and current['has_sample'] and previous['has_sample']),
            coverage=_coverage(current['data']),
            payments=self._baseer_payment_performance(company, month_first, cutoff, totals['recorded_sales']),
            previous_period={'from': previous_first.isoformat(), 'to': previous_last.isoformat()},
        )
        return result
