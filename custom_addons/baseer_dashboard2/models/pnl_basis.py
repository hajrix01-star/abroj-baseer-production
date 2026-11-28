"""Verified tax-basis accounting for the Dashboard 2 P&L only."""

from decimal import Decimal, ROUND_HALF_UP

from odoo import api, models, _
from odoo.exceptions import AccessError, UserError
from odoo.fields import Domain
from odoo.addons.baseer_reports_menu.report_drill import drill_result, exact_selector, positive_id
from odoo.addons.baseer_profit_loss_report.models.profit_loss import SECTION_KEYS

from .service import request_memo


class DashboardPnlBasis(models.AbstractModel):
    _inherit = 'baseer.dashboard2.service'

    @api.model
    def _pnl_json_money(self, amount):
        """Do not serialize a monetary value if JSON numbers lose its cents."""
        if amount is None:
            return None
        amount = Decimal(str(amount))
        value = float(amount)
        if not amount.is_finite() or Decimal(str(value)) != amount:
            raise UserError(_('The report amount exceeds the precision supported for display.'))
        return value

    @api.model
    def _pnl_tax_inclusive(self, params):
        value = params.get('tax_inclusive', True)
        if type(value) is not bool:
            raise UserError(_('Select a valid tax display option.'))
        return value

    @request_memo
    def _accounting_pnl_verified(self, ids, start, end, tax_inclusive):
        """Classify proved P&L amounts without crossing company boundaries."""
        self._check_reader()
        if type(tax_inclusive) is not bool or not ids or len(set(ids)) != len(ids):
            raise UserError(_('Select a valid tax display option.'))
        available = {item[0] for item in self._companies()}
        if not set(ids) <= available:
            raise AccessError(_('The selected company is not available.'))
        if end < start or (end - start).days >= 366:
            raise UserError(_('Select a period of no more than 366 days.'))
        companies = self.env['res.company'].browse(ids).exists()
        companies.check_access('read')
        if len(companies) != len(ids) or len(companies.mapped('currency_id')) != 1:
            raise UserError(_('Select companies using the same currency.'))
        currency = companies[0].currency_id
        categories = self.env['baseer.dashboard2.category'].with_context(allowed_company_ids=ids).search([])
        # Legacy dashboard prefixes could also classify asset/liability accounts.
        # Do not silently drop those rows when changing to the verified P&L scope.
        for company in companies:
            # Apply the same linked-record checks and verified-ID aggregation as
            # the report engine; an AML can be visible while its move is hidden.
            verifier = self.env['baseer.profit.loss.report'].with_company(company).with_context(
                allowed_company_ids=[company.id], _baseer_pl_inclusive=False)
            domain = Domain(self._aml_domain([company.id], start, end)) & Domain(
                'account_id.account_type', 'not in', list(SECTION_KEYS))
            for group in verifier._verified_groups(domain).values():
                account = group['account'].with_company(company)
                if group['debit'] != group['credit'] and self._category(account, categories):
                    raise UserError(_('A dashboard category includes a non-profit-and-loss account. Review the account classification.'))
        totals = {category.code: Decimal('0') for category in categories}
        totals['other_expense'] = Decimal('0')
        accounts = []
        arabic_lang = 'ar_001' if self.env['res.lang']._get_data(code='ar_001').code else self.env.lang
        for company in companies:
            engine = self.env['baseer.profit.loss.report'].with_company(company).with_context(
                allowed_company_ids=[company.id], _baseer_pl_inclusive=tax_inclusive,
            )
            engine._check_accounting_access()
            company.check_access('read')
            grouped = engine._section_rows(engine._domain(company, start, end, []))
            for rows in grouped.values():
                for row in rows:
                    account = row['account'].with_company(company)
                    # The P&L statement places income by its accounting type.
                    # A dashboard expense prefix (e.g. 999002 cash differences)
                    # must not move other income above operating profit.
                    key = ('revenue' if account.account_type == 'income' else
                           'other_income' if account.account_type == 'income_other' else
                           'food_cost' if account.account_type == 'expense_direct_cost' else
                           'other_expense' if account.account_type == 'expense_other' else
                           self._category(account, categories))
                    # Remaining expense types belong in operating expenses even
                    # when a configured prefix points at an income or cost group.
                    if account.account_type in ('expense', 'expense_depreciation') and key in ('revenue', 'other_income', 'food_cost'):
                        key = 'other_opex'
                    if not key or key not in totals:
                        raise UserError(_('A profit and loss account has no dashboard category.'))
                    amount = (row['credit'] - row['debit']) if key in ('revenue', 'other_income') else (row['debit'] - row['credit'])
                    totals[key] += amount
                    account_name = account.with_context(lang=arabic_lang).name or account.name or ''
                    if '|' in account_name:
                        parts = [part.strip() for part in account_name.split('|')]
                        account_name = next((part for part in parts if any('\u0600' <= char <= '\u06ff' for char in part)), parts[0])
                    accounts.append({'company_id': company.id, 'account_id': account.id, 'code': account.code,
                                     'name': account_name, 'category': key, 'amount': amount})
        sales = totals.get('revenue', Decimal('0'))
        gross = sales - totals.get('food_cost', Decimal('0'))
        operating = gross - sum((totals.get(key, Decimal('0')) for key in (
            'salaries', 'rent', 'utilities', 'marketing', 'commissions', 'other_opex', 'depreciation', 'non_operating', 'zakat_tax')), Decimal('0'))
        net = operating + totals.get('other_income', Decimal('0')) - totals.get('other_expense', Decimal('0'))
        fixed = sum((totals.get(key, Decimal('0')) for key in ('salaries', 'rent', 'utilities', 'depreciation')), Decimal('0'))
        variable = sum((totals.get(key, Decimal('0')) for key in ('food_cost', 'commissions', 'marketing', 'other_opex')), Decimal('0'))
        breakeven = fixed / (Decimal('1') - variable / sales) if sales and variable / sales < 1 else None

        def money(value):
            return self._pnl_json_money(Decimal(self.env['baseer.profit.loss.report']._format_money(value, currency).replace(',', '')))

        def ratio(value, precision='0.01'):
            return float((value * 100 / sales).quantize(Decimal(precision), rounding=ROUND_HALF_UP)) if sales else None

        for account in accounts:
            account['amount'] = money(account['amount'])
        return {'available': True, 'categories': {key: money(value) for key, value in totals.items()},
                'accounts': accounts, 'account_values': {f"{a['company_id']}:{a['account_id']}": a['amount'] for a in accounts},
                'sales_net': money(sales), 'gross_profit': money(gross), 'operating_profit': money(operating),
                'net_profit': money(net), 'breakeven': money(breakeven) if breakeven is not None else None,
                'safety_margin': money(sales - breakeven) if breakeven is not None else None,
                'fixed_costs': money(fixed), 'variable_ratio_pct': ratio(variable),
                'ratios': {'food_pct': ratio(totals.get('food_cost', Decimal('0')), '0.1'),
                           'salaries_pct': ratio(totals.get('salaries', Decimal('0'))),
                           'prime_pct': ratio(totals.get('food_cost', Decimal('0')) + totals.get('salaries', Decimal('0'))),
                           'net_margin_pct': ratio(net)}}

    def _pnl_detail_scope(self, descriptor):
        if type(descriptor) is not dict or set(descriptor) - {
                'section', 'key', 'child', 'column', 'company_key', 'period',
                'pnl_view', 'pnl_range', 'tax_inclusive'}:
            raise UserError(_('Unknown dashboard figure.'))
        if descriptor.get('section') != 'pnl':
            raise UserError(_('Unknown dashboard figure.'))
        self._check_reader()
        ids = self._scope(descriptor.get('company_key'))
        self = self._activate_scope(ids)
        tax = self._pnl_tax_inclusive(descriptor)
        start, end = self._period(descriptor.get('period') or {})
        first, last = self._pnl_bounds(start, end, descriptor)
        column = descriptor.get('column')
        if column is not None:
            if type(column) is not int or column < 0:
                raise UserError(_('Unknown dashboard figure.'))
            if descriptor.get('pnl_view') == 'quarter':
                if column:
                    raise UserError(_('Unknown dashboard figure.'))
            else:
                from .sections import month_bounds
                month_first, month_last = month_bounds(first, column)
                if month_first > last:
                    raise UserError(_('Unknown dashboard figure.'))
                first, last = max(first, month_first), min(last, month_last)
        categories = ('food_cost', 'salaries', 'rent', 'utilities', 'marketing', 'commissions',
                      'other_opex', 'depreciation', 'non_operating', 'zakat_tax')
        key = descriptor.get('key')
        mappings = {name: {name: (1 if name in ('revenue', 'other_income') else -1)} for name in (
            'revenue', 'food_cost', 'salaries', 'rent', 'utilities', 'marketing', 'commissions',
            'other_opex', 'depreciation', 'other_income', 'other_expense', 'zakat_tax')}
        mappings['other_opex']['non_operating'] = -1
        mappings['gross_profit'] = {'revenue': 1, 'food_cost': -1}
        mappings['operating_profit'] = {'revenue': 1, **{category: -1 for category in categories}}
        mappings['net_profit'] = {**mappings['operating_profit'], 'other_income': 1, 'other_expense': -1}
        if type(key) is not str or key not in mappings:
            raise UserError(_('Unknown dashboard figure.'))
        child = descriptor.get('child')
        if child is not None and (type(child) is not str or not child or len(child) > 50 or child.startswith('channel:')):
            raise UserError(_('Unknown dashboard figure.'))
        data = self.with_context(_bd2_request_cache={})._accounting_pnl_verified(ids, first, last, tax)
        selected = [account for account in data['accounts'] if account['category'] in mappings[key]]
        if child:
            selected = [account for account in selected if f"{account['company_id']}:{account['account_id']}" == child]
            if not selected:
                raise AccessError(_('The account is not available in this report.'))
        return ids, first, last, tax, mappings[key], selected

    def _pnl_details_account_rows(self, descriptor, company_id, account_id):
        ids, first, last, tax, factors, selected = self._pnl_detail_scope(descriptor)
        account_row = next((row for row in selected if row['company_id'] == company_id and row['account_id'] == account_id), None)
        if not account_row or company_id not in ids:
            raise AccessError(_('The account is not available in this report.'))
        company = self.env['res.company'].browse(company_id)
        engine = self.env['baseer.profit.loss.report'].with_company(company).with_context(allowed_company_ids=[company_id])
        filters = {'company_id': company_id, 'date_from': str(first), 'date_to': str(last),
                   'journal_ids': [], 'tax_inclusive': tax}
        parent = {'kind': 'account', 'account_id': account_id, 'period_key': 'current'}
        title, value, basis, columns, rows = engine._drill_rows(filters, parent)
        account = self.env['account.account'].with_company(company).browse(account_id)
        category_credit = account_row['category'] in ('revenue', 'other_income')
        natural_credit = account.account_type in ('income', 'income_other')
        sign = factors[account_row['category']] * (1 if category_credit == natural_credit else -1)

        def amount(text):
            return Decimal(text.replace(',', '')) * sign

        expected = Decimal(str(account_row['amount'])) * factors[account_row['category']]
        if amount(value) != expected or sum((amount(row['cells']['amount']) for row in rows), Decimal('0')) != expected:
            raise UserError(_('The dashboard detail no longer reconciles. Refresh the report.'))
        for row in rows:
            row['cells']['amount'] = engine._format_money(amount(row['cells']['amount']), company.currency_id)
            source = row.get('source')
            if source:
                row['source'] = {'kind': 'source', 'company_id': company_id, 'account_id': account_id,
                                 'line_id': source['line_id']}
        return engine, filters, parent, title, engine._format_money(expected, company.currency_id), basis, columns, rows

    @api.model
    def get_pnl_details(self, descriptor, selector, page=1):
        if type(selector) is not dict or selector.get('kind') not in ('row', 'account'):
            raise UserError(_('Unknown dashboard figure.'))
        if selector['kind'] == 'account':
            exact_selector(selector, {'kind', 'company_id', 'account_id'})
            positive_id(selector['company_id'])
            positive_id(selector['account_id'])
            _engine, _filters, _parent, title, value, basis, columns, rows = self._pnl_details_account_rows(
                descriptor, selector['company_id'], selector['account_id'])
            return drill_result(title, value, basis, columns, rows, page)
        exact_selector(selector, {'kind'})
        ids, _first, _last, _tax, factors, selected = self._pnl_detail_scope(descriptor)
        currency = self.env['res.company'].browse(ids[0]).currency_id
        engine = self.env['baseer.profit.loss.report']
        total = sum((Decimal(str(item['amount'])) * factors[item['category']] for item in selected), Decimal('0'))
        ar = (self.env.lang or '').startswith('ar')
        columns = [{'key': 'label', 'label': 'الحساب' if ar else 'Account'},
                   {'key': 'amount', 'label': 'المساهمة' if ar else 'Contribution', 'numeric': True}]
        rows = [{'key': f"{item['company_id']}:{item['account_id']}",
                 'cells': {'label': f"{item['code']} {item['name']}",
                           'amount': engine._format_money(Decimal(str(item['amount'])) * factors[item['category']], currency)},
                 'drill': {'kind': 'account', 'company_id': item['company_id'], 'account_id': item['account_id']}}
                for item in selected]
        return drill_result('تفاصيل البند' if ar else 'Item details', engine._format_money(total, currency),
                            'المبالغ بحسب الفترة وأساس الضريبة المختار.' if ar else 'Amounts follow the selected period and tax basis.',
                            columns, rows, page)

    @api.model
    def open_pnl_detail_source(self, descriptor, selector):
        exact_selector(selector, {'kind', 'company_id', 'account_id', 'line_id'})
        if selector['kind'] != 'source':
            raise UserError(_('Unknown dashboard figure.'))
        for key in ('company_id', 'account_id', 'line_id'):
            positive_id(selector[key])
        engine, filters, parent, _title, _value, _basis, _columns, rows = self._pnl_details_account_rows(
            descriptor, selector['company_id'], selector['account_id'])
        if not any(row.get('source') == selector for row in rows):
            raise AccessError(_('The source is not in this report detail.'))
        return engine._open_drill_source(filters, {'kind': 'source', 'parent': parent, 'line_id': selector['line_id']})
