import logging
import requests
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class Inbox(models.Model):
    _name = 'abroj.contracting.inbox'
    _inherit = 'abroj.contracting.document'
    _description = 'صندوق الوارد'
    _rec_name = 'filename'
    _order = 'id desc'

    project_id = fields.Many2one(required=False)
    company_id = fields.Many2one('res.company', related=False, compute='_compute_inbox_company', store=True)
    project_note_ids = fields.One2many('abroj.contracting.project.note', 'inbox_id', string='ملاحظة المشروع', readonly=True)

    @api.depends('project_id.company_id')
    def _compute_inbox_company(self):
        for item in self:
            item.company_id = item.project_id.company_id if item.project_id else (item.company_id or self.env.company)

    @api.constrains('project_id')
    def _check_project_company(self):
        super(Inbox, self.filtered('project_id'))._check_project_company()

    def _ensure_project_note(self):
        # Serialize repeated/concurrent assignment before checking the unique link.
        for item in self.filtered('project_id').sorted('id'):
            self.env.cr.execute('SELECT id FROM abroj_contracting_inbox WHERE id = %s FOR UPDATE', [item.id])
            item.invalidate_recordset(['project_note_ids'])
            if item.project_note_ids:
                continue
            mimetype = item.mimetype or ''
            kind = next((kind for kind in ('audio', 'image', 'video') if mimetype.startswith(kind + '/')), 'text')
            if mimetype == 'application/pdf':
                kind = 'pdf'
            self.env['abroj.contracting.project.note'].create({
                'project_id': item.project_id.id, 'inbox_id': item.id,
                'body': item.note, 'attachment': item.file, 'filename': item.filename,
                'mimetype': item.mimetype, 'note_type': kind,
                'author_id': item.create_uid.id, 'date': item.create_date,
            })

    def write(self, vals):
        result = super().write(vals)
        if 'project_id' in vals:
            self._ensure_project_note()
        return result

    file = fields.Binary('الملف', attachment=True)
    filename = fields.Char('اسم الملف', required=True)
    mimetype = fields.Char('نوع الملف')
    note = fields.Text('ملاحظة')
    state = fields.Selection([('pending', 'بانتظار التحليل'), ('analyzed', 'تم التحليل')], string='الحالة', default='pending', required=True)
    extracted_text = fields.Text('النص المستخرج للمراجعة')

    @api.model
    def _send_webhook(self, url, key, payload):
        # No response body, URL, headers or exception details in logs.
        try:
            requests.post(url, json=payload, headers={'X-Abroj-Key': key}, timeout=3, allow_redirects=False)
        except Exception:
            _logger.warning('Contracting inbox notification failed')

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._ensure_project_note()
        params = self.env['ir.config_parameter'].sudo()
        url = params.get_param('abroj_contracting.agent_webhook_url')
        if not url:
            return records
        key = params.get_param('abroj_contracting.agent_webhook_key', '')
        # Snapshot metadata now; callback uses neither a closed cursor nor file data.
        sender = self._send_webhook
        for r in records:
            payload = {'id': r.id, 'model': r._name, 'project_id': r.project_id.id,
                       'project_name': r.project_id.name, 'filename': r.filename,
                       'mimetype': r.mimetype, 'state': r.state,
                       'create_uid': r.create_uid.id, 'create_date': fields.Datetime.to_string(r.create_date)}
            if 'abroj_invoice_bill_id' in r._fields and r.abroj_invoice_bill_id:
                payload.update({'document_type': 'invoice', 'bill_id': r.abroj_invoice_bill_id.id})
            def notify(payload=payload):
                try:
                    sender(url, key, payload)
                except Exception:
                    _logger.warning('Contracting inbox notification failed')
            self.env.cr.postcommit.add(notify)
        return records
