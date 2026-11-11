"""Isolated projection of the posted P&L, preserving the billing report."""
from decimal import Decimal, ROUND_HALF_UP, localcontext
from odoo import _, api, models
from odoo.exceptions import AccessError, ValidationError
from odoo.addons.baseer_profit_loss_report.models.profit_loss import SECTION_KEYS, EXPENSE_KEYS


class FinancialDashboardReport(models.AbstractModel):
    _name = 'baseer.financial.dashboard.report'
    _inherit = 'baseer.profit.loss.report'
    _description = 'Financial Dashboard Profit and Loss Projection'

    @api.model
    def _dashboard_percentage(self, numerator, denominator):
        """Return a display-only percentage calculated beside the ledger totals.

        The browser receives a ready-to-display value and never parses or
        aggregates money.  A zero denominator is deliberately unavailable,
        rather than being presented as an invented 0% result.
        """
        # A margin/share has no interpretable denominator when net revenue is
        # zero or negative (for example a full sales reversal).  Do not turn a
        # return period into an artificial signed percentage.
        if denominator <= 0:
            return {'available': False, 'display': '', 'negative': False}
        with localcontext() as context:
            context.prec = max(28, len(numerator.as_tuple().digits)
                               + len(denominator.as_tuple().digits) + 6)
            value = (numerator * Decimal('100') / abs(denominator)).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP,
            )
        return {
            'available': True,
            'display': f'{value:,.2f}%',
            'negative': value < 0,
        }

    @api.model
    def _dashboard_change(self, current, comparison, higher_is_favorable=True):
        if comparison is None or not comparison:
            return {'available': False, 'display': '', 'direction': 'flat', 'tone': 'neutral'}
        with localcontext() as context:
            context.prec = max(28, len(current.as_tuple().digits)
                               + len(comparison.as_tuple().digits) + 6)
            value = ((current - comparison) * Decimal('100') / abs(comparison)).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP,
            )
        direction = 'up' if value > 0 else ('down' if value < 0 else 'flat')
        favorable = value > 0 if higher_is_favorable else value < 0
        return {
            'available': True,
            'display': f'{value:,.2f}%',
            'direction': direction,
            'tone': 'positive' if favorable else ('negative' if value else 'neutral'),
        }

    @api.model
    def _dashboard_margin_change(self, current, comparison):
        if (comparison is None or current['income'] <= 0
                or comparison['income'] <= 0):
            return {'available': False, 'display': '', 'direction': 'flat', 'tone': 'neutral'}
        with localcontext() as context:
            context.prec = max(28, *(len(value.as_tuple().digits) for value in (
                current['gross_profit'], current['income'], comparison['gross_profit'],
                comparison['income'],
            )))
            current_margin = current['gross_profit'] * Decimal('100') / abs(current['income'])
            comparison_margin = comparison['gross_profit'] * Decimal('100') / abs(comparison['income'])
            difference = (current_margin - comparison_margin).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP,
            )
        return {
            'available': True,
            'display': f'{difference:,.2f} pp',
            'direction': 'up' if difference > 0 else ('down' if difference < 0 else 'flat'),
            'tone': 'positive' if difference > 0 else ('negative' if difference < 0 else 'neutral'),
        }

    @api.model
    def _dashboard_payload(self, grouped_by_period, totals, periods, currency, journal_ids):
        """Build a visual P&L projection from the already verified ledger groups.

        This is intentionally a projection of ``_report_rows`` inputs, never a
        second accounting query.  It keeps the dashboard, table and exported
        report reconciled to exactly the same posted move lines.
        """
        current = totals['current']
        comparison_period = next((period for period in periods
                                  if period['key'] != 'current'), None)
        comparison = totals.get(comparison_period['key']) if comparison_period else None

        card_keys = (
            'income', 'cost_of_sales', 'gross_profit', 'expense', 'net_income',
        )
        cards = []
        for key in card_keys:
            cards.append({
                'key': key,
                'value': self._period_amount(current[key], currency),
                'change': self._dashboard_change(
                    current[key], comparison[key] if comparison else None,
                    higher_is_favorable=key not in ('cost_of_sales', 'expense'),
                ),
            })
        cards.insert(3, {
            'key': 'gross_margin',
            'value': self._dashboard_percentage(current['gross_profit'], current['income']),
            'change': self._dashboard_margin_change(current, comparison),
        })

        waterfall_values = (
            ('income', current['income']),
            ('cost_of_sales', -current['cost_of_sales']),
            ('expense', -current['expense']),
            ('net_other_income', current['net_other_income']),
            ('net_income', current['net_income']),
        )
        maximum = max((abs(value) for _key, value in waterfall_values), default=Decimal('0'))
        maximum = maximum or Decimal('1')
        waterfall = []
        for key, value in waterfall_values:
            width = int((abs(value) * Decimal('100') / maximum).quantize(
                Decimal('1'), rounding=ROUND_HALF_UP,
            ))
            waterfall.append({
                'key': key,
                'amount': self._period_amount(value, currency),
                'visual_width': width,
                'tone': 'positive' if value > 0 else ('negative' if value < 0 else 'neutral'),
            })

        revenue_rows = grouped_by_period['current']['income'] + grouped_by_period['current']['income_other']
        revenue_total = current['income'] + current['other_income']
        revenue_accounts = []
        for entry in sorted(revenue_rows, key=lambda item: (
                -item['raw'], item['account'].code or '', item['account'].id,
        ))[:5]:
            account = entry['account']
            revenue_accounts.append({
                'id': account.id,
                'code': account.code or '',
                'name': account.name or '',
                'amount': self._period_amount(entry['raw'], currency),
                'share': self._dashboard_percentage(entry['raw'], revenue_total),
            })

        notes = ['posted_only']
        if journal_ids:
            notes.append('partial_journals')
        notes.append('comparison_available' if comparison else 'comparison_unavailable')
        if current['income'] <= 0:
            notes.append('gross_margin_unavailable')
        if revenue_total <= 0:
            notes.append('revenue_share_unavailable')
        return {
            'cards': cards,
            'waterfall': waterfall,
            'revenue_accounts': revenue_accounts,
            'notes': notes,
        }

    @api.model
    def get_dashboard_report(self, filters):
        dashboard = self.env.ref('baseer_financial_dashboard.dashboard_financial_performance', raise_if_not_found=False)
        if not dashboard:
            raise AccessError(_('The financial dashboard is not available.'))
        dashboard.check_access('read')
        dashboard.check_access_rule('read')
        if dashboard.baseer_dashboard_kind != 'financial_dashboard' or not dashboard.is_published:
            raise AccessError(_('The financial dashboard is not available.'))
        if dashboard.group_ids and not (dashboard.group_ids & self.env.user.all_group_ids):
            raise AccessError(_('The financial dashboard is not available.'))
        company, journal_ids, periods, period_control, comparison_control = self._scope(filters)
        if dashboard.company_ids and (company not in dashboard.company_ids or self.env.company not in dashboard.company_ids):
            raise AccessError(_('The financial dashboard is not available for this company.'))
        if len(periods) > 2:
            raise ValidationError(_('Select no more than one comparison period.'))
        grouped_by_period = {
            period['key']: self._section_rows(period['domain']) for period in periods
        }
        currency = company.currency_id
        rows, totals = self._report_rows(grouped_by_period, periods, currency)
        # Preserve the old current-column envelope for callers that have not
        # yet moved to rows/periods.  New work must consume the keyed rows.
        grouped = grouped_by_period['current']
        current_period = next(period for period in periods if period['key'] == 'current')
        raw_totals = {key: sum((row['raw'] for row in grouped[key]), Decimal('0'))
                      for key in SECTION_KEYS}
        gross = totals['current']['gross_profit']
        net = totals['current']['net_income']
        sections = []
        for key in SECTION_KEYS:
            display = -raw_totals[key] if key in EXPENSE_KEYS else raw_totals[key]
            sections.append({
                'key': key,
                'amount': self._format_money(display, currency),
                'negative': display < 0,
                'account_count': len(grouped[key]),
            })
        return {
            'company': {
                'id': company.id, 'name': company.display_name,
                'currency_code': currency.name,
                'currency_symbol': currency.symbol or currency.name,
                'currency_digits': int(currency.decimal_places),
            },
            'period': {'date_from': current_period['date_from'],
                       'date_to': current_period['date_to']},
            'period_controls': period_control,
            'comparison_controls': comparison_control,
            'periods': [{key: value for key, value in period.items() if key != 'domain'}
                        for period in periods],
            'rows': rows,
            'is_partial_journals': bool(journal_ids),
            'sections': sections,
            'gross_profit': {'amount': self._format_money(gross, currency),
                             'negative': gross < 0},
            'net_profit': {'amount': self._format_money(net, currency),
                           'negative': net < 0},
            'dashboard': self._dashboard_payload(
                grouped_by_period, totals, periods, currency, journal_ids,
            ),
        }
