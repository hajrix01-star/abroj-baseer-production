"""Owner PDF: use the same fresh, permission-checked server snapshot as UI."""

from odoo import _, fields, models
from odoo.exceptions import AccessError, ValidationError


class _OwnerPdfValues:
    _pdf_landscape = False

    def _get_report_values(self, docids, data=None):
        if docids or not isinstance(data, dict) or not isinstance(data.get('filters'), dict):
            raise ValidationError(_('Select valid sales and payments filters.'))
        filters = data['filters']
        if type(filters.get('company_id')) is not int or filters['company_id'] != self.env.company.id:
            raise AccessError(_('Print the report for the active company only.'))
        snapshot = self.env['baseer.operations.report'].get_owner_snapshot(filters)
        if snapshot.get('complete') is not True or snapshot.get('company_id') != self.env.company.id:
            raise AccessError(_('Printing is unavailable until all movement sources are verified.'))
        periods = snapshot['periods']
        if not 1 <= len(periods) <= 4 or (len(periods) > 1) != self._pdf_landscape:
            raise ValidationError(_('Select the correct page layout for this comparison.'))
        journal_ids = filters.get('journal_ids', [])
        journals = self.env['account.journal'].with_context(active_test=False).browse(journal_ids)
        journals.check_access('read')
        return {
            'doc_ids': [], 'doc_model': 'baseer.operations.report',
            'company_record': self.env.company, 'snapshot': snapshot, 'periods': periods,
            'is_partial_journals': bool(journal_ids),
            'journal_names': ', '.join(journals.mapped('display_name')),
            'arabic': (self.env.context.get('lang') or self.env.user.lang or '').startswith('ar'),
            'generated_at': fields.Datetime.context_timestamp(self, fields.Datetime.now()),
        }


class OwnerPdfPortrait(_OwnerPdfValues, models.AbstractModel):
    _name = 'report.baseer_operations_report.owner_pdf_portrait'
    _description = 'Baseer Sales and Payments A4 Portrait'


class OwnerPdfLandscape(_OwnerPdfValues, models.AbstractModel):
    _name = 'report.baseer_operations_report.owner_pdf_landscape'
    _description = 'Baseer Sales and Payments A4 Landscape'
    _pdf_landscape = True
