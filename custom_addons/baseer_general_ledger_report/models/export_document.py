"""Presentation projection of the complete, secured ledger snapshot."""

from odoo import models
from odoo.addons.baseer_reports_menu.report_values import (
    export_document, require_active_filters, source_money,
)


class GeneralLedgerExport(models.AbstractModel):
    _inherit = 'baseer.general.ledger.report'

    def _ledger_export_metadata(self, filters, report):
        arabic = (self.env.lang or '').startswith('ar')
        journals = self.env['account.journal'].with_context(active_test=False).browse(filters.get('journal_ids', []))
        journals.check_access('read')
        return [
            ('الفترة' if arabic else 'Period', f"{report['period']['date_from']} — {report['period']['date_to']}"),
            ('بداية السنة المالية' if arabic else 'Fiscal year start', report['period']['fiscal_start']),
            ('الدفاتر' if arabic else 'Journals', ', '.join(journals.mapped('display_name'))
             if journals else ('جميع الدفاتر' if arabic else 'All journals')),
        ]

    def _get_export_document(self, filters):
        require_active_filters(self.env, filters, {'company_id', 'date_from', 'date_to', 'journal_ids'})
        report = self._build_report(filters, full=True)
        arabic = (self.env.lang or '').startswith('ar')
        keys = ('opening', 'debit', 'credit', 'closing')
        labels = ('الافتتاحي', 'مدين', 'دائن', 'الختامي') if arabic else ('Opening', 'Debit', 'Credit', 'Closing')
        columns = [{'key': 'label', 'label': 'الحساب' if arabic else 'Account', 'type': 'text', 'width': 48}]
        columns += [{'key': key, 'label': label, 'type': 'money', 'width': 20} for key, label in zip(keys, labels)]
        rows = []
        if report['rbf']['source_line_count']:
            rows.append({'kind': 'section', 'cells': {
                'label': 'نتيجة مرحلة من السنة السابقة' if arabic else 'Result brought forward',
                'opening': source_money(report['rbf']['amount']), 'closing': source_money(report['rbf']['amount']),
            }})
        for account in report['accounts']:
            rows.append({'kind': 'detail', 'cells': {
                'label': f"{account['code']} {account['name']}".strip(),
                **{key: source_money(account[key]) for key in keys},
            }})
        rows.append({'kind': 'total', 'cells': {'label': 'الإجمالي' if arabic else 'Total',
                     **{key: source_money(report['total'][key]) for key in keys}}})
        return export_document(self.env, 'دفتر الأستاذ العام' if arabic else 'General Ledger', columns, rows,
                               metadata=self._ledger_export_metadata(filters, report),
                               notes=['قيود مرحلة فقط' if arabic else 'Posted entries only'])
