from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from .guards import check_agent


class Project(models.Model):
    _inherit = 'project.project'

    contracting_goal = fields.Text('الهدف')
    contract_value = fields.Monetary('قيمة العقد')
    contracting_start = fields.Date('تاريخ الاتفاقية / البدء')
    contracting_end = fields.Date('تاريخ الانتهاء')
    duration_days = fields.Integer('مدة التنفيذ بالأيام', compute='_compute_duration', store=True)
    value_type = fields.Selection([('materials', 'شامل مواد'), ('labor', 'بدون مواد')], string='نوع القيمة')
    estimated_cost = fields.Monetary('التكلفة التقديرية')
    expected_profit = fields.Monetary('الربح المتوقع', compute='_compute_totals', store=True)
    subcontractor_ids = fields.One2many('abroj.contracting.subcontractor', 'project_id', string='مقاولو الباطن')
    voucher_ids = fields.One2many('abroj.contracting.voucher', 'project_id', string='السندات')
    invoice_ids = fields.One2many('abroj.contracting.invoice', 'project_id', string='فواتير المقاولين')
    cost_ids = fields.One2many('abroj.contracting.cost', 'project_id', string='المصروفات')
    inbox_ids = fields.One2many('abroj.contracting.inbox', 'project_id', string='السجلات')
    total_costs = fields.Monetary('إجمالي التكاليف', compute='_compute_totals', store=True)
    total_paid = fields.Monetary('المدفوع', compute='_compute_totals', store=True)
    total_received = fields.Monetary('المقبوض', compute='_compute_totals', store=True)
    remaining = fields.Monetary('المتبقي من العقد', compute='_compute_totals', store=True)
    profit = fields.Monetary('ربح العقد', compute='_compute_totals', store=True)
    cash_balance = fields.Monetary('صافي التدفق النقدي', compute='_compute_totals', store=True)

    @api.depends('contracting_start', 'contracting_end')
    def _compute_duration(self):
        for r in self:
            r.duration_days = (r.contracting_end - r.contracting_start).days if r.contracting_start and r.contracting_end else 0

    @api.constrains('contracting_start', 'contracting_end')
    def _check_dates(self):
        for r in self:
            if r.contracting_start and r.contracting_end and r.contracting_end < r.contracting_start:
                raise ValidationError('تاريخ الانتهاء يسبق تاريخ البدء.')

    @api.depends('contract_value', 'estimated_cost', 'company_id.currency_id', 'voucher_ids.amount', 'voucher_ids.state',
                 'voucher_ids.kind', 'invoice_ids.amount', 'invoice_ids.state', 'cost_ids.amount', 'cost_ids.state')
    def _compute_totals(self):
        for r in self:
            issued = r.voucher_ids.filtered(lambda v: v.state == 'issued')
            r.total_paid = sum(issued.filtered(lambda v: v.kind == 'payment').mapped('amount'))
            r.total_received = sum(issued.filtered(lambda v: v.kind == 'receipt').mapped('amount'))
            r.total_costs = sum(r.invoice_ids.filtered(lambda i: i.state == 'confirmed').mapped('amount')) + sum(r.cost_ids.filtered(lambda i: i.state == 'confirmed').mapped('amount'))
            r.remaining = r.contract_value - r.total_received
            r.profit = r.contract_value - r.total_costs
            r.expected_profit = r.contract_value - r.estimated_cost
            r.cash_balance = r.total_received - r.total_paid


class ProjectDocument(models.AbstractModel):
    _name = 'abroj.contracting.document'
    _description = 'مستند مشروع'
    _check_company_auto = True

    project_id = fields.Many2one('project.project', string='المشروع', required=True, check_company=True, ondelete='restrict')
    company_id = fields.Many2one('res.company', string='الشركة', related='project_id.company_id', store=True)
    currency_id = fields.Many2one('res.currency', string='العملة', related='company_id.currency_id')

    @api.constrains('project_id')
    def _check_project_company(self):
        for r in self:
            if not r.company_id:
                raise ValidationError('يجب تحديد شركة المشروع.')


class FrozenDocument(models.AbstractModel):
    _name = 'abroj.contracting.frozen'
    _inherit = 'abroj.contracting.document'
    _description = 'مستند مالي'

    amount = fields.Monetary('المبلغ', required=True)
    date = fields.Date('التاريخ', default=fields.Date.context_today, required=True)

    @api.constrains('amount')
    def _check_amount(self):
        for r in self:
            if r.amount <= 0:
                raise ValidationError('المبلغ يجب أن يكون موجباً.')

    @api.model_create_multi
    def create(self, vals_list):
        if any(v.get('state', 'draft') != 'draft' for v in vals_list):
            raise AccessError('أنشئ مسودة أولاً.')
        return super().create(vals_list)

    def write(self, vals):
        if any(r.state != 'draft' for r in self):
            raise UserError('لا يمكن تعديل مستند معتمد أو ملغى.')
        if 'state' in vals:
            raise AccessError('استخدم زر الاعتماد أو الإلغاء.')
        return super().write(vals)

    def unlink(self):
        if any(r.state != 'draft' for r in self):
            raise UserError('لا يمكن حذف مستند معتمد أو ملغى.')
        return super().unlink()

    def _transition(self, state):
        check_agent(self.env)
        if any(r.state != 'draft' for r in self):
            raise UserError('العملية متاحة للمسودات فقط.')
        return super(FrozenDocument, self).write({'state': state})

    def action_confirm(self):
        return self._transition('confirmed')


class Subcontractor(models.Model):
    _name = 'abroj.contracting.subcontractor'
    _inherit = 'abroj.contracting.document'
    _description = 'مقاول باطن'
    _rec_name = 'partner_id'

    partner_id = fields.Many2one('res.partner', string='المقاول', required=True, check_company=True)
    scope = fields.Text('نطاق العمل')
    contract_type = fields.Selection([('labor', 'عمالة'), ('materials', 'شامل مواد'), ('lump', 'مقطوعية'), ('other', 'أخرى')], string='نوع العقد')
    payment_terms = fields.Text('شروط الدفع')
    duration_days = fields.Integer('مدة الإنجاز بالأيام')
    agreed_amount = fields.Monetary('القيمة المتفق عليها')
    voucher_ids = fields.One2many('abroj.contracting.voucher', 'subcontractor_id', string='السندات')
    invoice_ids = fields.One2many('abroj.contracting.invoice', 'subcontractor_id', string='الفواتير')
    paid = fields.Monetary('المدفوع', compute='_compute_balances', store=True)
    received = fields.Monetary('المسترد', compute='_compute_balances', store=True)
    invoiced = fields.Monetary('المفوتر', compute='_compute_balances', store=True)
    remaining = fields.Monetary('المتبقي', compute='_compute_balances', store=True, help='المتفق عليه - المدفوع + المسترد')

    @api.depends('agreed_amount', 'voucher_ids.amount', 'voucher_ids.state', 'voucher_ids.kind', 'invoice_ids.amount', 'invoice_ids.state')
    def _compute_balances(self):
        for r in self:
            issued = r.voucher_ids.filtered(lambda v: v.state == 'issued')
            r.paid = sum(issued.filtered(lambda v: v.kind == 'payment').mapped('amount'))
            r.received = sum(issued.filtered(lambda v: v.kind == 'receipt').mapped('amount'))
            r.invoiced = sum(r.invoice_ids.filtered(lambda i: i.state == 'confirmed').mapped('amount'))
            r.remaining = r.agreed_amount - r.paid + r.received


class Voucher(models.Model):
    _name = 'abroj.contracting.voucher'
    _inherit = 'abroj.contracting.frozen'
    _description = 'سند صرف / قبض'
    _order = 'date desc, id desc'

    name = fields.Char('رقم السند', default='/', readonly=True, copy=False)
    kind = fields.Selection([('payment', 'سند صرف'), ('receipt', 'سند قبض')], string='نوع السند', required=True, default='payment')
    partner_id = fields.Many2one('res.partner', string='الطرف', required=True, check_company=True)
    subcontractor_id = fields.Many2one('abroj.contracting.subcontractor', string='مقاول الباطن', check_company=True, ondelete='restrict')
    method = fields.Selection([('cash', 'نقداً'), ('bank', 'تحويل بنكي'), ('other', 'أخرى')], string='طريقة الدفع', default='cash', required=True)
    memo = fields.Text('البيان')
    attachment = fields.Binary('المرفق', attachment=True)
    filename = fields.Char('اسم الملف')
    state = fields.Selection([('draft', 'مسودة'), ('issued', 'صادر'), ('cancelled', 'ملغى')], string='الحالة', default='draft', readonly=True, copy=False)
    create_payment = fields.Boolean('إنشاء دفعة محاسبية', default=False)
    journal_id = fields.Many2one('account.journal', string='دفتر الدفع', check_company=True, domain="[('type', 'in', ['bank', 'cash'])]")
    payment_id = fields.Many2one('account.payment', string='الدفعة المحاسبية', readonly=True, copy=False, check_company=True)
    issued_by = fields.Many2one('res.users', string='أصدره', readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        if any(set(v) & {'name', 'payment_id', 'issued_by'} for v in vals_list):
            raise AccessError('بيانات الإصدار للقراءة فقط.')
        return super().create(vals_list)

    def write(self, vals):
        if set(vals) & {'name', 'payment_id', 'issued_by'}:
            raise AccessError('بيانات الإصدار للقراءة فقط.')
        return super().write(vals)

    @api.constrains('subcontractor_id', 'project_id', 'partner_id')
    def _check_subcontractor(self):
        for r in self:
            if r.subcontractor_id and (r.subcontractor_id.project_id != r.project_id or r.subcontractor_id.partner_id != r.partner_id):
                raise ValidationError('المقاول يجب أن يطابق المشروع والطرف.')

    def action_issue(self):
        check_agent(self.env)
        for r in self:
            if r.state != 'draft':
                raise UserError('يمكن إصدار المسودة فقط.')
            # Serialize concurrent issue requests before creating a native payment.
            self.env.cr.execute('SELECT id FROM abroj_contracting_voucher WHERE id = %s FOR UPDATE', [r.id])
            r.invalidate_recordset(['state'])
            if r.state != 'draft':
                raise UserError('تم إصدار السند مسبقاً.')
            payment = False
            if r.create_payment:
                if not self.env.user.has_group('account.group_account_user'):
                    raise AccessError('إنشاء دفعة يتطلب صلاحية المحاسبة.')
                account = r.project_id.account_id
                if not account or not r.journal_id or r.journal_id.company_id != r.company_id:
                    raise UserError('حدد حساب المشروع التحليلي ودفتر دفع من نفس الشركة.')
                direction = 'outbound' if r.kind == 'payment' else 'inbound'
                lines = r.journal_id.outbound_payment_method_line_ids if direction == 'outbound' else r.journal_id.inbound_payment_method_line_ids
                if not lines:
                    raise UserError('لا توجد طريقة دفع في الدفتر.')
                payment = self.env['account.payment'].create({
                    'payment_type': direction, 'partner_type': 'supplier' if direction == 'outbound' else 'customer',
                    'partner_id': r.partner_id.id, 'amount': r.amount, 'date': r.date,
                    'currency_id': r.currency_id.id, 'journal_id': r.journal_id.id,
                    'payment_method_line_id': lines[0].id, 'company_id': r.company_id.id,
                })
                payment._generate_journal_entry()
                if not payment.move_id:
                    raise UserError('يلزم دفتر يولد قيد دفع لتخصيص الحساب التحليلي.')
                counterpart = payment.move_id.line_ids.filtered(lambda line: line.account_id == payment.destination_account_id)
                counterpart.write({'analytic_distribution': {str(account.id): 100}})
                payment.action_post()
            values = {'state': 'issued', 'issued_by': self.env.uid,
                      'name': self.env['ir.sequence'].with_company(r.company_id).next_by_code('abroj.contracting.' + r.kind),
                      'payment_id': payment.id if payment else False}
            super(FrozenDocument, r).write(values)
        return True

    def action_cancel(self):
        check_agent(self.env)
        for r in self:
            self.env.cr.execute('SELECT id FROM abroj_contracting_voucher WHERE id = %s FOR UPDATE', [r.id])
            r.invalidate_recordset(['state', 'payment_id'])
            if r.state not in ('draft', 'issued'):
                raise UserError('السند ملغى مسبقاً.')
            if r.payment_id:
                raise UserError('عالج الدفعة المحاسبية أولاً؛ لا يمكن إلغاء سند مرتبط بدفعة.')
            super(FrozenDocument, r).write({'state': 'cancelled'})
        return True


class Invoice(models.Model):
    _name = 'abroj.contracting.invoice'
    _inherit = 'abroj.contracting.frozen'
    _description = 'فاتورة مقاول باطن'
    _rec_name = 'number'

    number = fields.Char('رقم الفاتورة', required=True)
    subcontractor_id = fields.Many2one('abroj.contracting.subcontractor', string='مقاول الباطن', required=True, check_company=True, ondelete='restrict')
    attachment_ids = fields.Many2many('ir.attachment', string='المرفقات')
    state = fields.Selection([('draft', 'مسودة'), ('confirmed', 'مؤكدة')], string='الحالة', default='draft', readonly=True, copy=False)

    @api.constrains('project_id', 'subcontractor_id')
    def _check_subcontractor(self):
        for r in self:
            if r.subcontractor_id.project_id != r.project_id:
                raise ValidationError('المقاول يجب أن يتبع المشروع نفسه.')


class Cost(models.Model):
    _name = 'abroj.contracting.cost'
    _inherit = 'abroj.contracting.frozen'
    _description = 'مصروف مشروع'

    name = fields.Char('الوصف', required=True)
    partner_id = fields.Many2one('res.partner', string='المورد', check_company=True)
    category = fields.Char('التصنيف')
    invoice_number = fields.Char('رقم الفاتورة')
    attachment = fields.Binary('المرفق', attachment=True)
    state = fields.Selection([('draft', 'مسودة'), ('confirmed', 'مؤكد')], string='الحالة', default='draft', readonly=True, copy=False)
