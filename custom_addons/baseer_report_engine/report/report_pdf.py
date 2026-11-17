"""QWeb values for the generic report PDF."""

from odoo import _, models
from odoo.exceptions import ValidationError


class BaseerReportEnginePdf(models.AbstractModel):
    _name = 'report.baseer_report_engine.report_pdf'
    _description = 'Baseer Report Engine PDF'

    def _get_report_values(self, docids, data=None):
        if not isinstance(data, dict) or not data.get('report_code'):
            raise ValidationError(_('Select a report to print.'))
        payload = self.env['baseer.report.engine'].with_context(baseer_gl_export=True).get_report(
            data['report_code'], data.get('options') or {}, with_accounts=True,
        )
        return {
            'doc_ids': docids,
            'doc_model': 'baseer.report.definition',
            'docs': self.env['baseer.report.definition'].browse(docids),
            'payload': payload,
            'arabic': (self.env.lang or '').startswith('ar'),
            'company': self.env.company,
        }
