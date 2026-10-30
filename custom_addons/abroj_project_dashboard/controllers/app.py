import json
from pathlib import Path

from odoo import http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request


class AbrojApp(http.Controller):
    @http.route('/abroj/app', type='http', auth='user', methods=['GET'])
    def app(self):
        page = (Path(__file__).parent.parent / 'static/pwa/index.html').read_text(encoding='utf-8')
        page = page.replace('CSRF_TOKEN_PLACEHOLDER', request.csrf_token())
        return request.make_response(page, [('Content-Type', 'text/html; charset=utf-8')])

    @http.route('/abroj/app/manifest.webmanifest', type='http', auth='public', methods=['GET'])
    def manifest(self):
        data = {'name': 'أبرج للمقاولات', 'short_name': 'أبرج', 'start_url': '/abroj/app', 'scope': '/abroj/app', 'display': 'standalone', 'dir': 'rtl', 'lang': 'ar', 'theme_color': '#12243b', 'background_color': '#f5f6f8', 'icons': [{'src': '/abroj_project_dashboard/static/pwa/icon-%d.png' % n, 'sizes': '%dx%d' % (n, n), 'type': 'image/png'} for n in (192, 512)]}
        return request.make_response(json.dumps(data, ensure_ascii=False), [('Content-Type', 'application/manifest+json')])

    @http.route('/abroj/app/sw.js', type='http', auth='public', methods=['GET'])
    def sw(self):
        source = "self.addEventListener('install',e=>e.waitUntil(caches.open('abroj-v2').then(c=>c.addAll(['/abroj_project_dashboard/static/pwa/index.html','/abroj_project_dashboard/static/pwa/app.js','/abroj_project_dashboard/static/pwa/app.css']))));self.addEventListener('fetch',e=>{if(e.request.method==='GET')e.respondWith(fetch(e.request).catch(()=>caches.match(e.request).then(r=>r||(e.request.mode==='navigate'?caches.match('/abroj_project_dashboard/static/pwa/index.html'):Response.error()))))});"
        return request.make_response(source, [('Content-Type', 'application/javascript'), ('Service-Worker-Allowed', '/abroj/app')])

    @http.route('/abroj/app/data', type='jsonrpc', auth='user')
    def data(self, filters=None, project_id=None):
        projects = request.env['project.project']
        return projects.get_abroj_project_detail(project_id) if project_id else projects.get_abroj_dashboard_data(filters)

    @http.route('/abroj/app/save', type='jsonrpc', auth='user')
    def save(self, model, values, record_id=None):
        allowed = {'project.task': {'name', 'project_id', 'x_abroj_date_start', 'date_deadline', 'state', 'x_abroj_progress'}, 'project.project': {'abroj_type', 'last_update_status', 'abroj_manual_progress', 'abroj_use_manual_progress', 'abroj_budget', 'abroj_contract_value', 'abroj_budget_line_ids'}}
        try:
            if model not in allowed or set(values) - allowed[model]:
                raise AccessError('عملية غير مسموحة')
            record = request.env[model].browse(record_id).exists() if record_id else request.env[model]
            if record_id and not record:
                raise AccessError('السجل غير موجود')
            if record_id:
                record.write(values)
            else:
                record = record.create(values)
            return {'id': record.id}
        except (AccessError, UserError, ValidationError):
            return {'error': 'تعذر الحفظ. تحقق من صلاحياتك والبيانات المدخلة.'}

    @http.route('/abroj/app/attachments', type='jsonrpc', auth='user')
    def attachments(self, model, record_id):
        try:
            if model not in ('project.project', 'project.task'):
                raise AccessError('عملية غير مسموحة')
            record = request.env[model].browse(record_id).exists()
            if not record:
                raise AccessError('السجل غير موجود')
            record.check_access('read')
            attachments = request.env['ir.attachment'].search([('res_model', '=', model), ('res_id', '=', record.id), ('type', '=', 'binary')])
            return [{'id': a.id, 'name': a.name, 'mimetype': a.mimetype or ''} for a in attachments]
        except (AccessError, UserError):
            return {'error': 'تعذر عرض المرفقات. تحقق من صلاحياتك.'}

    @http.route('/abroj/app/upload', type='http', auth='user', methods=['POST'])
    def upload(self, model=None, record_id=None, file=None, **kwargs):
        import base64
        try:
            if model not in ('project.project', 'project.task') or not file:
                raise AccessError('عملية غير مسموحة')
            record = request.env[model].browse(int(record_id)).exists()
            if not record:
                raise AccessError('السجل غير موجود')
            record.check_access('write')
            content = file.read(25 * 1024 * 1024 + 1)
            if len(content) > 25 * 1024 * 1024:
                raise UserError('الملف أكبر من 25 ميغابايت')
            attachment = request.env['ir.attachment'].with_context(image_no_postprocess=True).create({'name': file.filename, 'res_model': model, 'res_id': record.id, 'datas': base64.b64encode(content), 'mimetype': file.content_type})
            return request.make_json_response({'id': attachment.id})
        except (AccessError, UserError, ValueError):
            return request.make_json_response({'error': 'تعذر رفع الملف. تحقق من الصلاحيات وحجم الملف.'}, status=403)
