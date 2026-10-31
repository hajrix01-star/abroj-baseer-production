from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import html2plaintext


class AbrojGallery(models.AbstractModel):
    _name = "abroj.gallery"
    _description = "Abroj gallery metadata"

    @api.model
    def get_items(self, model, record_id, type=None, task_id=None, uploader_id=None, sort="desc"):
        if model not in ('project.project', 'project.task') or type not in (None, '', 'image', 'audio', 'note', 'file') or sort not in ('asc', 'desc'):
            raise ValidationError('Invalid filter')
        record = self.env[model].browse(int(record_id)).exists()
        if not record:
            raise AccessError('Record not found')
        record.check_access('read')
        tasks = (self.env['project.task'].with_context(active_test=False).search([('project_id', '=', record.id)])
                 if model == 'project.project' else record)
        names = {task.id: task.name for task in tasks}
        targets = [('project.task', task.id) for task in tasks]
        if model == 'project.project':
            targets.append((model, record.id))
        if task_id:
            task_id = int(task_id)
            targets = [target for target in targets if target == ('project.task', task_id)]
        if not targets:
            return []
        domain = ['|'] * (len(targets) - 1)
        for target_model, target_id in targets:
            domain += ['&', ('res_model', '=', target_model), ('res_id', '=', target_id)]
        attachment_domain = domain + [('type', '=', 'binary')]
        if uploader_id:
            attachment_domain += [('create_uid', '=', int(uploader_id))]
        result = []
        for a in self.env['ir.attachment'].search(attachment_domain):
            mime = a.mimetype or ''
            category = 'image' if mime.startswith('image/') else 'audio' if mime.startswith('audio/') else 'file'
            if type and category != type:
                continue
            result.append({'id': a.id, 'name': a.name, 'mimetype': mime, 'type': category,
                           'create_uid': a.create_uid.name or '', 'uploader_id': a.create_uid.id,
                           'create_date': a.create_date.isoformat(timespec='seconds') + 'Z' if a.create_date else False, 'res_model': a.res_model,
                           'res_id': a.res_id, 'phase': names.get(a.res_id) if a.res_model == 'project.task' else None,
                           'description': a.description or ''})
        if not type or type == 'note':
            message_domain = ['|'] * (len(targets) - 1)
            for target_model, target_id in targets:
                message_domain += ['&', ('model', '=', target_model), ('res_id', '=', target_id)]
            message_domain += [('subtype_id', '=', self.env.ref('mail.mt_note').id), ('message_type', '=', 'comment')]
            if uploader_id:
                message_domain += [('create_uid', '=', int(uploader_id))]
            for m in self.env['mail.message'].search(message_domain):
                body = html2plaintext(m.body or '').strip()
                if body:
                    result.append({'id': m.id, 'name': '', 'mimetype': 'text/plain', 'type': 'note',
                                   'create_uid': m.create_uid.name or '', 'uploader_id': m.create_uid.id,
                                   'create_date': m.create_date.isoformat(timespec='seconds') + 'Z' if m.create_date else False, 'res_model': m.model,
                                   'res_id': m.res_id, 'phase': names.get(m.res_id) if m.model == 'project.task' else None,
                                   'description': body})
        result.sort(key=lambda item: (item['create_date'] or '', item['id']), reverse=sort == 'desc')
        return result


class Project(models.Model):
    _inherit = "project.project"

    abroj_gallery_widget = fields.Char(compute="_compute_abroj_gallery_widget")

    def _compute_abroj_gallery_widget(self):
        for project in self:
            project.abroj_gallery_widget = ""

    def get_abroj_gallery(self):
        self.ensure_one()
        return self.env["abroj.gallery"].get_items("project.project", self.id)
