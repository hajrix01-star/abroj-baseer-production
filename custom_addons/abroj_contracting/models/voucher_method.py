from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from .accounting_issue import ACCOUNTING_GROUPS, require_accountant
from .contracting import FrozenDocument
from .guards import check_agent


METHODS = [('cash', 'نقداً'), ('bank', 'تحويل بنكي'), ('other', 'أخرى')]


class Voucher(models.Model):
    _inherit = 'abroj.contracting.voucher'

    method_log_ids = fields.One2many('abroj.contracting.voucher.method.log', 'voucher_id',
                                     string='سجل تغيير طريقة الدفع', readonly=True, groups=ACCOUNTING_GROUPS)

    def _abroj_check_change_payment_method(self, method, journal):
        """Extension point for accounting-specific restrictions."""
        self.ensure_one()

    def action_open_change_method(self):
        self.ensure_one()
        check_agent(self.env)
        require_accountant(self.env)
        self.check_access('write')
        if self.state != 'issued' or self.payment_id:
            raise UserError('تغيير طريقة الدفع متاح لسند صادر دون دفعة فقط.')
        return {'type': 'ir.actions.act_window', 'name': 'تغيير طريقة الدفع',
                'res_model': 'abroj.contracting.voucher.change.method', 'view_mode': 'form',
                'target': 'new', 'context': dict(self.env.context, default_voucher_id=self.id)}

    def _abroj_change_payment_method(self, method, journal):
        self.ensure_one()
        check_agent(self.env)
        require_accountant(self.env)
        self.check_access('write')
        if method not in dict(METHODS):
            raise ValidationError('طريقة الدفع غير صالحة.')
        if journal:
            journal.ensure_one()
            if not journal.exists():
                raise ValidationError('دفتر الدفع غير موجود.')
        else:
            journal = self.env['account.journal']
        self.env.cr.execute('SELECT id FROM abroj_contracting_voucher WHERE id = %s FOR NO KEY UPDATE', [self.id])
        self.invalidate_recordset(['state', 'payment_id', 'method', 'journal_id', 'company_id'])
        if self.state != 'issued' or self.payment_id:
            raise UserError('تغيير طريقة الدفع متاح لسند صادر دون دفعة فقط.')
        if journal:
            journal.sudo().invalidate_recordset(['company_id', 'type', 'active'])
            journal_data = journal.sudo()
            # Both review and legacy approval treat "other" as a bank method.
            expected_type = 'cash' if method == 'cash' else 'bank'
            if journal_data.company_id != self.company_id or journal_data.type != expected_type or not journal_data.active:
                raise ValidationError('اختر دفترًا نشطًا من شركة السند يطابق طريقة الدفع.')
            journal.check_access('read')
        if self.method == method and self.journal_id == journal:
            raise UserError('لم تتغير طريقة الدفع أو دفتر الدفع.')
        self._abroj_check_change_payment_method(method, journal)
        old_method, old_journal = self.method, self.journal_id
        super(FrozenDocument, self).write({'method': method, 'journal_id': journal.id or False})
        self.env['abroj.contracting.voucher.method.log'].sudo().create({
            'voucher_id': self.id, 'user_id': self.env.uid, 'changed_at': fields.Datetime.now(),
            'old_method': old_method, 'new_method': method,
            'old_journal_id': old_journal.id or False, 'new_journal_id': journal.id or False,
        })
        return True


class VoucherMethodLog(models.Model):
    _name = 'abroj.contracting.voucher.method.log'
    _description = 'سجل تغيير طريقة دفع السند'
    _order = 'changed_at desc, id desc'

    voucher_id = fields.Many2one('abroj.contracting.voucher', required=True, ondelete='cascade', index=True, readonly=True)
    company_id = fields.Many2one(related='voucher_id.company_id', store=True, readonly=True)
    user_id = fields.Many2one('res.users', string='المستخدم', required=True, readonly=True)
    changed_at = fields.Datetime('وقت التغيير', required=True, readonly=True)
    old_method = fields.Selection(METHODS, string='الطريقة السابقة', required=True, readonly=True)
    new_method = fields.Selection(METHODS, string='الطريقة الجديدة', required=True, readonly=True)
    old_journal_id = fields.Many2one('account.journal', string='الدفتر السابق', readonly=True, ondelete='restrict')
    new_journal_id = fields.Many2one('account.journal', string='الدفتر الجديد', readonly=True, ondelete='restrict')


class VoucherChangeMethod(models.TransientModel):
    _name = 'abroj.contracting.voucher.change.method'
    _description = 'تغيير طريقة دفع السند'

    voucher_id = fields.Many2one('abroj.contracting.voucher', string='السند', required=True, readonly=True)
    company_id = fields.Many2one(related='voucher_id.company_id', readonly=True)
    method = fields.Selection(METHODS, string='طريقة الدفع الجديدة', required=True)
    journal_id = fields.Many2one('account.journal', string='دفتر الدفع الجديد')

    @api.onchange('method')
    def _onchange_method(self):
        for wizard in self:
            if wizard.journal_id and wizard.journal_id.type != ('cash' if wizard.method == 'cash' else 'bank'):
                wizard.journal_id = False

    @api.model
    def default_get(self, field_list):
        values = super().default_get(field_list)
        voucher = self.env['abroj.contracting.voucher'].browse(values.get('voucher_id')).exists()
        if voucher:
            if 'method' in field_list:
                values['method'] = voucher.method
            if 'journal_id' in field_list:
                values['journal_id'] = voucher.journal_id.id
        return values

    def action_apply(self):
        self.ensure_one()
        self.voucher_id._abroj_change_payment_method(self.method, self.journal_id)
        return {'type': 'ir.actions.act_window_close'}
