from markupsafe import Markup, escape
from odoo import api, fields, models


class ProjectNote(models.Model):
    _name = 'abroj.contracting.project.note'
    _inherit = 'abroj.contracting.document'
    _description = 'ملاحظة المشروع'
    _rec_name = 'body'
    _order = 'date desc, id desc'

    project_id = fields.Many2one(ondelete='cascade')
    note_type = fields.Selection([
        ('text', 'نص'), ('audio', 'صوت'), ('image', 'صورة'),
        ('video', 'فيديو'), ('pdf', 'مستند PDF')], string='النوع', default='text', required=True)
    body = fields.Text('الملاحظة')
    attachment = fields.Binary('الملف', attachment=True)
    filename = fields.Char('اسم الملف')
    mimetype = fields.Char('نوع الملف')
    author_id = fields.Many2one('res.users', string='الكاتب', default=lambda self: self.env.user, required=True)
    date = fields.Datetime('التاريخ', default=fields.Datetime.now, required=True)
    inbox_id = fields.Many2one('abroj.contracting.inbox', string='الوارد', ondelete='set null', copy=False, index=True)
    _inbox_unique = models.Constraint('UNIQUE(inbox_id)', 'يوجد ملاحظة لهذا السجل بالفعل.')

    @api.model_create_multi
    def create(self, vals_list):
        notes = super().create(vals_list)
        for note in notes:
            project = note.project_id
            project.check_access('read')
            # Posting this note must not require write access to its project.
            project = project.sudo()
            attachments = project.env['ir.attachment']
            if note.attachment:
                attachments = attachments.create({
                    'name': note.filename or 'مرفق', 'datas': note.attachment,
                    'mimetype': note.mimetype or 'application/octet-stream',
                    'res_model': 'project.project', 'res_id': project.id,
                })
            body = Markup('<p>%s</p>') % escape(note.body or 'ملاحظة جديدة')
            project.message_post(body=body, attachment_ids=attachments.ids,
                                 author_id=note.author_id.partner_id.id,
                                 message_type='comment', subtype_xmlid='mail.mt_note')
        return notes
