from datetime import datetime, time, timedelta
import pytz
from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import html2plaintext

RIYADH = pytz.timezone('Asia/Riyadh')


def today_riyadh():
    return datetime.now(pytz.UTC).astimezone(RIYADH).date()


class DailyReport(models.Model):
    _name = 'abroj.daily.report'
    _description = 'Daily engineer report'
    _order = 'date desc, id desc'

    engineer_id = fields.Many2one('res.users', required=True, index=True, ondelete='cascade')
    date = fields.Date(required=True, default=today_riyadh, index=True)
    state = fields.Selection([('draft', 'Draft'), ('approved', 'Approved'), ('auto_sent', 'لم يُراجع')], default='draft', required=True)
    approved_at = fields.Datetime()
    sent_at = fields.Datetime()
    line_ids = fields.One2many('abroj.daily.report.line', 'report_id')
    _engineer_date_unique = models.Constraint('unique(engineer_id, date)', 'Only one report per engineer per day.')

    def report_projects(self):
        self.ensure_one()
        projects = self.env['project.project'].sudo()
        if self.engineer_id.has_group('project.group_project_manager') or self.engineer_id.has_group('base.group_system'):
            return projects.search([])
        assigned = self.env['project.task'].sudo().search([('user_ids', 'in', self.engineer_id.id)]).mapped('project_id')
        return projects.search(['|', ('user_id', '=', self.engineer_id.id), ('id', 'in', assigned.ids)])

    def generate(self):
        self.ensure_one()
        if self.state != 'draft':
            return self
        start = RIYADH.localize(datetime.combine(self.date, time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
        end = start + timedelta(days=1)
        projects = self.report_projects()
        tasks = self.env['project.task'].sudo().search([('project_id', 'in', projects.ids)])
        all_messages = self.env['mail.message'].sudo().search([('model', '=', 'project.task'), ('res_id', 'in', tasks.ids), ('date', '>=', start), ('date', '<', end)], order='date, id')
        messages = self.env['mail.message'].sudo().search([('model', '=', 'project.task'), ('res_id', 'in', tasks.ids), ('date', '>=', start), ('date', '<', end), ('author_id', '=', self.engineer_id.partner_id.id)])
        attachments = self.env['ir.attachment'].sudo().search([('res_model', '=', 'project.task'), ('res_id', 'in', tasks.ids), ('create_date', '>=', start), ('create_date', '<', end), ('create_uid', '=', self.engineer_id.id), ('mimetype', '=like', 'image/%')])
        existing = {line.task_id.id: line for line in self.line_ids}
        seen = set()
        for task in tasks:
            task_messages = messages.filtered(lambda m: m.res_id == task.id)
            changes = all_messages.filtered(lambda m: m.res_id == task.id).mapped('tracking_value_ids').filtered(lambda v: v.field_id.name in ('date_deadline', 'x_abroj_duration_days'))
            deadlines = changes.filtered(lambda v: v.field_id.name == 'date_deadline')
            durations = changes.filtered(lambda v: v.field_id.name == 'x_abroj_duration_days')
            old = fields.Datetime.to_datetime(deadlines[0].old_value_datetime) if deadlines else False
            new = fields.Datetime.to_datetime(deadlines[-1].new_value_datetime) if deadlines else False
            old_date = pytz.UTC.localize(old).astimezone(RIYADH).date() if old else False
            new_date = pytz.UTC.localize(new).astimezone(RIYADH).date() if new else False
            delta = (new_date - old_date).days if old_date and new_date else 0
            duration_delta = durations[-1].new_value_integer - durations[0].old_value_integer if durations else 0
            kind = 'advanced' if delta < 0 else 'extended' if delta > 0 and duration_delta > 0 else 'postponed' if delta > 0 else False
            photos = attachments.filtered(lambda a: a.res_id == task.id)
            status = task.with_context(tz='Asia/Riyadh')._abroj_phase_status()['status']
            tomorrow = task.state not in ('1_done', '1_canceled') and (not task.x_abroj_date_start or task.x_abroj_date_start <= self.date + timedelta(days=1))
            if not (task_messages or changes or photos or status == 'overdue' or tomorrow):
                continue
            seen.add(task.id)
            tracking = task_messages.mapped('tracking_value_ids').filtered(lambda v: v.field_id.name == 'x_abroj_progress')
            notes, note_keys = [], set()
            for message in task_messages:
                if message.message_type != 'comment' or message.subtype_id not in (self.env.ref('mail.mt_note'), self.env.ref('mail.mt_comment')):
                    continue
                note = ' '.join(html2plaintext(message.body or '').split())
                key = note.casefold()
                if not note or key in note_keys or key in ('تم إنشاء مهمة جديدة', 'task created'):
                    continue
                note_keys.add(key)
                notes.append(note)
            vals = {'has_activity': bool(notes or tracking or changes or photos), 'project_id': task.project_id.id, 'task_id': task.id, 'progress_from': tracking[0].old_value_float if tracking else task.x_abroj_progress, 'progress_to': task.x_abroj_progress, 'status': 'late' if status == 'overdue' else status, 'notes': '\n'.join(notes), 'photo_count': len(photos), 'deadline_old': old_date, 'deadline_new': new_date, 'deadline_change_days': abs(delta), 'change_kind': kind}
            if task.id in existing:
                existing[task.id].write(vals)
            else:
                vals.update(report_id=self.id, tomorrow_plan=task.name if tomorrow else '')
                self.env['abroj.daily.report.line'].sudo().create(vals)
        self.line_ids.filtered(lambda line: line.task_id.id not in seen).unlink()
        return self

    def financial_operations(self, projects):
        """Read current financial records for the report day and permitted projects."""
        self.ensure_one()
        start = RIYADH.localize(datetime.combine(self.date, time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
        end = start + timedelta(days=1)
        operations = []

        def add(project, sentence):
            if project.id in projects.ids:
                operations.append({'project_id': project.id, 'project': project.name, 'sentence': sentence})

        def amount(value):
            return format(value, ',.2f').rstrip('0').rstrip('.')

        vouchers = self.env['abroj.contracting.voucher'].sudo().search([
            ('project_id', 'in', projects.ids), ('state', '=', 'issued'),
            ('issued_at', '>=', start), ('issued_at', '<', end)])
        for voucher in vouchers:
            verb = 'استلام' if voucher.kind == 'receipt' else 'صرف'
            add(voucher.project_id, 'تم %s مبلغ %s ريال — %s' % (verb, amount(voucher.amount), voucher.project_id.name))
        linked_payments = self.env['abroj.contracting.voucher'].sudo().search([('payment_id', '!=', False)]).mapped('payment_id')
        payments = self.env['account.payment'].sudo().search([('date', '=', self.date), ('state', 'not in', ('draft', 'canceled', 'cancelled'))]) - linked_payments
        for payment in payments:
            payment_projects = payment.project_id if 'project_id' in payment._fields and payment.project_id else self.env['project.project']
            if payment.move_id:
                payment_projects |= payment.move_id._abroj_projects()
            for project in payment_projects & projects:
                verb = 'استلام' if payment.payment_type == 'inbound' else 'صرف'
                add(project, 'تم %s مبلغ %s ريال — %s' % (verb, amount(payment.amount), project.name))
        contracts = self.env['abroj.contracting.subcontractor'].sudo().search([
            ('project_id', 'in', projects.ids), ('create_date', '>=', start), ('create_date', '<', end)])
        for contract in contracts:
            add(contract.project_id, 'تم إصدار عقد %s — %s' % (contract.partner_id.name, contract.project_id.name))
        moves = self.env['account.move'].sudo().search([('state', '=', 'posted'), ('date', '=', self.date), ('move_type', 'in', ('out_invoice', 'out_refund', 'in_invoice', 'in_refund', 'out_receipt', 'in_receipt'))])
        for move in moves:
            for project in move._abroj_projects() & projects:
                add(project, 'تم ترحيل فاتورة %s — %s' % (move.name, project.name))
        return operations

    @api.model
    def cron_auto_send(self):
        day = today_riyadh()
        projects = self.env['project.project'].sudo().search([('user_id', '!=', False)])
        for user in projects.mapped('user_id').filtered(lambda u: not u.share and not u.has_group('base.group_system') and not u.has_group('project.group_project_manager')):
            report = self.sudo().search([('engineer_id', '=', user.id), ('date', '=', day)], limit=1)
            if not report:
                report = self.sudo().create({'engineer_id': user.id, 'date': day})
            if report.state == 'draft':
                report.generate()
                report.write({'state': 'auto_sent', 'sent_at': fields.Datetime.now()})


class DailyReportLine(models.Model):
    _name = 'abroj.daily.report.line'
    _description = 'Daily report phase'
    _order = 'project_id, id'
    report_id = fields.Many2one('abroj.daily.report', required=True, ondelete='cascade', index=True)
    project_id = fields.Many2one('project.project', required=True, ondelete='cascade')
    analytic_account_id = fields.Many2one('account.analytic.account', string='الحساب التحليلي', related='project_id.account_id', store=True, readonly=True, index=True)
    task_id = fields.Many2one('project.task', required=True, ondelete='cascade')
    has_activity = fields.Boolean()
    progress_from = fields.Float()
    progress_to = fields.Float()
    status = fields.Selection([('late', 'Late'), ('on_time', 'On time'), ('done', 'Done')], required=True)
    notes = fields.Text()
    photo_count = fields.Integer()
    tomorrow_plan = fields.Text()

    deadline_old = fields.Date()
    deadline_new = fields.Date()
    deadline_change_days = fields.Integer()
    change_kind = fields.Selection([('extended', 'Extended'), ('postponed', 'Postponed'), ('advanced', 'Advanced')])
