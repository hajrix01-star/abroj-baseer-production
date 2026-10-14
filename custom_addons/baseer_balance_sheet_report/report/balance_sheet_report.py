"""A4 rendering of the exact verified balance-sheet snapshot."""

from odoo import _, fields, models
from odoo.exceptions import AccessError, ValidationError


class BalanceSheetPdf(models.AbstractModel):
    _name = 'report.baseer_balance_sheet_report.balance_sheet_pdf'
    _description = 'Baseer Balance Sheet A4 Portrait'

    def _get_report_values(self, docids, data=None):
        if docids or not isinstance(data, dict) or not isinstance(data.get('filters'), dict):
            raise ValidationError(_('Select valid balance sheet filters.'))
        filters = data['filters']
        if type(filters.get('company_id')) is not int or filters['company_id'] != self.env.company.id:
            raise AccessError(_('Print the report for the active company only.'))
        report = self.env['baseer.balance.sheet.report']._build_pdf_report(filters)
        journals = self.env['account.journal'].with_context(active_test=False).browse(
            filters.get('journal_ids', []),
        )
        journals.check_access('read')
        return {
            'doc_ids': [], 'doc_model': 'baseer.balance.sheet.report',
            'company_record': self.env.company,
            'report': report,
            'journals': ', '.join(f'{row.code} · {row.name}' for row in journals),
            'arabic': (self.env.user.lang or '').startswith('ar'),
            'generated_at': fields.Datetime.context_timestamp(self, fields.Datetime.now()),
        }
