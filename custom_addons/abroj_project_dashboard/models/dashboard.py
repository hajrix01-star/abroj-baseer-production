from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

TYPES = [('residential', 'سكني / فلل'), ('commercial', 'تجاري'), ('renovation', 'ترميم'), ('infrastructure', 'بنية تحتية'), ('other', 'أخرى')]
STATUS = {'on_track': 'على المسار', 'at_risk': 'معرّض للخطر', 'off_track': 'متعثر', 'on_hold': 'متوقف', 'done': 'مكتمل', 'to_define': 'غير محدد'}
TYPES_EN = dict(residential='Residential / villas', commercial='Commercial', renovation='Renovation', infrastructure='Infrastructure', other='Other')
STATUS_EN = dict(on_track='On track', at_risk='At risk', off_track='Off track', on_hold='On hold', done='Completed', to_define='Undefined')


class ProjectTask(models.Model):
    _inherit = 'project.task'

    x_abroj_date_start = fields.Date(string='تاريخ بداية المرحلة')
    x_abroj_duration_days = fields.Integer(string='المدة (أيام)', default=1, required=True)
    x_abroj_progress = fields.Float(string='نسبة إنجاز المرحلة')

    @api.constrains('x_abroj_duration_days')
    def _check_abroj_duration(self):
        for task in self:
            if task.x_abroj_duration_days < 1:
                raise ValidationError('مدة المرحلة يجب أن تكون يوماً واحداً على الأقل.')

    @api.onchange('x_abroj_date_start', 'x_abroj_duration_days')
    def _onchange_abroj_dates(self):
        for task in self:
            if task.x_abroj_date_start and task.x_abroj_duration_days >= 1:
                task.date_deadline = fields.Datetime.to_datetime(
                    task.x_abroj_date_start + timedelta(days=task.x_abroj_duration_days - 1))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            start = vals.get('x_abroj_date_start')
            duration = vals.get('x_abroj_duration_days', 1)
            if start and duration and duration >= 1:
                vals['date_deadline'] = fields.Datetime.to_datetime(
                    fields.Date.to_date(start) + timedelta(days=duration - 1))
        return super().create(vals_list)

    def write(self, vals):
        if {'x_abroj_date_start', 'x_abroj_duration_days', 'date_deadline'} & vals.keys():
            for task in self:
                values = dict(vals)
                start = values.get('x_abroj_date_start', task.x_abroj_date_start)
                duration = values.get('x_abroj_duration_days', task.x_abroj_duration_days)
                if start and duration and duration >= 1:
                    values['date_deadline'] = fields.Datetime.to_datetime(
                        fields.Date.to_date(start) + timedelta(days=duration - 1))
                super(ProjectTask, task).write(values)
            return True
        return super().write(vals)

    @api.constrains('x_abroj_progress')
    def _check_abroj_task_progress(self):
        for task in self:
            if not 0 <= task.x_abroj_progress <= 100:
                raise ValidationError('نسبة الإنجاز يجب أن تكون بين 0 و 100.')


class BudgetLine(models.Model):
    _name = 'abroj.project.budget.line'
    _description = 'Project budget category'
    _check_company_auto = True

    project_id = fields.Many2one('project.project', required=True, ondelete='cascade', check_company=True)
    company_id = fields.Many2one(related='project_id.company_id', store=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    name = fields.Char(string='بند التكلفة', required=True)
    budget = fields.Monetary(string='الميزانية')
    manual_actual = fields.Monetary(string='الفعلي اليدوي')
    actual = fields.Monetary(string='التكلفة الفعلية', compute='_compute_actual')
    analytic_line_ids = fields.One2many('account.analytic.line', 'abroj_budget_line_id')

    def _check_budget_manager(self):
        if not self.env.su and not self.env.user.has_group('project.group_project_manager'):
            raise AccessError('لا تملك صلاحية تعديل الميزانية.')

    @api.model_create_multi
    def create(self, vals_list):
        self._check_budget_manager()
        return super().create(vals_list)

    def write(self, vals):
        self._check_budget_manager()
        return super().write(vals)

    def unlink(self):
        self._check_budget_manager()
        return super().unlink()

    @api.depends_context('uid')
    def _compute_actual(self):
        for line in self:
            line.actual = line.manual_actual + (sum(-a.amount for a in line.analytic_line_ids if a.amount < 0) if self.env['account.analytic.line'].has_access('read') else 0)


class AnalyticLine(models.Model):
    _inherit = 'account.analytic.line'

    abroj_budget_line_id = fields.Many2one('abroj.project.budget.line', string='بند ميزانية أبرج', ondelete='set null', check_company=True)

    @api.constrains('abroj_budget_line_id', 'account_id')
    def _check_abroj_budget_account(self):
        for line in self.filtered('abroj_budget_line_id'):
            if line.account_id != line.abroj_budget_line_id.project_id.account_id:
                raise ValidationError('يجب أن يطابق الحساب التحليلي حساب المشروع.')


class Project(models.Model):
    _inherit = 'project.project'

    abroj_type = fields.Selection(TYPES, string='نوع المشروع', default='other')
    abroj_budget = fields.Monetary(string='الميزانية', currency_field='abroj_currency_id')
    abroj_contract_value = fields.Monetary(string='قيمة العقد', currency_field='abroj_currency_id')
    abroj_currency_id = fields.Many2one(related='company_id.currency_id')
    abroj_manual_progress = fields.Float(string='الإنجاز اليدوي %')
    abroj_use_manual_progress = fields.Boolean(string='استخدام الإنجاز اليدوي')
    # Managers can operate project stages even when the optional stages UI is disabled.
    stage_id = fields.Many2one(groups='project.group_project_stages,project.group_project_manager')
    abroj_closed_date = fields.Date(string='تاريخ الإغلاق')
    abroj_stage_closed = fields.Boolean(related='stage_id.fold', store=True)
    abroj_budget_line_ids = fields.One2many('abroj.project.budget.line', 'project_id', string='بنود الميزانية')

    @api.model_create_multi
    def create(self, vals_list):
        protected = {'abroj_budget', 'abroj_contract_value', 'abroj_budget_line_ids'}
        if any(protected.intersection(vals) for vals in vals_list) and not self.env.su and not self.env.user.has_group('project.group_project_manager'):
            raise AccessError('لا تملك صلاحية تعديل الميزانية أو قيمة العقد.')
        return super().create(vals_list)

    def write(self, vals):
        protected = {'abroj_budget', 'abroj_contract_value', 'abroj_budget_line_ids'}
        if protected.intersection(vals) and not self.env.su and not self.env.user.has_group('project.group_project_manager'):
            raise AccessError('لا تملك صلاحية تعديل الميزانية أو قيمة العقد.')
        return super().write(vals)

    @api.constrains('abroj_manual_progress')
    def _check_abroj_progress(self):
        for project in self:
            if not 0 <= project.abroj_manual_progress <= 100:
                raise ValidationError('نسبة الإنجاز يجب أن تكون بين 0 و 100.')

    @api.model
    def ensure_abroj_closed_stage(self):
        stages = self.env['project.project.stage']
        return stages.search([('fold', '=', True), ('company_id', '=', False)], limit=1) or stages.create({'name': 'منتهي', 'fold': True})

    def _abroj_check_close_access(self):
        self.ensure_one()
        if not self.env.user.has_group('project.group_project_manager'):
            raise AccessError('Project manager access required')
        self.check_access('write')

    def abroj_close_summary(self):
        self._abroj_check_close_access()
        data = self._abroj_data()
        subcontractors = self.env['abroj.contracting.subcontractor'].search([('project_id', '=', self.id)]) if 'abroj.contracting.subcontractor' in self.env and self.env['abroj.contracting.subcontractor'].has_access('read') else []
        drafts = self.env['abroj.contracting.voucher'].search([('project_id', '=', self.id), ('state', '=', 'draft')]) if 'abroj.contracting.voucher' in self.env and self.env['abroj.contracting.voucher'].has_access('read') else []
        return {'unfinished': [p['name'] for p in data['phases'] if not p['done']], 'receivable': data['contract'] - data['received'], 'payable': sum(sub.remaining for sub in subcontractors), 'draft_vouchers': [{'name': v.name, 'amount': v.amount} for v in drafts]}

    def abroj_set_closed(self, closed, note=''):
        self._abroj_check_close_access()
        stages = self.env['project.project.stage']
        domain = [('fold', '=', bool(closed)), '|', ('company_id', '=', False), ('company_id', '=', self.company_id.id)]
        stage = stages.search(domain, limit=1)
        if not stage:
            raise ValidationError('A suitable project stage is required. Please contact your administrator.')
        values = {'stage_id': stage.id, 'abroj_closed_date': fields.Date.context_today(self) if closed else False, 'active': True}
        if not closed and self.last_update_status == 'done':
            values['last_update_status'] = 'on_track'
        self.write(values)
        self.message_post(body=('%s%s' % ('Project closed / تم إغلاق المشروع' if closed else 'Project reopened / تم إعادة فتح المشروع', (' — ' + note.strip()) if note and note.strip() else '')))
        return True

    def _abroj_data(self, stall_days=30):
        self.ensure_one()
        today = fields.Date.context_today(self)
        tasks = self.env['project.task'].search([('project_id', '=', self.id)])
        done = tasks.filtered(lambda t: t.state in ('1_done', '1_canceled'))
        progress = self.abroj_manual_progress if self.abroj_use_manual_progress else (100 * len(done) / len(tasks) if tasks else 0)
        analytic = self.env['account.analytic.line'].search([('account_id', '=', self.account_id.id), ('amount', '<', 0)]) if self.account_id and self.env['account.analytic.line'].has_access('read') else self.env['account.analytic.line']
        actual = sum(-line.amount for line in analytic) + sum(self.abroj_budget_line_ids.mapped('manual_actual'))
        categories = [{'id': line.id, 'name': line.name, 'budget': line.budget, 'actual': line.actual, 'manual_actual': line.manual_actual} for line in self.abroj_budget_line_ids]
        vouchers = []
        if 'abroj.contracting.voucher' in self.env and self.env['abroj.contracting.voucher'].has_access('read'):
            vouchers = self.env['abroj.contracting.voucher'].search([('project_id', '=', self.id), ('state', '=', 'issued')])
        contracts = []
        if 'abroj.contracting.subcontractor' in self.env and self.env['abroj.contracting.subcontractor'].has_access('read'):
            contracts = [{'name': sub.display_name, 'partner': sub.partner_id.name, 'amount': sub.agreed_amount} for sub in self.env['abroj.contracting.subcontractor'].search([('project_id', '=', self.id)])]
        received = sum(v.amount for v in vouchers if v.kind == 'receipt')
        paid = sum(v.amount for v in vouchers if v.kind == 'payment')
        delayed_tasks = tasks.filtered(lambda t: t not in done and t.date_deadline and t.date_deadline.date() < today)
        completed = self.last_update_status == 'done' or bool(self.abroj_closed_date) or self.abroj_stage_closed
        delayed = not completed and bool(self.date and self.date < today or delayed_tasks)
        last_activity = max([self.write_date] + tasks.mapped('write_date')) if tasks else self.write_date
        stalled = not completed and (self.last_update_status in ('off_track', 'on_hold') or bool(last_activity and last_activity.date() < today - timedelta(days=stall_days)))
        phases = [{'id': t.id, 'name': t.name, 'start': str(t.x_abroj_date_start or (t.date_assign.date() if t.date_assign else '')), 'end': str(t.date_deadline.date() if t.date_deadline else ''), 'duration': t.x_abroj_duration_days, 'done': t in done, 'state': t.state, 'progress': t.x_abroj_progress, 'can_write': t.has_access('write'), 'delayed': t in delayed_tasks, 'assignee': ', '.join(t.user_ids.mapped('name'))} for t in tasks]
        return {'id': self.id, 'archived': not self.active or completed, 'can_close': self.env.user.has_group('project.group_project_manager') and self.has_access('write'), 'can_write': self.has_access('write'), 'can_create_task': self.env['project.task'].has_access('create'), 'can_edit_budget': self.env.user.has_group('project.group_project_manager') and self.has_access('write'), 'name': self.name, 'type': self.abroj_type, 'type_label': (dict(TYPES) if (self.env.lang or '').startswith('ar') else TYPES_EN).get(self.abroj_type, ''), 'status': self.last_update_status, 'status_label': (STATUS if (self.env.lang or '').startswith('ar') else STATUS_EN).get(self.last_update_status, ''), 'client': self.partner_id.name or '—', 'manager': self.user_id.name or '—', 'start': str(self.date_start or ''), 'end': str(self.date or ''), 'progress': round(progress, 1), 'budget': self.abroj_budget, 'actual': actual, 'over': max(actual - self.abroj_budget, 0), 'over_categories': sum(c['actual'] > c['budget'] for c in categories), 'contract': self.abroj_contract_value or (self.contract_value if 'contract_value' in self._fields else 0), 'received': received, 'paid': paid, 'liquidity': received - paid, 'categories': categories, 'contracts': contracts, 'phases': phases, 'delayed': delayed, 'stalled': stalled, 'completed': completed, 'vouchers': [{'name': v.name, 'kind': v.kind, 'partner': v.partner_id.name, 'amount': v.amount, 'date': str(v.date)} for v in vouchers]}

    @api.model
    def get_abroj_my_day(self):
        today = fields.Date.context_today(self)
        start = fields.Datetime.to_datetime(today)
        tomorrow = start + timedelta(days=1)
        projects = self.search([('abroj_closed_date', '=', False), ('abroj_stage_closed', '=', False), ('last_update_status', '!=', 'done')])
        tasks = self.env['project.task'].search([
            ('project_id', 'in', projects.ids), ('date_deadline', '>=', start),
            '|', ('x_abroj_date_start', '<=', today), ('date_deadline', '<', tomorrow),
        ], order='project_id, x_abroj_date_start, id')
        grouped = {}
        for task in tasks:
            project = task.project_id
            group = grouped.setdefault(project.id, {'id': project.id, 'name': project.name, 'phases': []})
            group['phases'].append({
                'id': task.id, 'name': task.name,
                'start': str(task.x_abroj_date_start or ''),
                'end': str(task.date_deadline.date()),
                'duration': task.x_abroj_duration_days,
                'assignee': ', '.join(task.user_ids.mapped('name')),
            })
        return list(grouped.values())

    @api.model
    def get_abroj_dashboard_data(self, filters=None, include_archived=False):
        filters = filters or {}
        domain = ['|', ('company_id', '=', False), ('company_id', 'in', self.env.companies.ids)]
        for key, field in [('type', 'abroj_type'), ('manager', 'user_id'), ('client', 'partner_id')]:
            if filters.get(key):
                domain.append((field, '=', filters[key]))
        if filters.get('search'):
            domain.append(('name', 'ilike', filters['search']))
        if filters.get('from'):
            domain += ['|', ('date', '=', False), ('date', '>=', filters['from'])]
        if filters.get('to'):
            domain += ['|', ('date_start', '=', False), ('date_start', '<=', filters['to'])]
        projects = self.with_context(active_test=False).search(domain) if include_archived else self.search(domain + [('abroj_closed_date', '=', False), ('abroj_stage_closed', '=', False), ('last_update_status', '!=', 'done')])
        data = [p._abroj_data() for p in projects]
        for project, item in zip(projects, data):
            item['archived'] = not project.active or item['completed']
        status = filters.get('status')
        if status in ('delayed', 'stalled', 'completed'):
            data = [p for p in data if p[status]]
        elif status == 'ongoing':
            data = [p for p in data if not p['completed']]
        elif status:
            data = [p for p in data if p['status'] == status]
        types = dict(TYPES) if (self.env.lang or '').startswith('ar') else TYPES_EN
        return {'projects': data, 'types': [{'id': k, 'name': types[k]} for k, _ in TYPES], 'managers': [{'id': p.id, 'name': p.name} for p in projects.mapped('user_id')], 'clients': [{'id': p.id, 'name': p.name} for p in projects.mapped('partner_id')]}

    @api.model
    def get_abroj_project_detail(self, project_id):
        project = self.with_context(active_test=False).search([('id', '=', project_id), '|', ('company_id', '=', False), ('company_id', 'in', self.env.companies.ids)], limit=1)
        return project._abroj_data() if project else False
