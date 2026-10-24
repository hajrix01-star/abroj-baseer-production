"""Typed export projection of the established Saudi VAT calculator."""

from odoo import _, api, models

from odoo.addons.baseer_reports_menu.report_values import (
    export_document, require_active_filters, source_money,
)


class TaxReportExport(models.TransientModel):
    _inherit = 'baseer.tax.report.wizard'

    @api.model
    def _get_export_document(self, filters):
        allowed = {'period_type', 'year', 'month', 'quarter', 'display_mode', 'journal_ids'}
        require_active_filters(self.env, filters, allowed)
        options = {key: filters[key] for key in allowed | {'company_id'} if key in filters}
        # The hub validator deliberately requires every selector, including those
        # not active for the selected period, before it reads any ledger values.
        wizard = self._hub_wizard(options)
        report = wizard._build_report()
        ar = (self.env.context.get('lang') or self.env.user.lang or '').startswith('ar')
        labels = ({'box': 'الخانة', 'name': 'البيان', 'base': 'المبلغ', 'tax': 'الضريبة',
                   'untagged_vat': 'قيود ضريبة القيمة المضافة غير المصنفة',
                   'untagged_other': 'قيود رسوم وضرائب أخرى بلا وسوم',
                   'title': 'تقرير ضريبة القيمة المضافة', 'from': 'من', 'to': 'إلى',
                   'journals': 'الدفاتر', 'all_journals': 'جميع الدفاتر'} if ar else
                  {'box': 'Box', 'name': 'Description', 'base': 'Amount', 'tax': 'VAT Amount',
                   'untagged_vat': 'Untagged VAT entries',
                   'untagged_other': 'Other untagged tax entries',
                   'title': 'Saudi VAT Report', 'from': 'From', 'to': 'To',
                   'journals': 'Journals', 'all_journals': 'All journals'})
        columns = [
            {'key': 'box', 'label': labels['box'], 'type': 'text', 'width': 10},
            {'key': 'name', 'label': labels['name'], 'type': 'text', 'width': 54},
            {'key': 'base', 'label': labels['base'], 'type': 'money', 'width': 19},
            {'key': 'tax', 'label': labels['tax'], 'type': 'money', 'width': 19},
        ]
        rows = []
        # Export all statutory boxes; screen simple mode intentionally hides zeros.
        for item in report['rows']:
            cells = {'box': str(item['number']), 'name': item['name']}
            if item['base'] is not None:
                cells['base'] = source_money(item['base'])
            if item['tax'] is not None:
                cells['tax'] = source_money(item['tax'])
            rows.append({'cells': cells, 'kind': 'detail'})
        exception = report['exception']
        rows.extend([
            {'cells': {'name': labels['untagged_vat'],
                       'base': source_money(exception['amount'])}, 'kind': 'total'},
            {'cells': {'name': labels['untagged_other'],
                       'base': source_money(exception['other_amount'])}, 'kind': 'total'},
        ])
        return export_document(self.env, labels['title'], columns, rows,
                               metadata=[(labels['from'], report['date_from'].isoformat()),
                                         (labels['to'], report['date_to'].isoformat()),
                                         (labels['journals'], report['journal_names'] or labels['all_journals'])])
