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
            def notify(payload=payload):
                try:
                    sender(url, key, payload)
                except Exception:
                    _logger.warning('Contracting inbox notification failed')
            self.env.cr.postcommit.add(notify)
        return records
