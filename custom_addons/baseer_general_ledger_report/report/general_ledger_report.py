"""A4 summary of the already-verified posted general ledger source."""

from odoo import _, fields, models
from odoo.exceptions import AccessError, ValidationError


class GeneralLedgerPdf(models.AbstractModel):
    _name = 'report.baseer_general_ledger_report.general_ledger_pdf'
    _description = 'Baseer General Ledger A4 Landscape'

    def _get_report_values(self, docids, data=None):
        if docids or not isinstance(data, dict) or not isinstance(data.get('filters'), dict):
            raise ValidationError(_('Select valid general ledger filters.'))
        filters = data['filters']
        if type(filters.get('company_id')) is not int or filters['company_id'] != self.env.company.id:
            raise AccessError(_('Print the report for the active company only.'))
        # The private builder keeps the screen's 100-row contract while printing
        # one complete, access-checked financial snapshot without page loops.
        report = self.env['baseer.general.ledger.report']._build_report(filters, full=True)
        journal_ids = filters.get('journal_ids', [])
        journals = self.env['account.journal'].with_context(active_test=False).browse(journal_ids)
        journals.check_access('read')
        arabic = (self.env.user.lang or '').startswith('ar')
        return {
            'doc_ids': [],
            'doc_model': 'baseer.general.ledger.report',
            'company_record': self.env.company,
            'report': report,
            'accounts': report['accounts'],
            'journals': ', '.join(f'{journal.code} · {journal.name}' for journal in journals),
            'arabic': arabic,
            'generated_at': fields.Datetime.context_timestamp(self, fields.Datetime.now()),
        }
