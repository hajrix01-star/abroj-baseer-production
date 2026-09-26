from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    followup_evaluation_ids = fields.One2many(
        'baseer.followup.employee.evaluation', 'employee_id', string='تقييمات المتابعة')
    followup_excluded = fields.Boolean(
        string='استثناء من تقييم المتابعة',
        help='لا يظهر الموظف في قائمة تقييمات مدير الوردية ولا يدخل ضمن إجمالي التقييم اليومي.',
    )


class ResCompany(models.Model):
    _inherit = 'res.company'

    baseer_followup_performance_threshold = fields.Integer(
        string='حد تنبيه أداء الموظف (%)',
        default=80,
        help='يظهر أداء الموظف دون هذا الحد بحالة تنبيه في لوحة متابعة الموظفين.',
    )

    @api.constrains('baseer_followup_performance_threshold')
    def _check_baseer_followup_performance_threshold(self):
        for company in self:
            if not 0 <= company.baseer_followup_performance_threshold <= 100:
                raise ValidationError(_('The employee performance threshold must be between 0 and 100.'))


class BaseerFollowupShift(models.Model):
    _name = 'baseer.followup.shift'
    _description = 'وردية متابعة الموظف'
    _order = 'started_at desc, id desc'

    employee_id = fields.Many2one('hr.employee', string='الموظف', required=True, readonly=True, index=True)
    company_id = fields.Many2one(related='employee_id.company_id', string='الشركة', store=True, index=True)
    started_at = fields.Datetime(string='وقت بدء الوردية', required=True, readonly=True, default=fields.Datetime.now)
    operational_date = fields.Date(
        string='تاريخ الوردية التشغيلي', required=True, readonly=True,
        default=fields.Date.context_today, index=True,
        help='يثبت عند بدء الدوام. تبقى كل مهام وتقييمات الوردية محسوبة على هذا التاريخ حتى لو أغلقت بعد منتصف الليل.',
    )
    state = fields.Selection([
        ('opening', 'بداية الدوام'),
        ('midday', 'وسط الدوام'),
        ('closing', 'الإغلاق'),
        ('closed', 'مغلقة'),
    ], string='مرحلة الوردية', default='opening', required=True)
    opening_line_ids = fields.One2many('baseer.followup.opening.line', 'shift_id', string='مهام بداية الدوام', domain=[('stage', '=', 'opening')])
    midday_line_ids = fields.One2many('baseer.followup.opening.line', 'shift_id', string='مهام وسط الدوام', domain=[('stage', '=', 'midday')])
    closing_line_ids = fields.One2many('baseer.followup.opening.line', 'shift_id', string='مهام الإغلاق', domain=[('stage', '=', 'closing')])
    absence_ids = fields.One2many('baseer.followup.shift.absence', 'shift_id', string='الموظفون الغائبون')
    opening_completion = fields.Integer(string='إنجاز بداية الدوام', compute='_compute_stage_completion', store=True)
    midday_completion = fields.Integer(string='إنجاز وسط الدوام', compute='_compute_stage_completion', store=True)
    closing_completion = fields.Integer(string='إنجاز الإغلاق', compute='_compute_stage_completion', store=True)

    @api.depends('opening_line_ids.done', 'midday_line_ids.done', 'closing_line_ids.done')
    def _compute_stage_completion(self):
        for record in self:
            for lines, field_name in (
                (record.opening_line_ids, 'opening_completion'),
                (record.midday_line_ids, 'midday_completion'),
                (record.closing_line_ids, 'closing_completion'),
            ):
                total = len(lines)
                record[field_name] = (sum(lines.mapped('done')) * 100 // total) if total else 0

    @api.model
    def action_start_my_shift(self):
        employee_model = self.env['hr.employee'].sudo()
        employee = employee_model.search([
            ('user_id', '=', self.env.user.id),
            ('company_id', '=', self.env.company.id),
            ('active', '=', True),
        ], limit=1)
        if not employee:
            raise AccessError(_('Your Odoo user must be linked to one active employee profile.'))
        return self.action_start_for_employee(employee)

    @api.model
    def action_start_for_employee(self, employee):
        """Start a shift for a controller-validated employee identity."""
        if not employee or not employee.active:
            raise AccessError(_('An active employee profile is required to start a shift.'))
        shift_model = self.with_company(employee.company_id)
        existing = shift_model.search([('employee_id', '=', employee.id), ('state', 'in', ('opening', 'midday', 'closing'))], limit=1)
        if existing:
            existing._add_missing_default_tasks()
            return existing
        shift = shift_model.create({'employee_id': employee.id})
        shift._add_missing_default_tasks()
        return shift

    def _add_missing_default_tasks(self):
        """Copy the standard templates only for stages that have no lines yet.

        This also lets shifts created before a new stage was introduced continue
        naturally, without replacing or deleting the manager's existing checks.
        """
        template_model = self.env['baseer.followup.task.template'].sudo()
        stages = ('opening', 'midday', 'closing')
        for shift in self:
            templates = template_model.search([
            ('active', '=', True),
            '|', ('company_id', '=', False), ('company_id', '=', shift.company_id.id),
        ], order='stage, sequence, id')
            present_stages = set(shift.mapped('opening_line_ids.stage'))
            present_stages.update(shift.mapped('midday_line_ids.stage'))
            present_stages.update(shift.mapped('closing_line_ids.stage'))
            missing_stages = set(stages) - present_stages
            if missing_stages:
                self.env['baseer.followup.opening.line'].create([
                    {
                        'shift_id': shift.id,
                        'template_id': template.id,
                        'stage': template.stage,
                        'name': template.name,
                        'name_en': template.name_en,
                    }
                    for template in templates
                    if template.stage in missing_stages
                ])

    def action_set_stage(self, stage):
        self.ensure_one()
        if stage not in ('opening', 'midday', 'closing', 'closed'):
            raise ValueError('Unknown follow-up stage')
        transitions = {
            ('opening', 'midday'): self.opening_completion,
            ('midday', 'closing'): self.midday_completion,
            ('closing', 'closed'): self.closing_completion,
        }
        required_completion = transitions.get((self.state, stage))
        if required_completion is None:
            raise ValidationError(_('Shift stages must be completed in order.'))
        if required_completion < 100:
            raise ValidationError(_('Complete every task in the current stage before continuing.'))
        if self.state == 'opening' and stage == 'midday':
            midday_available_at = self.started_at + timedelta(hours=4)
            if fields.Datetime.now() < midday_available_at:
                raise ValidationError(_('Mid-shift becomes available four hours after the shift starts.'))
        if self.state == 'midday' and stage == 'closing' and not self._required_evaluations_complete():
            raise ValidationError(_('Complete the required employee evaluations before starting closing tasks.'))
        if stage == 'closed' and min(self.opening_completion, self.midday_completion, self.closing_completion) < 100:
            raise ValidationError(_('Complete every shift stage before closing the shift.'))
        self.write({'state': stage})

    def _required_evaluations_complete(self):
        self.ensure_one()
        eligible_employees = self.env['hr.employee'].sudo().search([
            ('company_id', '=', self.company_id.id), ('active', '=', True), ('followup_excluded', '=', False),
        ])
        absent_employee_ids = set(self.absence_ids.mapped('employee_id').ids)
        evaluated_employee_ids = set(self.env['baseer.followup.employee.evaluation'].search([
            ('shift_id', '=', self.id),
        ]).mapped('employee_id').ids)
        required_employee_ids = set(eligible_employees.ids) - absent_employee_ids
        return required_employee_ids.issubset(evaluated_employee_ids)


class BaseerFollowupShiftAbsence(models.Model):
    _name = 'baseer.followup.shift.absence'
    _description = 'غياب موظف في وردية المتابعة'
    _order = 'marked_at desc, id desc'

    shift_id = fields.Many2one('baseer.followup.shift', string='الوردية', required=True, readonly=True, ondelete='cascade', index=True)
    employee_id = fields.Many2one('hr.employee', string='الموظف الغائب', required=True, readonly=True, index=True)
    company_id = fields.Many2one(related='shift_id.company_id', string='الشركة', store=True, index=True)
    marked_at = fields.Datetime(string='وقت تسجيل الغياب', required=True, readonly=True, default=fields.Datetime.now)

    _one_absence_per_employee_shift = models.Constraint(
        'UNIQUE(shift_id, employee_id)',
        'تم تسجيل غياب هذا الموظف في الوردية الحالية بالفعل.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            shift = self.env['baseer.followup.shift'].browse(vals.get('shift_id')).exists()
            employee = self.env['hr.employee'].browse(vals.get('employee_id')).exists()
            if not shift or not employee or shift.company_id != employee.company_id:
                raise ValidationError(_('The absent employee must belong to the shift company.'))
            if shift.state == 'closed':
                raise ValidationError(_('A closed shift cannot be edited.'))
            if employee.followup_excluded:
                raise ValidationError(_('This employee is already excluded from follow-up evaluation.'))
            if self.env['baseer.followup.employee.evaluation'].search_count([
                ('shift_id', '=', shift.id), ('employee_id', '=', employee.id),
            ]):
                raise ValidationError(_('A rated employee cannot be marked absent in the same shift.'))
        return super().create(vals_list)

    def unlink(self):
        if any(record.shift_id.state == 'closed' for record in self):
            raise ValidationError(_('A closed shift cannot be edited.'))
        return super().unlink()


class BaseerFollowupOpeningLine(models.Model):
    _name = 'baseer.followup.opening.line'
    _description = 'بند متابعة الوردية'
    _order = 'id'
    shift_id = fields.Many2one('baseer.followup.shift', string='الوردية', required=True, ondelete='cascade', index=True)
    template_id = fields.Many2one('baseer.followup.task.template', string='قالب المهمة', readonly=True, ondelete='set null')
    company_id = fields.Many2one(related='shift_id.company_id', string='الشركة', store=True, index=True)
    stage = fields.Selection([('opening', 'بداية الدوام'), ('midday', 'وسط الدوام'), ('closing', 'الإغلاق')], string='المرحلة', required=True, default='opening', index=True)
    name = fields.Char(string='اسم المهمة بالعربية', required=True)
    name_en = fields.Char(string='اسم المهمة بالإنجليزية', readonly=True)
    done = fields.Boolean(string='تم التنفيذ')
    completed_at = fields.Datetime(string='وقت الإنجاز', readonly=True)

    def write(self, vals):
        if 'done' in vals and any(record.shift_id.state == 'closed' for record in self):
            raise ValidationError(_('A closed shift cannot be edited.'))
        if vals.get('done'):
            vals['completed_at'] = fields.Datetime.now()
        return super().write(vals)


class BaseerFollowupTaskTemplate(models.Model):
    _name = 'baseer.followup.task.template'
    _description = 'قالب مهام متابعة الموظف'
    _order = 'stage, sequence, id'

    name = fields.Char(string='اسم المهمة بالعربية', required=True)
    name_en = fields.Char(string='اسم المهمة بالإنجليزية', required=True)
    stage = fields.Selection([
        ('opening', 'بداية الدوام'),
        ('midday', 'وسط الدوام'),
        ('closing', 'الإغلاق'),
    ], string='المرحلة', required=True, default='opening', index=True)
    sequence = fields.Integer(string='الترتيب', default=10)
    company_id = fields.Many2one('res.company', string='الشركة', help='اتركه فارغًا ليكون قالبًا افتراضيًا لجميع الشركات.')
    active = fields.Boolean(string='نشط', default=True)


class BaseerFollowupNote(models.Model):
    _name = 'baseer.followup.note'
    _description = 'ملاحظة الوردية'
    _order = 'reported_at desc, id desc'

    name = fields.Char(string='عنوان الملاحظة', required=True)
    item_type = fields.Selection([
        ('note', 'ملاحظة'),
        ('task', 'مهمة'),
        ('reminder', 'تذكير'),
    ], string='نوع المتابعة', required=True, default='note', index=True)
    recurrence = fields.Selection([
        ('once', 'مرة واحدة'),
        ('daily', 'يومي'),
        ('weekly', 'أسبوعي'),
        ('monthly', 'شهري'),
    ], string='تكرار التذكير', required=True, default='once', index=True)
    item_ids = fields.One2many('baseer.followup.note.item', 'note_id', string='عناصر المهمة')
    task_remaining_count = fields.Integer(string='عناصر المهمة المتبقية', compute='_compute_task_remaining_count')
    description = fields.Text(string='التفاصيل')
    image = fields.Image(string='صورة المشكلة', max_width=1920, max_height=1920)
    line_id = fields.Many2one('baseer.followup.opening.line', string='المهمة المرتبطة', readonly=True, ondelete='cascade', index=True)
    stage = fields.Selection(related='shift_id.state', string='مرحلة الوردية', readonly=True)
    employee_id = fields.Many2one('hr.employee', string='المبلّغ', required=True, readonly=True, index=True)
    shift_id = fields.Many2one('baseer.followup.shift', string='الوردية', required=True, readonly=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='shift_id.company_id', string='الشركة', store=True, index=True)
    reported_at = fields.Datetime(string='وقت البلاغ', required=True, readonly=True, default=fields.Datetime.now)
    target_at = fields.Datetime(string='موعد المتابعة', index=True)
    state = fields.Selection([
        ('open', 'مفتوحة'),
        ('resolved', 'تمت المعالجة'),
    ], string='الحالة', required=True, default='open', index=True)
    resolved_at = fields.Datetime(string='وقت المعالجة', readonly=True)

    @api.constrains('item_type', 'target_at')
    def _check_reminder_target(self):
        for record in self:
            if record.item_type == 'reminder' and not record.target_at:
                raise ValidationError(_('A reminder requires a scheduled time.'))

    @api.constrains('item_type', 'recurrence')
    def _check_reminder_recurrence(self):
        for record in self:
            if record.item_type != 'reminder' and record.recurrence != 'once':
                raise ValidationError(_('Only reminders can repeat.'))

    @api.depends('item_ids.done')
    def _compute_task_remaining_count(self):
        for record in self:
            record.task_remaining_count = len(record.item_ids.filtered(lambda item: not item.done))

    @api.constrains('item_type', 'item_ids')
    def _check_task_items(self):
        for record in self:
            if record.item_type == 'task' and not record.item_ids:
                raise ValidationError(_('A task requires at least one checklist item.'))

    def action_resolve(self):
        for record in self:
            if record.item_type == 'task' and record.task_remaining_count:
                raise ValidationError(_('Complete every task item before resolving the task.'))
            if record.item_type == 'reminder' and record.recurrence != 'once':
                if not record.target_at:
                    raise ValidationError(_('A recurring reminder requires a scheduled time.'))
                if record.recurrence == 'daily':
                    next_target = record.target_at + timedelta(days=1)
                elif record.recurrence == 'weekly':
                    next_target = record.target_at + timedelta(weeks=1)
                else:
                    next_target = record.target_at + relativedelta(months=1)
                record.write({'target_at': next_target})
            else:
                record.write({'state': 'resolved', 'resolved_at': fields.Datetime.now()})


class BaseerFollowupNoteItem(models.Model):
    _name = 'baseer.followup.note.item'
    _description = 'عنصر مهمة المتابعة'
    _order = 'sequence, id'

    note_id = fields.Many2one('baseer.followup.note', string='المهمة', required=True, ondelete='cascade', index=True)
    name = fields.Char(string='العنصر', required=True)
    sequence = fields.Integer(string='الترتيب', default=10)
    done = fields.Boolean(string='تم الإنجاز', default=False, index=True)
    completed_at = fields.Datetime(string='وقت الإنجاز', readonly=True)
    company_id = fields.Many2one(related='note_id.company_id', string='الشركة', store=True, index=True)

    @api.constrains('note_id')
    def _check_task_parent(self):
        if any(item.note_id.item_type != 'task' for item in self):
            raise ValidationError(_('Checklist items can only belong to a task.'))

    def action_toggle_done(self):
        for item in self:
            if item.note_id.state != 'open':
                raise ValidationError(_('Resolved tasks cannot be changed.'))
            item.write({'done': not item.done, 'completed_at': fields.Datetime.now() if not item.done else False})


class BaseerFollowupEvaluationTemplate(models.Model):
    _name = 'baseer.followup.evaluation.template'
    _description = 'قالب مؤشرات تقييم الموظف'
    _order = 'sequence, id'

    name = fields.Char(string='اسم المؤشر بالعربية', required=True)
    name_en = fields.Char(string='اسم المؤشر بالإنجليزية', required=True)
    sequence = fields.Integer(string='الترتيب', default=10)
    company_id = fields.Many2one('res.company', string='الشركة', help='اتركه فارغًا ليكون مؤشرًا افتراضيًا لجميع الشركات.')
    active = fields.Boolean(string='نشط', default=True)


class BaseerFollowupEmployeeEvaluation(models.Model):
    _name = 'baseer.followup.employee.evaluation'
    _description = 'تقييم الموظف اليومي'
    _order = 'evaluated_at desc, id desc'

    employee_id = fields.Many2one('hr.employee', string='الموظف المُقيَّم', required=True, readonly=True, index=True)
    evaluator_id = fields.Many2one('hr.employee', string='المقيِّم', required=True, readonly=True, index=True)
    company_id = fields.Many2one(related='employee_id.company_id', string='الشركة', store=True, index=True)
    shift_id = fields.Many2one('baseer.followup.shift', string='الوردية', required=True, readonly=True, ondelete='cascade')
    evaluated_at = fields.Datetime(string='وقت التقييم', required=True, readonly=True, default=fields.Datetime.now)
    line_ids = fields.One2many('baseer.followup.employee.evaluation.line', 'evaluation_id', string='المؤشرات', readonly=True)
    note = fields.Text(string='ملاحظة عامة')
    image = fields.Image(string='صورة مرفقة', max_width=1920, max_height=1920)

    _one_evaluation_per_employee_shift = models.Constraint(
        'UNIQUE(shift_id, employee_id)',
        'يوجد تقييم مسجل لهذا الموظف في الوردية الحالية.',
    )


class BaseerFollowupEmployeeEvaluationLine(models.Model):
    _name = 'baseer.followup.employee.evaluation.line'
    _description = 'بند تقييم الموظف'
    _order = 'sequence, id'

    evaluation_id = fields.Many2one('baseer.followup.employee.evaluation', string='التقييم', required=True, ondelete='cascade', index=True)
    template_id = fields.Many2one('baseer.followup.evaluation.template', string='قالب المؤشر', readonly=True, ondelete='set null')
    sequence = fields.Integer(string='الترتيب', default=10)
    name = fields.Char(string='المؤشر بالعربية', required=True, readonly=True)
    name_en = fields.Char(string='المؤشر بالإنجليزية', required=True, readonly=True)
    rating = fields.Integer(string='التقييم بالنجوم', required=True)

    _rating_range = models.Constraint(
        'CHECK(rating >= 1 AND rating <= 5)',
        'التقييم يجب أن يكون من نجمة إلى خمس نجمات.',
    )
