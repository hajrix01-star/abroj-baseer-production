from .month_names import english_months, month_label
from .service import request_memo, food_ratio
import calendar
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from odoo import api, fields, models, _
from odoo import _ as translate
from odoo.osv import expression
from odoo.exceptions import UserError

from .service import SOURCES, food_ratio, PNL_DEFAULT_VIEW


def month_bounds(day, offset=0):
    index = day.year * 12 + day.month - 1 + offset
    year, month = divmod(index, 12)
    first = date(year, month + 1, 1)
    return first, first.replace(day=calendar.monthrange(year, month + 1)[1])


def pnl_year_start(end):
    # The 12-month view trails the selected month; change this helper for a calendar-year policy.
    return month_bounds(end, -11)[0]


def year_to_date_months(end):
    return [month_bounds(date(end.year, month, 1)) for month in range(1, end.month + 1)]


def percent(value, base):
    return round(100 * value / base, 2) if base else None


def change(value, previous):
    return round((value - previous) / abs(previous) * 100, 2) if value is not None and previous else None


EXPENSE_KEYS_EX_PURCHASES = (
    'salaries', 'rent', 'utilities', 'marketing', 'commissions',
    'other_opex', 'depreciation', 'non_operating', 'zakat_tax',
)


def expenses_ex_purchases(data):
    return sum(data['categories'].get(key, 0) for key in EXPENSE_KEYS_EX_PURCHASES)


def low_salaries(current, history):
    return bool(len(history) == 3 and sum(history) > 0 and current < 0.7 * sum(history) / 3)


def hours_data_end(first, last, today, last_data):
    """Limit the hours matrix to the available portion of the selected month."""
    return max(first, min(last, today, last_data or last))


def incomplete_fixed_costs(partial, current, history):
    """A partial month needs at least half the mean fixed costs of three months."""
    return bool(partial and len(history) == 3 and sum(history) > 0 and current < sum(history) / 6)


class DashboardSections(models.AbstractModel):
    _inherit = 'baseer.dashboard2.service'

    @request_memo
    def _cash_drill_candidates(self, ids, end):
        first = month_bounds(end, -5)[0]
        trace = {}
        values = self.with_context(_bd2_cash_trace=trace, _bd2_request_cache=None)._cash_out(ids, first, end, split=True)
        result = {'total': {}, 'items': {}, 'sources': {}}
        for field in result:
            keys = {'total'} if field == 'total' else {key for data in values.values() for key in data[field]}
            for key in keys:
                combined_ids = set()
                expected_total = 0.0
                for month, data in values.items():
                    expected = data['total'] if field == 'total' else data[field].get(key, 0)
                    expected_total += expected
                    parts = trace.get(month, {}).get(field, {}).get(key, {})
                    ids_for_value = set(parts)
                    raw = sum(credit for credit, _part in parts.values())
                    if ids_for_value and abs(round(raw, 2) - expected) < .005:
                        result[field].setdefault(month, {})[key] = sorted(ids_for_value)
                    combined_ids.update(ids_for_value)
                raw_total = sum(trace[month][field][key][line_id][0]
                                for month in trace for line_id in trace[month].get(field, {}).get(key, {}))
                if combined_ids and abs(round(raw_total, 2) - round(expected_total, 2)) < .005:
                    result[field].setdefault('all', {})[key] = sorted(combined_ids)
        return result

    @api.model
    def get_cash_drill_availability(self, params):
        self._check_reader()
        ids = self._scope((params or {}).get('company_key'))
        _start, end = self._period((params or {}).get('period') or {})
        candidates = self._cash_drill_candidates(ids, end)
        return {field: {month: list(keys) for month, keys in months.items()} for field, months in candidates.items()}

    def _heatmap_hours_end(self, ids, first, last):
        bounds = self.env['account.move.line'].with_context(allowed_company_ids=ids)._read_group(
            [('company_id', 'in', ids), ('parent_state', '=', 'posted')], [], ['date:max'])
        last_data = bounds[0][0] if bounds else None
        return hours_data_end(first, last, fields.Date.context_today(self), last_data)

    def _pnl_bounds(self, start, end, params):
        view = params.get('pnl_view', PNL_DEFAULT_VIEW)
        if view == 'range':
            requested = params.get('pnl_range')
            if requested:
                return self._period({'mode': 'range', **requested})
            if params.get('period', {}).get('mode') == 'range':
                return start, end
            return month_bounds(end)
        if view == 'quarter':
            first = date(end.year, ((end.month - 1) // 3) * 3 + 1, 1)
            return first, month_bounds(first, 2)[1]
        if view == 'year':
            return pnl_year_start(end), month_bounds(end)[1]
        if view == 'month':
            return month_bounds(end)
        raise UserError(translate('Invalid P&L view.'))

    def _inclusive_drill_domain(self, ids, start, end, base_domain, include_revenue=False, include_input=True):
        """Add only tax journal items wholly attributable to the selected accounts."""
        lines = self.env['account.move.line'].with_context(allowed_company_ids=ids)
        groups = lines._read_group(base_domain, ['company_id', 'account_id'], [])
        selected = {(company.id, account.id) for company, account in groups}
        tax_parts = defaultdict(list)
        for day, cid, kind, account_id, amount, line_id in self._tax_window(ids, start, end):
            tax_parts[line_id].append((cid, kind, account_id, amount))
        tax_ids = []
        for line_id, parts in tax_parts.items():
            if parts[0][1] in ('output_vat', 'tobacco_fee'):
                if include_revenue:
                    tax_ids.append(line_id)
                continue
            if not include_input:
                continue
            if parts[0][1] == 'unallocated_input_vat':
                raise UserError(_('This figure is allocated across journal items.'))
            flags = {(cid, account_id) in selected for cid, _kind, account_id, amount in parts if amount}
            if len(flags) > 1:
                raise UserError(_('This figure is allocated across journal items.'))
            if flags == {True}:
                tax_ids.append(line_id)
        return expression.OR([base_domain, [('id', 'in', tax_ids)]])

    @api.model
    def get_drilldown(self, descriptor):
        self._check_reader()
        if not isinstance(descriptor, dict):
            raise UserError(_('Unknown dashboard figure.'))
        ids = self._scope(descriptor.get('company_key'))
        start, end = self._period(descriptor.get('period') or {})
        section, key = descriptor.get('section'), descriptor.get('key')
        context = {'allowed_company_ids': ids, 'create': False, 'edit': False,
                   'delete': False, 'duplicate': False}
        model = 'account.move.line'
        if section in ('overview', 'revenue') and key in ('timeline_ytd', 'timeline_previous_ytd', 'timeline_best', 'timeline_point'):
            mode = descriptor.get('timeline_mode', 'monthly') if key == 'timeline_point' else 'monthly'
            timeline = self._timeline(ids, end, mode)
            stats = timeline['stats']
            cutoff = stats['end_date' if key == 'timeline_ytd' else 'previous_end_date']
            if key in ('timeline_best', 'timeline_point'):
                cutoff = stats['end_date']
            if not cutoff or (key == 'timeline_previous_ytd' and stats['previous_ytd'] is None):
                raise UserError(_('Unknown dashboard figure.'))
            end = fields.Date.to_date(cutoff)
            if key == 'timeline_point':
                points = timeline['years' if mode == 'yearly' else 'months']
                index = descriptor.get('index')
                if type(index) is not int or not 0 <= index < len(points) or points[index]['value'] is None:
                    raise UserError(_('Unknown dashboard figure.'))
                point = points[index]
                if mode == 'yearly':
                    start, last = date(point['year'], 1, 1), date(point['year'], 12, 31)
                else:
                    start, last = month_bounds(date(end.year, point['month'], 1))
                end = min(last, end)
            elif key == 'timeline_best':
                if not stats['best_month']:
                    raise UserError(_('Unknown dashboard figure.'))
                start, last = month_bounds(date(end.year, stats['best_month']['month'], 1))
                end = min(last, end)
            else:
                start = date(end.year, 1, 1)
        if section == 'heatmap':
            month_start, month_end = month_bounds(end)
            if descriptor.get('day'):
                start, end = self._period({'mode': 'range', 'date_from': descriptor['day'], 'date_to': descriptor['day']})
                if descriptor.get('year_calendar') is True:
                    valid_day = start.year == month_start.year
                else:
                    valid_day = month_start <= start <= month_end
                if not valid_day:
                    raise UserError(_('Unknown dashboard figure.'))
            else:
                start, end = month_start, month_end
        if section == 'inout' and key in ('gross', 'channel', 'sales_vat', 'cash_out'):
            if descriptor.get('month'):
                first, last = self._period({'mode': 'month', 'month': descriptor['month']})
                if not month_bounds(end, -5)[0] <= first <= end:
                    raise UserError(_('Unknown dashboard figure.'))
                start, end = first, min(last, end)
            else:
                start = month_bounds(end, -5)[0]
        if section == 'inout' and key == 'cash_out':
            original_end = self._period(descriptor.get('period') or {})[1]
            field = descriptor.get('group')
            item = descriptor.get('item') if field in ('items', 'sources') else 'total'
            month = descriptor.get('month') or 'all'
            if field not in ('total', 'items', 'sources') or not isinstance(item, str):
                raise UserError(_('Unknown dashboard figure.'))
            candidates = self._cash_drill_candidates(ids, original_end)
            line_ids = candidates[field].get(month, {}).get(item)
            if not line_ids:
                raise UserError(_('This figure is allocated across journal items.'))
            domain = expression.AND([self._aml_domain(ids, start, end), [('id', 'in', line_ids)]])
            label = 'المدفوعات الفعلية'
        elif section == 'inout' and key == 'sales_vat':
            vat_trace = set()
            self.with_context(_bd2_vat_trace=vat_trace, _bd2_request_cache=None)._sales_vat(ids, start, end)
            domain = [('company_id', 'in', ids), ('parent_state', '=', 'posted'), ('id', 'in', list(vat_trace))]
            label = 'ضريبة المبيعات'
        elif section == 'heatmap' and key == 'hours':
            weekday, hour = descriptor.get('weekday'), descriptor.get('hour')
            if type(weekday) is not int or type(hour) is not int or not 0 <= weekday <= 6 or not 0 <= hour <= 23:
                raise UserError(_('Unknown dashboard figure.'))
            end = self._heatmap_hours_end(ids, start, end)
            domain = self._customer_hour_domain(ids, start, end, weekday, hour)
            model, label = 'pos.order', 'الطلبات حسب الساعة'
        elif section in ('overview', 'revenue', 'heatmap', 'inout') and key in ('gross', 'apps', 'channel') and not (section == 'revenue' and key == 'gross'):
            trace, pos_trace = {}, {}
            summary, days, channels, _hours = self.with_context(_bd2_sales_trace=trace, _bd2_pos_trace=pos_trace, _bd2_request_cache=None)._sales_summary(ids, start, end)
            counts = summary['source_counts']
            if bool(counts['summary']) == bool(counts['pos']):
                raise UserError(_('This figure contains more than one source.'))
            known = {c['key'] for c in channels} | {'other', 'unclassified'}
            if key == 'channel':
                selected = {descriptor.get('channel')}
                if not selected <= known:
                    raise UserError(_('Unknown dashboard figure.'))
            elif key == 'apps':
                selected = {c['key'] for c in channels if c['kind'] == 'app'}
            else:
                selected = known
            selected_trace = trace if counts['summary'] else pos_trace
            line_ids = {line_id for by_channel in selected_trace.values() for channel, line_ids in by_channel.items()
                        if channel in selected for line_id in line_ids}
            if counts['summary']:
                domain = expression.AND([self._aml_domain(ids, start, end), [('id', 'in', list(line_ids))]])
            else:
                model = 'pos.payment'
                domain = [('company_id', 'in', ids), ('id', 'in', list(line_ids))]
            label = 'المبيعات'
        elif section in ('overview', 'revenue') and key == 'recorded_commissions':
            base_domain = self._commission_domain(ids, start, end)
            domain = self._inclusive_drill_domain(ids, start, end, base_domain)
            label = 'عمولات التطبيقات'
        elif section in ('overview', 'revenue', 'heatmap') and key == 'customers':
            domain = self._customer_orders_domain(ids, start, end)
            model, label = 'pos.order', 'عدد العملاء'
        elif section == 'overview' and key == 'purchases':
            domain = self._purchase_domain(ids, start, end)
            if domain is None:
                raise UserError(_('Unknown dashboard figure.'))
            domain = self._inclusive_drill_domain(ids, start, end, domain)
            context['group_by'] = 'move_id'
            label = 'المشتريات'
        elif section == 'pnl' and key in ('revenue', 'food_cost', 'gross_profit', 'salaries', 'rent', 'utilities',
                                           'marketing', 'commissions', 'other_opex', 'depreciation',
                                           'operating_profit', 'other_income', 'zakat_tax', 'net_profit'):
            if type(descriptor.get('tax_inclusive', False)) is not bool or descriptor.get('tax_inclusive', False):
                raise UserError(_('Use the verified profit and loss details for tax-inclusive figures.'))
            view = descriptor.get('pnl_view')
            first, last = self._pnl_bounds(start, end, descriptor)
            full_first, full_last = first, last
            column = descriptor.get('column')
            if column is not None:
                if not isinstance(column, int) or isinstance(column, bool) or column < 0:
                    raise UserError(_('Unknown dashboard figure.'))
                if view == 'quarter':
                    if column:
                        raise UserError(_('Unknown dashboard figure.'))
                else:
                    month_first, month_last = month_bounds(first, column)
                    if month_first > last:
                        raise UserError(_('Unknown dashboard figure.'))
                    first, last = max(first, month_first), min(last, month_last)
            start, end = first, last
            expense_categories = ('food_cost', 'salaries', 'rent', 'utilities', 'marketing', 'commissions', 'other_opex', 'depreciation', 'non_operating')
            categories = {'other_opex': ('other_opex', 'non_operating'),
                          'gross_profit': ('revenue', 'food_cost'),
                          'operating_profit': ('revenue',) + expense_categories,
                          'net_profit': ('revenue', 'other_income', 'zakat_tax') + expense_categories}.get(key, (key,))
            accounts = [a for a in self._accounting(ids, start, end)['accounts'] if a['category'] in categories]
            child = descriptor.get('child')
            if child:
                valid_children = self._accounting(ids, full_first, full_last)['accounts']
                if not any(a['category'] in categories and '%s:%s' % (a['company_id'], a['account_id']) == child for a in valid_children):
                    raise UserError(_('Unknown dashboard figure.'))
                accounts = [a for a in accounts if '%s:%s' % (a['company_id'], a['account_id']) == child]
            pairs = expression.OR([[('company_id', '=', a['company_id']), ('account_id', '=', a['account_id'])]
                                   for a in accounts]) if accounts else [('id', '=', 0)]
            domain = expression.AND([self._aml_domain(ids, start, end), pairs])
            label = 'قائمة الدخل'
        elif section in ('overview', 'revenue', 'expenses', 'ratios'):
            expense_keys = ('food_cost', 'salaries', 'rent', 'utilities', 'marketing', 'commissions', 'other_opex', 'depreciation', 'non_operating', 'zakat_tax')
            mapping = {k: (k,) for k in expense_keys + ('revenue', 'other_income')}
            mapping.update({'gross': ('revenue',), 'sales_net': ('revenue',), 'timeline_ytd': ('revenue',), 'timeline_previous_ytd': ('revenue',), 'timeline_best': ('revenue',), 'timeline_point': ('revenue',), 'food_pct': ('food_cost',),
                            'salaries_pct': ('salaries',), 'prime_pct': ('food_cost', 'salaries'),
                            'rent_utilities': ('rent', 'utilities'), 'expenses_total': expense_keys,
                            'operating_expenses': tuple(k for k in expense_keys if k != 'zakat_tax'),
                            'gross_profit': ('revenue', 'food_cost'),
                            'operating_profit': ('revenue',) + tuple(k for k in expense_keys if k != 'zakat_tax'),
                            'net_profit': ('revenue', 'other_income') + expense_keys,
                            'net_margin_pct': ('revenue', 'other_income') + expense_keys})
            if section == 'expenses':
                mapping['other_opex'] = ('other_opex', 'non_operating')
                all_categories = self.env['baseer.dashboard2.category'].with_context(allowed_company_ids=ids).search([]).mapped('code')
                mapping['expenses_total'] = tuple(k for k in all_categories if k not in ('revenue', 'other_income'))
                mapping['operating_expenses'] = tuple(k for k in all_categories if k not in ('revenue', 'other_income', 'zakat_tax'))
            categories = mapping.get(key)
            if not categories:
                raise UserError(_('Unknown dashboard figure.'))
            if descriptor.get('month'):
                month_start, month_end = self._period({'mode': 'month', 'month': descriptor['month']})
                start, end = month_start, min(month_end, end)
                if end < start:
                    raise UserError(_('Invalid dashboard period.'))
            accounts = [a for a in self._accounting(ids, start, end)['accounts'] if a['category'] in categories]
            child = descriptor.get('child')
            if child:
                accounts = [a for a in accounts if '%s:%s' % (a['company_id'], a['account_id']) == child]
                if not accounts:
                    raise UserError(_('Unknown dashboard figure.'))
            pairs = expression.OR([[('company_id', '=', a['company_id']), ('account_id', '=', a['account_id'])]
                                   for a in accounts]) if accounts else [('id', '=', 0)]
            base_domain = expression.AND([self._aml_domain(ids, start, end), pairs])
            domain = self._inclusive_drill_domain(ids, start, end, base_domain, include_revenue='revenue' in categories, include_input=any(k not in ('revenue', 'other_income') for k in categories))
            label = 'القيود المحاسبية'
        else:
            raise UserError(_('Unknown dashboard figure.'))
        period_label = month_label(start, year=True) if start.day == 1 and end == month_bounds(start)[1] else '%s – %s' % (start, end)
        return {'type': 'ir.actions.act_window', 'name': '%s — %s' % (label, period_label),
                'res_model': model, 'domain': domain,
                'views': [[False, 'list'], [False, 'form']], 'context': context, 'target': 'current'}

    def _purchase_domain(self, ids, start, end):
        settings = self.env['baseer.dashboard2.settings'].with_context(allowed_company_ids=ids).search([('company_id', 'in', ids)])
        if set(settings.mapped('company_id').ids) != set(ids) or any(not setting.food_purchase_account_ids for setting in settings):
            return None
        excluded = self._reset_move_ids(ids, end, start)
        excluded += self.env['res.company'].browse(ids).mapped('account_opening_move_id').ids
        company_accounts = expression.OR([[('company_id', '=', setting.company_id.id),
                                           ('account_id', 'in', setting.food_purchase_account_ids.ids)]
                                          for setting in settings])
        return expression.AND([self._aml_domain(ids, start, end), company_accounts,
                               [('move_id', 'not in', excluded), ('move_id.ref', '!=', 'Opening Entry')]])

    def _purchases(self, ids, start, end, sales):
        domain = self._purchase_domain(ids, start, end)
        if domain is None:
            return {'available': False, 'value': None, 'pct': None}
        settings = self.env['baseer.dashboard2.settings'].with_context(allowed_company_ids=ids).search([('company_id', 'in', ids)])
        rows = self.env['account.move.line'].with_context(allowed_company_ids=ids)._read_group(
            domain, ['company_id'], ['balance:sum'])
        values = {company.id: amount or 0 for company, amount in rows}
        value = sum((values.get(setting.company_id.id, 0) for setting in settings), 0.0)
        allocated = self._tax_basis(ids, start, end)['accounts']
        value += sum(allocated.get((setting.company_id.id, account.id), 0) for setting in settings for account in setting.food_purchase_account_ids)
        bill_exists = self.env['account.move.line'].with_context(allowed_company_ids=ids).search_count([
            ('company_id', 'in', ids), ('parent_state', '=', 'posted'),
            ('date', '>=', start), ('date', '<=', end), ('move_id.move_type', 'in', ('in_invoice', 'in_refund')),
            ('account_id', 'in', settings.mapped('food_purchase_account_ids').ids)], limit=1)
        return {'available': True, 'value': round(value, 2), 'pct': food_ratio(value, sales), 'has_bills': bool(bill_exists)}

    @request_memo
    def _tooltip_purchase_months(self, ids, start, end):
        settings = self.env['baseer.dashboard2.settings'].with_context(allowed_company_ids=ids).search([('company_id', 'in', ids)])
        if set(settings.mapped('company_id').ids) != set(ids) or any(not setting.food_purchase_account_ids for setting in settings):
            return {}
        accounts = expression.OR([[('company_id', '=', setting.company_id.id), ('account_id', 'in', setting.food_purchase_account_ids.ids)] for setting in settings])
        lines = self.env['account.move.line'].with_context(allowed_company_ids=ids)
        rows = lines._read_group(expression.AND([self._aml_domain(ids, start, end), accounts]), ['date:month', 'move_id'], ['balance:sum'])
        moves = self.env['account.move'].browse([move.id for _, move, _ in rows])
        moves.fetch(['ref', 'move_type'])
        excluded = set(self._reset_move_ids(ids, end, start)) | set(self.env['res.company'].browse(ids).mapped('account_opening_move_id').ids)
        amounts, bill_months = defaultdict(float), set()
        for month, move, value in rows:
            if not month:
                continue
            key = month.strftime('%Y-%m')
            if move.move_type in ('in_invoice', 'in_refund'):
                bill_months.add(key)
            if move.id not in excluded and move.ref != 'Opening Entry':
                amounts[key] += value or 0
        return {key: round(amounts[key], 2) for key in bill_months}

    def _commission_domain(self, ids, start, end):
        domains = []
        settings_model = self.env['baseer.dashboard2.settings'].with_context(allowed_company_ids=ids)
        for company in self.env['res.company'].browse(ids):
            setting = settings_model.search([('company_id', '=', company.id)], limit=1)
            accounts = setting.app_commission_account_ids
            if not accounts:
                accounts = self.env['account.account'].with_company(company).search([
                    ('company_ids', 'in', company.id), ('code', '=', '400011')])
            excluded = self._reset_move_ids([company.id], end, start) + company.account_opening_move_id.ids
            domains.append([('company_id', '=', company.id), ('account_id', 'in', accounts.ids),
                            ('move_id', 'not in', excluded), ('move_id.ref', '!=', 'Opening Entry')])
        return expression.AND([self._aml_domain(ids, start, end), expression.OR(domains)])

    def _recorded_app_commissions(self, ids, start, end, include_tax=True):
        rows = self.env['account.move.line'].with_context(allowed_company_ids=ids)._read_group(
            self._commission_domain(ids, start, end), ['company_id', 'account_id'], ['balance:sum'])
        total = sum(amount or 0 for _company, _account, amount in rows)
        if include_tax:
            pairs = {(company.id, account.id) for company, account, _amount in rows}
            allocated = self._tax_basis(ids, start, end)['accounts']
            total += sum(amount for pair, amount in allocated.items() if pair in pairs)
        return round(total, 2)

    @request_memo
    def _posted_months(self, ids, revenue_only=False):
        reset_ids = set(self._reset_move_ids(ids, fields.Date.to_date('9999-12-31')))
        opening_ids = set(self.env['res.company'].browse(ids).mapped('account_opening_move_id').ids)
        types = ('income', 'income_other') if revenue_only else (
            'income', 'income_other', 'expense', 'expense_depreciation', 'expense_direct_cost')
        rows = self.env['account.move.line'].with_context(allowed_company_ids=ids)._read_group([
            ('company_id', 'in', ids), ('parent_state', '=', 'posted'),
            ('account_id.account_type', 'in', types), ('move_id', 'not in', list(reset_ids | opening_ids)),
            ('move_id.ref', '!=', 'Opening Entry')], ['date:month'], [])
        return {month.strftime('%Y-%m') for (month,) in rows if month}

    def _timeline(self, ids, end, mode):
        if mode not in ('monthly', 'yearly'):
            raise UserError(_('Invalid timeline mode.'))
        line_model = self.env['account.move.line'].with_context(allowed_company_ids=ids)
        bounds = line_model._read_group([('company_id', 'in', ids), ('parent_state', '=', 'posted')], [], ['date:min', 'date:max'])
        first_data, last = bounds[0] if bounds else (None, None)
        posted_months = self._posted_months(ids, revenue_only=True)
        def covered(first, finish):
            return any(first.strftime('%Y-%m') <= month <= finish.strftime('%Y-%m') for month in posted_months)
        cutoff = min(end, last, fields.Date.context_today(self)) if last else None
        start_year = date(end.year, 1, 1)
        previous_end = cutoff.replace(year=cutoff.year - 1, day=min(cutoff.day, calendar.monthrange(cutoff.year - 1, cutoff.month)[1])) if cutoff else None
        ytd = self._accounting_gross(ids, start_year, cutoff)['sales_net'] if cutoff and cutoff >= start_year else 0
        pytd = self._accounting_gross(ids, date(end.year - 1, 1, 1), previous_end)['sales_net'] if previous_end and previous_end.year == end.year - 1 else None
        if previous_end and not covered(date(end.year - 1, 1, 1), previous_end):
            pytd = None
        months = []
        for m in range(1, 13):
            first, last_month = month_bounds(date(end.year, m, 1))
            prior_first, prior_last = month_bounds(date(end.year - 1, m, 1))
            months.append({'month': m, 'value': self._accounting_gross(ids, first, min(last_month, cutoff))['sales_net'] if cutoff and first <= cutoff and covered(first, min(last_month, cutoff)) else None,
                           'partial': bool(cutoff and first <= cutoff < last_month),
                           'previous': self._accounting_gross(ids, prior_first, min(prior_last, previous_end))['sales_net'] if previous_end and prior_first <= previous_end and covered(prior_first, min(prior_last, previous_end)) else None})
        years = []
        if mode == 'yearly':
            for year in range(end.year - 4, end.year + 1):
                first, last_year = date(year, 1, 1), date(year, 12, 31)
                prior_first, prior_last = date(year - 1, 1, 1), date(year - 1, 12, 31)
                prior_cutoff = min(prior_last, previous_end) if previous_end else None
                years.append({'year': year, 'value': self._accounting_gross(ids, first, min(last_year, cutoff))['sales_net'] if cutoff and first <= cutoff and covered(first, min(last_year, cutoff)) else None, 'previous': self._accounting_gross(ids, prior_first, prior_cutoff)['sales_net'] if prior_cutoff and prior_first <= prior_cutoff and covered(prior_first, prior_cutoff) else None, 'partial': bool(cutoff and year == cutoff.year and cutoff < last_year)})
        eligible = [m for m in months if m['value'] is not None]
        return {'available': True, 'mode': mode, 'months': months, 'years': years,
                'stats': {'end_date': str(cutoff) if cutoff else None, 'previous_end_date': str(previous_end) if previous_end else None, 'ytd': ytd, 'previous_ytd': pytd, 'growth_pct': change(ytd, pytd), 'best_month': max(eligible, key=lambda x: x['value']) if eligible else None}}

    def _compare(self, companies, start, end):
        result = []
        for cid, label, name in companies:
            data = self._accounting_gross([cid], start, end)
            posted = self._posted_months([cid])
            covered = any(start.strftime('%Y-%m') <= month <= end.strftime('%Y-%m') for month in posted)
            prior_months = sorted((m for m in posted if m < start.strftime('%Y-%m')), reverse=True)[:3]
            prior_salaries = [self._accounting([cid], *month_bounds(date.fromisoformat(m + '-01')))['categories'].get('salaries', 0) for m in prior_months] if len(prior_months) == 3 else []
            result.append({'key': str(cid), 'label': label, 'name': name, 'sales_net': data['sales_net'], 'targets': self._targets([cid], data),
                           'salaries_warning': covered and low_salaries(data['categories'].get('salaries', 0), prior_salaries), **data['ratios']})
        return result

    def _targets(self, ids, current):
        targets = {}
        model = self.env['baseer.dashboard2.target'].with_context(allowed_company_ids=ids)
        company_id = ids[0] if len(ids) == 1 else False
        rows = model.search([('company_id', 'in', [False, company_id])], order='id')
        by_key = {}
        for row in rows:
            by_key.setdefault((row.company_id.id or False, row.key), row)
        for key, value in current['ratios'].items():
            target = by_key.get((company_id, key)) or by_key.get((False, key))
            if target:
                good = value is not None and (value <= target.value if target.operator == 'le' else value >= target.value)
                targets[key] = {'value': target.value, 'operator': target.operator,
                                'status': ('ok' if good else 'near' if value is not None and abs(value - target.value) <= 3 else 'bad') if value is not None else None}
        return targets

    @request_memo
    def _tooltip_accounting_months(self, ids, start, end):
        """Aggregate all comparison months in one query using the accounting basis."""
        categories = self.env['baseer.dashboard2.category'].with_context(allowed_company_ids=ids).search([])
        lines = self.env['account.move.line'].with_context(allowed_company_ids=ids)
        rows = lines._read_group(self._aml_domain(ids, start, end), ['date:month', 'company_id', 'account_id'], ['debit:sum', 'credit:sum'])
        grouped = defaultdict(lambda: defaultdict(float))
        grouped_accounts = defaultdict(dict)
        for month, company, account, debit, credit in rows:
            key = self._category(account.with_company(company), categories)
            if key:
                amount = (credit - debit) if key in ('revenue', 'other_income') else (debit - credit)
                grouped[month.strftime('%Y-%m')][key] += amount
                grouped_accounts[month.strftime('%Y-%m')][f'{company.id}:{account.id}'] = round(amount, 2)
        result = {}
        for month, totals in grouped.items():
            sales = totals['revenue']
            gross = sales - totals['food_cost']
            operating = gross - sum(totals[k] for k in ('salaries', 'rent', 'utilities', 'marketing', 'commissions', 'other_opex', 'depreciation', 'non_operating'))
            net = operating + totals['other_income'] - totals['zakat_tax']
            fixed = sum(totals[k] for k in ('salaries', 'rent', 'utilities', 'depreciation'))
            variable = sum(totals[k] for k in ('food_cost', 'commissions', 'marketing', 'other_opex'))
            breakeven = fixed / (1 - variable / sales) if sales and variable / sales < 1 else None
            result[month] = {'account_values': grouped_accounts[month], 'categories': {k: round(v, 2) for k, v in totals.items()},
                             'sales_net': round(sales, 2), 'gross_profit': round(gross, 2),
                             'operating_profit': round(operating, 2), 'net_profit': round(net, 2),
                             'breakeven': round(breakeven, 2) if breakeven is not None else None,
                             'ratios': {k: (food_ratio(v, sales) if k == 'food_pct' else round(v / sales * 100, 2) if sales else None) for k, v in {
                                 'food_pct': totals['food_cost'], 'salaries_pct': totals['salaries'],
                                 'prime_pct': totals['food_cost'] + totals['salaries'], 'net_margin_pct': net}.items()}}
        return result

    def _accounting_sections(self, ids, section, start, end, previous_start, previous_end, companies, params):
        tax_inclusive = self._pnl_tax_inclusive(params) if section == 'pnl' else None
        accounting = (lambda company_ids, first, last: self._accounting_pnl_verified(company_ids, first, last, tax_inclusive)) if section == 'pnl' else self._accounting_gross
        current = accounting(ids, start, end)
        previous = accounting(ids, previous_start, previous_end)
        bounds = self.env['account.move.line'].with_context(allowed_company_ids=ids)._read_group(
            [('company_id', 'in', ids), ('parent_state', '=', 'posted')], [], ['date:min', 'date:max'])
        first_data, last_data = bounds[0] if bounds else (None, None)
        posted_months = self._posted_months(ids)
        def covered(first, last):
            return any(first.strftime('%Y-%m') <= month <= last.strftime('%Y-%m') for month in posted_months)
        trend = []
        for offset in ((0,) if section == 'pnl' else range(-5, 1)):
            first, last = month_bounds(end, offset)
            trend.append({'month': first.strftime('%Y-%m'), 'data': accounting(ids, first, min(last, end)),
                          'has_data': covered(first, min(last, end)), 'partial': bool(first <= min(end, fields.Date.context_today(self), last_data or end) < last)})
        if section in ('overview', 'expenses', 'ratios'):
            prior_end = end.replace(year=end.year - 1, day=min(end.day, calendar.monthrange(end.year - 1, end.month)[1]))
            first_prior, _ = month_bounds(prior_end, -5)
            _, last_prior = month_bounds(prior_end)
            previous_year = self._tooltip_accounting_months(ids, first_prior, last_prior)
            for key, data in previous_year.items():
                first, last = month_bounds(date.fromisoformat(key + '-01'))
                previous_year[key] = self._accounting_gross(ids, first, last, data)
            for month in trend:
                key = str(int(month['month'][:4]) - 1) + month['month'][4:]
                month['previous_year'] = previous_year.get(key) if key in posted_months else None
        targets = self._targets(ids, current)
        result = {'available': True, 'period': {'date_from': str(start), 'date_to': str(end)},
                  'current': current, 'previous': previous, 'trend': trend, 'targets': targets, 'has_data': covered(start, end)}
        if section != 'pnl':
            result.update(basis='inclusive', tax=current['tax'])
            if current['tax']['unallocated_input_vat_lines']:
                result['warnings'] = ['unallocated_input_vat']
        prior_months = sorted((m for m in posted_months if m < start.strftime('%Y-%m')), reverse=True)[:3]
        history_accounting = accounting if section == 'pnl' else self._accounting
        prior_salaries = [history_accounting(ids, *month_bounds(date.fromisoformat(m + '-01')))['categories'].get('salaries', 0) for m in prior_months] if len(prior_months) == 3 else []
        result['salaries_warning'] = covered(start, end) and low_salaries(current['categories'].get('salaries', 0), prior_salaries)
        before_previous_months = sorted((m for m in posted_months if m < previous_start.strftime('%Y-%m')), reverse=True)[:3]
        before_previous_salaries = [self._accounting(ids, *month_bounds(date.fromisoformat(m + '-01')))['categories'].get('salaries', 0) for m in before_previous_months] if section != 'pnl' else []
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
                                       'previous_trend': [None] + [value(m['data'], key) if m['has_data'] else None for m in trend[:-1]], 'previous_year_trend': [value(m['previous_year'], key) if m.get('previous_year') else None for m in trend], 'good_when': 'down' if key in expense_keys or key == 'expenses_total' else 'up'}
            bridge = [('sales_net', current['sales_net']), ('food_cost', -current['categories'].get('food_cost', 0)), ('gross_profit', current['gross_profit']),
                      ('salaries', -current['categories'].get('salaries', 0)), ('rent', -current['categories'].get('rent', 0))]
            commission = self._recorded_app_commissions(ids, start, end)
            if not self._recorded_app_commissions(ids, start, end, include_tax=False):
                commission = 0
            bridge += [(k, -(commission if k == 'commissions' else current['categories'].get(k, 0)
                             + (current['categories'].get('non_operating', 0)
                                + current['categories'].get('commissions', 0) - commission if k == 'other_opex' else 0)))
                       for k in ('utilities', 'marketing', 'commissions', 'other_opex', 'depreciation')]
            bridge += [('operating_profit', current['operating_profit']), ('other_income', current['categories'].get('other_income', 0)), ('zakat_tax', -current['categories'].get('zakat_tax', 0)), ('net_profit', current['net_profit'])]
            result['bridge'] = [{'key': key, 'amount': amount, 'pct': percent(amount, current['sales_net'])} for key, amount in bridge if amount or key in ('sales_net', 'gross_profit', 'operating_profit', 'net_profit')]
            result['breakeven_series'] = [{'month': m['month'], 'partial': m['partial'], 'sales_net': m['data']['sales_net'] if m['has_data'] else None, 'net_profit': m['data']['net_profit'] if m['has_data'] else None, 'breakeven': m['data']['breakeven'] if m['has_data'] else None, 'safety_margin': m['data']['safety_margin'] if m['has_data'] else None, 'margin_pct': m['data']['ratios']['net_margin_pct'] if m['has_data'] else None, 'previous_year': m.get('previous_year')} for m in trend]
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
                                    'data': accounting(ids, first, min(last, end)),
                                    'partial': bool(first <= min(end, fields.Date.context_today(self), last_data or end) < last)})
            for month in mini_months:
                month_start, month_end = month_bounds(date.fromisoformat(month['month'] + '-01'))
                month_end = min(month_end, end)
                purchase = self._purchases(ids, month_start, month_end, month['data']['sales_net'])
                result['purchases']['trend'].append({'month': month['month'], 'partial': month['partial'], **purchase, 'has_data': bool(purchase.get('has_bills')),
                                                    'value': purchase['value'] if purchase.get('has_bills') else None,
                                                    'pct': purchase['pct'] if purchase.get('has_bills') else None})
                monthly_sales, _, _, _ = self._sales_summary(ids, month_start, month_end)
                monthly_sales['apps_pct'] = percent(monthly_sales['apps'], month['data']['sales_net'])
                sales_trend.append({'month': month['month'], 'has_data': bool(monthly_sales['source_counts']['pos'] or monthly_sales['source_counts']['summary']), **monthly_sales})
            prior_start = date(end.year - 1, 1, 1)
            prior_finish = date(end.year - 1, end.month, calendar.monthrange(end.year - 1, end.month)[1])
            prior_mini = self._tooltip_sales_months(ids, prior_start, prior_finish)
            purchase_prior = self._tooltip_purchase_months(ids, prior_start, prior_finish)
            prior_accounting = self._tooltip_accounting_months(ids, prior_start, prior_finish)
            settings = self.env['baseer.dashboard2.settings'].with_context(allowed_company_ids=ids).search([('company_id', 'in', ids)])
            purchase_accounts = {(setting.company_id.id, account.id) for setting in settings for account in setting.food_purchase_account_ids}
            for key, data in prior_accounting.items():
                first, last = month_bounds(date.fromisoformat(key + '-01'))
                prior_accounting[key] = self._accounting_gross(ids, first, last, data)
                if key in purchase_prior:
                    allocated = self._tax_basis(ids, first, last)['accounts']
                    purchase_prior[key] = round(purchase_prior[key] + sum(allocated.get(pair, 0) for pair in purchase_accounts), 2)
            for month in result['purchases']['trend']:
                prior_key = str(int(month['month'][:4]) - 1) + month['month'][4:]
                amount = purchase_prior.get(prior_key)
                sales = prior_accounting.get(prior_key, {}).get('sales_net')
                month['previous_year'] = {'value': amount, 'pct': food_ratio(amount, sales) if amount is not None else None}
            for month in sales_trend:
                prior_key = str(int(month['month'][:4]) - 1) + month['month'][4:]
                month['previous_year'] = prior_mini.get(prior_key)
            sales, days, channels, hours = self._sales_summary(ids, start, end)
            prior_sales, _, _, _ = self._sales_summary(ids, previous_start, previous_end)
            prior_sales['apps_pct'] = percent(prior_sales['apps'], previous['sales_net'])
            result['sales'] = dict(sales)
            result['sales']['apps_pct'] = percent(sales['apps'], current['sales_net'])
            if not days:
                result['sales']['apps'] = None
            result['sales']['previous'] = prior_sales
            result['sales']['apps_change_pct'] = change(result['sales']['apps'], prior_sales['apps'])
            result['sales']['customers_change_pct'] = change(sales['customers']['value'], prior_sales['customers']['value'])
            result['sales']['trend'] = sales_trend
            result['timeline'] = self._timeline(ids, end, params.get('timeline_mode', 'monthly'))
            result.update(self._overview_layout(ids, start, end, params['period']['mode'], current, previous, result, days, covered, first_data, last_data, companies))
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
            if current['breakeven'] is None and not incomplete:
                result['breakeven']['reason'] = 'invalid_contribution_margin'
            elif current['breakeven'] is not None and not incomplete and sales['gross']:
                cumulative = 0
                for day in sorted({d for _, d in days}):
                    cumulative += sum(sum(data['channels'].values()) for (_, d), data in days.items() if d == day)
                    if cumulative * current['sales_net'] / sales['gross'] >= current['breakeven']:
                        result['breakeven']['day'] = day.day
                        break
            if section == 'overview' and incomplete:
                result['breakeven_series'][-1]['breakeven'] = None
                result['breakeven_series'][-1]['safety_margin'] = None
        if section == 'expenses':
            rows = []
            for key in expense_keys:
                if key in ('zakat_tax', 'non_operating'):
                    continue
                def displayed_amount(data):
                    return data['categories'].get(key, 0) + (data['categories'].get('non_operating', 0) if key == 'other_opex' else 0)
                amount = displayed_amount(current)
                rows.append({'key': key, 'amount': amount, 'previous': displayed_amount(previous),
                             'trend': [displayed_amount(m['data']) if m['has_data'] else None for m in trend], 'pct': percent(amount, current['sales_net']),
                             'accounts': sorted([a for a in current['accounts'] if a['category'] == key or (key == 'other_opex' and a['category'] == 'non_operating')], key=lambda x: x['amount'], reverse=True)})
            result['ranked'] = sorted((r for r in rows if r['amount'] or any(r['trend'])), key=lambda x: x['amount'], reverse=True)
            total = sum(current['categories'].get(k, 0) for k in expense_keys if k != 'zakat_tax')
            result['ring'] = {'available': bool(current['sales_net']), 'value': percent(total, current['sales_net']), 'reason': False if current['sales_net'] else 'zero_sales'}
        if section == 'pnl':
            view = params.get('pnl_view', PNL_DEFAULT_VIEW)
            if view not in ('month', 'quarter', 'year', 'range'):
                raise UserError(translate('Invalid P&L view.'))
            first_period, last_period = self._pnl_bounds(start, end, params)
            pnl_trend = []
            first = month_bounds(first_period)[0]
            while first <= last_period:
                _, last = month_bounds(first)
                clipped_first, clipped_last = max(first, first_period), min(last, last_period)
                pnl_trend.append({'month': first.strftime('%Y-%m'), 'first': clipped_first, 'last': clipped_last,
                    'data': accounting(ids, clipped_first, clipped_last),
                    'has_data': covered(clipped_first, clipped_last),
                    'partial': bool(clipped_first > first or clipped_last < last or first <= min(fields.Date.context_today(self), last_data or last) < last)})
                first = month_bounds(first, 1)[0]
            if len(pnl_trend) > 1 and view != 'quarter':
                prior_rows = {}
                prior_sales_pnl = {}
                for month in pnl_trend:
                    def previous_year(day):
                        year = day.year - 1
                        return day.replace(year=year, day=min(day.day, calendar.monthrange(year, day.month)[1]))
                    prior_first, prior_last = previous_year(month['first']), previous_year(month['last'])
                    prior_key = prior_first.strftime('%Y-%m')
                    prior_rows[prior_key] = accounting(ids, prior_first, prior_last)
                    summary, _days, _channels, _hours = self._sales_summary(ids, prior_first, prior_last)
                    prior_sales_pnl[prior_key] = summary
                    month['previous_year'] = prior_rows.get(prior_key) if prior_key in posted_months else None
            rows = []
            currency = self.env['res.company'].browse(ids[0]).currency_id
            report_engine = self.env['baseer.profit.loss.report']
            def decimal(value):
                return Decimal(str(value or 0))
            def monetary(value):
                return Decimal(report_engine._format_money(decimal(value), currency).replace(',', ''))
            def ratio(value, base):
                return float(percent(value, base)) if base else None
            def number(value):
                return self._pnl_json_money(value)
            arabic_lang = 'ar_001' if self.env['res.lang']._get_data(code='ar_001').code else self.env.lang
            category_names = {c.code: c.name for c in self.env['baseer.dashboard2.category'].with_context(allowed_company_ids=ids, lang=arabic_lang).search([])}
            monthly_channels = []
            for month in pnl_trend:
                first, last = month['first'], month['last']
                summary, _, channels, _ = self._sales_summary(ids, first, last)
                monthly_channels.append((summary, channels))
            for key in ('revenue', 'food_cost', 'gross_profit', 'salaries', 'rent', 'utilities', 'marketing', 'commissions', 'other_opex', 'depreciation', 'zakat_tax', 'operating_profit', 'other_income', 'other_expense', 'net_profit'):
                factor = -1 if key in expense_keys or key == 'other_expense' else 1
                values = [factor * decimal(m['data'].get(key, m['data']['categories'].get(key, 0))) if m['has_data'] else None for m in pnl_trend]
                if key == 'other_opex':
                    values = [value - decimal(m['data']['categories'].get('non_operating', 0)) if value is not None else None for value, m in zip(values, pnl_trend)]
                children = {}
                for i, month in enumerate(pnl_trend):
                    if key == 'revenue':
                        summary, channels = monthly_channels[i]
                        gross = {channel: decimal(amount) for channel, amount in summary['channels'].items()}
                        net = decimal(month['data']['sales_net'])
                        if month['has_data'] and net:
                            names = {c['key']: c['name'] for c in channels}
                            names.update({'other': 'أخرى', 'unclassified': 'غير مصنف'})
                            shares = {k: monetary(net * v / sum(gross.values())) for k, v in gross.items()} if sum(gross.values()) else {'unclassified': net}
                            largest = max(shares, key=lambda k: abs(gross.get(k, 0)))
                            shares[largest] = monetary(shares[largest] + net - sum(shares.values()))
                            for channel, amount in shares.items():
                                row = children.setdefault(channel, {'key': 'channel:' + channel, 'code': '', 'name': names.get(channel, channel), 'months': [0 if m['has_data'] else None for m in pnl_trend]})
                                row['months'][i] = amount
                        continue
                    for account in month['data']['accounts']:
                        if account['category'] == key or (key == 'other_opex' and account['category'] == 'non_operating'):
                            ident = (account['company_id'], account['account_id'])
                            row = children.setdefault(ident, {'key': '%s:%s' % ident, 'code': account['code'], 'name': account['name'], 'months': [0 if m['has_data'] else None for m in pnl_trend]})
                            row['months'][i] += factor * decimal(account['amount'])
                for child in children.values():
                    if child['key'].startswith('channel:') and len(pnl_trend) > 1 and view != 'quarter':
                        prior_values = []
                        for month in pnl_trend:
                            prior_key = str(int(month['month'][:4]) - 1) + month['month'][4:]
                            accounting = month.get('previous_year')
                            gross = {channel: decimal(amount) for channel, amount in prior_sales_pnl.get(prior_key, {}).get('channels', {}).items()}
                            net = decimal(accounting['sales_net']) if accounting else None
                            if net is None or not net:
                                prior_values.append(None if net is None else 0)
                                continue
                            shares = {k: monetary(net * v / sum(gross.values())) for k, v in gross.items()} if sum(gross.values()) else {'unclassified': net}
                            largest = max(shares, key=lambda k: abs(gross.get(k, 0)))
                            shares[largest] = monetary(shares[largest] + net - sum(shares.values()))
                            prior_values.append(shares.get(child['key'].split(':', 1)[1], 0))
                        child['previous_year_months'] = prior_values
                    elif not child['key'].startswith('channel:'):
                        child['previous_year_months'] = [factor * decimal(m['previous_year']['account_values'].get(child['key'], 0)) if m.get('previous_year') else None for m in pnl_trend]
                    child_total = monetary(sum((decimal(v) for v in child['months'] if v is not None), Decimal('0')))
                    child['total'] = number(child_total)
                    child['pct'] = ratio(child_total, sum((decimal(m['data']['sales_net']) for m in pnl_trend), Decimal('0')))
                    child['months'] = [number(v) for v in child['months']]
                    if 'previous_year_months' in child:
                        child['previous_year_months'] = [number(v) for v in child['previous_year_months']]
                total = sum(v for v in values if v is not None)
                prior_values = [factor * decimal(m['previous_year'].get(key, m['previous_year']['categories'].get(key, 0))) if m.get('previous_year') else None for m in pnl_trend]
                if key == 'other_opex':
                    prior_values = [v - decimal(m['previous_year']['categories'].get('non_operating', 0)) if v is not None else None for v, m in zip(prior_values, pnl_trend)]
                rows.append({'key': key, 'name': False if key == 'other_opex' else category_names.get(key), 'previous_year_months': [number(v) for v in prior_values], 'months': [number(v) for v in values], 'total': number(monetary(total)), 'pct': ratio(total, sum((decimal(m['data']['sales_net']) for m in pnl_trend), Decimal('0'))), 'children': list(children.values())})
            if view == 'quarter':
                for row in rows:
                    for item in [row] + row['children']:
                        item['months'] = [item['total'] if any(v is not None for v in item['months']) else None]
                        item.pop('previous_year_months', None)
                quarter = (end.month - 1) // 3 + 1
                columns = [{'month': first_period.strftime('%Y-%m'), 'label': 'الربع %s %s' % (('الأول', 'الثاني', 'الثالث', 'الرابع')[quarter - 1], end.year),
                            'partial': fields.Date.context_today(self) <= last_period}]
            else:
                columns = [{'month': m['month'], 'partial': m['partial']} for m in pnl_trend]
            result['pnl_columns'] = columns
            result['rows'] = rows
            result['basis'] = 'inclusive' if tax_inclusive else 'exclusive'
        return result

    def _revenue(self, ids, start, end, previous_start, previous_end, params):
        current, days, channels, hours = self._sales_summary(ids, start, end)
        previous, _, _, _ = self._sales_summary(ids, previous_start, previous_end)
        accounting = self._accounting_gross(ids, start, end)
        previous_accounting = self._accounting_gross(ids, previous_start, previous_end)
        bounds = self.env['account.move.line'].with_context(allowed_company_ids=ids)._read_group(
            [('company_id', 'in', ids), ('parent_state', '=', 'posted')], [], ['date:min', 'date:max'])
        first_data, last_data = bounds[0] if bounds else (None, None)
        posted_months = self._posted_months(ids)
        monthly = []
        for offset in range(-9, 1):
            first, last = month_bounds(end, offset)
            summary, _, _, _ = self._sales_summary(ids, first, min(last, end))
            summary['gross'] = self._accounting_gross(ids, first, min(last, end))['sales_net']
            summary['apps_pct'] = percent(summary['apps'], summary['gross'])
            monthly.append({'month': first.strftime('%Y-%m'), 'data': summary,
                            'has_data': first.strftime('%Y-%m') in posted_months,
                            'partial': bool(first <= min(end, fields.Date.context_today(self), last_data or end) < last)})
        prior_end = end.replace(year=end.year - 1, day=min(end.day, calendar.monthrange(end.year - 1, end.month)[1]))
        prior_first, _ = month_bounds(prior_end, -9)
        _, prior_last = month_bounds(prior_end)
        prior_sales = self._tooltip_sales_months(ids, prior_first, prior_last)
        prior_accounting = self._tooltip_accounting_months(ids, prior_first, prior_last)
        for key, data in prior_accounting.items():
            first, last = month_bounds(date.fromisoformat(key + '-01'))
            prior_accounting[key] = self._accounting_gross(ids, first, last, data)
        for month in monthly:
            prior_key = str(int(month['month'][:4]) - 1) + month['month'][4:]
            month['previous_year'] = prior_sales.get(prior_key)
            if month['previous_year'] is not None and prior_key in prior_accounting:
                month['previous_year']['gross'] = prior_accounting[prior_key]['sales_net']
        apps_trend = monthly
        monthly = monthly[-6:]
        known = {c['key']: c for c in channels}
        known['other'] = {'key': 'other', 'name': 'أخرى', 'kind': 'hall', 'color_token': False, 'commission_rate': 0}
        channel_gross, prior_channel_gross = current['gross'], previous['gross']
        current['gross'], previous['gross'] = accounting['sales_net'], previous_accounting['sales_net']
        current['apps_pct'] = percent(current['apps'], current['gross'])
        previous['apps_pct'] = percent(previous['apps'], previous['gross'])
        rows = []
        for key in set(known) | set(current['channels']) | set(previous['channels']):
            channel = known[key]
            amount = current['channels'].get(key, 0)
            before = previous['channels'].get(key, 0)
            rows.append({'key': key, 'name': channel['name'], 'kind': channel['kind'], 'color_token': channel['color_token'],
                         'amount': amount, 'share_pct': percent(amount, current['gross']), 'change_pct': change(amount, before),
                         'trend': [m['data']['channels'].get(key, 0) if m['has_data'] else None for m in monthly]})
        difference = round(current['gross'] - channel_gross, 2)
        previous_difference = round(previous['gross'] - prior_channel_gross, 2)
        differences = [round(m['data']['gross'] - sum(m['data']['channels'].values()), 2) if m['has_data'] else None for m in monthly]
        if abs(difference) >= 0.01:
            rows.append({'key': 'accounting_adjustments', 'name': 'فواتير وتسويات أخرى', 'kind': 'hall', 'color_token': False,
                         'amount': difference, 'share_pct': percent(difference, current['gross']),
                         'change_pct': change(difference, previous_difference), 'trend': differences})
        commission_amount = self._recorded_app_commissions(ids, start, end)
        split = {'hall': round(current['gross'] - current['apps'], 2), 'apps': current['apps']}
        if not days:
            current = dict(current, gross=current['gross'] if current['gross'] else None, apps=None)
            split = {'hall': None, 'apps': None}
        return {'available': True, 'basis': 'inclusive', 'tax': accounting['tax'],
                'warnings': ['unallocated_input_vat'] if accounting['tax']['unallocated_input_vat_lines'] else [],
                'current': current, 'previous': previous, 'trend': monthly, 'apps_trend': apps_trend,
                'ranked': sorted((row for row in rows if row['amount'] or any(row['trend'])), key=lambda row: row['amount'], reverse=True),
                'split': split,
                'commissions': {'available': bool(commission_amount), 'amount': commission_amount},
                'timeline': self._timeline(ids, end, params.get('timeline_mode', 'monthly'))}

    def _inout(self, ids, end):
        bounds = self.env['account.move.line'].with_context(allowed_company_ids=ids)._read_group([('company_id', 'in', ids), ('parent_state', '=', 'posted')], [], ['date:max'])
        last_data = bounds[0][0] if bounds else None
        months = []
        first = month_bounds(end, -5)[0]
        out_by_month = self._cash_out(ids, first, end, split=True)
        bill_ends = [min(month_bounds(end, offset)[1], end) for offset in range(-5, 1)]
        unpaid_by_end = self._unpaid_bills_batch(ids, bill_ends)
        for offset in range(-5, 1):
            start, last = month_bounds(end, offset)
            last = min(last, end)
            sales, _, _, _ = self._sales_summary(ids, start, last)
            out = out_by_month.get(start.strftime('%Y-%m'), {'available': True, 'unconfigured_company_ids': [], 'total': 0, 'items': {}, 'sources': {}})
            vat = self._sales_vat(ids, start, last)
            sales['available'] = bool(sales['channels'])
            months.append({'month': start.strftime('%Y-%m'), 'partial': bool(start <= min(end, last_data or end) < month_bounds(start)[1]), 'incoming': sales, 'outgoing': out,
                           'unpaid_bills': unpaid_by_end[last], 'sales_vat': vat, 'net': round(sales['gross'] - out['total'], 2)})
        prior_end = end.replace(year=end.year - 1, day=min(end.day, calendar.monthrange(end.year - 1, end.month)[1]))
        prior_first, _ = month_bounds(prior_end, -5)
        _, prior_last = month_bounds(prior_end)
        prior_sales = self._tooltip_sales_months(ids, prior_first, prior_last)
        prior_out = self._cash_out(ids, prior_first, prior_last, split=True)
        for month in months:
            prior_key = str(int(month['month'][:4]) - 1) + month['month'][4:]
            incoming, outgoing = prior_sales.get(prior_key), prior_out.get(prior_key)
            month['previous_year'] = {'incoming': incoming, 'outgoing': outgoing,
                                      'net': round(incoming['gross'] - outgoing['total'], 2) if incoming and incoming['gross'] is not None and outgoing else None}
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
            event['name'] = english_months(event['name'])
            event['note'] = english_months(event['note'])
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
        hours_end = self._heatmap_hours_end(ids, first, last)
        current_summary, _, _, hours = self._sales_summary(ids, first, hours_end)
        matrix = [{'weekday': wd, 'hour': hour, 'orders': hours[(wd, hour)]['orders'] if (wd, hour) in hours else None, 'gross': round(hours[(wd, hour)]['gross'], 2) if (wd, hour) in hours else None} for wd in range(7) for hour in range(24)]
        return {'available': True, 'period': {'date_from': str(first), 'date_to': str(last)}, 'days': days, 'events': events, 'weekday_month': averages(first, last),
                'weekday_ytd': averages(year_start, last), 'year_calendar': year_calendar,
                'daily_average': {'current': round(current_summary['gross'] / len([d for d in days if d['gross'] is not None]), 2) if any(d['gross'] is not None for d in days) else None, 'previous': round(previous['gross'] / len({d for (_, d), row in prev_days.items() if not row.get('sales_missing')}), 2) if any(not row.get('sales_missing') for row in prev_days.values()) else None},
                'best_day': max((d for d in days if d['gross'] is not None), key=lambda d: d['gross'], default=None),
                'worst_day': min((d for d in days if d['gross'] is not None), key=lambda d: d['gross'], default=None),
                'hours': {'available': bool(hours), 'reason': False if hours else 'no_pos_days', 'matrix': matrix,
                          'period': {'date_from': str(first), 'date_to': str(hours_end)}, 'partial': hours_end < last}}


    def _snapshot(self, ids, start, end, sales_net=None):
        """One window of overview figures on the session-open-day basis.

        ``sales`` is the figure every overview card must use: the dated sales sources (POS sessions by the day they
        were opened, Noorix summaries) whenever the window has any, otherwise accounting revenue. Accounting revenue
        alone dates a session by its closing entry, so a session opened before midnight and closed after it would
        move into the next day (and a session opened on the last day of a month into the next month).
        ``net_profit`` is the accounting net re-based on that same sales figure, so sales - purchases - expenses
        always equals it.
        """
        accounting = self._accounting_gross(ids, start, end)
        sales, days, _channels, _hours = self._sales_summary(ids, start, end)
        from_sources = bool(days) or self._has_pos_session_closings(ids, start, end)
        basis_sales = sales['gross'] if from_sources else accounting['sales_net']
        purchases = self._purchases(ids, start, end, sales_net if sales_net is not None else basis_sales)
        expenses = expenses_ex_purchases(accounting)
        return {
            'sales': basis_sales,
            'sales_from_sources': from_sources,
            'sales_net': accounting['sales_net'],
            'sales_gross': sales['gross'],
            'apps': sales['apps'],
            'apps_pct': percent(sales['apps'], accounting['sales_net']),
            'customers': sales['customers'],
            'purchases': purchases['value'] if purchases.get('available', True) else None,
            'purchases_pct': purchases.get('pct'),
            'expenses': expenses,
            'expenses_pct': percent(expenses, basis_sales),
            'net_profit': round(accounting['net_profit'] + basis_sales - accounting['sales_net'], 2),
            'days': days,
            'has_sales_days': bool(days),
        }

    def _compare_metric(self, current, previous, previous_year, previous_year_ok):
        return {
            'previous': previous,
            'previous_change_pct': change(current, previous),
            'previous_year': previous_year if previous_year_ok else None,
            'previous_year_change_pct': change(current, previous_year) if previous_year_ok else None,
            'previous_year_label': None if previous_year_ok else ('بيانات ناقصة' if previous_year else 'لا بيانات'),
        }

    def _window_covered(self, ids, start, end):
        posted = self._posted_months(ids)
        return any(start.strftime('%Y-%m') <= month <= end.strftime('%Y-%m') for month in posted)

    def _single_day_sales(self, ids, snapshot, day, default):
        """Sales of a snapshot for a card, or ``default`` when the window has neither a sales source nor revenue.

        A POS session closing entry booked on a day belongs to the day the session was opened, so it is never read
        back as that day's sales while the window has sales sources (see ``_snapshot``).
        """
        if snapshot['sales_from_sources']:
            return snapshot['sales']
        return snapshot['sales'] or default

    def _overview_layout(self, ids, start, end, mode, current, previous, result, days, covered, first_data, last_data, companies):
        today = fields.Date.context_today(self)
        year_start, year_end = self._comparison_bounds(start, end, mode, 'previous_year')
        year_ok = self._window_covered(ids, year_start, year_end)
        month_start, month_last = month_bounds(end if mode != 'year' else today)
        month_end = min(month_last, today) if (month_start.year, month_start.month) == (today.year, today.month) else month_last
        if mode in ('today', 'date', 'yesterday'):
            focus = start
        elif mode != 'year' and start <= today <= end:
            focus = today
        else:
            focus = min(end, today) if today.year == end.year and today.month == end.month else end

        def pack(snapshot, key, comparisons, extra=None):
            payload = {'value': snapshot[key], **comparisons}
            if extra:
                payload.update(extra)
            return payload

        # Every card below reads the same session-open-day basis (see _snapshot): the sales card, the month card,
        # the net equation and every previous-period / previous-year comparison.
        period_snap = self._snapshot(ids, start, end)
        prev_start, prev_end = self._comparison_bounds(start, end, mode, 'previous_period')
        prev_snap = self._snapshot(ids, prev_start, prev_end)
        year_snap = self._snapshot(ids, year_start, year_end)
        year_ok = year_ok and (year_snap['sales'] or year_snap['has_sales_days'])

        cards = {
            'mode': mode,
            'date_from': str(start),
            'date_to': str(end),
            'partial': bool(mode == 'month' and end < month_last) or bool(mode == 'year' and end < date(end.year, 12, 31)),
        }

        if mode != 'year':
            day_snap = self._snapshot(ids, focus, focus)
            day_value = self._single_day_sales(ids, day_snap, focus, 0)
            prev_day_start, prev_day_end = self._comparison_bounds(focus, focus, 'date', 'previous_period')
            prev_day = self._snapshot(ids, prev_day_start, prev_day_end)
            year_day_start, year_day_end = self._comparison_bounds(focus, focus, 'date', 'previous_year')
            year_day = self._snapshot(ids, year_day_start, year_day_end)
            year_day_ok = self._window_covered(ids, year_day_start, year_day_end) and year_day['sales']
            cards['today_sales'] = pack(
                {'today_sales': day_value},
                'today_sales',
                self._compare_metric(day_value, self._single_day_sales(ids, prev_day, prev_day_start, None),
                                     self._single_day_sales(ids, year_day, year_day_start, None), year_day_ok),
                {'date': str(focus)},
            )
            # A one-day view (today / yesterday / a picked day) accumulates the month up to that same day, so the
            # month card and its previous-month window (the 1st to the same day number) end where the day card does.
            mtd_end = min(month_end, focus) if mode in ('today', 'date', 'yesterday') else month_end
            mtd_sales = self._snapshot(ids, month_start, mtd_end)['sales']
            prev_mtd_start, prev_mtd_end = self._comparison_bounds(month_start, mtd_end, 'month', 'previous_period')
            year_mtd_start, year_mtd_end = self._comparison_bounds(month_start, mtd_end, 'month', 'previous_year')
            prev_mtd = self._snapshot(ids, prev_mtd_start, prev_mtd_end)
            year_mtd = self._snapshot(ids, year_mtd_start, year_mtd_end)
            year_mtd_ok = self._window_covered(ids, year_mtd_start, year_mtd_end) and (year_mtd['sales'] or year_mtd['has_sales_days'])
            cards['period_sales'] = pack(
                {'period_sales': mtd_sales},
                'period_sales',
                self._compare_metric(mtd_sales, prev_mtd['sales'] or None, year_mtd['sales'] or None, year_mtd_ok),
                {'date_from': str(month_start), 'date_to': str(mtd_end), 'kind': 'mtd'},
            )
        else:
            cards['period_sales'] = pack(
                {'period_sales': period_snap['sales']},
                'period_sales',
                self._compare_metric(period_snap['sales'], prev_snap['sales'] if self._window_covered(ids, prev_start, prev_end) else None,
                                     year_snap['sales'] or None, year_ok),
                {'date_from': str(start), 'date_to': str(end), 'kind': 'ytd'},
            )

        purchases = period_snap['purchases']
        expenses = period_snap['expenses']
        net = period_snap['net_profit']
        prev_purchases = prev_snap['purchases']
        prev_expenses = prev_snap['expenses']
        prev_net = prev_snap['net_profit']
        cards['net'] = pack(
            {'net': net}, 'net',
            self._compare_metric(net, prev_net, year_snap['net_profit'], year_ok),
            {
                'salaries_warning': result.get('salaries_warning'),
                'equation': {'sales': period_snap['sales'], 'purchases': purchases or 0, 'expenses': expenses},
            },
        )
        cards['purchases'] = pack(
            {'purchases': purchases}, 'purchases',
            self._compare_metric(purchases, prev_purchases, year_snap['purchases'], year_ok),
            {'pct': period_snap['purchases_pct']},
        )
        cards['expenses'] = pack(
            {'expenses': expenses}, 'expenses',
            self._compare_metric(expenses, prev_expenses, year_snap['expenses'], year_ok),
            {'pct': period_snap['expenses_pct']},
        )

        sales_line = self._sales_line(ids, start, end, mode, days, today, result)
        sales = result.get('sales')
        if sales is not None:
            prior_apps = year_snap['apps'] if year_ok else None
            prior_customers = (year_snap.get('customers') or {}) if year_ok else {}
            sales['previous_year'] = {
                'apps': prior_apps,
                'customers': year_snap.get('customers') if year_ok else None,
            }
            sales['apps_previous_year_change_pct'] = change(sales.get('apps'), prior_apps) if year_ok else None
            current_customers = (sales.get('customers') or {}).get('value')
            sales['customers_previous_year_change_pct'] = (
                change(current_customers, prior_customers.get('value')) if year_ok else None
            )
            sales['previous_year_label'] = None if year_ok else (
                'بيانات ناقصة' if (year_snap.get('sales_net') or year_snap.get('has_sales_days')) else 'لا بيانات'
            )
        return {'cards': cards, 'sales_line': sales_line}

    def _sales_line(self, ids, start, end, mode, days, today, result):
        if mode == 'year':
            points = []
            peak = None
            for month in range(1, 13):
                first, last = month_bounds(date(end.year, month, 1))
                key = first.strftime('%Y-%m')
                month_end = min(last, end)
                future = first > end
                value = self._accounting_gross(ids, first, month_end)['sales_net'] if not future and self._window_covered(ids, first, month_end) else None
                row = next((item for item in result['sales']['trend'] if item['month'] == key), None)
                prior = row.get('previous_year') if row else None
                prior_value = prior.get('gross') if isinstance(prior, dict) else prior
                if prior_value is None and not future:
                    prior_first, prior_last = month_bounds(date(end.year - 1, month, 1))
                    prior_value = self._accounting_gross(ids, prior_first, prior_last)['sales_net'] if self._window_covered(ids, prior_first, prior_last) else None
                point = {
                    'key': key,
                    'label': month_label(key, short=True),
                    'value': None if future else value,
                    'previous_year': None if future else prior_value,
                    'empty': future or value is None,
                    'current': first.month == end.month,
                    'partial': (not future) and month_end < last,
                }
                points.append(point)
                if point['value'] is not None and (peak is None or point['value'] > peak['value']):
                    peak = {'key': key, 'label': month_label(key), 'value': point['value']}
            return {'granularity': 'month', 'points': points, 'peak': peak, 'year': end.year}
        # Daily line for the month containing the selected period.
        month_start, month_last = month_bounds(end)
        month_end = min(month_last, today, end if end >= month_start else month_last)
        # Load the whole month so today/yesterday/date still show the month curve.
        sales, month_days, _channels, _hours = self._sales_summary(ids, month_start, min(month_last, today))
        totals = {}
        for (_cid, day), data in month_days.items():
            totals[day] = totals.get(day, 0.0) + sum(data['channels'].values())
        points = []
        peak = None
        cursor = month_start
        while cursor <= month_last:
            future = cursor > today
            value = round(totals[cursor], 2) if cursor in totals else None
            point = {
                'key': str(cursor),
                'label': str(cursor.day),
                'value': None if future else value,
                'empty': future or value is None,
                'current': cursor == min(end, today),
                'partial': False,
            }
            points.append(point)
            if point['value'] is not None and (peak is None or point['value'] > peak['value']):
                peak = {'key': str(cursor), 'label': month_label(cursor), 'value': point['value'], 'day': cursor.day}
            cursor += timedelta(days=1)
        return {'granularity': 'day', 'points': points, 'peak': peak, 'month': month_start.strftime('%Y-%m')}

    @api.model
    def get_section(self, section, params=None):
        self._check_reader()
        if section not in ('overview', 'revenue', 'expenses', 'ratios', 'pnl', 'inout', 'heatmap', 'glossary'):
            raise UserError(_('Unknown dashboard section.'))
        if section == 'glossary':
            return {'sources': SOURCES}
        params = params or {}
        self = self.with_context(_bd2_request_cache={})
        companies = self._companies()
        if not companies:
            return {'available': False, 'reason': 'empty_company_scope'}
        ids = self._scope(params.get('company_key'))
        period = params.get('period') or {}
        start, end = self._period(period)
        mode = period.get('mode') or 'today'
        previous_start, previous_end = self._comparison_bounds(start, end, mode, 'previous_period')
        params = dict(params, period=dict(period, mode=mode))
        year_start, year_end = self._comparison_bounds(start, end, mode, 'previous_year')
        if section in ('overview', 'revenue', 'expenses', 'ratios'):
            self = self.with_context(_bd2_tax_window=(min(start, previous_start, year_start, date(max(1, end.year - 5), 1, 1)), end),
                                     _bd2_tax_companies=[cid for cid, _, _ in companies])
        if section in ('overview', 'expenses', 'ratios', 'pnl'):
            return self._accounting_sections(ids, section, start, end, previous_start, previous_end, companies, params)
        if section == 'revenue':
            return self._revenue(ids, start, end, previous_start, previous_end, params)
        if section == 'inout':
            return self._inout(ids, end)
        return self._heatmap(ids, params.get('heatmap_month') or end.strftime('%Y-%m'))
