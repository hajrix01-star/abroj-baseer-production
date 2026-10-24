"""Bounded presentation of keyed P&L periods and all account sections."""

from odoo import _, models
from odoo.exceptions import ValidationError
from odoo.addons.baseer_reports_menu.report_values import export_document, require_active_filters, source_money
from ..report.profit_loss_report import LABELS


class ProfitLossExport(models.AbstractModel):
    _inherit = 'baseer.profit.loss.report'

    def _get_export_document(self, filters):
        require_active_filters(self.env, filters, {
            'company_id', 'period', 'comparison', 'journal_ids', 'date_from', 'date_to',
            'period_mode', 'anchor_date', 'period_direction', 'comparison_mode', 'comparison_count',
            'comparison_order', 'comparison_date_from', 'comparison_date_to',
        })
        report = self.get_report(filters)
        arabic = (self.env.lang or '').startswith('ar')
        periods = report['periods']
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

        for row in report['rows']:
            label = LABELS.get(row['key'], (row['label'], row['label']))[0 if arabic else 1]
            add_row(label, row['amounts'], 'total' if row['kind'] == 'result' else row['kind'])
            if not row.get('expandable'):
                continue
            page, seen, expected = 1, set(), None
            while True:
                detail = self.get_accounts(filters, row['section'], page)
                if expected is None:
                    expected = detail['total_count']
                if expected != detail['total_count'] or expected > 5000:
                    raise ValidationError(_('The report changed or exceeds 5,000 accounts. Narrow the scope and retry.'))
                for account in detail['accounts']:
                    if account['id'] in seen:
                        raise ValidationError(_('The report changed while exporting. Retry.'))
                    seen.add(account['id'])
                    add_row(f"{account['code']} {account['name']}".strip(), account['amounts'], indent=1)
                    for channel in account.get('channels', []):
                        add_row(channel['name'], channel['amounts'], indent=2)
                if len(seen) == expected:
                    break
                if not detail['accounts'] or len(seen) > expected:
                    raise ValidationError(_('The complete report is not available. Retry.'))
                page += 1
        journals = self.env['account.journal'].with_context(active_test=False).browse(filters.get('journal_ids', []))
        journals.check_access('read')
        metadata = [('الدفاتر' if arabic else 'Journals', ', '.join(journals.mapped('display_name')) if journals
                     else ('جميع الدفاتر' if arabic else 'All journals'))]
        metadata += [(label, f"{period['date_from']} — {period['date_to']}") for period, label in zip(periods, period_labels)]
        return export_document(self.env, 'الربح والخسارة' if arabic else 'Profit and Loss', columns, rows,
                               metadata=metadata, notes=['قيود مرحلة فقط' if arabic else 'Posted entries only'])
