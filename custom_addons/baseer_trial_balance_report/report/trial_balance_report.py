"""A4 rendering of one secured trial-balance snapshot."""

from odoo import _, fields, models
from odoo.exceptions import AccessError, ValidationError


class TrialBalancePdf(models.AbstractModel):
    _name = 'report.baseer_trial_balance_report.trial_balance_pdf'
    _description = 'Baseer Trial Balance A4 Landscape'

    def _get_report_values(self, docids, data=None):
        if docids or not isinstance(data, dict) or not isinstance(data.get('filters'), dict):
            raise ValidationError(_('Select valid trial balance filters.'))
        filters = data['filters']
        if type(filters.get('company_id')) is not int or filters['company_id'] != self.env.company.id:
            raise AccessError(_('Print the report for the active company only.'))
        report = self.env['baseer.trial.balance.report']._build_trial_balance(filters, full=True)
        journal_ids = filters.get('journal_ids', [])
        journals = self.env['account.journal'].with_context(active_test=False).browse(journal_ids)
        journals.check_access('read')
        return {
            'doc_ids': [],
            'doc_model': 'baseer.trial.balance.report',
            'company_record': self.env.company,
            'report': report,
            'accounts': report['accounts'],
            'journals': ', '.join(f'{row.code} · {row.name}' for row in journals),
            'arabic': (self.env.user.lang or '').startswith('ar'),
            'generated_at': fields.Datetime.context_timestamp(self, fields.Datetime.now()),
        }
