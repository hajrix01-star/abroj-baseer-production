import calendar
from collections import defaultdict
from datetime import date, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from .service import SOURCES


def month_bounds(day, offset=0):
    index = day.year * 12 + day.month - 1 + offset
    year, month = divmod(index, 12)
    first = date(year, month + 1, 1)
    return first, first.replace(day=calendar.monthrange(year, month + 1)[1])


def year_to_date_months(end):
    return [month_bounds(date(end.year, month, 1)) for month in range(1, end.month + 1)]


def percent(value, base):
    return round(100 * value / base, 2) if base else None


def change(value, previous):
    # A base less than one sixth of the current magnitude produces an
    # uninformative change above 500%; treat it as too small to compare.
    return round((value - previous) / abs(previous) * 100, 2) if value is not None and previous and abs(value) <= 6 * abs(previous) else None


def low_salaries(current, history):
    return bool(len(history) == 3 and sum(history) > 0 and current < 0.7 * sum(history) / 3)


def incomplete_fixed_costs(partial, current, history):
    """A partial month needs at least half the mean fixed costs of three months."""
    return bool(partial and len(history) == 3 and sum(history) > 0 and current < sum(history) / 6)


class DashboardSections(models.AbstractModel):
    _inherit = 'baseer.dashboard2.service'

    def _purchases(self, ids, start, end, sales):
        settings = self.env['baseer.dashboard2.settings'].with_context(allowed_company_ids=ids).search([('company_id', 'in', ids)])
        if set(settings.mapped('company_id').ids) != set(ids) or any(not setting.food_purchase_account_ids for setting in settings):
            return {'available': False, 'value': None, 'pct': None}
        excluded = self._reset_move_ids(ids, end, start)
        excluded += self.env['res.company'].browse(ids).mapped('account_opening_move_id').ids
        value = 0.0
        for setting in settings:
            rows = self.env['account.move.line'].with_company(setting.company_id)._read_group([
                ('company_id', '=', setting.company_id.id), ('parent_state', '=', 'posted'),
                ('date', '>=', start), ('date', '<=', end),
                ('account_id', 'in', setting.food_purchase_account_ids.ids),
                ('move_id', 'not in', excluded), ('move_id.ref', '!=', 'Opening Entry')], [], ['balance:sum'])
            value += (rows[0][0] or 0) if rows else 0
        return {'available': True, 'value': round(value, 2), 'pct': percent(value, sales)}

    def _posted_months(self, ids, revenue_only=False):
        lines = self.env['account.move.line'].with_context(allowed_company_ids=ids).search([
            ('company_id', 'in', ids), ('parent_state', '=', 'posted'),
            ('account_id.account_type', 'in', ('income', 'income_other', 'expense', 'expense_depreciation', 'expense_direct_cost'))])
        reset_ids = set(self._reset_move_ids(ids, fields.Date.to_date('9999-12-31')))
        opening_ids = set(self.env['res.company'].browse(ids).mapped('account_opening_move_id').ids)
        return {line.date.strftime('%Y-%m') for line in lines if line.move_id.id not in reset_ids | opening_ids and line.move_id.ref != 'Opening Entry' and (not revenue_only or line.account_id.account_type in ('income', 'income_other'))}

    def _timeline(self, ids, end, mode):
        if mode not in ('monthly', 'yearly'):
            raise UserError(_('Invalid timeline mode.'))
        line_model = self.env['account.move.line'].with_context(allowed_company_ids=ids)
        bounds = line_model._read_group([('company_id', 'in', ids), ('parent_state', '=', 'posted')], [], ['date:min', 'date:max'])
        first_data, last = bounds[0] if bounds else (None, None)
        posted_months = self._posted_months(ids, revenue_only=True)
        def covered(first, finish):
            return any(first.strftime('%Y-%m') <= month <= finish.strftime('%Y-%m') for month in posted_months)
        cutoff = min(end, last) if last else None
        start_year = date(end.year, 1, 1)
        previous_end = cutoff.replace(year=cutoff.year - 1, day=min(cutoff.day, calendar.monthrange(cutoff.year - 1, cutoff.month)[1])) if cutoff else None
        ytd = self._accounting(ids, start_year, cutoff)['sales_net'] if cutoff and cutoff >= start_year else 0
        pytd = self._accounting(ids, date(end.year - 1, 1, 1), previous_end)['sales_net'] if previous_end and previous_end.year == end.year - 1 else None
        if previous_end and not covered(date(end.year - 1, 1, 1), previous_end):
            pytd = None
        months = []
        for m in range(1, 13):
            first, last_month = month_bounds(date(end.year, m, 1))
            prior_first, prior_last = month_bounds(date(end.year - 1, m, 1))
            months.append({'month': m, 'value': self._accounting(ids, first, min(last_month, cutoff))['sales_net'] if cutoff and first <= cutoff and covered(first, min(last_month, cutoff)) else None,
                           'partial': bool(cutoff and first <= cutoff < last_month),
                           'previous': self._accounting(ids, prior_first, min(prior_last, previous_end))['sales_net'] if previous_end and prior_first <= previous_end and covered(prior_first, min(prior_last, previous_end)) else None})
        years = []
        if mode == 'yearly':
            for year in range(end.year - 4, end.year + 1):
                first, last_year = date(year, 1, 1), date(year, 12, 31)
                prior_first, prior_last = date(year - 1, 1, 1), date(year - 1, 12, 31)
                prior_cutoff = min(prior_last, previous_end) if previous_end else None
                years.append({'year': year, 'value': self._accounting(ids, first, min(last_year, cutoff))['sales_net'] if cutoff and first <= cutoff and covered(first, min(last_year, cutoff)) else None, 'previous': self._accounting(ids, prior_first, prior_cutoff)['sales_net'] if prior_cutoff and prior_first <= prior_cutoff and covered(prior_first, prior_cutoff) else None, 'partial': bool(cutoff and year == cutoff.year and cutoff < last_year)})
        eligible = [m for m in months if m['value'] is not None]
        return {'available': True, 'mode': mode, 'months': months, 'years': years,
                'stats': {'end_date': str(cutoff) if cutoff else None, 'previous_end_date': str(previous_end) if previous_end else None, 'ytd': ytd, 'previous_ytd': pytd, 'growth_pct': change(ytd, pytd), 'best_month': max(eligible, key=lambda x: x['value']) if eligible else None}}

    def _compare(self, companies, start, end):
        result = []
        for cid, label, name in companies:
            data = self._accounting([cid], start, end)
            result.append({'key': str(cid), 'label': label, 'name': name, 'sales_net': data['sales_net'], 'targets': self._targets([cid], data), **data['ratios']})
        return result

    def _targets(self, ids, current):
        targets = {}
        model = self.env['baseer.dashboard2.target'].with_context(allowed_company_ids=ids)
        for key, value in current['ratios'].items():
            target = model.search([('company_id', '=', ids[0] if len(ids) == 1 else False), ('key', '=', key)], limit=1)
            if not target and len(ids) == 1:
                target = model.search([('company_id', '=', False), ('key', '=', key)], limit=1)
            if target:
                good = value is not None and (value <= target.value if target.operator == 'le' else value >= target.value)
                targets[key] = {'value': target.value, 'operator': target.operator,
                                'status': ('ok' if good else 'near' if value is not None and abs(value - target.value) <= 3 else 'bad') if value is not None else None}
        return targets

    def _accounting_sections(self, ids, section, start, end, previous_start, previous_end, companies, params):
        current = self._accounting(ids, start, end)
        previous = self._accounting(ids, previous_start, previous_end)
        bounds = self.env['account.move.line'].with_context(allowed_company_ids=ids)._read_group(
            [('company_id', 'in', ids), ('parent_state', '=', 'posted')], [], ['date:min', 'date:max'])
        first_data, last_data = bounds[0] if bounds else (None, None)
        posted_months = self._posted_months(ids)
        def covered(first, last):
            return any(first.strftime('%Y-%m') <= month <= last.strftime('%Y-%m') for month in posted_months)
        trend = []
        for offset in range(-5, 1):
            first, last = month_bounds(end, offset)
            trend.append({'month': first.strftime('%Y-%m'), 'data': self._accounting(ids, first, min(last, end)),
                          'has_data': covered(first, min(last, end)), 'partial': bool(first <= min(end, last_data or end) < last)})
        targets = self._targets(ids, current)
        result = {'available': True, 'period': {'date_from': str(start), 'date_to': str(end)},
                  'current': current, 'previous': previous, 'trend': trend, 'targets': targets, 'has_data': covered(start, end)}
        prior_months = sorted((m for m in posted_months if m < start.strftime('%Y-%m')), reverse=True)[:3]
        prior_salaries = [self._accounting(ids, *month_bounds(date.fromisoformat(m + '-01')))['categories'].get('salaries', 0) for m in prior_months]
        result['salaries_warning'] = covered(start, end) and low_salaries(current['categories'].get('salaries', 0), prior_salaries)
        before_previous_months = sorted((m for m in posted_months if m < previous_start.strftime('%Y-%m')), reverse=True)[:3]
        before_previous_salaries = [self._accounting(ids, *month_bounds(date.fromisoformat(m + '-01')))['categories'].get('salaries', 0) for m in before_previous_months]
        result['previous_salaries_warning'] = low_salaries(previous['categories'].get('salaries', 0), before_previous_salaries)
        if section in ('overview', 'ratios'):
            result['companies_compare'] = self._compare(companies, start, end)
        expense_keys = ('food_cost', 'salaries', 'rent', 'utilities', 'marketing', 'commissions', 'other_opex', 'depreciation', 'non_operating', 'zakat_tax')
        if section == 'overview':
            def value(data, key):
                if key == 'expenses_total':
                    return sum(data['categories'].get(k, 0) for k in expense_keys)
                return data.get(key, data['categories'].get(key, 0))
            result['kpis'] = {}
            for key in ('sales_net', 'food_cost', 'salaries', 'expenses_total', 'net_profit'):
                now, before = value(current, key) if covered(start, end) else None, value(previous, key) if covered(previous_start, previous_end) else None
                result['kpis'][key] = {'available': True, 'value': now, 'previous': before, 'change_pct': None if key == 'salaries' and result['previous_salaries_warning'] else change(now, before),
                                       'trend': [value(m['data'], key) if m['has_data'] else None for m in trend],
                                       'previous_trend': [None] + [value(m['data'], key) if m['has_data'] else None for m in trend[:-1]], 'good_when': 'down' if key in expense_keys or key == 'expenses_total' else 'up'}
            bridge = [('sales_net', current['sales_net']), ('food_cost', -current['categories'].get('food_cost', 0)), ('gross_profit', current['gross_profit']),
                      ('salaries', -current['categories'].get('salaries', 0)), ('rent', -current['categories'].get('rent', 0))]
            bridge += [(k, -current['categories'].get(k, 0)) for k in ('utilities', 'marketing', 'commissions', 'other_opex', 'depreciation') if current['categories'].get(k)]
            bridge += [('operating_profit', current['operating_profit']), ('other_income', current['categories'].get('other_income', 0)), ('non_operating', -current['categories'].get('non_operating', 0)), ('zakat_tax', -current['categories'].get('zakat_tax', 0)), ('net_profit', current['net_profit'])]
            result['bridge'] = [{'key': key, 'amount': amount, 'pct': percent(amount, current['sales_net'])} for key, amount in bridge if amount or key in ('sales_net', 'gross_profit', 'operating_profit', 'net_profit')]
            result['breakeven_series'] = [{'month': m['month'], 'partial': m['partial'], 'sales_net': m['data']['sales_net'] if m['has_data'] else None, 'net_profit': m['data']['net_profit'] if m['has_data'] else None, 'breakeven': m['data']['breakeven'] if m['has_data'] else None, 'margin_pct': m['data']['ratios']['net_margin_pct'] if m['has_data'] else None} for m in trend]
            result['purchases'] = self._purchases(ids, start, end, current['sales_net'])
            if not covered(start, end):
                result['purchases']['value'] = None
            result['purchases']['previous'] = self._purchases(ids, previous_start, previous_end, previous['sales_net'])
            result['purchases']['change_pct'] = change(result['purchases']['value'], result['purchases']['previous']['value'])
            result['purchases']['trend'] = []
            sales_trend = []
            mini_months = []
            for first, last in year_to_date_months(end):
                mini_months.append({'month': first.strftime('%Y-%m'), 'has_data': covered(first, min(last, end)),
                                    'data': self._accounting(ids, first, min(last, end))})
            for month in mini_months:
                month_start, month_end = month_bounds(date.fromisoformat(month['month'] + '-01'))
                month_end = min(month_end, end)
                result['purchases']['trend'].append({'month': month['month'], 'has_data': month['has_data'], **self._purchases(ids, month_start, month_end, month['data']['sales_net'])})
                monthly_sales, _, _, _ = self._sales_summary(ids, month_start, month_end)
                sales_trend.append({'month': month['month'], 'has_data': bool(monthly_sales['source_counts']['pos'] or monthly_sales['source_counts']['summary']), **monthly_sales})
            sales, days, channels, hours = self._sales_summary(ids, start, end)
            prior_sales, _, _, _ = self._sales_summary(ids, previous_start, previous_end)
            result['sales'] = dict(sales)
            if not days:
                result['sales']['apps'] = None
            result['sales']['previous'] = prior_sales
            result['sales']['apps_change_pct'] = change(result['sales']['apps'], prior_sales['apps'])
            result['sales']['customers_change_pct'] = change(sales['customers']['value'], prior_sales['customers']['value'])
            result['sales']['trend'] = sales_trend
            result['timeline'] = self._timeline(ids, end, params.get('timeline_mode', 'monthly'))
        if section in ('overview', 'ratios'):
            if section == 'ratios':
                sales, days, _, _ = self._sales_summary(ids, start, end)
            # Partial months with less than half of the trailing three months' fixed costs
            # are not sufficiently complete for a meaningful break-even estimate.
            fixed_keys = ('salaries', 'rent', 'utilities', 'depreciation')
            fixed_now = sum(current['categories'].get(k, 0) for k in fixed_keys)
            fixed_history = [sum(self._accounting(ids, *month_bounds(date.fromisoformat(m + '-01')))['categories'].get(k, 0) for k in fixed_keys) for m in prior_months]
            incomplete = incomplete_fixed_costs(min(end, fields.Date.context_today(self), last_data or end) < month_bounds(end)[1], fixed_now, fixed_history)
            result['breakeven'] = {'available': current['breakeven'] is not None and not incomplete, 'value': None if incomplete else current['breakeven'], 'safety_margin': None if incomplete else current['safety_margin'], 'day': None}
            if incomplete:
                result['breakeven']['reason'] = 'incomplete_costs'
            if current['breakeven'] is None:
                result['breakeven']['reason'] = 'invalid_contribution_margin'
            elif not incomplete and sales['gross']:
                cumulative = 0
                for day in sorted({d for _, d in days}):
                    cumulative += sum(sum(data['channels'].values()) for (_, d), data in days.items() if d == day)
                    if cumulative * current['sales_net'] / sales['gross'] >= current['breakeven']:
                        result['breakeven']['day'] = day.day
                        break
        if section == 'expenses':
            rows = []
            for key in expense_keys:
                if key == 'zakat_tax':
                    continue
                amount = current['categories'].get(key, 0)
                rows.append({'key': key, 'amount': amount, 'previous': previous['categories'].get(key, 0),
                             'trend': [m['data']['categories'].get(key, 0) if m['has_data'] else None for m in trend], 'pct': percent(amount, current['sales_net']),
                             'accounts': sorted([a for a in current['accounts'] if a['category'] == key], key=lambda x: x['amount'], reverse=True)})
            result['ranked'] = sorted((r for r in rows if r['amount'] or any(r['trend'])), key=lambda x: x['amount'], reverse=True)
            total = sum(r['amount'] for r in rows)
            result['ring'] = {'available': bool(current['sales_net']), 'value': percent(total, current['sales_net']), 'reason': False if current['sales_net'] else 'zero_sales'}
        if section == 'pnl':
            rows = []
            arabic_lang = 'ar_001' if self.env['res.lang']._get_data(code='ar_001').code else self.env.lang
            category_names = {c.code: c.name for c in self.env['baseer.dashboard2.category'].with_context(allowed_company_ids=ids, lang=arabic_lang).search([])}
            monthly_channels = []
            for month in trend:
                first, last = month_bounds(date.fromisoformat(month['month'] + '-01'))
                summary, _, channels, _ = self._sales_summary(ids, first, last)
                monthly_channels.append((summary, channels))
            for key in ('revenue', 'food_cost', 'gross_profit', 'salaries', 'rent', 'utilities', 'marketing', 'commissions', 'other_opex', 'depreciation', 'operating_profit', 'other_income', 'non_operating', 'zakat_tax', 'net_profit'):
                factor = -1 if key in expense_keys else 1
                values = [factor * m['data'].get(key, m['data']['categories'].get(key, 0)) if m['has_data'] else None for m in trend]
                children = {}
                for i, month in enumerate(trend):
                    if key == 'revenue':
                        summary, channels = monthly_channels[i]
                        gross = summary['channels']
                        net = month['data']['sales_net']
                        if month['has_data'] and net:
                            names = {c['key']: c['name'] for c in channels}
                            names.update({'other': 'أخرى', 'unclassified': 'غير مصنف'})
                            shares = {k: round(net * v / sum(gross.values()), 2) for k, v in gross.items()} if sum(gross.values()) else {'unclassified': net}
                            largest = max(shares, key=lambda k: abs(gross.get(k, 0)))
                            shares[largest] = round(shares[largest] + net - sum(shares.values()), 2)
                            for channel, amount in shares.items():
                                row = children.setdefault(channel, {'code': '', 'name': names.get(channel, channel), 'months': [0 if m['has_data'] else None for m in trend]})
                                row['months'][i] = amount
                        continue
                    for account in month['data']['accounts']:
                        if account['category'] == key:
                            ident = (account['company_id'], account['account_id'])
                            row = children.setdefault(ident, {'code': account['code'], 'name': account['name'], 'months': [0 if m['has_data'] else None for m in trend]})
                            row['months'][i] += factor * account['amount']
                for child in children.values():
                    child['total'] = round(sum(v for v in child['months'] if v is not None), 2)
                    child['pct'] = percent(child['total'], sum(m['data']['sales_net'] for m in trend))
                total = sum(v for v in values if v is not None)
                rows.append({'key': key, 'name': category_names.get(key), 'months': values, 'total': round(total, 2), 'pct': percent(total, sum(m['data']['sales_net'] for m in trend)), 'children': list(children.values())})
            result['rows'] = rows
        return result

    def _revenue(self, ids, start, end, previous_start, previous_end, params):
        current, days, channels, hours = self._sales_summary(ids, start, end)
        previous, _, _, _ = self._sales_summary(ids, previous_start, previous_end)
        bounds = self.env['account.move.line'].with_context(allowed_company_ids=ids)._read_group(
            [('company_id', 'in', ids), ('parent_state', '=', 'posted')], [], ['date:min', 'date:max'])
        first_data, last_data = bounds[0] if bounds else (None, None)
        posted_months = self._posted_months(ids)
        monthly = []
        for offset in range(-9, 1):
            first, last = month_bounds(end, offset)
            summary, _, _, _ = self._sales_summary(ids, first, min(last, end))
            monthly.append({'month': first.strftime('%Y-%m'), 'data': summary,
                            'has_data': bool(summary['source_counts']['pos'] or summary['source_counts']['summary']),
                            'partial': bool(first <= min(end, last_data or end) < last)})
        apps_trend = monthly
        monthly = monthly[-6:]
        known = {c['key']: c for c in channels}
        known['other'] = {'key': 'other', 'name': 'أخرى', 'kind': 'hall', 'color_token': False, 'commission_rate': 0}
        net_sales = self._accounting(ids, start, end)['sales_net']
        rows = []
        for key in set(known) | set(current['channels']) | set(previous['channels']):
            channel = known[key]
            amount = current['channels'].get(key, 0)
            before = previous['channels'].get(key, 0)
            rows.append({'key': key, 'name': channel['name'], 'kind': channel['kind'], 'color_token': channel['color_token'],
                         'amount': amount, 'commission_rate': channel['commission_rate'], 'share_pct': percent(amount, current['gross']), 'change_pct': change(amount, before),
                         'trend': [m['data']['channels'].get(key, 0) if m['has_data'] else None for m in monthly]})
        commissions = []
        for row in rows:
            channel = known[row['key']]
            rate = channel['commission_rate']
            if row['kind'] == 'app' and rate > 0:
                fee = round(row['amount'] * rate / 100, 2)
                commissions.append({'key': row['key'], 'name': row['name'], 'rate': rate, 'gross': row['amount'], 'commission': fee, 'net': round(row['amount'] - fee, 2)})
        split = {'hall': round(current['gross'] - current['apps'], 2), 'apps': current['apps']}
        if not days:
            current = dict(current, gross=None, apps=None)
            split = {'hall': None, 'apps': None}
        return {'available': True, 'current': current, 'previous': previous, 'trend': monthly, 'apps_trend': apps_trend,
                'ranked': sorted((row for row in rows if row['amount'] or any(row['trend'])), key=lambda row: row['amount'], reverse=True),
                'split': split,
                'commissions': {'available': bool(commissions), 'reason': False if commissions else 'no_commission_rates', 'rows': commissions},
                'timeline': self._timeline(ids, end, params.get('timeline_mode', 'monthly'))}

    def _inout(self, ids, end):
        bounds = self.env['account.move.line'].with_context(allowed_company_ids=ids)._read_group([('company_id', 'in', ids), ('parent_state', '=', 'posted')], [], ['date:max'])
        last_data = bounds[0][0] if bounds else None
        months = []
        first = month_bounds(end, -5)[0]
        out_by_month = self._cash_out(ids, first, end, split=True)
        for offset in range(-5, 1):
            start, last = month_bounds(end, offset)
            last = min(last, end)
            sales, _, _, _ = self._sales_summary(ids, start, last)
            out = out_by_month.get(start.strftime('%Y-%m'), {'available': True, 'unconfigured_company_ids': [], 'total': 0, 'items': {}, 'sources': {}})
            vat = self._sales_vat(ids, start, last)
            sales['available'] = bool(sales['channels'])
            months.append({'month': start.strftime('%Y-%m'), 'partial': bool(start <= min(end, last_data or end) < month_bounds(start)[1]), 'incoming': sales, 'outgoing': out,
                           'unpaid_bills': self._unpaid_bills(ids, last), 'sales_vat': vat, 'net': round(sales['gross'] - out['total'], 2)})
        channel_totals, item_totals, source_totals = defaultdict(float), defaultdict(float), defaultdict(float)
        for key in ('salaries', 'rent', 'utilities', 'purchases', 'commissions', 'marketing', 'non_operating', 'other'):
            item_totals[key] = 0
        for key in ('bank', 'cash'):
            source_totals[key] = 0
        for month in months:
            for key, amount in month['incoming']['channels'].items():
                channel_totals[key] += amount
            for key, amount in month['outgoing']['items'].items():
                item_totals[key] += amount
            for key, amount in month['outgoing']['sources'].items():
                source_totals[key] += amount
        return {'available': True, 'months': months, 'channel_names': months[-1]['incoming']['channel_names'], 'total': {'incoming': round(sum(m['incoming']['gross'] for m in months), 2),
                'outgoing': round(sum(m['outgoing']['total'] for m in months), 2), 'net': round(sum(m['net'] for m in months), 2),
                'channels': {key: round(amount, 2) for key, amount in channel_totals.items()},
                'items': {key: round(amount, 2) for key, amount in item_totals.items()},
                'sources': {key: round(amount, 2) for key, amount in source_totals.items()},
                'sales_vat': round(sum(m['sales_vat']['value'] for m in months), 2),
                'unpaid_bills': months[-1]['unpaid_bills'], 'apps_unreceived': self._sales_summary(ids, month_bounds(end, -5)[0], end)[0]['apps_unreceived']}}

    def _heatmap(self, ids, month):
        try:
            first = date.fromisoformat(month + '-01')
        except (TypeError, ValueError):
            raise UserError(_('Invalid heatmap month.'))
        first, last = month_bounds(first)
        year_start, year_end = date(first.year, 1, 1), date(first.year, 12, 31)
        year_summary, year_days, channels, year_hours = self._sales_summary(ids, year_start, year_end)
        prev_first, prev_last = month_bounds(first, -1)
        previous, prev_days, _, _ = self._sales_summary(ids, prev_first, prev_last)
        events = self.env['baseer.dashboard2.event'].with_context(allowed_company_ids=ids).search_read([
            ('date_from', '<=', year_end), ('date_to', '>=', year_start), '|', ('company_ids', '=', False), ('company_ids', 'in', ids)],
            ['name', 'date_from', 'date_to', 'company_ids', 'kind', 'note', 'color_token'])
        for event in events:
            event['date_from'] = str(event['date_from'])
            event['date_to'] = str(event['date_to'])
        warnings = year_summary['warnings']
        def day_values(day, source):
            rows = [v for (_, d), v in source.items() if d == day]
            covered_rows = [r for r in rows if r['customers'] is not None]
            sales_rows = [r for r in rows if not r.get('sales_missing')]
            sources = {r['source'] for r in sales_rows}
            source_label = 'mixed' if 'mixed' in sources or {'summary', 'pos'} <= sources else next(iter(sources), False)
            return {'source': source_label, 'date': str(day), 'warnings': [w for w in warnings if w['date'] == str(day)], 'events': [event for event in events if event['date_from'] <= str(day) <= event['date_to']], 'gross': round(sum(sum(r['channels'].values()) for r in sales_rows), 2) if sales_rows else None,
                    'customers': sum(r['customers'] for r in covered_rows) if covered_rows else None,
                    'pos_gross': sum(r['pos_gross'] for r in covered_rows) if covered_rows else None,
                    'partial': bool(covered_rows and len(covered_rows) < len(rows))}
        def dates(start, end):
            return [start + timedelta(days=i) for i in range((end - start).days + 1)]
        days = []
        for d in dates(first, last):
            item = day_values(d, year_days)
            item['events'] = [event for event in events if event['date_from'] <= str(d) <= event['date_to']]
            days.append(item)
        def averages(start, finish):
            result = []
            values = [day_values(d, year_days) for d in dates(start, finish)]
            for weekday in range(7):
                selected = [row for row in values if date.fromisoformat(row['date']).weekday() == weekday and row['gross'] is not None]
                available = [row['customers'] for row in selected if row['customers'] is not None]
                result.append({'weekday': weekday, 'gross': round(sum(row['gross'] for row in selected) / len(selected), 2) if selected else None,
                               'customers': round(sum(available) / len(available), 2) if available else None,
                               'covered_days': len(available), 'partial': bool(available and len(available) < len(selected))})
            return result
        year_calendar = []
        for m in range(1, 13):
            mfirst, mlast = month_bounds(date(first.year, m, 1))
            year_calendar.append({'month': mfirst.strftime('%Y-%m'), 'days': [day_values(d, year_days) for d in dates(mfirst, mlast)]})
        current_summary, _, _, hours = self._sales_summary(ids, first, last)
        matrix = [{'weekday': wd, 'hour': hour, 'orders': hours[(wd, hour)]['orders'] if (wd, hour) in hours else None, 'gross': round(hours[(wd, hour)]['gross'], 2) if (wd, hour) in hours else None} for wd in range(7) for hour in range(24)]
        return {'available': True, 'days': days, 'events': events, 'weekday_month': averages(first, last),
                'weekday_ytd': averages(year_start, last), 'year_calendar': year_calendar,
                'daily_average': {'current': round(current_summary['gross'] / len([d for d in days if d['gross'] is not None]), 2) if any(d['gross'] is not None for d in days) else None, 'previous': round(previous['gross'] / len({d for (_, d), row in prev_days.items() if not row.get('sales_missing')}), 2) if any(not row.get('sales_missing') for row in prev_days.values()) else None},
                'best_day': max((d for d in days if d['gross'] is not None), key=lambda d: d['gross'], default=None),
                'worst_day': min((d for d in days if d['gross'] is not None), key=lambda d: d['gross'], default=None),
                'hours': {'available': bool(hours), 'reason': False if hours else 'no_pos_days', 'matrix': matrix}}

    @api.model
    def get_section(self, section, params=None):
        self._check_reader()
        if section not in ('overview', 'revenue', 'expenses', 'ratios', 'pnl', 'inout', 'heatmap', 'glossary'):
            raise UserError(_('Unknown dashboard section.'))
        if section == 'glossary':
            return {'sources': SOURCES}
        params = params or {}
        companies = self._companies()
        if not companies:
            return {'available': False, 'reason': 'empty_company_scope'}
        ids = self._scope(params.get('company_key'))
        start, end = self._period(params.get('period') or {})
        previous_end = start - timedelta(days=1)
        previous_start = previous_end.replace(day=1) if params['period']['mode'] == 'month' else previous_end - (end - start)
        if section in ('overview', 'expenses', 'ratios', 'pnl'):
            return self._accounting_sections(ids, section, start, end, previous_start, previous_end, companies, params)
        if section == 'revenue':
            return self._revenue(ids, start, end, previous_start, previous_end, params)
        if section == 'inout':
            return self._inout(ids, end)
        return self._heatmap(ids, params.get('heatmap_month') or end.strftime('%Y-%m'))
