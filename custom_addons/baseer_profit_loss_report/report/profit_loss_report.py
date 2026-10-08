"""A4 print adapter for the existing posted profit/loss report."""

from odoo import _, fields, models
from odoo.exceptions import AccessError, ValidationError


LABELS = {
    'income': ('الإيرادات', 'Income'),
    'cost_of_sales': ('تكلفة المبيعات', 'Cost of Sales'),
    'gross_profit': ('إجمالي الربح', 'Gross Profit'),
    'expense': ('المصروفات', 'Expense'),
    'net_operating_income': ('صافي الربح التشغيلي', 'Net Operating Income'),
    'other_income': ('إيرادات أخرى', 'Other Income'),
    'other_expense': ('مصروفات أخرى', 'Other Expense'),
    'net_other_income': ('صافي الإيرادات الأخرى', 'Net Other Income'),
    'net_income': ('صافي الربح', 'Net Income'),
}


class _ProfitLossPdfValues:
    _pdf_landscape = False

    def _get_report_values(self, docids, data=None):
        if docids or not isinstance(data, dict) or not isinstance(data.get('filters'), dict):
            raise ValidationError(_('Select valid profit and loss filters.'))
        filters = data['filters']
        if type(filters.get('company_id')) is not int or filters['company_id'] != self.env.company.id:
            raise AccessError(_('Print the report for the active company only.'))
        # get_report is the sole financial read. It enforces the accounting group,
        # ACLs, record rules, all selected periods, and journal ownership.
        report = self.env['baseer.profit.loss.report'].get_report(filters)
        periods = report['periods']
        if not 1 <= len(periods) <= 4 or (len(periods) > 1) != self._pdf_landscape:
            raise ValidationError(_('Select the correct page layout for this comparison.'))
        journal_ids = filters.get('journal_ids', [])
        journals = self.env['account.journal'].with_context(active_test=False).browse(journal_ids)
        journals.check_access('read')
        arabic = (self.env.user.lang or '').startswith('ar')
        labels = {key: pair[0 if arabic else 1] for key, pair in LABELS.items()}
        return {
            'doc_ids': [],
            'doc_model': 'baseer.profit.loss.report',
            'company_record': self.env.company,
            'report': report,
            'periods': periods,
            'rows': report['rows'],
            'labels': labels,
            'journal_names': ', '.join(journals.mapped('display_name')),
            'arabic': arabic,
            'generated_at': fields.Datetime.context_timestamp(self, fields.Datetime.now()),
        }


class ProfitLossPdfPortrait(_ProfitLossPdfValues, models.AbstractModel):
    _name = 'report.baseer_profit_loss_report.profit_loss_pdf_portrait'
    _description = 'Baseer Profit and Loss A4 Portrait'


class ProfitLossPdfLandscape(_ProfitLossPdfValues, models.AbstractModel):
    _name = 'report.baseer_profit_loss_report.profit_loss_pdf_landscape'
    _description = 'Baseer Profit and Loss A4 Landscape'
    _pdf_landscape = True
