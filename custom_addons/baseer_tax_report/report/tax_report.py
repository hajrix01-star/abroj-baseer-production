from odoo import _, models
from odoo.exceptions import AccessError


class BaseerTaxReport(models.AbstractModel):
    _name = 'report.baseer_tax_report.report_tax'
    _description = 'Saudi VAT Report PDF'

    def _get_report_values(self, docids, data=None):
        wizard = self.env['baseer.tax.report.wizard'].browse(docids).exists()
        if len(wizard) != 1:
            raise AccessError(_('Open the VAT report from its period form.'))
        report_data = wizard._build_report()
        # A printed return remains complete even when the screen hides zero boxes.
        report_data['visible_rows'] = report_data['rows']
        report_data['interactive'] = False
        return {
            'doc_ids': wizard.ids, 'doc_model': wizard._name,
            'docs': wizard, 'report_data': report_data,
        }
