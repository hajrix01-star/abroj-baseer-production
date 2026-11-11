"""Private PDF actions use only the dashboard's isolated owner snapshot."""
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

from odoo.addons.baseer_operations_report.models.owner_presentation import owner_print_rows
from .owner_export import assert_snapshot_revisions, validate_revisions


class FinancialDashboardOperationsPrint(models.AbstractModel):
    _inherit = 'baseer.financial.dashboard.operations'

    @api.model
    def action_print_owner(self, filters, revisions):
        validate_revisions(revisions)
        snapshot = self.get_owner_snapshot(filters)
        assert_snapshot_revisions(snapshot, revisions)
        periods = snapshot['periods']
        if not 1 <= len(periods) <= 4:
            raise ValidationError(_('Select the correct page layout for this comparison.'))
        layout = 'landscape' if len(periods) > 1 else 'portrait'
        return self.env.ref(
            f'baseer_financial_dashboard.action_dashboard_owner_pdf_{layout}'
        ).report_action([], data={'filters': filters, 'revisions': revisions}, config=False)


class _DashboardPdfValues:
    _pdf_landscape = False

    def _get_report_values(self, docids, data=None):
        if docids or not isinstance(data, dict) or not isinstance(data.get('filters'), dict):
            raise ValidationError(_('Select valid sales and payments filters.'))
        filters = data['filters']
        revisions = data.get('revisions')
        validate_revisions(revisions)
        if type(filters.get('company_id')) is not int or filters['company_id'] != self.env.company.id:
            raise AccessError(_('Print the report for the active company only.'))
        snapshot = self.env['baseer.financial.dashboard.operations'].get_owner_snapshot(filters)
        assert_snapshot_revisions(snapshot, revisions)
        if snapshot.get('company_id') != self.env.company.id:
            raise AccessError(_('Printing is unavailable until all movement sources are verified.'))
        periods = snapshot['periods']
        if not 1 <= len(periods) <= 4 or (len(periods) > 1) != self._pdf_landscape:
            raise ValidationError(_('Select the correct page layout for this comparison.'))
        journal_ids = filters.get('journal_ids', [])
        journals = self.env['account.journal'].with_context(active_test=False).browse(journal_ids)
        journals.check_access('read')
        return {
            'doc_ids': [], 'doc_model': 'baseer.financial.dashboard.operations',
            'company_record': self.env.company, 'snapshot': snapshot, 'periods': periods,
            'rows': owner_print_rows(periods),
            'is_partial_journals': bool(journal_ids),
            'journal_names': ', '.join(journals.mapped('display_name')),
            'arabic': (self.env.context.get('lang') or self.env.user.lang or '').startswith('ar'),
            'generated_at': fields.Datetime.context_timestamp(self, fields.Datetime.now()),
        }


class FinancialDashboardOwnerPdfPortrait(_DashboardPdfValues, models.AbstractModel):
    _name = 'report.baseer_financial_dashboard.dashboard_owner_pdf_portrait'
    _description = 'Financial Dashboard Sales and Payments Portrait'


class FinancialDashboardOwnerPdfLandscape(_DashboardPdfValues, models.AbstractModel):
    _name = 'report.baseer_financial_dashboard.dashboard_owner_pdf_landscape'
    _description = 'Financial Dashboard Sales and Payments Landscape'
    _pdf_landscape = True
