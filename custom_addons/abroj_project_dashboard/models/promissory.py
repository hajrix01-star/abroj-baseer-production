from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class PromissoryNote(models.Model):
    _name = 'abroj.promissory.note'
    _description = 'سند أمر'
    _order = 'issue_date desc, id desc'

    name = fields.Char('الرقم', required=True, default='/', readonly=True, copy=False)
    project_id = fields.Many2one('project.project', required=True, ondelete='restrict', index=True)
    company_id = fields.Many2one(related='project_id.company_id', store=True, index=True)
    analytic_account_id = fields.Many2one('account.analytic.account', string='الحساب التحليلي', related='project_id.account_id', store=True, readonly=True, index=True)
    partner_id = fields.Many2one('res.partner', string='الطرف', required=True, check_company=True)
    currency_id = fields.Many2one('res.currency', required=True, default=lambda self: self.env.company.currency_id)
    amount = fields.Monetary('المبلغ', required=True)
    issue_date = fields.Date('تاريخ الإصدار', required=True, default=fields.Date.context_today)
    due_date = fields.Date('تاريخ الاستحقاق', required=True)
    place = fields.Char('مكان الإصدار')
    notes = fields.Text('ملاحظات')
    attachment_ids = fields.Many2many('ir.attachment', string='المرفقات')
    state = fields.Selection([('draft', 'مسودة'), ('issued', 'صادر'), ('paid', 'مدفوع'), ('cancelled', 'ملغى')], default='draft', required=True, readonly=True, copy=False)

    @api.constrains('amount', 'issue_date', 'due_date')
    def _check_values(self):
        for note in self:
            if note.amount <= 0 or (note.issue_date and note.due_date and note.due_date < note.issue_date):
                raise ValidationError('يجب أن يكون المبلغ موجباً وتاريخ الاستحقاق بعد تاريخ الإصدار.')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('state', 'draft') != 'draft' or vals.get('name', '/') != '/':
                raise AccessError('أنشئ مسودة أولاً.')
            project = self.env['project.project'].browse(vals.get('project_id')).exists()
            if not project:
                raise ValidationError('المشروع غير موجود.')
            project.check_access('read')
            vals['name'] = self.env['ir.sequence'].next_by_code('abroj.promissory.note') or '/'
        return super().create(vals_list)

    def write(self, vals):
        if 'state' in vals or 'name' in vals:
            raise AccessError('استخدم أزرار الحالة.')
        if any(note.state != 'draft' for note in self):
            raise UserError('لا يمكن تعديل سند صادر أو ملغى.')
        if 'project_id' in vals:
            self.env['project.project'].browse(vals['project_id']).check_access('read')
        return super().write(vals)

    def unlink(self):
        if any(note.state != 'draft' for note in self):
            raise UserError('لا يمكن حذف سند صادر أو ملغى.')
        return super().unlink()

    def _transition(self, allowed, target):
        self.check_access('write')
        for note in self.sorted('id'):
            self.env.cr.execute('SELECT id FROM abroj_promissory_note WHERE id = %s FOR UPDATE', [note.id])
            note.invalidate_recordset(['state'])
            if note.state not in allowed:
                raise UserError('لا يمكن تغيير حالة السند.')
        return super().write({'state': target})

    def action_issue(self):
        return self._transition(('draft',), 'issued')

    def action_paid(self):
        return self._transition(('issued',), 'paid')

    def action_cancel(self):
        return self._transition(('draft', 'issued'), 'cancelled')
