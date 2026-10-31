from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from .guards import check_agent


class Project(models.Model):
    _inherit = 'project.project'

    contracting_goal = fields.Text('الهدف', help='حدد الهدف لهذا السجل وفق مستند المشروع الأصلي.')
    contract_value = fields.Monetary('قيمة العقد', help='قيمة عقد العميل؛ تستخدم لحساب ربح المشروع والمتبقي للتحصيل.')
    contracting_start = fields.Date('تاريخ الاتفاقية / البدء', help='حدد تاريخ الاتفاقية / البدء لهذا السجل وفق مستند المشروع الأصلي.')
    contracting_end = fields.Date('تاريخ الانتهاء', help='حدد تاريخ الانتهاء لهذا السجل وفق مستند المشروع الأصلي.')
    duration_days = fields.Integer('مدة التنفيذ بالأيام', compute='_compute_duration', store=True, help='حدد مدة التنفيذ بالأيام لهذا السجل وفق مستند المشروع الأصلي.')
    value_type = fields.Selection([('materials', 'شامل مواد'), ('labor', 'بدون مواد')], string='نوع القيمة', help='حدد نوع القيمة لهذا السجل وفق مستند المشروع الأصلي.')
    estimated_cost = fields.Monetary('التكلفة التقديرية', help='حدد التكلفة التقديرية لهذا السجل وفق مستند المشروع الأصلي.')
    expected_profit = fields.Monetary('الربح المتوقع', compute='_compute_totals', store=True, help='حدد الربح المتوقع لهذا السجل وفق مستند المشروع الأصلي.')
    subcontractor_ids = fields.One2many('abroj.contracting.subcontractor', 'project_id', string='مقاولو الباطن', help='حدد مقاولو الباطن لهذا السجل وفق مستند المشروع الأصلي.')
    voucher_ids = fields.One2many('abroj.contracting.voucher', 'project_id', string='السندات', help='حدد السندات لهذا السجل وفق مستند المشروع الأصلي.')
    invoice_ids = fields.One2many('abroj.contracting.invoice', 'project_id', string='فواتير المقاولين', help='حدد فواتير المقاولين لهذا السجل وفق مستند المشروع الأصلي.')
    cost_ids = fields.One2many('abroj.contracting.cost', 'project_id', string='المصروفات', help='حدد المصروفات لهذا السجل وفق مستند المشروع الأصلي.')
    inbox_ids = fields.One2many('abroj.contracting.inbox', 'project_id', string='السجلات', help='حدد السجلات لهذا السجل وفق مستند المشروع الأصلي.')
    materials_purchase_total = fields.Monetary('مشتريات المواد عن المقاولين', compute='_compute_totals', store=True, help='مواد أبروج المعتمدة المسجلة كشراء ضمن تكلفة عقود الباطن؛ لا تضاف إلى قيمة العقود مرة أخرى.')
    total_costs = fields.Monetary('إجمالي التكاليف', compute='_compute_totals', store=True, help='إجمالي عقود الباطن والمصروفات المستقلة المعتمدة؛ مواد العقود جزء من قيمتها وليست إضافة عليها.')
    total_paid = fields.Monetary('المدفوع', compute='_compute_totals', store=True, help='حدد المدفوع لهذا السجل وفق مستند المشروع الأصلي.')
    total_received = fields.Monetary('المقبوض', compute='_compute_totals', store=True, help='حدد المقبوض لهذا السجل وفق مستند المشروع الأصلي.')
    remaining = fields.Monetary('المتبقي من العقد', compute='_compute_totals', store=True, help='المبلغ المتبقي من عقد العميل بعد سندات القبض الصادرة.')
    profit = fields.Monetary('ربح العقد', compute='_compute_totals', store=True, help='حدد ربح العقد لهذا السجل وفق مستند المشروع الأصلي.')
    cash_balance = fields.Monetary('صافي التدفق النقدي', compute='_compute_totals', store=True, help='المقبوض ناقص المدفوع حسب السندات الصادرة؛ لا يشمل الالتزامات غير المسددة.')

    project_note_ids = fields.One2many('abroj.contracting.project.note', 'project_id', string='الملاحظات', help='حدد الملاحظات لهذا السجل وفق مستند المشروع الأصلي.')
    project_note_count = fields.Integer('عدد الملاحظات', compute='_compute_project_note_count', help='حدد عدد الملاحظات لهذا السجل وفق مستند المشروع الأصلي.')

    @api.depends('project_note_ids')
    def _compute_project_note_count(self):
        for project in self:
            project.project_note_count = len(project.project_note_ids)

    def action_project_notes(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'الملاحظات',
                'res_model': 'abroj.contracting.project.note', 'view_mode': 'list,form',
                'domain': [('project_id', '=', self.id)],
                'context': {'default_project_id': self.id}}

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
                 'voucher_ids.kind', 'invoice_ids.amount', 'invoice_ids.state', 'cost_ids.amount', 'cost_ids.state', 'subcontractor_ids.agreed_amount', 'subcontractor_ids.materials_total')
    def _compute_totals(self):
        for r in self:
            issued = r.voucher_ids.filtered(lambda v: v.state == 'issued')
            r.total_paid = sum(issued.filtered(lambda v: v.kind == 'payment').mapped('amount'))
            r.total_received = sum(issued.filtered(lambda v: v.kind == 'receipt').mapped('amount'))
            r.materials_purchase_total = sum(r.subcontractor_ids.mapped('materials_total'))
            r.total_costs = sum(r.subcontractor_ids.mapped('agreed_amount')) + sum(r.cost_ids.filtered(lambda i: i.state == 'confirmed').mapped('amount'))
            r.remaining = r.contract_value - r.total_received
            r.profit = r.contract_value - r.total_costs
            r.expected_profit = r.contract_value - r.estimated_cost
            r.cash_balance = r.total_received - r.total_paid


class ProjectDocument(models.AbstractModel):
    _name = 'abroj.contracting.document'
    _description = 'مستند مشروع'
    _check_company_auto = True

    project_id = fields.Many2one('project.project', string='المشروع', required=True, check_company=True, ondelete='restrict', help='حدد المشروع لهذا السجل وفق مستند المشروع الأصلي.')
    company_id = fields.Many2one('res.company', string='الشركة', related='project_id.company_id', store=True, help='حدد الشركة لهذا السجل وفق مستند المشروع الأصلي.')
    currency_id = fields.Many2one('res.currency', string='العملة', related='company_id.currency_id', help='حدد العملة لهذا السجل وفق مستند المشروع الأصلي.')

    @api.constrains('project_id')
    def _check_project_company(self):
        for r in self:
            if not r.company_id:
                raise ValidationError('يجب تحديد شركة المشروع.')


class FrozenDocument(models.AbstractModel):
    _name = 'abroj.contracting.frozen'
    _inherit = 'abroj.contracting.document'
    _description = 'مستند مالي'

    amount = fields.Monetary('المبلغ', required=True, help='مبلغ المستند بعملة الشركة؛ مبلغ مواد أبروج يخصم من المستحق كما أدخل دون احتساب ضريبة تلقائي.')
    date = fields.Date('التاريخ', default=fields.Date.context_today, required=True, help='حدد التاريخ لهذا السجل وفق مستند المشروع الأصلي.')

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

    partner_id = fields.Many2one('res.partner', string='المقاول', required=True, check_company=True, help='حدد المقاول لهذا السجل وفق مستند المشروع الأصلي.')
    scope = fields.Text('نطاق العمل', help='حدد نطاق العمل لهذا السجل وفق مستند المشروع الأصلي.')
    contract_type = fields.Selection([('labor', 'بدون مواد'), ('materials', 'شامل المواد'), ('lump', 'مقطوعية'), ('other', 'أخرى')], string='نوع العقد', help='بدون مواد للعمالة فقط وشامل المواد عند دخول المواد في قيمة العقد؛ مقطوعية وأخرى محفوظتان للعقود السابقة.')
    vat_registered = fields.Boolean('المقاول مسجل بالضريبة', help='حدد vat_registered لهذا السجل وفق مستند المشروع الأصلي.')
    retention_percent = fields.Float('نسبة الضمان %', help='نسبة اختيارية من العقد؛ لا تخصم من المستحق الإجمالي.')
    materials_total = fields.Monetary('دفعة عن المقاول — المواد', compute='_compute_balances', store=True, help='مواد أبروج المعتمدة التي تخصم من مستحق المقاول.')
    payment_terms = fields.Text('شروط الدفع', help='حدد شروط الدفع لهذا السجل وفق مستند المشروع الأصلي.')
    duration_days = fields.Integer('مدة الإنجاز بالأيام', help='حدد مدة الإنجاز بالأيام لهذا السجل وفق مستند المشروع الأصلي.')
    agreed_amount = fields.Monetary('القيمة المتفق عليها', help='إجمالي تكلفة عقد الباطن المتفق عليها بعملة الشركة، تشمل المواد ولا تتكرر عند تسجيل فواتيرها.')
    voucher_ids = fields.One2many('abroj.contracting.voucher', 'subcontractor_id', string='السندات', help='حدد السندات لهذا السجل وفق مستند المشروع الأصلي.')
    invoice_ids = fields.One2many('abroj.contracting.invoice', 'subcontractor_id', string='الفواتير', help='حدد الفواتير لهذا السجل وفق مستند المشروع الأصلي.')
    paid = fields.Monetary('المدفوع', compute='_compute_balances', store=True, help='مجموع سندات الصرف الصادرة؛ مواد أبروج تظهر منفصلة كدفعة عن المقاول.')
    received = fields.Monetary('المسترد', compute='_compute_balances', store=True, help='مجموع سندات القبض الصادرة؛ المسترد من المقاول يزيد مستحقه المتبقي.')
    invoiced = fields.Monetary('المفوتر', compute='_compute_balances', store=True, help='إجمالي المستندات المعتمدة بما فيها المرفقات الداعمة؛ لا يمثل تكلفة إضافية.')
    remaining = fields.Monetary('المتبقي', compute='_compute_balances', store=True, help='قيمة العقد ناقص مواد أبروج ناقص المدفوع مع إضافة المسترد؛ يشمل الضمان.')

    @api.depends('agreed_amount', 'voucher_ids.amount', 'voucher_ids.state', 'voucher_ids.kind', 'invoice_ids.amount', 'invoice_ids.state', 'invoice_ids.invoice_kind')
    def _compute_balances(self):
        for r in self:
            issued = r.voucher_ids.filtered(lambda v: v.state == 'issued')
            r.paid = sum(issued.filtered(lambda v: v.kind == 'payment').mapped('amount'))
            r.received = sum(issued.filtered(lambda v: v.kind == 'receipt').mapped('amount'))
            r.invoiced = sum(r.invoice_ids.filtered(lambda i: i.state == 'confirmed').mapped('amount'))
            r.materials_total = sum(r.invoice_ids.filtered(lambda i: i.state == 'confirmed' and i.invoice_kind == 'materials_company').mapped('amount'))
            r.remaining = r.agreed_amount - r.materials_total - r.paid + r.received

    @api.constrains('agreed_amount', 'retention_percent', 'invoice_ids')
    def _check_contract_limits(self):
        for r in self:
            if r.agreed_amount < 0 or not 0 <= r.retention_percent <= 100:
                raise ValidationError('قيمة العقد غير سالبة ونسبة الضمان بين صفر و١٠٠.')
            if r.currency_id.compare_amounts(r.materials_total, r.agreed_amount) > 0:
                raise ValidationError('مواد أبروج تتجاوز قيمة عقد المقاول.')

    def action_settlement(self):
        self.ensure_one()
        return self.env.ref('abroj_contracting.report_settlement').report_action(self)


class Voucher(models.Model):
    _name = 'abroj.contracting.voucher'
    _inherit = 'abroj.contracting.frozen'
    _description = 'سند صرف / قبض'
    _order = 'date desc, id desc'

    name = fields.Char('رقم السند', default='/', readonly=True, copy=False, help='حدد رقم السند لهذا السجل وفق مستند المشروع الأصلي.')
    kind = fields.Selection([('payment', 'سند صرف'), ('receipt', 'سند قبض')], string='نوع السند', required=True, default='payment', help='حدد نوع السند لهذا السجل وفق مستند المشروع الأصلي.')
    partner_id = fields.Many2one('res.partner', string='الطرف', required=True, check_company=True, help='حدد الطرف لهذا السجل وفق مستند المشروع الأصلي.')
    subcontractor_id = fields.Many2one('abroj.contracting.subcontractor', string='مقاول الباطن', check_company=True, ondelete='restrict', help='حدد مقاول الباطن لهذا السجل وفق مستند المشروع الأصلي.')
    method = fields.Selection([('cash', 'نقداً'), ('bank', 'تحويل بنكي'), ('other', 'أخرى')], string='طريقة الدفع', default='cash', required=True, help='حدد طريقة الدفع لهذا السجل وفق مستند المشروع الأصلي.')
    memo = fields.Text('البيان', help='حدد البيان لهذا السجل وفق مستند المشروع الأصلي.')
    attachment = fields.Binary('المرفق', attachment=True, help='حدد المرفق لهذا السجل وفق مستند المشروع الأصلي.')
    filename = fields.Char('اسم الملف', help='حدد اسم الملف لهذا السجل وفق مستند المشروع الأصلي.')
    state = fields.Selection([('draft', 'مسودة'), ('issued', 'صادر'), ('cancelled', 'ملغى')], string='الحالة', default='draft', readonly=True, copy=False, help='المسودة قابلة للتعديل؛ الاعتماد يقفل المستند ويحدث الإجماليات.')
    create_payment = fields.Boolean('إنشاء دفعة محاسبية', default=False, help='حقل قديم؛ أنشئ الدفعة عبر زر الاعتماد المحاسبي بعد إصدار السند.')
    journal_id = fields.Many2one('account.journal', string='دفتر الدفع', check_company=True, domain="[('type', 'in', ['bank', 'cash'])]", help='اختر دفتر الدفع قبل الإصدار؛ عند تركه فارغاً يختار الاعتماد المحاسبي دفتر نقد أو بنك متاحاً من شركة المشروع حسب طريقة الدفع.')
    payment_id = fields.Many2one('account.payment', string='الدفعة المحاسبية', readonly=True, copy=False, check_company=True, help='الدفعة التي أنشأها محاسب آخر عبر الاعتماد المحاسبي؛ يخصص حسابها المقابل للحساب التحليلي للمشروع.')
    issued_by = fields.Many2one('res.users', string='أصدره', readonly=True, copy=False, help='حدد أصدره لهذا السجل وفق مستند المشروع الأصلي.')

    abroj_stage = fields.Selection([
        ('draft', 'مسودة'), ('issued', 'صادر بانتظار الاعتماد المحاسبي'),
        ('approved', 'معتمد محاسبيًا'), ('cancelled', 'ملغي'),
    ], string='المرحلة', compute='_compute_abroj_stage', store=True)

    @api.depends('state', 'payment_id')
    def _compute_abroj_stage(self):
        for voucher in self:
            voucher.abroj_stage = ('approved' if voucher.payment_id else 'issued') if voucher.state == 'issued' else voucher.state

    @api.model
    def abroj_voucher_summary(self, domain):
        vouchers = self.search((domain or []) + [('state', '=', 'issued')])
        received = sum(vouchers.filtered(lambda v: v.kind == 'receipt').mapped('amount'))
        paid = sum(vouchers.filtered(lambda v: v.kind == 'payment').mapped('amount'))
        return {'received': received, 'paid': paid, 'balance': received - paid}

    abroj_can_accounting_approve = fields.Boolean(compute='_compute_can_accounting_approve')

    @api.depends('state', 'payment_id', 'issued_by')
    @api.depends_context('uid')
    def _compute_can_accounting_approve(self):
        user = self.env.user
        accountant = (user.has_group('account.group_account_manager')
                      or user.has_group('account.group_account_invoice'))
        allowed = accountant and not user.has_group('abroj_contracting.group_extraction_agent')
        for voucher in self:
            voucher.abroj_can_accounting_approve = bool(
                allowed and voucher.state == 'issued' and not voucher.payment_id
                and voucher.issued_by != user
            )

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
            values = {'state': 'issued', 'issued_by': self.env.uid,
                      'name': self.env['ir.sequence'].with_company(r.company_id).next_by_code('abroj.contracting.' + r.kind),
                      'payment_id': False}
            super(FrozenDocument, r).write(values)
        return True

    def action_accounting_approve(self):
        # This prohibition also applies to agents holding accounting groups.
        if self.env.user.has_group('abroj_contracting.group_extraction_agent'):
            raise AccessError('وكيل الاستخراج لا يملك صلاحية الاعتماد المحاسبي.')
        if not (self.env.user.has_group('account.group_account_manager')
                or self.env.user.has_group('account.group_account_invoice')):
            raise AccessError('الاعتماد المحاسبي يتطلب صلاحية المحاسبة.')
        self.check_access('write')
        for r in self:
            self.env.cr.execute('SELECT id FROM abroj_contracting_voucher WHERE id = %s FOR UPDATE', [r.id])
            r.invalidate_recordset(['state', 'payment_id', 'issued_by'])
            if r.state != 'issued' or r.payment_id:
                raise UserError('الاعتماد المحاسبي متاح لسند صادر دون دفعة فقط.')
            if r.issued_by == self.env.user:
                raise AccessError('لا يجوز لمصدر السند اعتماده محاسبياً.')
            account = r.project_id.account_id
            journal = r.journal_id or self.env['account.journal'].search([
                ('company_id', '=', r.company_id.id),
                ('type', '=', 'cash' if r.method == 'cash' else 'bank'),
            ], limit=1)
            if not account or not journal or journal.company_id != r.company_id or journal.type not in ('bank', 'cash'):
                raise UserError('حدد حساب المشروع التحليلي ودفتر نقد أو بنك من نفس الشركة.')
            direction = 'outbound' if r.kind == 'payment' else 'inbound'
            lines = journal.outbound_payment_method_line_ids if direction == 'outbound' else journal.inbound_payment_method_line_ids
            if not lines:
                raise UserError('لا توجد طريقة دفع في الدفتر.')
            payment = self.env['account.payment'].with_company(r.company_id).create({
                'payment_type': direction, 'partner_type': 'supplier' if direction == 'outbound' else 'customer',
                'partner_id': r.partner_id.id, 'amount': r.amount, 'date': r.date,
                'currency_id': r.currency_id.id, 'journal_id': journal.id,
                'payment_method_line_id': lines[0].id, 'company_id': r.company_id.id,
                'memo': r.name, 'abroj_voucher_id': r.id,
            })
            payment._generate_journal_entry()
            if not payment.move_id:
                raise UserError('يلزم دفتر يولد قيد دفع لتخصيص الحساب التحليلي.')
            payment.move_id.write({'ref': r.name, 'abroj_voucher_id': r.id})
            counterpart = payment.move_id.line_ids.filtered(lambda line: line.account_id == payment.destination_account_id)
            counterpart.write({'analytic_distribution': {str(account.id): 100}})
            payment.action_post()
            super(FrozenDocument, r).write({'payment_id': payment.id})
        return True

    def action_open_journal_entry(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': 'القيد المحاسبي',
            'res_model': 'account.move', 'res_id': self.payment_id.move_id.id,
            'view_mode': 'form', 'target': 'current',
        }

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

    invoice_kind = fields.Selection([('subcontract', 'مستخلص المقاول'), ('materials_company', 'مواد باسم أبروج'), ('materials_subcontractor', 'مواد باسم المقاول — مرفقات فقط')], string='معالجة الفاتورة', default='subcontract', required=True, help='مواد أبروج تسجل عند الاعتماد ضمن تكلفة العقد ودفعة عن المقاول. مواد المقاول للإثبات بلا تكلفة أو ضريبة. المستخلص لا يكرر تكلفة العقد.')
    buyer_vat = fields.Char('الرقم الضريبي للمشتري', help='الرقم المطبوع في الفاتورة؛ يجب أن يطابق شركة المشروع لمواد أبروج.')

    def action_confirm(self):
        check_agent(self.env)
        for r in self.sorted('subcontractor_id'):
            self.env.cr.execute('SELECT id FROM abroj_contracting_subcontractor WHERE id = %s FOR UPDATE', [r.subcontractor_id.id])
            r.subcontractor_id.invalidate_recordset()
            if r.invoice_kind == 'materials_company' and (not r.company_id.vat or (r.buyer_vat or '').strip() != r.company_id.vat.strip()):
                raise ValidationError('يلزم رقم أبروج الضريبي المطابق للفاتورة.')
            if r.invoice_kind == 'materials_subcontractor' and not r.attachment_ids:
                raise ValidationError('أرفق فاتورة المواد باسم المقاول كمستند داعم.')
        result = super().action_confirm()
        self.subcontractor_id._check_contract_limits()
        return result

    number = fields.Char('رقم الفاتورة', required=True, help='حدد رقم الفاتورة لهذا السجل وفق مستند المشروع الأصلي.')
    subcontractor_id = fields.Many2one('abroj.contracting.subcontractor', string='مقاول الباطن', required=True, check_company=True, ondelete='restrict', help='حدد مقاول الباطن لهذا السجل وفق مستند المشروع الأصلي.')
    attachment_ids = fields.Many2many('ir.attachment', string='المرفقات', help='حدد المرفقات لهذا السجل وفق مستند المشروع الأصلي.')
    state = fields.Selection([('draft', 'مسودة'), ('confirmed', 'مؤكدة')], string='الحالة', default='draft', readonly=True, copy=False, help='المسودة قابلة للتعديل؛ الاعتماد يقفل المستند ويحدث الإجماليات.')

    @api.constrains('project_id', 'subcontractor_id')
    def _check_subcontractor(self):
        for r in self:
            if r.subcontractor_id.project_id != r.project_id:
                raise ValidationError('المقاول يجب أن يتبع المشروع نفسه.')


class Cost(models.Model):
    _name = 'abroj.contracting.cost'
    _inherit = 'abroj.contracting.frozen'
    _description = 'مصروف مشروع'

    name = fields.Char('الوصف', required=True, help='حدد الوصف لهذا السجل وفق مستند المشروع الأصلي.')
    partner_id = fields.Many2one('res.partner', string='المورد', check_company=True, help='حدد المورد لهذا السجل وفق مستند المشروع الأصلي.')
    category = fields.Char('التصنيف', help='حدد التصنيف لهذا السجل وفق مستند المشروع الأصلي.')
    invoice_number = fields.Char('رقم الفاتورة', help='حدد رقم الفاتورة لهذا السجل وفق مستند المشروع الأصلي.')
    attachment = fields.Binary('المرفق', attachment=True, help='حدد المرفق لهذا السجل وفق مستند المشروع الأصلي.')
    state = fields.Selection([('draft', 'مسودة'), ('confirmed', 'مؤكد')], string='الحالة', default='draft', readonly=True, copy=False, help='المسودة قابلة للتعديل؛ الاعتماد يقفل المستند ويحدث الإجماليات.')
