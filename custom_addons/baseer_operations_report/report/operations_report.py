"""Unactivated A4 adapter for a future complete Gross Operations snapshot."""

from odoo import _, fields, models
from odoo.exceptions import AccessError, ValidationError

from odoo.addons.baseer_operations_report.models.operations import ROW_KEYS


# Match the Gross Operations screen; these balances are not accounting profit.
LABELS = {
    'income': ('الإيرادات', 'Income'),
    'cost_of_sales': ('تكلفة المبيعات', 'Cost of sales'),
    'gross_profit': ('إجمالي العمليات بعد تكلفة المبيعات', 'Gross operations after cost of sales'),
    'expense': ('المصروفات', 'Expenses'),
    'net_operating_income': ('رصيد العمليات التشغيلية', 'Operating balance'),
    'other_income': ('إيرادات أخرى', 'Other income'),
    'other_expense': ('مصروفات أخرى', 'Other expenses'),
    'net_other_income': ('رصيد العمليات الأخرى', 'Other operations balance'),
    'net_income': ('صافي العمليات', 'Net operations'),
}


class _OperationsPdfValues:
    _pdf_landscape = False

    def _get_report_values(self, docids, data=None):
        if docids or not isinstance(data, dict) or not isinstance(data.get('filters'), dict):
            raise ValidationError(_('Select valid gross operations filters.'))
        filters = data['filters']
        if type(filters.get('company_id')) is not int or filters['company_id'] != self.env.company.id:
            raise AccessError(_('Print the report for the active company only.'))

        # The source enforces accounting/source ACLs, record rules, period and
        # journal validity. Never elevate privileges or trust a browser payload.
        snapshot = self.env['baseer.operations.report'].get_source_snapshot(filters)
        if snapshot.get('complete') is not True:
            raise AccessError(_('Gross operations printing is unavailable until the source is complete.'))
        if snapshot.get('company_id') != self.env.company.id:
            raise AccessError(_('Print the report for the active company only.'))
        periods = snapshot.get('periods')
        if (not isinstance(periods, list) or not 1 <= len(periods) <= 4
                or (len(periods) > 1) != self._pdf_landscape):
            raise ValidationError(_('Select the correct page layout for this comparison.'))
        for period in periods:
            rows = period.get('rows')
            if (not isinstance(rows, list) or len(rows) != len(ROW_KEYS)
                    or tuple(row.get('key') for row in rows) != ROW_KEYS):
                raise ValidationError(_('The gross operations source is incomplete.'))
        arabic = (self.env.user.lang or '').startswith('ar')
        labels = {key: pair[0 if arabic else 1] for key, pair in LABELS.items()}
        journal_ids = filters.get('journal_ids', [])
        journals = self.env['account.journal'].with_context(active_test=False).browse(journal_ids)
        journals.check_access('read')
        # Formatting only. Amounts and sign flags are copied verbatim from
        # the single server snapshot, with no financial arithmetic in QWeb.
        rows = [{
            'key': key,
            'label': labels[key],
            'style': 'section' if key in ('income', 'expense', 'net_income') else '',
            'amounts': [period['rows'][index] for period in periods],
        } for index, key in enumerate(ROW_KEYS)]
        return {
            'doc_ids': [],
            'doc_model': 'baseer.operations.report',
            'company_record': self.env.company,
            'snapshot': snapshot,
            'periods': periods,
            'rows': rows,
            'is_partial_journals': bool(journal_ids),
            'journal_names': ', '.join(journals.mapped('display_name')),
            'arabic': arabic,
            'generated_at': fields.Datetime.context_timestamp(self, fields.Datetime.now()),
        }


class OperationsPdfPortrait(_OperationsPdfValues, models.AbstractModel):
    _name = 'report.baseer_operations_report.operations_pdf_portrait'
    _description = 'Baseer Gross Operations A4 Portrait'


class OperationsPdfLandscape(_OperationsPdfValues, models.AbstractModel):
    _name = 'report.baseer_operations_report.operations_pdf_landscape'
    _description = 'Baseer Gross Operations A4 Landscape'
    _pdf_landscape = True
