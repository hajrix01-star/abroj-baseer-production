import base64
import binascii
import json
import html
import hashlib
import re
import logging
from pathlib import Path
import math

from odoo import fields

from odoo import http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request


_logger = logging.getLogger(__name__)

_PWA_DIR = Path(__file__).parent.parent / 'static/pwa'
# The worker's ASSETS list is the source of truth for the versioned files.
_worker_source = (_PWA_DIR / 'sw.js').read_text(encoding='utf-8')
_asset_list = re.search(r'const ASSETS = \[(.*?)\];', _worker_source, re.DOTALL).group(1)
_asset_paths = re.findall(r"'(/abroj_project_dashboard/static/pwa/[^']+)'", _asset_list)
if not _asset_paths:
    raise ValueError('The service worker asset list is empty')
_asset_hash = hashlib.sha1()
for _asset in _asset_paths:
    _asset_hash.update(_asset.encode('utf-8') + b'\0')
    _asset_hash.update((_PWA_DIR / _asset.rsplit('/static/pwa/', 1)[1]).read_bytes())
ASSET_VERSION = _asset_hash.hexdigest()[:12]


class AbrojApp(http.Controller):
    @staticmethod
    def _real_image(value):
        if not value:
            return False
        try:
            raw = base64.b64decode(value)
        except (ValueError, binascii.Error):
            return False
        return bool(raw and b'<svg' not in raw[:1024].lower())

    @staticmethod
    def _message(ar, en):
        return ar if (request.env.lang or '').startswith('ar') else en

    @staticmethod
    def _can_create_invoice():
        user = request.env.user
        purchase_group = request.env.ref('purchase.group_purchase_user', raise_if_not_found=False)
        return bool('account.move' in request.env and
                    (user.has_group('account.group_account_invoice') or
                     (purchase_group and user.has_group('purchase.group_purchase_user'))) and
                    request.env['account.move'].has_access('create'))

    @http.route('/abroj/app', type='http', auth='user', methods=['GET'])
    def app(self):
        page = (Path(__file__).parent.parent / 'static/pwa/index.html').read_text(encoding='utf-8')
        page = page.replace('ASSET_VERSION_PLACEHOLDER', ASSET_VERSION)
        page = page.replace('CSRF_TOKEN_PLACEHOLDER', request.csrf_token())
        page = page.replace('SESSION_UID_PLACEHOLDER', str(request.session.uid)).replace('SESSION_DB_PLACEHOLDER', html.escape(request.session.db, quote=True))
        page = page.replace('USER_LANG_PLACEHOLDER', 'ar' if (request.env.user.lang or '').startswith('ar') else 'en')
        return request.make_response(page, [('Content-Type', 'text/html; charset=utf-8'), ('Cache-Control', 'no-store')])

    @http.route('/abroj/app/language', type='jsonrpc', auth='user')
    def language(self, lang):
        requested = lang if isinstance(lang, str) else ''
        ui_lang = 'ar' if requested.lower().startswith('ar') else 'en'
        languages = request.env['res.lang'].sudo()
        if requested in ('ar', 'en'):
            preferred = 'ar_001' if requested == 'ar' else 'en_US'
            language = languages.search([('code', '=', preferred), ('active', '=', True)], limit=1)
            if not language:
                language = languages.search([('code', '=like', 'ar%' if requested == 'ar' else 'en_%'), ('active', '=', True)], order='code', limit=1)
        else:
            language = languages.search([('code', '=', requested), ('active', '=', True)], limit=1)
        result = {'ok': True, 'server_synced': False, 'ui_lang': ui_lang}
        if not language:
            return result
        try:
            with request.env.cr.savepoint():
                request.env.user.write({'lang': language.code})
            request.session.context = dict(request.session.context, lang=language.code)
            result['server_synced'] = True
        except (AccessError, UserError, ValidationError):
            pass
        return result

    @http.route('/abroj/app/manifest.webmanifest', type='http', auth='public', methods=['GET'])
    def manifest(self):
        data = {'name': self._message('أبرج للمقاولات', 'Abroj Contracting'), 'short_name': self._message('أبرج', 'Abroj'), 'start_url': '/abroj/app', 'scope': '/abroj/app', 'display': 'standalone', 'dir': self._message('rtl', 'ltr'), 'lang': self._message('ar', 'en'), 'theme_color': '#12243b', 'background_color': '#f5f6f8', 'icons': [{'src': '/abroj_project_dashboard/static/pwa/icon-%d.png?v=%s' % (n, ASSET_VERSION), 'sizes': '%dx%d' % (n, n), 'type': 'image/png'} for n in (192, 512)] + [{'src': '/abroj_project_dashboard/static/pwa/icon-maskable-512.png?v=%s' % ASSET_VERSION, 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'}]}
        return request.make_response(json.dumps(data, ensure_ascii=False), [('Content-Type', 'application/manifest+json'), ('Cache-Control', 'no-store, no-cache, must-revalidate'), ('Pragma', 'no-cache'), ('Expires', '0')])

    @http.route('/abroj/app/sw.js', type='http', auth='public', methods=['GET'])
    def sw(self):
        source = _worker_source.replace('ASSET_VERSION_PLACEHOLDER', ASSET_VERSION)
        return request.make_response(source, [('Content-Type', 'application/javascript'), ('Service-Worker-Allowed', '/abroj/app'), ('Cache-Control', 'no-store')])

    @http.route('/abroj/app/data', type='jsonrpc', auth='user')
    def data(self, filters=None, project_id=None, include_archived=False):
        projects = request.env['project.project']
        result = projects.get_abroj_project_detail(project_id) if project_id else projects.get_abroj_dashboard_data(filters, include_archived=include_archived)
        if isinstance(result, dict):
            result['can_create_invoice'] = self._can_create_invoice()
            user = request.env.user
            employee = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1) if 'hr.employee' in request.env else None
            image_model, image_record = ('hr.employee', employee) if employee and self._real_image(employee.image_128) else ('res.users', user)
            avatar_url = '/web/image/%s/%s/image_128' % (image_model, image_record.id) if self._real_image(image_record.image_128) else False
            admin = request.env.ref('base.user_admin', raise_if_not_found=False)
            result['current_user'] = {
                'id': user.id, 'name': user.name or '', 'avatar_url': avatar_url, 'tz': user.tz or False,
                'is_system': user == admin or user.id == 1 or user.login == '__system__' or user.name == 'Administrator',
                'department': employee.department_id.name or '' if employee else '',
                'job_title': employee.job_title or '' if employee else '',
                'email': user.email or '', 'phone': user.phone or '',
            }
        return result

    @http.route('/abroj/app/project/options', type='jsonrpc', auth='user')
    def project_options(self, search=''):
        try:
            if not request.env['project.project'].has_access('create'):
                raise AccessError('Project create access required')
            partners = request.env['res.partner'].search([('name', 'ilike', str(search or '')[:100])], limit=20) if search else request.env['res.partner']
            users = request.env['res.users'].search([('share', '=', False)])
            return {'partners': [{'id': p.id, 'name': p.name} for p in partners],
                    'users': [{'id': u.id, 'name': u.name, 'is_system': u.id in (1, request.env.ref('base.user_admin').id) or u.login == '__system__' or u.name == 'Administrator'} for u in users], 'current_user': request.env.uid}
        except AccessError:
            return {'error': self._message('لا تملك صلاحية إنشاء مشروع.', 'You do not have permission to create a project.')}

    @http.route('/abroj/app/project/create', type='jsonrpc', auth='user')
    def create_project(self, name='', customer_id=None, customer_name='', location='', budget=0, start='', end='', manager_id=None, project_type='other'):
        try:
            if not request.env['project.project'].has_access('create'):
                raise AccessError('Project create access required')
            if not isinstance(name, str) or not name.strip():
                return {'field': 'name', 'error': self._message('اسم المشروع مطلوب.', 'Project name is required.')}
            start_date = fields.Date.to_date(start) if start else False
            end_date = fields.Date.to_date(end) if end else False
            if start_date and end_date and end_date < start_date:
                return {'field': 'end', 'error': self._message('يجب أن يكون تاريخ النهاية بعد البداية أو مساوياً لها.', 'End date must be on or after start date.')}
            if not isinstance(location, str) or not isinstance(customer_name, str):
                raise ValueError('Invalid text')
            amount = float(budget or 0)
            if not math.isfinite(amount) or amount < 0:
                raise ValueError('Invalid budget')
            if project_type not in dict(request.env['project.project']._fields['abroj_type'].selection):
                raise ValueError('Invalid type')
            with request.env.cr.savepoint():
                partner = request.env['res.partner']
                if customer_id:
                    partner = partner.search([('id', '=', int(customer_id))], limit=1)
                    if not partner:
                        raise AccessError('Customer unavailable')
                elif customer_name.strip():
                    partner = partner.create({'name': customer_name.strip()})
                manager = request.env['res.users'].search([('id', '=', int(manager_id or request.env.uid)), ('share', '=', False)], limit=1)
                if not manager:
                    raise AccessError('Manager unavailable')
                project = request.env['project.project'].create({'name': name.strip(), 'company_id': request.env.company.id,
                    'partner_id': partner.id or False, 'user_id': manager.id, 'abroj_location': location.strip(),
                    'abroj_budget': amount, 'date_start': start_date, 'date': end_date, 'abroj_type': project_type})
            return {'id': project.id}
        except AccessError:
            return {'error': self._message('لا تملك صلاحية إنشاء المشروع أو العميل المحدد.', 'You do not have permission to create the project or selected customer.')}
        except (UserError, ValidationError, ValueError, TypeError, OverflowError):
            return {'error': self._message('تعذر إنشاء المشروع. تحقق من البيانات المدخلة.', 'Could not create the project. Check your input.')}

    @http.route('/abroj/app/project/close-summary', type='jsonrpc', auth='user')
    def close_summary(self, project_id):
        try:
            project = request.env['project.project'].with_context(active_test=False).browse(int(project_id)).exists()
            if not project:
                raise AccessError('Project not found')
            return project.abroj_close_summary()
        except (AccessError, UserError, ValidationError):
            return {'error': self._message('تعذر عرض ملخص الإغلاق. تحقق من صلاحياتك.', 'Could not view the close summary. Check your permissions.')}

    @http.route('/abroj/app/project/set-closed', type='jsonrpc', auth='user')
    def set_closed(self, project_id, closed, note=''):
        try:
            if not isinstance(closed, bool) or not isinstance(note, str):
                raise ValidationError('Invalid input')
            with request.env.cr.savepoint():
                project = request.env['project.project'].with_context(active_test=False).browse(int(project_id)).exists()
                if not project:
                    raise AccessError('Project not found')
                project.abroj_set_closed(closed, note)
            return {'ok': True}
        except (AccessError, UserError, ValidationError):
            return {'error': self._message('تعذر تغيير حالة المشروع. تحقق من صلاحياتك وإعداد المراحل.', 'Could not change the project status. Check your permissions and stage setup.')}

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

    @http.route('/abroj/app/note', type='jsonrpc', auth='user')
    def text_note(self, model, record_id, body):
        try:
            if model not in ('project.project', 'project.task') or not isinstance(body, str) or not body.strip():
                raise ValidationError('Invalid note')
            record = request.env[model].browse(int(record_id)).exists()
            if not record:
                raise AccessError('Record not found')
            record.check_access('write')
            message = record.message_post(body=body.strip(), message_type='comment', subtype_xmlid='mail.mt_note')
            return {'id': message.id}
        except (AccessError, UserError, ValidationError, ValueError, TypeError):
            return {'error': self._message('تعذر حفظ الملاحظة.', 'Could not save the note.')}

    @http.route('/abroj/app/attachments', type='jsonrpc', auth='user')
    def attachments(self, model, record_id, type=None, task_id=None, uploader_id=None, sort='desc'):
        try:
            return request.env['abroj.gallery'].get_items(model, record_id, type, task_id, uploader_id, sort)
        except (AccessError, UserError, ValidationError, ValueError, TypeError):
            return {'error': self._message('تعذر عرض المرفقات. تحقق من صلاحياتك.', 'Could not view attachments. Check your permissions.')}

    @http.route('/abroj/app/library', type='jsonrpc', auth='user')
    def library(self, project_id):
        try:
            project = request.env['project.project'].with_context(active_test=False).browse(int(project_id)).exists()
            if not project:
                raise AccessError('Project not found')
            project.check_access('read')
            tasks = request.env['project.task'].with_context(active_test=False).search([('project_id', '=', project.id)])
            attachments = request.env['ir.attachment'].search([
                ('type', '=', 'binary'), ('abroj_is_invoice', '=', False),
                '|', '&', ('res_model', '=', 'project.project'), ('res_id', '=', project.id),
                '&', ('res_model', '=', 'project.task'), ('res_id', 'in', tasks.ids),
            ])
            # Older invoice inbox items generated a project note and an unmarked
            # project attachment. Match that copy by project, filename and bytes.
            inboxes = request.env['abroj.contracting.inbox'].sudo().search([
                ('project_id', '=', project.id), ('abroj_invoice_bill_id', '!=', False),
            ])
            invoice_files = request.env['ir.attachment'].sudo().search([
                ('res_model', '=', 'abroj.contracting.inbox'), ('res_id', 'in', inboxes.ids),
                ('res_field', '=', 'file'),
            ])
            filenames = {inbox.id: inbox.filename for inbox in inboxes}
            invoice_keys = {(filenames[attachment.res_id], attachment.checksum)
                            for attachment in invoice_files if attachment.checksum}
            attachments = attachments.filtered(lambda attachment: attachment.res_model != 'project.project'
                                               or (attachment.name, attachment.checksum) not in invoice_keys)
            return [{'id': a.id, 'name': a.name, 'mimetype': a.mimetype or ''} for a in attachments]
        except (AccessError, UserError, ValueError, TypeError):
            return {'error': self._message('تعذر عرض المكتبة. تحقق من صلاحياتك.', 'Could not view the library. Check your permissions.')}

    @http.route('/abroj/app/invoice', type='http', auth='user', methods=['POST'])
    def invoice_upload(self, project_id=None, file=None, **kwargs):
        import base64
        if 'account.move' not in request.env:
            return request.make_json_response({'error': self._message('تطبيق المحاسبة غير متاح.', 'The Accounting app is not available.')}, status=400)
        try:
            if not self._can_create_invoice():
                return request.make_json_response({'error': self._message('لا تملك صلاحية إنشاء فواتير الموردين.', 'You do not have permission to create vendor bills.')}, status=403)
            with request.env.cr.savepoint():
                project = request.env['project.project'].with_context(active_test=False).browse(int(project_id)).exists()
                if not project or not file:
                    raise AccessError('Project or file missing')
                project.check_access('write')
                content = file.read(25 * 1024 * 1024 + 1)
                if not content or len(content) > 25 * 1024 * 1024:
                    raise UserError('Invalid file size')
                # An empty bill cannot yet have analytic lines; keep an explicit project reference.
                bill = request.env['account.move'].with_company(project.company_id).create({
                    'move_type': 'in_invoice', 'company_id': project.company_id.id,
                    'ref': 'Project: %s (ID %s) — pending extraction' % (project.name, project.id),
                })
                request.env['ir.attachment'].with_context(image_no_postprocess=True).create({
                    'name': file.filename, 'res_model': 'account.move', 'res_id': bill.id,
                    'datas': base64.b64encode(content), 'mimetype': file.content_type, 'abroj_is_invoice': True,
                })
                request.env['abroj.contracting.inbox'].create({
                    'project_id': project.id, 'filename': file.filename, 'mimetype': file.content_type,
                    'file': base64.b64encode(content), 'abroj_invoice_bill_id': bill.id,
                    'note': 'Invoice — pending extraction',
                })
            return request.make_json_response({'id': bill.id, 'state': bill.state, 'extraction': 'pending'})
        except Exception:
            _logger.exception('Could not create the draft vendor bill')
            return request.make_json_response({'error': self._message('تعذر إنشاء الفاتورة المسودة. تحقق من الصلاحيات والملف وإعدادات المحاسبة.', 'Could not create the draft bill. Check permissions, the file and accounting setup.')}, status=403)

    @http.route('/abroj/app/upload', type='http', auth='user', methods=['POST'])
    def upload(self, model=None, record_id=None, file=None, **kwargs):
        import base64
        try:
            if kwargs.get('owner_uid') is not None and str(kwargs['owner_uid']) != str(request.session.uid):
                raise AccessError('Upload owner does not match session')
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
                    rows.append({'id': rec.id, 'name': '' if rec.display_name == '/' else rec.display_name, 'state': rec.state if 'state' in rec._fields else '', 'values': vals, 'can_write': rec.has_access('write')})
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
        except AccessError:
            return request.make_response(self._message('تعذر تنزيل التقرير. تحقق من صلاحياتك.', 'Could not download the report. Check your permissions.'), status=403)
        except Exception as error:
            return request.make_response(str(error), [('Content-Type', 'text/plain; charset=utf-8')], status=500)

    @http.route('/abroj/app/voice', type='http', auth='user', methods=['POST'])
    def voice_note(self, project_id=None, body='', file=None, **kwargs):
        import base64
        try:
            if kwargs.get('owner_uid') is not None and str(kwargs['owner_uid']) != str(request.session.uid):
                raise AccessError('Upload owner does not match session')
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
