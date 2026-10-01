from odoo import http
from odoo.exceptions import AccessError, MissingError, UserError
from odoo.http import request


class AbrojPlanExport(http.Controller):
    @http.route('/abroj/costing/plan/export/<int:wizard_id>', type='http', auth='user',
                methods=['GET'], readonly=True)
    def download(self, wizard_id, company_id=None, **kwargs):
        try:
            company_id = int(company_id)
            wizard = request.env['abroj.cost.plan.import.wizard']._export_download_record(
                wizard_id, company_id,
            )
            stream = wizard.env['ir.binary']._get_stream_from(
                wizard, 'export_file', filename_field='export_filename',
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
        except (AccessError, MissingError, UserError, TypeError, ValueError):
            raise request.not_found() from None
        return stream.get_response(as_attachment=True)
