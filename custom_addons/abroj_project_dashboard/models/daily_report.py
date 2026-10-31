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

    def generate(self):
        self.ensure_one()
        if self.state != 'draft':
            return self
        start = RIYADH.localize(datetime.combine(self.date, time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
        end = start + timedelta(days=1)
        projects = self.env['project.project'].sudo().search([('user_id', '=', self.engineer_id.id)])
        tasks = self.env['project.task'].sudo().search([('project_id', 'in', projects.ids)])
        messages = self.env['mail.message'].sudo().search([('model', '=', 'project.task'), ('res_id', 'in', tasks.ids), ('date', '>=', start), ('date', '<', end), ('author_id', '=', self.engineer_id.partner_id.id)])
        attachments = self.env['ir.attachment'].sudo().search([('res_model', '=', 'project.task'), ('res_id', 'in', tasks.ids), ('create_date', '>=', start), ('create_date', '<', end), ('create_uid', '=', self.engineer_id.id), ('mimetype', '=like', 'image/%')])
        existing = {line.task_id.id: line for line in self.line_ids}
        seen = set()
        for task in tasks:
            task_messages = messages.filtered(lambda m: m.res_id == task.id)
            photos = attachments.filtered(lambda a: a.res_id == task.id)
            status = task.with_context(tz='Asia/Riyadh')._abroj_phase_status()['status']
            tomorrow = task.state not in ('1_done', '1_canceled') and (not task.x_abroj_date_start or task.x_abroj_date_start <= self.date + timedelta(days=1))
            if not (task_messages or photos or status == 'overdue' or tomorrow):
                continue
            seen.add(task.id)
            tracking = task_messages.mapped('tracking_value_ids').filtered(lambda v: v.field_id.name == 'x_abroj_progress')
            vals = {'project_id': task.project_id.id, 'task_id': task.id, 'progress_from': tracking[0].old_value_float if tracking else task.x_abroj_progress, 'progress_to': task.x_abroj_progress, 'status': 'late' if status == 'overdue' else status, 'notes': '\n'.join(html2plaintext(m.body or '').strip() for m in task_messages if m.body), 'photo_count': len(photos)}
            if task.id in existing:
                existing[task.id].write(vals)
            else:
                vals.update(report_id=self.id, tomorrow_plan=task.name if tomorrow else '')
                self.env['abroj.daily.report.line'].sudo().create(vals)
        self.line_ids.filtered(lambda line: line.task_id.id not in seen).unlink()
        return self

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
    task_id = fields.Many2one('project.task', required=True, ondelete='cascade')
    progress_from = fields.Float()
    progress_to = fields.Float()
    status = fields.Selection([('late', 'Late'), ('on_time', 'On time'), ('done', 'Done')], required=True)
    notes = fields.Text()
    photo_count = fields.Integer()
    tomorrow_plan = fields.Text()
