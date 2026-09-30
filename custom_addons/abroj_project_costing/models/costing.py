from collections import defaultdict
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


PRICING_METHODS = [
    ('detailed', 'تفصيلي'),
    ('supply_only', 'توريد فقط'),
    ('labor_only', 'عمل يد فقط'),
    ('supply_install', 'توريد وتركيب شامل'),
    ('lump_sum', 'مقطوعية'),
]

PROJECT_STATES = [
    ('draft', 'مسودة'),
    ('pricing', 'تحت التسعير'),
    ('approved', 'معتمد'),
    ('in_progress', 'جاري التنفيذ'),
    ('completed', 'مكتمل'),
    ('closed', 'مغلق'),
    ('cancelled', 'ملغي'),
]


class AbrojCostCategory(models.Model):
    _name = 'abroj.cost.category'
    _description = 'Abroj Cost Category'
    _order = 'sequence, name'

    name = fields.Char('اسم الفئة', required=True, translate=True)
    sequence = fields.Integer('الترتيب', default=10)
    company_id = fields.Many2one('res.company', 'الشركة', required=True, default=lambda self: self.env.company, index=True)
    active = fields.Boolean('نشط', default=True)
    color = fields.Integer('اللون')

    _sql_constraints = [
        ('abroj_category_company_name_unique', 'unique(company_id, name)', 'اسم الفئة مستخدم بالفعل في هذه الشركة.'),
    ]


class AbrojCostMaterial(models.Model):
    _name = 'abroj.cost.material'
    _description = 'Abroj Cost Material Library'
    _order = 'name'

    name = fields.Char('اسم المادة', required=True, translate=True)
    name_en = fields.Char('الاسم بالإنجليزية')
    code = fields.Char('كود المادة')
    company_id = fields.Many2one('res.company', 'الشركة', required=True, default=lambda self: self.env.company, index=True)
    category_id = fields.Many2one('abroj.cost.category', 'الفئة', required=True, check_company=True)
    image_1920 = fields.Image('الصورة')
    uom_type = fields.Selection([
        ('m2', 'متر مربع m²'), ('lm', 'متر طولي lm'), ('m3', 'متر مكعب m³'),
        ('unit', 'حبة'), ('set', 'طقم'), ('kg', 'كيلو'), ('ton', 'طن'),
        ('liter', 'لتر'), ('carton', 'كرتون'), ('bag', 'كيس'), ('hour', 'ساعة'),
        ('day', 'يوم'), ('lump_sum', 'مقطوعية'),
    ], required=True, default='unit', string='وحدة القياس')
    material_unit_cost = fields.Monetary('سعر المادة الأساسي المرجعي', currency_field='currency_id')
    auxiliary_unit_cost = fields.Monetary('تكلفة المواد المساعدة المرجعية', currency_field='currency_id')
    labor_unit_cost = fields.Monetary('تكلفة شغل اليد المرجعية', currency_field='currency_id')
    inclusive_unit_cost = fields.Monetary('سعر توريد وتركيب المرجعي', currency_field='currency_id')
    default_pricing_method = fields.Selection(PRICING_METHODS, 'طريقة التسعير الافتراضية', default='detailed', required=True)
    supplier_id = fields.Many2one('res.partner', 'المورد المرجعي', check_company=True)
    supplier_text = fields.Char('اسم المورد')
    original_product_id = fields.Many2one('product.template', 'المنتج الأصلي', check_company=True, readonly=True)
    description = fields.Text('الوصف')
    notes = fields.Text('ملاحظات')
    last_price_update = fields.Date('آخر تحديث للسعر', default=fields.Date.context_today)
    active = fields.Boolean('نشط', default=True)
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)

    _sql_constraints = [
        ('abroj_material_company_code_unique', 'unique(company_id, code)', 'كود المادة مستخدم بالفعل في هذه الشركة.'),
    ]


class AbrojCostMaterialImportWizard(models.TransientModel):
    _name = 'abroj.cost.material.import.wizard'
    _description = 'Import Odoo Products into Abroj Materials'

    company_id = fields.Many2one('res.company', 'الشركة', required=True, default=lambda self: self.env.company)
    category_id = fields.Many2one('abroj.cost.category', required=True, check_company=True, string='فئة المواد المستوردة')
    product_ids = fields.Many2many('product.template', string='منتجات أودو', required=True)

    def _uom_type_from_product(self, product):
        name = (product.uom_id.name or '').lower()
        mapping = {
            'm²': 'm2', 'm2': 'm2', 'متر مربع': 'm2', 'lm': 'lm', 'متر طولي': 'lm',
            'm³': 'm3', 'm3': 'm3', 'متر مكعب': 'm3', 'kg': 'kg', 'كيلو': 'kg',
            'طن': 'ton', 'ton': 'ton', 'لتر': 'liter', 'liter': 'liter', 'ساعة': 'hour',
            'hour': 'hour', 'يوم': 'day', 'day': 'day',
        }
        return mapping.get(name, 'unit')

    def action_import_products(self):
        self.ensure_one()
        Material = self.env['abroj.cost.material']
        for product in self.product_ids:
            existing = Material.search([
                ('company_id', '=', self.company_id.id),
                ('original_product_id', '=', product.id),
            ], limit=1)
            if existing:
                continue
            Material.create({
                'company_id': self.company_id.id,
                'category_id': self.category_id.id,
                'name': product.name,
                'image_1920': product.image_1920,
                'uom_type': self._uom_type_from_product(product),
                'description': product.description_sale or product.description,
                'original_product_id': product.id,
            })
        return {'type': 'ir.actions.act_window_close'}


class AbrojCostProject(models.Model):
    _name = 'abroj.cost.project'
    _description = 'Abroj Project Costing'
    _order = 'write_date desc, id desc'

    name = fields.Char('اسم المشروع', required=True, translate=True)
    company_id = fields.Many2one('res.company', 'الشركة', required=True, default=lambda self: self.env.company, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)
    owner_id = fields.Many2one('res.users', 'مالك المشروع', required=True, default=lambda self: self.env.user, readonly=True, index=True)
    customer_name = fields.Char('العميل')
    partner_id = fields.Many2one('res.partner', 'جهة الاتصال', check_company=True)
    image_1920 = fields.Image('صورة المشروع')
    description = fields.Text('الوصف')
    location = fields.Char('الموقع')
    state = fields.Selection(PROJECT_STATES, 'الحالة', default='draft', required=True, index=True)
    agreement_amount = fields.Monetary('قيمة الاتفاقية', required=True, currency_field='currency_id')
    agreement_start_date = fields.Date('بداية الاتفاقية')
    agreement_end_date = fields.Date('نهاية الاتفاقية')
    close_date = fields.Date('تاريخ الإغلاق', readonly=True)
    active = fields.Boolean('نشط', default=True)
    note = fields.Html('ملاحظات')
    plan_line_ids = fields.One2many('abroj.cost.plan.line', 'project_id', string='دراسة المشروع')
    plan_leaf_ids = fields.One2many(
        'abroj.cost.plan.line', 'project_id', string='بنود الدراسة المسعّرة',
        domain=[('node_kind', '=', 'item')],
    )
    actual_line_ids = fields.One2many('abroj.cost.actual.line', 'project_id', string='التكاليف الفعلية')
    progress_stage_ids = fields.One2many('abroj.cost.progress.stage', 'project_id', string='الإنجاز')
    receipt_ids = fields.One2many('abroj.cost.receipt', 'project_id', string='دفعات العميل')
    amendment_ids = fields.One2many('abroj.cost.agreement.amendment', 'project_id', string='تعديلات الاتفاقية')
    member_ids = fields.One2many('abroj.cost.project.member', 'project_id', string='الأعضاء')
    estimated_material_total = fields.Monetary('إجمالي المواد الأساسية', compute='_compute_totals', store=True, currency_field='currency_id')
    estimated_auxiliary_total = fields.Monetary('إجمالي المواد المساعدة', compute='_compute_totals', store=True, currency_field='currency_id')
    estimated_labor_total = fields.Monetary('إجمالي شغل اليد', compute='_compute_totals', store=True, currency_field='currency_id')
    estimated_lump_sum_total = fields.Monetary('إجمالي المقطوعيات', compute='_compute_totals', store=True, currency_field='currency_id')
    estimated_total = fields.Monetary('تكلفة الدراسة المتوقعة', compute='_compute_totals', store=True, currency_field='currency_id')
    actual_total = fields.Monetary('إجمالي التكلفة الفعلية', compute='_compute_totals', store=True, currency_field='currency_id')
    variance_amount = fields.Monetary('الانحراف', compute='_compute_totals', store=True, currency_field='currency_id')
    variance_percent = fields.Float('نسبة الانحراف', compute='_compute_totals', store=True, digits=(16, 2))
    expected_profit = fields.Monetary('النتيجة المتوقعة', compute='_compute_totals', store=True, currency_field='currency_id')
    actual_profit = fields.Monetary('النتيجة الفعلية', compute='_compute_totals', store=True, currency_field='currency_id')
    received_total = fields.Monetary('إجمالي المستلم', compute='_compute_totals', store=True, currency_field='currency_id')
    receivable_remaining = fields.Monetary('المتبقي من الاتفاقية', compute='_compute_totals', store=True, currency_field='currency_id')
    receipt_count = fields.Integer('عدد دفعات العميل', compute='_compute_receipt_count')
    progress = fields.Float('نسبة الإنجاز', compute='_compute_totals', store=True, digits=(16, 2))
    attachment_count = fields.Integer(compute='_compute_attachment_count')
    # Presentation-only field.  The Study Tree OWL field reads the protected
    # project record and never becomes a second source of plan data.
    study_tree_token = fields.Char(compute='_compute_study_tree_token')

    def _compute_study_tree_token(self):
        for project in self:
            project.study_tree_token = str(project.id or '')

    @api.depends('plan_line_ids.node_kind', 'plan_line_ids.estimated_material_amount', 'plan_line_ids.estimated_auxiliary_amount',
                 'plan_line_ids.estimated_labor_amount', 'plan_line_ids.estimated_lump_sum_amount',
                 'plan_line_ids.estimated_total', 'actual_line_ids.amount', 'receipt_ids.amount',
                 'progress_stage_ids.state', 'agreement_amount')
    def _compute_totals(self):
        for project in self:
            # Only priced leaves are included.  A section displays its own
            # rolled-up total, so including it here would double count.
            plan_lines = project.plan_line_ids.filtered(lambda line: line.node_kind == 'item')
            currency = project.currency_id
            project.estimated_material_total = currency.round(sum(plan_lines.mapped('estimated_material_amount')))
            project.estimated_auxiliary_total = currency.round(sum(plan_lines.mapped('estimated_auxiliary_amount')))
            project.estimated_labor_total = currency.round(sum(plan_lines.mapped('estimated_labor_amount')))
            project.estimated_lump_sum_total = currency.round(sum(plan_lines.mapped('estimated_lump_sum_amount')))
            project.estimated_total = currency.round(sum(plan_lines.mapped('estimated_total')))
            project.actual_total = currency.round(sum(project.actual_line_ids.mapped('amount')))
            project.variance_amount = currency.round(project.actual_total - project.estimated_total)
            project.variance_percent = (project.variance_amount / project.estimated_total * 100.0) if project.estimated_total else 0.0
            project.expected_profit = project.agreement_amount - project.estimated_total
            project.actual_profit = project.agreement_amount - project.actual_total
            project.received_total = sum(project.receipt_ids.mapped('amount'))
            project.receivable_remaining = project.agreement_amount - project.received_total
            stages = project.progress_stage_ids.filtered(lambda stage: stage.state != 'cancelled')
            project.progress = 100.0 * len(stages.filtered(lambda stage: stage.state == 'done')) / len(stages) if stages else 0.0

    def _compute_attachment_count(self):
        attachment_data = self.env['ir.attachment'].read_group(
            [('res_model', '=', self._name), ('res_id', 'in', self.ids)], ['res_id'], ['res_id'])
        counts = {item['res_id']: item['res_id_count'] for item in attachment_data}
        for project in self:
            project.attachment_count = counts.get(project.id, 0)

    @api.depends('receipt_ids')
    def _compute_receipt_count(self):
        for project in self:
            project.receipt_count = len(project.receipt_ids)

    @api.constrains('agreement_amount')
    def _check_agreement_amount(self):
        for project in self:
            if project.agreement_amount < 0:
                raise ValidationError(_('قيمة الاتفاقية لا يمكن أن تكون سالبة.'))
            if project.received_total > project.agreement_amount:
                raise ValidationError(_('لا يمكن أن تكون الاتفاقية أقل من المبالغ المستلمة.'))

    @api.constrains('agreement_start_date', 'agreement_end_date')
    def _check_agreement_dates(self):
        for project in self:
            if project.agreement_start_date and project.agreement_end_date and project.agreement_end_date < project.agreement_start_date:
                raise ValidationError(_('نهاية الاتفاقية يجب أن تكون بعد بدايتها.'))

    def _check_project_write_allowed(self, vals):
        protected = {'state', 'close_date'}
        for project in self:
            if project.state == 'closed' and not self.env.user.has_group('abroj_project_costing.group_abroj_cost_manager'):
                raise AccessError(_('المشروع مغلق ولا يمكن تعديله.'))
            if protected.intersection(vals) and not (project.owner_id == self.env.user or self.env.user.has_group('abroj_project_costing.group_abroj_cost_manager')):
                raise AccessError(_('مالك المشروع أو المدير فقط يستطيع تغيير الحالة.'))

    def write(self, vals):
        self._check_project_write_allowed(vals)
        return super().write(vals)

    def action_close(self):
        self._check_project_write_allowed({'state': 'closed'})
        self.write({'state': 'closed', 'close_date': fields.Date.context_today(self)})

    def action_reopen(self):
        if not self.env.user.has_group('abroj_project_costing.group_abroj_cost_manager'):
            raise AccessError(_('المدير فقط يستطيع إعادة فتح المشروع.'))
        self.write({'state': 'in_progress', 'close_date': False})

    def action_open_attachments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('وثائق المشروع'), 'res_model': 'ir.attachment',
            'view_mode': 'kanban,list,form', 'domain': [('res_model', '=', self._name), ('res_id', '=', self.id)],
            'context': {'default_res_model': self._name, 'default_res_id': self.id},
        }

    def action_open_receipts(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('دفعات العميل'),
            'res_model': 'abroj.cost.receipt',
            'view_mode': 'list,form',
            'views': [
                (self.env.ref('abroj_project_costing.view_abroj_receipt_list').id, 'list'),
                (self.env.ref('abroj_project_costing.view_abroj_receipt_form_readonly').id, 'form'),
            ],
            'domain': [('project_id', '=', self.id)],
            'context': {
                'default_project_id': self.id,
                'default_company_id': self.company_id.id,
            },
        }

    def action_create_customer_receipt(self):
        """Open a deliberate receipt-issuance dialog with its number reserved."""
        self.ensure_one()
        receipt_model = self.env['abroj.cost.receipt']
        return {
            'type': 'ir.actions.act_window',
            'name': _('إصدار سند قبض للعميل'),
            'res_model': 'abroj.cost.receipt',
            'view_mode': 'form',
            'views': [(self.env.ref(
                'abroj_project_costing.view_abroj_receipt_form_create'
            ).id, 'form')],
            'target': 'new',
            'context': {
                'default_project_id': self.id,
                # The number is reserved here instead of relying on an inline
                # One2many default payload, which may omit readonly fields.
                'default_name': receipt_model._next_receipt_number(self.company_id),
            },
        }

    def action_open_plan_import(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('استيراد دراسة المشروع'),
            'res_model': 'abroj.cost.plan.import.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_project_id': self.id},
        }

    def action_export_plan(self):
        self.ensure_one()
        wizard = self.env['abroj.cost.plan.import.wizard'].create({
            'project_id': self.id,
            'company_id': self.company_id.id,
        })
        return wizard.action_export_plan()

    def action_open_plan_section_form(self):
        """Open the dedicated, aggregation-only form for a root study section."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('إنشاء البند الأب'),
            'res_model': 'abroj.cost.plan.line',
            'view_mode': 'form',
            'view_id': self.env.ref('abroj_project_costing.view_abroj_plan_section_form').id,
            'target': 'new',
            'context': {
                **self.env.context,
                'default_project_id': self.id,
                'default_node_kind': 'section',
                'default_quantity': 0.0,
                'abroj_create_root_section': True,
            },
        }


class AbrojCostPlanLine(models.Model):
    _name = 'abroj.cost.plan.line'
    _description = 'Abroj Project Cost Plan Line'
    _order = 'sequence, id'
    _parent_store = True
    _parent_name = 'parent_id'

    project_id = fields.Many2one('abroj.cost.project', 'المشروع', required=True, ondelete='restrict', index=True, check_company=True)
    company_id = fields.Many2one(related='project_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='project_id.currency_id', readonly=True)
    sequence = fields.Integer('الترتيب', default=10)
    node_kind = fields.Selection([
        ('section', 'قسم'),
        ('item', 'بند مسعّر'),
    ], string='نوع العقدة', required=True, default='item', index=True)
    parent_id = fields.Many2one(
        'abroj.cost.plan.line', 'البند الأب', ondelete='restrict', index=True,
        check_company=True,
    )
    parent_path = fields.Char(index=True)
    child_ids = fields.One2many('abroj.cost.plan.line', 'parent_id', string='البنود التابعة')
    category_id = fields.Many2one('abroj.cost.category', 'نوع العمل', check_company=True)
    material_id = fields.Many2one('abroj.cost.material', 'المادة', check_company=True)
    image_1920 = fields.Image('الصورة')
    name = fields.Char('اسم البند', required=True)
    description = fields.Text('الوصف')
    pricing_method = fields.Selection(PRICING_METHODS, 'طريقة التسعير', required=True, default='detailed')
    uom_type = fields.Selection(related='material_id.uom_type', string='وحدة القياس', readonly=False)
    quantity = fields.Float('الكمية', default=1.0, digits=(16, 3))
    material_unit_cost = fields.Monetary('سعر المادة للوحدة', currency_field='currency_id')
    auxiliary_unit_cost = fields.Monetary('المواد المساعدة للوحدة', currency_field='currency_id')
    labor_unit_cost = fields.Monetary('شغل اليد للوحدة', currency_field='currency_id')
    inclusive_unit_cost = fields.Monetary('توريد وتركيب للوحدة', currency_field='currency_id')
    lump_sum_cost = fields.Monetary('قيمة المقطوعية', currency_field='currency_id')
    estimated_unit_cost = fields.Monetary('إجمالي تكلفة الوحدة', compute='_compute_amounts', store=True, recursive=True, currency_field='currency_id')
    estimated_total = fields.Monetary('إجمالي التكلفة المتوقعة', compute='_compute_amounts', store=True, recursive=True, currency_field='currency_id')
    estimated_material_amount = fields.Monetary(compute='_compute_amounts', store=True, recursive=True, currency_field='currency_id')
    estimated_auxiliary_amount = fields.Monetary(compute='_compute_amounts', store=True, recursive=True, currency_field='currency_id')
    estimated_labor_amount = fields.Monetary(compute='_compute_amounts', store=True, recursive=True, currency_field='currency_id')
    estimated_lump_sum_amount = fields.Monetary(compute='_compute_amounts', store=True, recursive=True, currency_field='currency_id')
    actual_total = fields.Monetary('إجمالي التكلفة الفعلية', compute='_compute_actual_total', store=True, recursive=True, currency_field='currency_id')
    variance_amount = fields.Monetary('الانحراف', compute='_compute_actual_total', store=True, recursive=True, currency_field='currency_id')
    variance_percent = fields.Float('نسبة الانحراف', compute='_compute_actual_total', store=True, recursive=True, digits=(16, 2))
    supplier_id = fields.Many2one('res.partner', 'المورد', check_company=True)
    supplier_text = fields.Char('اسم المورد')
    status = fields.Selection([('draft', 'مسودة'), ('pricing', 'قيد التسعير'), ('waiting', 'بانتظار الاعتماد'), ('approved', 'معتمد'), ('in_progress', 'جاري التنفيذ'), ('done', 'مكتمل'), ('cancelled', 'ملغي')], 'الحالة', default='draft')
    notes = fields.Text('ملاحظات')
    actual_line_ids = fields.One2many('abroj.cost.actual.line', 'plan_line_id')

    @api.model
    def _lock_project_structures(self, projects):
        """Serialize hierarchy changes for a project without bypassing ORM ACLs."""
        projects = projects.exists()
        if not projects:
            return
        projects.check_access('write')
        self.env.cr.execute(
            'SELECT id FROM abroj_cost_project WHERE id IN %s FOR UPDATE',
            [tuple(projects.ids)],
        )

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get('abroj_create_root_section'):
            # This context selects the dedicated parent-section flow, but it
            # is client supplied. Enforce the safe aggregation-only shape on
            # the server instead of trusting a browser default selection.
            vals_list = [dict(values, node_kind='section', parent_id=False) for values in vals_list]
        vals_list = [self._normalize_section_values(vals) for vals in vals_list]
        projects = self.env['abroj.cost.project'].browse(
            [vals['project_id'] for vals in vals_list if vals.get('project_id')]
        )
        self._lock_project_structures(projects)
        return super().create(vals_list)

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        if self.env.context.get('abroj_create_root_section'):
            defaults.update({
                'node_kind': 'section',
                'parent_id': False,
                'quantity': 0.0,
            })
        return defaults

    @api.constrains('parent_id', 'project_id', 'node_kind', 'category_id', 'child_ids')
    def _check_tree_contract(self):
        if self._has_cycle():
            raise ValidationError(_('لا يمكن إنشاء دورة في شجرة دراسة المشروع.'))
        for line in self:
            if line.parent_id:
                if line.parent_id.project_id != line.project_id or line.parent_id.company_id != line.company_id:
                    raise ValidationError(_('البند الأب يجب أن ينتمي إلى المشروع والشركة نفسيهما.'))
                if line.parent_id == line:
                    raise ValidationError(_('لا يمكن ربط البند بنفسه أو بأحد أبنائه.'))
                if line.parent_id.node_kind != 'section':
                    raise ValidationError(_('لا يمكن إضافة بند تابع إلى بند مسعّر. أضف قسماً أولاً.'))
            if line.node_kind == 'section':
                if line.category_id or line.material_id or line.actual_line_ids:
                    raise ValidationError(_('القسم للتجميع فقط ولا يحمل نوع عمل أو مادة أو تكلفة فعلية.'))
            else:
                if not line.category_id:
                    raise ValidationError(_('نوع العمل مطلوب للبند المسعّر.'))
                if line.child_ids:
                    raise ValidationError(_('لا يمكن للبند المسعّر أن يحتوي بنوداً تابعة. استخدم قسماً.'))

    @api.model
    def _normalize_section_values(self, values):
        """A section is a pure roll-up node, never a directly priced row."""
        values = dict(values)
        if values.get('node_kind') == 'section':
            values.update({
                'category_id': False,
                'material_id': False,
                'quantity': 0.0,
                'material_unit_cost': 0.0,
                'auxiliary_unit_cost': 0.0,
                'labor_unit_cost': 0.0,
                'inclusive_unit_cost': 0.0,
                'lump_sum_cost': 0.0,
                'supplier_id': False,
                'supplier_text': False,
            })
        return values

    @api.onchange('node_kind')
    def _onchange_node_kind(self):
        if self.node_kind == 'section':
            for field_name, value in self._normalize_section_values({'node_kind': 'section'}).items():
                if field_name != 'node_kind':
                    setattr(self, field_name, value)

    @api.onchange('material_id')
    def _onchange_material_id(self):
        material = self.material_id
        if material:
            self.name = material.name
            self.category_id = material.category_id
            self.image_1920 = material.image_1920
            self.uom_type = material.uom_type
            self.material_unit_cost = material.material_unit_cost
            self.auxiliary_unit_cost = material.auxiliary_unit_cost
            self.labor_unit_cost = material.labor_unit_cost
            self.inclusive_unit_cost = material.inclusive_unit_cost
            self.pricing_method = material.default_pricing_method
            self.supplier_id = material.supplier_id
            self.supplier_text = material.supplier_text

    def _round_amount(self, amount):
        """Round draft lines safely before their related project currency is resolved."""
        self.ensure_one()
        currency = self.currency_id or self.project_id.currency_id or self.env.company.currency_id
        return currency.round(amount) if currency else amount

    @api.depends('node_kind', 'pricing_method', 'quantity', 'material_unit_cost', 'auxiliary_unit_cost', 'labor_unit_cost', 'inclusive_unit_cost', 'lump_sum_cost',
                 'child_ids.estimated_material_amount', 'child_ids.estimated_auxiliary_amount', 'child_ids.estimated_labor_amount', 'child_ids.estimated_lump_sum_amount', 'child_ids.estimated_total')
    def _compute_amounts(self):
        for line in self:
            if line.node_kind == 'section':
                line.estimated_material_amount = line._round_amount(sum(line.child_ids.mapped('estimated_material_amount')))
                line.estimated_auxiliary_amount = line._round_amount(sum(line.child_ids.mapped('estimated_auxiliary_amount')))
                line.estimated_labor_amount = line._round_amount(sum(line.child_ids.mapped('estimated_labor_amount')))
                line.estimated_lump_sum_amount = line._round_amount(sum(line.child_ids.mapped('estimated_lump_sum_amount')))
                line.estimated_total = line._round_amount(sum(line.child_ids.mapped('estimated_total')))
                line.estimated_unit_cost = 0.0
                continue
            quantity = line.quantity or 0.0
            material = auxiliary = labor = lump = 0.0
            if line.pricing_method == 'detailed':
                material, auxiliary, labor = quantity * line.material_unit_cost, quantity * line.auxiliary_unit_cost, quantity * line.labor_unit_cost
            elif line.pricing_method == 'supply_only':
                material = quantity * line.material_unit_cost
            elif line.pricing_method == 'labor_only':
                labor = quantity * line.labor_unit_cost
            elif line.pricing_method == 'supply_install':
                material = quantity * line.inclusive_unit_cost
            elif line.pricing_method == 'lump_sum':
                lump = line.lump_sum_cost
            line.estimated_material_amount = line._round_amount(material)
            line.estimated_auxiliary_amount = line._round_amount(auxiliary)
            line.estimated_labor_amount = line._round_amount(labor)
            line.estimated_lump_sum_amount = line._round_amount(lump)
            line.estimated_total = line._round_amount(material + auxiliary + labor + lump)
            line.estimated_unit_cost = line._round_amount(line.estimated_total / quantity) if quantity and line.pricing_method != 'lump_sum' else line._round_amount(lump)

    @api.depends('node_kind', 'actual_line_ids.amount', 'estimated_total', 'child_ids.actual_total')
    def _compute_actual_total(self):
        for line in self:
            actual_total = sum(line.child_ids.mapped('actual_total')) if line.node_kind == 'section' else sum(line.actual_line_ids.mapped('amount'))
            line.actual_total = line._round_amount(actual_total)
            line.variance_amount = line._round_amount(line.actual_total - line.estimated_total)
            line.variance_percent = (line.variance_amount / line.estimated_total * 100.0) if line.estimated_total else 0.0

    def write(self, vals):
        if any(line.project_id.state == 'closed' for line in self) and not self.env.user.has_group('abroj_project_costing.group_abroj_cost_manager'):
            raise AccessError(_('لا يمكن تعديل بنود مشروع مغلق.'))
        structural_fields = {'parent_id', 'project_id', 'node_kind'}
        if structural_fields.intersection(vals):
            projects = self.mapped('project_id')
            if vals.get('project_id'):
                projects |= self.env['abroj.cost.project'].browse(vals['project_id'])
            self._lock_project_structures(projects)
        # A section remains an aggregation node once created.  Turning an
        # empty section into a priced item would silently reintroduce direct
        # prices on a parent through RPC or a future form view.
        sections = self.filtered(lambda line: line.node_kind == 'section' or vals.get('node_kind') == 'section')
        other_lines = self - sections
        result = True
        if sections:
            # Existing and newly selected sections remain aggregation-only
            # even when a write comes from an import, RPC call, or a future
            # form view.
            section_vals = self._normalize_section_values({**vals, 'node_kind': 'section'})
            result = super(AbrojCostPlanLine, sections).write(section_vals)
        if other_lines:
            result = super(AbrojCostPlanLine, other_lines).write(vals) and result
        return result

    def unlink(self):
        self._lock_project_structures(self.mapped('project_id'))
        return super().unlink()


class AbrojCostActualLine(models.Model):
    _name = 'abroj.cost.actual.line'
    _description = 'Abroj Actual Project Cost'
    _order = 'date desc, id desc'

    project_id = fields.Many2one('abroj.cost.project', 'المشروع', required=True, ondelete='restrict', check_company=True, index=True)
    company_id = fields.Many2one(related='project_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='project_id.currency_id', readonly=True)
    plan_line_id = fields.Many2one('abroj.cost.plan.line', 'بند الدراسة', check_company=True, ondelete='restrict')
    # This is deliberately non-stored.  It is a convenient scope picker for
    # the form, while plan_line_id remains the one auditable source of truth.
    plan_scope_id = fields.Many2one(
        'abroj.cost.plan.line', 'نطاق الدراسة', compute='_compute_plan_scope_id',
        inverse='_inverse_plan_scope_id', search='_search_plan_scope_id',
    )
    is_unplanned = fields.Boolean('تكلفة إضافية غير مخططة')
    category_id = fields.Many2one('abroj.cost.category', 'الفئة', required=True, check_company=True)
    material_id = fields.Many2one('abroj.cost.material', 'المادة', check_company=True)
    name = fields.Char('اسم البند', required=True)
    description = fields.Text('الوصف')
    date = fields.Date('التاريخ', default=fields.Date.context_today, required=True)
    uom_type = fields.Selection(related='material_id.uom_type', string='وحدة القياس', readonly=False)
    quantity = fields.Float('الكمية', default=1.0, digits=(16, 3))
    amount = fields.Monetary('المبلغ الفعلي', required=True, currency_field='currency_id')
    supplier_id = fields.Many2one('res.partner', 'المورد / المستفيد', check_company=True)
    supplier_text = fields.Char('اسم المورد / المستفيد')
    cost_type = fields.Selection([('material', 'مادة'), ('auxiliary', 'مواد مساعدة'), ('labor', 'عمل يد'), ('lump_sum', 'مقطوعية'), ('other', 'أخرى')], 'نوع التكلفة', required=True, default='material')
    notes = fields.Text('ملاحظات')
    attachment_ids = fields.Many2many(
        'ir.attachment',
        'abroj_cost_actual_attachment_rel',
        'actual_line_id',
        'attachment_id',
        string='مرفقات الفاتورة أو سند الصرف',
    )
    attachment_count = fields.Integer(compute='_compute_attachment_count')

    @api.depends('plan_line_id')
    def _compute_plan_scope_id(self):
        for line in self:
            line.plan_scope_id = line.plan_line_id.parent_id or line.plan_line_id

    def _inverse_plan_scope_id(self):
        # The scope only filters the picker.  Saving it must never create a
        # second hierarchy reference alongside the selected priced leaf.
        return None

    @api.model
    def _search_plan_scope_id(self, operator, value):
        return [('plan_line_id', 'child_of', value)]

    @api.onchange('plan_scope_id')
    def _onchange_plan_scope_id(self):
        for line in self:
            if line.plan_scope_id and line.plan_line_id:
                scope_prefix = '%s%s/' % (line.plan_scope_id.parent_path, line.plan_scope_id.id)
                if not line.plan_line_id.parent_path.startswith(scope_prefix):
                    line.plan_line_id = False

    @api.onchange('plan_line_id')
    def _onchange_plan_line_id(self):
        line = self.plan_line_id
        if line:
            self.is_unplanned = False
            self.category_id = line.category_id
            self.material_id = line.material_id
            self.name = line.name
            self.description = line.description
            self.uom_type = line.uom_type
            self.supplier_id = line.supplier_id
            self.supplier_text = line.supplier_text

    @api.constrains('plan_line_id', 'project_id', 'is_unplanned', 'category_id')
    def _check_plan_line_project(self):
        for line in self:
            if not line.plan_line_id and not line.is_unplanned:
                raise ValidationError(_('اختر بند الدراسة أو حدّد أن التكلفة غير مخططة.'))
            if line.plan_line_id and line.plan_line_id.project_id != line.project_id:
                raise ValidationError(_('بند الدراسة يجب أن ينتمي للمشروع نفسه.'))
            if line.plan_line_id and line.plan_line_id.node_kind != 'item':
                raise ValidationError(_('التكلفة الفعلية يجب أن ترتبط ببند مسعّر، وليس بقسم تجميعي.'))
            if line.plan_line_id and line.is_unplanned:
                raise ValidationError(_('لا يمكن اعتبار تكلفة مرتبطة ببند دراسة تكلفة غير مخططة.'))
            if line.plan_line_id and line.category_id != line.plan_line_id.category_id:
                raise ValidationError(_('نوع عمل التكلفة الفعلية يجب أن يطابق نوع عمل بند الدراسة المرتبط.'))

    @api.depends('attachment_ids')
    def _compute_attachment_count(self):
        data = self.env['ir.attachment'].read_group([('res_model', '=', self._name), ('res_id', 'in', self.ids)], ['res_id'], ['res_id'])
        counts = {item['res_id']: item['res_id_count'] for item in data}
        for line in self:
            line.attachment_count = counts.get(line.id, 0) + len(line.attachment_ids)

    def action_open_attachments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('مرفقات التكلفة'),
            'res_model': 'ir.attachment',
            'view_mode': 'kanban,list,form',
            'domain': ['|', '&', ('res_model', '=', self._name), ('res_id', '=', self.id), ('id', 'in', self.attachment_ids.ids)],
            'context': {'default_res_model': self._name, 'default_res_id': self.id},
        }


class AbrojCostProgressStage(models.Model):
    _name = 'abroj.cost.progress.stage'
    _description = 'Abroj Project Progress Stage'
    _order = 'sequence, id'

    project_id = fields.Many2one('abroj.cost.project', 'المشروع', required=True, ondelete='restrict', check_company=True)
    company_id = fields.Many2one(related='project_id.company_id', store=True, index=True)
    sequence = fields.Integer('الترتيب', default=10)
    name = fields.Char('اسم مرحلة الإنجاز', required=True)
    planned_start_date = fields.Date('تاريخ البداية المخطط', required=True)
    planned_duration_days = fields.Integer('المدة المخططة بالأيام', required=True, default=1)
    planned_end_date = fields.Date('تاريخ النهاية المخطط', compute='_compute_dates', store=True)
    actual_completion_date = fields.Date('تاريخ الإنجاز الفعلي', readonly=True)
    state = fields.Selection([('planned', 'مخطط'), ('done', 'تم الإنجاز'), ('cancelled', 'ملغي')], 'الحالة', default='planned', required=True)
    delay_days = fields.Integer('أيام التأخير', compute='_compute_dates', store=True)
    is_overdue = fields.Boolean('متأخر', compute='_compute_dates', store=True)
    notes = fields.Text('ملاحظات')

    @api.depends('planned_start_date', 'planned_duration_days', 'actual_completion_date', 'state')
    def _compute_dates(self):
        for stage in self:
            stage.planned_end_date = fields.Date.add(stage.planned_start_date, days=max(stage.planned_duration_days - 1, 0)) if stage.planned_start_date else False
            reference = stage.actual_completion_date if stage.state == 'done' else fields.Date.context_today(stage)
            stage.delay_days = max((reference - stage.planned_end_date).days, 0) if reference and stage.planned_end_date else 0
            stage.is_overdue = bool(stage.state == 'planned' and stage.planned_end_date and fields.Date.context_today(stage) > stage.planned_end_date)

    @api.constrains('planned_duration_days')
    def _check_duration(self):
        if any(stage.planned_duration_days < 1 for stage in self):
            raise ValidationError(_('مدة الإنجاز يجب أن تكون يومًا واحدًا على الأقل.'))

    def action_mark_done(self):
        self.write({'state': 'done', 'actual_completion_date': fields.Date.context_today(self)})


class AbrojCostReceipt(models.Model):
    _name = 'abroj.cost.receipt'
    _description = 'Abroj Internal Receipt'
    _order = 'date desc, id desc'

    project_id = fields.Many2one('abroj.cost.project', 'المشروع', required=True, ondelete='restrict', check_company=True)
    company_id = fields.Many2one(related='project_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='project_id.currency_id', readonly=True)
    name = fields.Char('رقم السند', default='/', required=True, readonly=True, copy=False, index=True)
    date = fields.Date('التاريخ', default=fields.Date.context_today, required=True)
    amount = fields.Monetary('المبلغ', required=True, currency_field='currency_id')
    note = fields.Text('ملاحظات')
    # The fields below adapt this operational receipt to Odoo's native payment
    # receipt template. They do not create an account.payment or account.move.
    partner_id = fields.Many2one(related='project_id.partner_id', readonly=True)
    partner_type = fields.Selection([('customer', 'Customer')], default='customer', readonly=True)
    payment_receipt_title = fields.Char(compute='_compute_payment_receipt_title')
    memo = fields.Text(related='note', readonly=True, string='مذكرة سند القبض')
    # Some installed Odoo localizations extend the native receipt template with
    # withholding details. Project receipts never create withholding entries,
    # so this explicit display-only flag keeps that optional block empty.
    withholding_line_ids = fields.Boolean(default=False, readonly=True)

    @api.depends('name')
    def _compute_payment_receipt_title(self):
        for receipt in self:
            receipt.payment_receipt_title = _('سند قبض مشروع')

    def _get_payment_receipt_report_values(self):
        """Supply only the display contract expected by Odoo's native template."""
        self.ensure_one()
        return {
            'display_payment_method': False,
            'display_invoices': False,
        }

    def _get_prior_project_receipts(self):
        """Return prior receipts for this project, ordered for the printed audit trail."""
        self.ensure_one()
        prior = self.project_id.receipt_ids.filtered(
            lambda receipt: (receipt.date, receipt.id) < (self.date, self.id)
        )
        return prior.sorted(lambda receipt: (receipt.date, receipt.id))

    def _get_project_receipt_summary(self):
        """Keep all receipt totals authoritative in the Odoo backend."""
        self.ensure_one()
        prior = self._get_prior_project_receipts()
        prior_amount = sum(prior.mapped('amount'))
        received_after = prior_amount + self.amount
        return {
            'prior_receipts': prior,
            'prior_amount': prior_amount,
            'received_after': received_after,
            'remaining_after': self.project_id.agreement_amount - received_after,
        }

    @api.model
    def default_get(self, fields_list):
        """Show the definitive voucher reference before a project receipt is saved."""
        values = super().default_get(fields_list)
        if 'name' in fields_list and values.get('name') in (False, '/', _('استلام جديد')):
            project_id = values.get('project_id') or self.env.context.get('default_project_id')
            project = self.env['abroj.cost.project'].browse(project_id).exists()
            if project:
                values['name'] = self._next_receipt_number(project.company_id)
        return values

    @api.model
    def _next_receipt_number(self, company):
        """Keep voucher references immutable and sequential within each company."""
        Sequence = self.env['ir.sequence'].sudo()
        sequence = Sequence.search([
            ('code', '=', 'abroj.cost.receipt'),
            ('company_id', '=', company.id),
        ], limit=1)
        if not sequence:
            sequence = Sequence.create({
                'name': _('أبرج | سندات استلام العميل'),
                'code': 'abroj.cost.receipt',
                'prefix': 'RCV/%(year)s/',
                'padding': 5,
                'implementation': 'standard',
                'company_id': company.id,
            })
        return sequence.with_company(company).next_by_id() or '/'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Readonly fields are omitted by some relational-form payloads.  An
            # omitted value must be handled as the standard '/' placeholder.
            if not vals.get('name') or vals.get('name') in ('/', _('استلام جديد')):
                project = self.env['abroj.cost.project'].browse(vals.get('project_id')).exists()
                vals['name'] = self._next_receipt_number(project.company_id if project else self.env.company)
        return super().create(vals_list)

    def action_open_edit_form(self):
        """Open the explicit correction form; the normal form remains read-only."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('تعديل سند الاستلام'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': self.env.ref('abroj_project_costing.view_abroj_receipt_form_edit').id,
            'target': 'current',
            'context': dict(self.env.context, form_view_initial_mode='edit'),
        }

    def action_open_receipt_view(self):
        """Open a saved receipt in read-only mode, not as an inline draft."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('سند قبض العميل'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(self.env.ref(
                'abroj_project_costing.view_abroj_receipt_form_readonly'
            ).id, 'form')],
            'target': 'new',
            'context': dict(self.env.context, form_view_initial_mode='readonly'),
        }

    @api.model
    def _assign_missing_numbers(self):
        """Number placeholder vouchers created before the sequence was introduced."""
        # Legacy entries used free text such as "استلام جديد" or "دفعة أولى".
        # New vouchers are immutable and always use the RCV/year/sequence format.
        for receipt in self.search([('name', 'not like', 'RCV/%')], order='date, id'):
            receipt.name = self._next_receipt_number(receipt.company_id)

    @api.constrains('amount', 'project_id')
    def _check_received_total(self):
        for receipt in self:
            total = sum(receipt.project_id.receipt_ids.mapped('amount'))
            if receipt.amount < 0 or total > receipt.project_id.agreement_amount:
                raise ValidationError(_('إجمالي الاستلامات لا يمكن أن يتجاوز قيمة الاتفاقية السارية.'))


class AbrojCostAgreementAmendment(models.Model):
    _name = 'abroj.cost.agreement.amendment'
    _description = 'Abroj Agreement Amendment'
    _order = 'date desc, id desc'

    project_id = fields.Many2one('abroj.cost.project', 'المشروع', required=True, ondelete='restrict', check_company=True)
    company_id = fields.Many2one(related='project_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='project_id.currency_id', readonly=True)
    date = fields.Date('التاريخ', default=fields.Date.context_today, required=True)
    previous_amount = fields.Monetary('قيمة الاتفاقية السابقة', related='project_id.agreement_amount', readonly=True, currency_field='currency_id')
    new_amount = fields.Monetary('قيمة الاتفاقية الجديدة', required=True, currency_field='currency_id')
    reason = fields.Text('سبب التعديل', required=True)
    state = fields.Selection([('draft', 'مسودة'), ('applied', 'مطبق')], 'الحالة', default='draft', required=True)

    @api.constrains('new_amount')
    def _check_new_amount(self):
        for amendment in self:
            if amendment.new_amount < amendment.project_id.received_total:
                raise ValidationError(_('لا يمكن تخفيض الاتفاقية تحت المبلغ المستلم.'))

    def action_apply(self):
        for amendment in self:
            if amendment.project_id.owner_id != self.env.user and not self.env.user.has_group('abroj_project_costing.group_abroj_cost_manager'):
                raise AccessError(_('مالك المشروع أو المدير فقط يستطيع تعديل الاتفاقية.'))
            amendment.project_id.write({'agreement_amount': amendment.new_amount})
            amendment.state = 'applied'


class AbrojCostProjectMember(models.Model):
    _name = 'abroj.cost.project.member'
    _description = 'Abroj Project Member'

    project_id = fields.Many2one('abroj.cost.project', 'المشروع', required=True, ondelete='cascade', check_company=True)
    company_id = fields.Many2one(related='project_id.company_id', store=True, index=True)
    user_id = fields.Many2one('res.users', 'المستخدم', required=True, ondelete='cascade')
    access_level = fields.Selection([('view', 'مشاهدة'), ('edit', 'تعديل وإضافة')], 'الصلاحية', required=True, default='view')

    _sql_constraints = [
        ('abroj_project_member_unique', 'unique(project_id, user_id)', 'المستخدم مضاف للمشروع بالفعل.'),
    ]
