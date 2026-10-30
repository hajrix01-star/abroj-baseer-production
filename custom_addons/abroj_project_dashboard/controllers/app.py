import json
from pathlib import Path

from odoo import http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request


class AbrojApp(http.Controller):
    @staticmethod
    def _message(ar, en):
        return ar if (request.env.lang or '').startswith('ar') else en

    @http.route('/abroj/app', type='http', auth='user', methods=['GET'])
    def app(self):
        page = (Path(__file__).parent.parent / 'static/pwa/index.html').read_text(encoding='utf-8')
        page = page.replace('CSRF_TOKEN_PLACEHOLDER', request.csrf_token())
        page = page.replace('USER_LANG_PLACEHOLDER', 'ar' if (request.env.user.lang or '').startswith('ar') else 'en')
        return request.make_response(page, [('Content-Type', 'text/html; charset=utf-8'), ('Cache-Control', 'no-store')])

    @http.route('/abroj/app/language', type='jsonrpc', auth='user')
    def language(self, lang):
        code = {'ar': 'ar_001', 'en': 'en_US'}.get(lang)
        if not code or not request.env['res.lang'].search_count([('code', '=', code), ('active', '=', True)]):
            return {'ok': False}
        try:
            with request.env.cr.savepoint():
                request.env.user.write({'lang': code})
            request.session.context = dict(request.session.context, lang=code)
            return {'ok': True}
        except (AccessError, UserError, ValidationError):
            return {'ok': False}

    @http.route('/abroj/app/manifest.webmanifest', type='http', auth='public', methods=['GET'])
    def manifest(self):
        data = {'name': self._message('أبرج للمقاولات', 'Abroj Contracting'), 'short_name': self._message('أبرج', 'Abroj'), 'start_url': '/abroj/app', 'scope': '/abroj/app', 'display': 'standalone', 'dir': self._message('rtl', 'ltr'), 'lang': self._message('ar', 'en'), 'theme_color': '#12243b', 'background_color': '#f5f6f8', 'icons': [{'src': '/abroj_project_dashboard/static/pwa/icon-%d.png' % n, 'sizes': '%dx%d' % (n, n), 'type': 'image/png'} for n in (192, 512)] + [{'src': '/abroj_project_dashboard/static/pwa/icon-maskable-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'}]}
        return request.make_response(json.dumps(data, ensure_ascii=False), [('Content-Type', 'application/manifest+json'), ('Cache-Control', 'no-store, no-cache, must-revalidate'), ('Pragma', 'no-cache'), ('Expires', '0')])

    @http.route('/abroj/app/sw.js', type='http', auth='public', methods=['GET'])
    def sw(self):
        source = (Path(__file__).parent.parent / 'static/pwa/sw.js').read_text(encoding='utf-8')
        return request.make_response(source, [('Content-Type', 'application/javascript'), ('Service-Worker-Allowed', '/abroj/app'), ('Cache-Control', 'no-store')])

    @http.route('/abroj/app/data', type='jsonrpc', auth='user')
    def data(self, filters=None, project_id=None, include_archived=False):
        projects = request.env['project.project']
        return projects.get_abroj_project_detail(project_id) if project_id else projects.get_abroj_dashboard_data(filters, include_archived=include_archived)

    @http.route('/abroj/app/project/create', type='jsonrpc', auth='user')
    def create_project(self, name):
        try:
            if not isinstance(name, str) or not name.strip():
                raise ValidationError('Name is required')
            with request.env.cr.savepoint():
                project = request.env['project.project'].create({'name': name.strip(), 'company_id': request.env.company.id})
            return {'id': project.id}
        except (AccessError, UserError, ValidationError):
            return {'error': self._message('تعذر إنشاء المشروع. تحقق من صلاحياتك والبيانات المدخلة.', 'Could not create the project. Check your permissions and input.')}

    @http.route('/abroj/app/my-day', type='jsonrpc', auth='user')
    def my_day(self):
        return request.env['project.project'].get_abroj_my_day()

    @http.route('/abroj/app/save', type='jsonrpc', auth='user')
    def save(self, model, values, record_id=None):
        allowed = {'project.task': {'name', 'project_id', 'x_abroj_date_start', 'x_abroj_duration_days', 'state', 'x_abroj_progress'}, 'project.project': {'abroj_type', 'last_update_status', 'abroj_manual_progress', 'abroj_use_manual_progress', 'abroj_budget', 'abroj_contract_value', 'abroj_budget_line_ids', 'contracting_goal_ar', 'contracting_goal_en', 'contract_payment_schedule_ar', 'contract_payment_schedule_en', 'contracting_start', 'contracting_end', 'contract_value', 'value_type', 'estimated_cost', 'contract_vat_percent', 'contract_retention_percent'}}
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
            return {'error': self._message('تعذر الحفظ. تحقق من صلاحياتك والبيانات المدخلة.', 'Could not save. Check your permissions and input.')}

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
            return {'error': self._message('تعذر عرض المرفقات. تحقق من صلاحياتك.', 'Could not view attachments. Check your permissions.')}

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
            attachment = request.env['ir.attachment'].with_context(image_no_postprocess=True).create({'name': file.filename, 'res_model': model, 'res_id': record.id, 'datas': base64.b64encode(content), 'mimetype': file.content_type, 'description': kwargs.get('description', '')})
            return request.make_json_response({'id': attachment.id})
        except (AccessError, UserError, ValueError):
            return request.make_json_response({'error': self._message('تعذر رفع الملف. تحقق من الصلاحيات وحجم الملف.', 'Could not upload the file. Check permissions and file size.')}, status=403)

    # Only project-owned business documents are exposed here. All operations use
    # the current user's environment, including record rules and model guards.
    _documents = {
        'contract': ('abroj.contracting.subcontractor', {'partner_id', 'scope', 'agreed_amount', 'contract_type', 'payment_terms', 'duration_days'}),
        'payment': ('abroj.contracting.voucher', {'partner_id', 'amount', 'date', 'method', 'memo', 'subcontractor_id', 'vendor_contract_reference', 'vendor_contract_value'}),
        'receipt': ('abroj.contracting.voucher', {'partner_id', 'amount', 'date', 'method', 'memo'}),
        'promissory': ('abroj.promissory.note', {'partner_id', 'amount', 'issue_date', 'due_date', 'place', 'notes', 'currency_id'}),
        'note': ('abroj.contracting.project.note', {'body', 'note_type'}),
        'invoice': ('abroj.contracting.invoice', {'number', 'subcontractor_id', 'amount', 'date', 'invoice_kind', 'buyer_vat'}),
        'cost': ('abroj.contracting.cost', {'name', 'partner_id', 'amount', 'date', 'category', 'invoice_number'}),
    }

    @http.route('/abroj/app/documents', type='jsonrpc', auth='user')
    def documents(self, project_id):
        try:
            project = request.env['project.project'].browse(int(project_id)).exists()
            if not project:
                raise AccessError('المشروع غير موجود')
            project.check_access('read')
            result = {'partners': [{'id': p.id, 'name': p.display_name} for p in request.env['res.partner'].search([], limit=500)], 'records': {}, 'capabilities': {}, 'agreement': {name: (str(project[name]) if project._fields[name].type == 'date' and project[name] else project[name]) for name in ('contracting_goal_ar', 'contracting_goal_en', 'contract_payment_schedule_ar', 'contract_payment_schedule_en', 'contracting_start', 'contracting_end', 'contract_value', 'value_type', 'estimated_cost', 'contract_vat_percent', 'contract_retention_percent')}}
            for key, (model, allowed) in self._documents.items():
                records = request.env[model]
                result['capabilities'][key] = {'create': records.has_access('create')}
                if not records.has_access('read'):
                    result['records'][key] = []
                    continue
                domain = [('project_id', '=', project.id)]
                if key in ('payment', 'receipt'):
                    domain.append(('kind', '=', key))
                rows = []
                for rec in records.search(domain, limit=200):
                    vals = {}
                    for name in allowed:
                        field = rec._fields[name]
                        val = rec[name]
                        vals[name] = val.id if field.type == 'many2one' else (str(val) if field.type in ('date', 'datetime') and val else val)
                    rows.append({'id': rec.id, 'name': rec.display_name, 'state': rec.state if 'state' in rec._fields else '', 'values': vals, 'can_write': rec.has_access('write')})
                result['records'][key] = rows
            return result
        except (AccessError, UserError, ValueError):
            return {'error': self._message('تعذر عرض مستندات المشروع. تحقق من صلاحياتك.', 'Could not view project documents. Check your permissions.')}

    @http.route('/abroj/app/document/save', type='jsonrpc', auth='user')
    def document_save(self, project_id, kind, values, record_id=None):
        try:
            if kind not in self._documents:
                raise AccessError('عملية غير مسموحة')
            model, allowed = self._documents[kind]
            if set(values) - allowed:
                raise AccessError('حقول غير مسموحة')
            project = request.env['project.project'].browse(int(project_id)).exists()
            if not project:
                raise AccessError('المشروع غير موجود')
            project.check_access('read')
            vals = dict(values)
            if record_id:
                record = request.env[model].browse(int(record_id)).exists()
                if not record or record.project_id != project or (kind in ('payment', 'receipt') and record.kind != kind):
                    raise AccessError('المستند غير موجود')
                with request.env.cr.savepoint():
                    record.write(vals)
            else:
                vals['project_id'] = project.id
                if kind in ('payment', 'receipt'):
                    vals['kind'] = kind
                with request.env.cr.savepoint():
                    record = request.env[model].create(vals)
            return {'id': record.id}
        except (AccessError, UserError, ValidationError, ValueError):
            return {'error': self._message('تعذر حفظ المستند. تحقق من صلاحياتك والبيانات المدخلة.', 'Could not save the document. Check your permissions and input.')}

    @http.route('/abroj/app/document/action', type='jsonrpc', auth='user')
    def document_action(self, project_id, kind, record_id, action):
        try:
            actions = {'payment': ('issue', 'cancel'), 'receipt': ('issue', 'cancel'), 'promissory': ('issue', 'paid', 'cancel'), 'invoice': ('confirm',), 'cost': ('confirm',)}
            if action not in actions.get(kind, ()):
                raise AccessError('عملية غير مسموحة')
            project = request.env['project.project'].browse(int(project_id)).exists()
            if not project:
                raise AccessError('المشروع غير موجود')
            project.check_access('read')
            record = request.env[self._documents[kind][0]].browse(int(record_id)).exists()
            if not record or record.project_id != project or (kind in ('payment', 'receipt') and record.kind != kind):
                raise AccessError('المستند غير موجود')
            record.check_access('write')
            with request.env.cr.savepoint():
                getattr(record, 'action_' + action)()
            return {'ok': True}
        except (AccessError, UserError, ValidationError, ValueError):
            return {'error': self._message('تعذر تنفيذ العملية. تحقق من صلاحياتك وحالة المستند.', 'Could not complete the operation. Check your permissions and document status.')}

    @http.route('/abroj/app/pdf/<string:kind>/<int:record_id>', type='http', auth='user', methods=['GET'])
    def document_pdf(self, kind, record_id):
        reports = {
            'agreement': ('project.project', 'abroj_contracting.agreement'),
            'contract': ('abroj.contracting.subcontractor', 'abroj_contracting.subcontract'),
            'payment': ('abroj.contracting.voucher', 'abroj_contracting.voucher'),
            'receipt': ('abroj.contracting.voucher', 'abroj_contracting.voucher'),
            'promissory': ('abroj.promissory.note', 'abroj_project_dashboard.promissory_document'),
        }
        try:
            if kind not in reports:
                raise AccessError('تقرير غير متاح')
            model, report = reports[kind]
            record = request.env[model].browse(record_id).exists()
            if not record:
                raise AccessError('المستند غير موجود')
            record.check_access('read')
            project = record if kind == 'agreement' else record.project_id
            project.check_access('read')
            if kind in ('payment', 'receipt') and record.kind != kind:
                raise AccessError('المستند غير موجود')
            pdf, _ = request.env['ir.actions.report']._render_qweb_pdf(report, res_ids=record.ids)
            return request.make_response(pdf, [('Content-Type', 'application/pdf'), ('Content-Disposition', 'attachment; filename="document.pdf"')])
        except (AccessError, UserError, ValueError):
            return request.make_response(self._message('تعذر تنزيل التقرير. تحقق من صلاحياتك.', 'Could not download the report. Check your permissions.'), status=403)

    @http.route('/abroj/app/voice', type='http', auth='user', methods=['POST'])
    def voice_note(self, project_id=None, body='', file=None, **kwargs):
        import base64
        try:
            project = request.env['project.project'].browse(int(project_id)).exists()
            if not project or not file:
                raise AccessError('المشروع أو التسجيل غير موجود')
            project.check_access('read')
            content = file.read(25 * 1024 * 1024 + 1)
            if not content or len(content) > 25 * 1024 * 1024 or not (file.content_type or '').startswith('audio/'):
                raise ValidationError('التسجيل غير صالح')
            note = request.env['abroj.contracting.project.note'].create({
                'project_id': project.id, 'note_type': 'audio', 'body': body,
                'attachment': base64.b64encode(content), 'filename': file.filename,
                'mimetype': file.content_type,
            })
            return request.make_json_response({'id': note.id})
        except (AccessError, UserError, ValidationError, ValueError):
            return request.make_json_response({'error': self._message('تعذر حفظ الملاحظة الصوتية.', 'Could not save the voice note.')}, status=403)
