"""Bounded presentation of keyed P&L periods and all account sections."""

from odoo import _, models
from odoo.exceptions import ValidationError
from odoo.fields import Domain
from odoo.addons.baseer_reports_menu.report_values import export_document, require_active_filters, source_money
from ..report.profit_loss_report import LABELS
from .profit_loss import SECTION_GROUPS


class ProfitLossExport(models.AbstractModel):
    _inherit = 'baseer.profit.loss.report'

    def _get_export_document(self, filters):
        require_active_filters(self.env, filters, {
            'company_id', 'period', 'comparison', 'journal_ids', 'date_from', 'date_to',
            'period_mode', 'anchor_date', 'period_direction', 'comparison_mode', 'comparison_count',
            'comparison_order', 'comparison_date_from', 'comparison_date_to',
        })
        company, _journals, periods, _period_control, _comparison_control = self._scope(filters)
        grouped = {period['key']: self._section_rows(period['domain']) for period in periods}
        report_rows, _totals = self._report_rows(grouped, periods, company.currency_id)
        # All collections live only in this call. The normal verified collectors,
        # account ordering, native amounts and channel allocation remain authoritative.
        # Reject an excessive account projection before the optional POS work.
        section_ids = {}
        for row in report_rows:
            if row.get('expandable'):
                keys = SECTION_GROUPS.get(row['section'], (row['section'],))
                section_ids[row['section']] = {
                    entry['account'].id for period in periods for key in keys
                    for entry in grouped[period['key']][key]
                }
        if len(report_rows) + sum(map(len, section_ids.values())) > 5000:
            raise ValidationError(_('The export is limited to 5,000 rows. Narrow the period or selected journals.'))
        # Account type is singular; combined expense is the only multi-type row.
        # Fail closed if a future layout renders any account in two sections,
        # because its repeated channel rows would need a section-aware budget.
        rendered_ids = [account_id for ids in section_ids.values() for account_id in ids]
        if len(set(rendered_ids)) != len(rendered_ids):
            raise ValidationError(_('The export account sections overlap. Retry after correcting the report layout.'))
        income_ids = sorted(section_ids.get('income', set()) | section_ids.get('income_other', set()))
        channel_periods = {}
        budget = {'keys': set(), 'limit': 5000 - len(report_rows) - len(rendered_ids)}
        for period in periods if income_ids else []:
            channels = self._revenue_channels(
                company, period['domain'] & Domain('account_id', 'in', income_ids),
                _export_channel_budget=budget)
            # Also guard extension collectors before creating any display payload.
            for account_id, entries in channels.items():
                for key in entries:
                    self._claim_export_channel(budget, account_id, key)
            channel_periods[period['key']] = channels
        arabic = (self.env.lang or '').startswith('ar')
        period_labels = [('الفترة' if arabic else 'Period') + (f' {index}' if len(periods) > 1 else '')
                         for index in range(1, len(periods) + 1)]
        columns = [{'key': 'label', 'label': 'الحساب' if arabic else 'Account', 'type': 'text', 'width': 52}]
        columns += [{'key': period['key'], 'label': label if len(periods) > 1 else ('المبلغ' if arabic else 'Amount'),
                     'type': 'money', 'width': 24} for period, label in zip(periods, period_labels)]
        rows = []

        def add_row(label, amounts, kind='detail', indent=0):
            if len(rows) >= 5000:
                raise ValidationError(_('The export is limited to 5,000 rows. Narrow the period or selected journals.'))
            rows.append({'kind': kind, 'indent': indent, 'cells': {'label': label,
                         **{period['key']: source_money(amounts[period['key']]['amount']) for period in periods}}})

        for row in report_rows:
            label = LABELS.get(row['key'], (row['label'], row['label']))[0 if arabic else 1]
            add_row(label, row['amounts'], 'total' if row['kind'] == 'result' else row['kind'])
            if not row.get('expandable'):
                continue
            detail = self._account_section(company, periods, grouped, row['section'],
                                           channel_periods=channel_periods)
            if detail['total_count'] != len(detail['accounts']):
                raise ValidationError(_('The complete report is not available. Retry.'))
            for account in detail['accounts']:
                add_row(f"{account['code']} {account['name']}".strip(), account['amounts'], indent=1)
                for channel in account.get('channels', []):
                    add_row(channel['name'], channel['amounts'], indent=2)
        journals = self.env['account.journal'].with_context(active_test=False).browse(filters.get('journal_ids', []))
        journals.check_access('read')
        metadata = [('الدفاتر' if arabic else 'Journals', ', '.join(journals.mapped('display_name')) if journals
                     else ('جميع الدفاتر' if arabic else 'All journals'))]
        metadata += [(label, f"{period['date_from']} — {period['date_to']}") for period, label in zip(periods, period_labels)]
        return export_document(self.env, 'الربح والخسارة' if arabic else 'Profit and Loss', columns, rows,
                               metadata=metadata, notes=['قيود مرحلة فقط' if arabic else 'Posted entries only'])
