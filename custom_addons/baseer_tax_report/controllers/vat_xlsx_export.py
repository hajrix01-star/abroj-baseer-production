import base64

from odoo import http
from odoo.exceptions import AccessError, MissingError, UserError, ValidationError
from odoo.http import content_disposition, request


class BaseerVatXlsxExport(http.Controller):
    @http.route('/baseer/tax/vat/export/<int:export_id>', type='http', auth='user',
                methods=['GET'], readonly=True)
    def download(self, export_id, company_id=None, **kwargs):
        try:
            if type(company_id) is not str or not company_id.isdecimal():
                raise AccessError('Invalid company.')
            active_cookie = request.httprequest.cookies.get('cids')
            if active_cookie:
                parts = active_cookie.split('-')
                if not parts or any(not part.isdecimal() for part in parts):
                    raise AccessError('Invalid active companies.')
                active_ids = [int(part) for part in parts]
            else:
                active_ids = [request.env.company.id]
            if int(company_id) not in active_ids:
                raise AccessError('The export company is not active.')
            export = request.env['baseer.tax.report.xlsx']._download_record(
                export_id, int(company_id),
            )
            data = base64.b64decode(export.file_data, validate=True)
            if len(data) > 1024 * 1024:
                raise UserError('Export file exceeded size limit.')
        except (AccessError, MissingError, UserError, ValidationError, TypeError, ValueError):
            raise request.not_found() from None
        return request.make_response(data, headers=[
            ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
            ('Content-Disposition', content_disposition(export.file_name)),
            ('Cache-Control', 'private, no-store'),
            ('X-Content-Type-Options', 'nosniff'),
        ])
