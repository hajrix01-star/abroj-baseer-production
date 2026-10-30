import base64
from odoo import http
from odoo.http import request
from werkzeug.exceptions import BadRequest


class Capture(http.Controller):
    @http.route('/abroj/contracting/capture', type='http', auth='user', methods=['GET', 'POST'], csrf=True)
    def capture(self, **kwargs):
        projects = request.env['project.project'].search([('company_id', 'in', request.env.companies.ids)])
        if request.httprequest.method == 'POST':
            if not kwargs.get('project_id'):
                raise BadRequest('يجب اختيار المشروع')
            try:
                project_id = int(kwargs.get('project_id', '0'))
            except (TypeError, ValueError):
                raise BadRequest('المشروع غير صالح')
            project = projects.filtered(lambda p: p.id == project_id)
            if not project:
                raise BadRequest('المشروع غير متاح')
            upload = request.httprequest.files.get('file')
            values = {'project_id': project.id, 'note': kwargs.get('note'), 'filename': 'ملاحظة'}
            if upload and upload.filename:
                content = upload.read(25 * 1024 * 1024 + 1)
                if len(content) > 25 * 1024 * 1024:
                    raise BadRequest('الحد الأقصى للملف 25 ميغابايت')
                mimetype = upload.mimetype or 'application/octet-stream'
                if not (mimetype.startswith(('audio/', 'image/', 'video/')) or mimetype == 'application/pdf'):
                    raise BadRequest('نوع الملف غير مدعوم')
                values.update(file=base64.b64encode(content), filename=upload.filename, mimetype=mimetype)
            request.env['abroj.contracting.inbox'].create(values)
            return request.redirect('/abroj/contracting/capture?saved=1')
        return request.render('abroj_contracting.capture', {'projects': projects, 'saved': kwargs.get('saved') == '1'})
