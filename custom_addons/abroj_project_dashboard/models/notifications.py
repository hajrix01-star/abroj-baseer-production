import json

from odoo import api, fields, models
from odoo.tools import html2plaintext


def _amount(value):
    return ('%s' % format(value, ',.2f')).rstrip('0').rstrip('.')


class Project(models.Model):
    _inherit = 'project.project'

    def _abroj_notify(self, body, category='document'):
        params = self.env['ir.config_parameter'].sudo()
        users = self.env['res.users'].sudo()

        def configured(key, group):
            value = params.get_param(key, default=None)
            if value is not None and value is not False:
                try:
                    ids = json.loads(value)
                    if not isinstance(ids, list):
                        ids = str(value).split(',')
                    ids = [int(x) for x in ids]
                except (ValueError, TypeError):
                    ids = [int(x.strip()) for x in str(value).split(',') if x.strip().isdigit()]
                return users.browse(ids).exists().filtered(lambda u: u.active and not u.share)
            ref = self.env.ref(group, raise_if_not_found=False)
            return users.search([('group_ids', 'in', ref.id), ('active', '=', True), ('share', '=', False)]) if ref else users.browse()

        owners = configured('abroj.notify_owner_ids', 'base.group_system').filtered(lambda u: u.id != 1 and u.login != '__system__')
        accountants = configured('abroj.notify_accountant_ids', 'account.group_account_manager')
        for project in self:
            partners = (owners | accountants | project.user_id.sudo()).mapped('partner_id')
            project.sudo().message_subscribe(partner_ids=partners.ids)
            msg = project.sudo().with_context(mail_notify_author=True, mail_notify_force_send=False, abroj_notification_partner_ids=partners.ids).message_post(
                body=body, message_type='comment', subtype_xmlid='mail.mt_comment', partner_ids=partners.ids)
            msg.sudo().write({'abroj_notification_category': category})
            # Ensure the native bell has an inbox notification even for users whose
            # standard mail preference is email. Keep one notification per partner.
            notifications = self.env['mail.notification'].sudo().search([('mail_message_id', '=', msg.id), ('res_partner_id', 'in', partners.ids)])
            notifications.write({'notification_type': 'inbox', 'notification_status': 'sent', 'is_read': False})
            missing = partners - notifications.mapped('res_partner_id')
            self.env['mail.notification'].sudo().create([{'mail_message_id': msg.id, 'res_partner_id': p.id, 'notification_type': 'inbox', 'notification_status': 'sent'} for p in missing])
        return True

    def _notify_get_recipients(self, message, msg_vals=False, **kwargs):
        recipients = super()._notify_get_recipients(message, msg_vals=msg_vals, **kwargs)
        ids = self.env.context.get('abroj_notification_partner_ids')
        if ids is not None:
            recipients = [dict(recipient, notif='inbox') for recipient in recipients if recipient.get('id') in ids]
        return recipients

    @api.model
    def _abroj_notification_feed(self, message_id=None, mark=False):
        projects = self.with_context(active_test=False).search(self._abroj_scope_domain())
        domain = [('res_partner_id', '=', self.env.user.partner_id.id), ('notification_type', '=', 'inbox'), ('is_read', '=', False), ('mail_message_id.model', '=', 'project.project'), ('mail_message_id.res_id', 'in', projects.ids), ('mail_message_id.abroj_notification_category', '!=', False)]
        notifications = self.env['mail.notification'].sudo().search(domain, order='id desc')
        if mark:
            selected = notifications.filtered(lambda n: n.mail_message_id.id == int(message_id)) if message_id else notifications
            selected.write({'is_read': True})
            return {'count': len(notifications - selected)}
        return {'count': len(notifications), 'items': [{'id': n.mail_message_id.id, 'body': html2plaintext(n.mail_message_id.body or '').strip(), 'date': fields.Datetime.to_string(n.mail_message_id.date), 'category': n.mail_message_id.abroj_notification_category} for n in notifications[:100]]}


class MailMessage(models.Model):
    _inherit = 'mail.message'
    abroj_notification_category = fields.Selection([('done', 'Done'), ('overdue', 'Overdue'), ('financial', 'Financial'), ('document', 'Document')], index=True)


class Task(models.Model):
    _inherit = 'project.task'
    abroj_overdue_notified = fields.Boolean(copy=False)

    def write(self, vals):
        pending = self.filtered(lambda t: t.state != '1_done') if vals.get('state') == '1_done' else self.browse()
        result = super().write(vals)
        for task in pending.filtered('project_id'):
            task.project_id._abroj_notify('تم إنجاز مرحلة %s ✓ — %s' % (task.name, task.project_id.name), 'done')
        return result

    @api.model
    def _cron_abroj_overdue(self):
        tasks = self.sudo().search([('project_id', '!=', False), ('date_deadline', '<', fields.Datetime.now()), ('state', 'not in', ('1_done', '1_canceled')), ('abroj_overdue_notified', '=', False)])
        for task in tasks:
            self.env.cr.execute('SELECT id FROM project_task WHERE id = %s FOR UPDATE', [task.id])
            task.invalidate_recordset(['abroj_overdue_notified'])
            days = task._abroj_phase_status()['overdue_days']
            if not task.abroj_overdue_notified and days:
                task.project_id._abroj_notify('تأخير: %s — %s (%s أيام)' % (task.name, task.project_id.name, days), 'overdue')
                task.abroj_overdue_notified = True


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _abroj_projects(self):
        projects = self.env['project.project']
        for move in self:
            if 'project_id' in move._fields and move.project_id:
                projects |= move.project_id
            projects |= self.env['abroj.contracting.inbox'].sudo().search([('abroj_invoice_bill_id', '=', move.id)]).mapped('project_id')
            account_ids = set()
            for line in move.line_ids:
                for key in (line.analytic_distribution or {}):
                    account_ids.update(int(part) for part in key.split(',') if part.isdigit())
            if account_ids:
                projects |= projects.sudo().search([('account_id', 'in', list(account_ids))])
        return projects

    def action_post(self):
        pending = self.filtered(lambda m: m.state != 'posted' and m.is_invoice(include_receipts=True))
        result = super().action_post()
        for move in pending.filtered(lambda m: m.state == 'posted'):
            for project in move._abroj_projects():
                project._abroj_notify('تم ترحيل فاتورة %s — %s' % (move.name, project.name), 'financial')
        return result


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    def action_post(self):
        pending = self.filtered(lambda p: p.state == 'draft' and p.payment_type == 'inbound')
        result = super().action_post()
        for payment in pending if not self.env.context.get('abroj_voucher_payment') else self.browse():
            projects = payment.project_id if 'project_id' in payment._fields and payment.project_id else self.env['project.project']
            if payment.move_id:
                projects |= payment.move_id._abroj_projects()
            for project in projects:
                project._abroj_notify('تم استلام مبلغ %s ريال — %s' % (_amount(payment.amount), project.name), 'financial')
        return result


class Subcontractor(models.Model):
    _inherit = 'abroj.contracting.subcontractor'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            record.project_id._abroj_notify('تم إنشاء عقد — %s' % record.project_id.name)
        return records


class Voucher(models.Model):
    _inherit = 'abroj.contracting.voucher'

    def action_issue(self):
        result = super().action_issue()
        for voucher in self:
            text = 'تم استلام مبلغ %s ريال' % _amount(voucher.amount) if voucher.kind == 'receipt' else 'تم إصدار سند صرف بمبلغ %s ريال' % _amount(voucher.amount)
            voucher.project_id._abroj_notify('%s — %s' % (text, voucher.project_id.name), 'financial')
        return result


    def action_accounting_approve(self):
        return super(Voucher, self.with_context(abroj_voucher_payment=True)).action_accounting_approve()


class Promissory(models.Model):
    _inherit = 'abroj.promissory.note'

    def action_issue(self):
        result = super().action_issue()
        for note in self:
            note.project_id._abroj_notify('تم إصدار سند أمر — %s' % note.project_id.name, 'financial')
        return result


class Report(models.Model):
    _inherit = 'ir.actions.report'

    def _render_qweb_pdf(self, report_ref, res_ids=None, data=None):
        result = super()._render_qweb_pdf(report_ref, res_ids=res_ids, data=data)
        report = self._get_report(report_ref)
        if report.report_name in ('abroj_contracting.agreement', 'abroj_contracting.subcontract'):
            model = 'project.project' if report.report_name.endswith('.agreement') else 'abroj.contracting.subcontractor'
            for record in self.env[model].browse(res_ids or []).exists():
                project = record if model == 'project.project' else record.project_id
                project._abroj_notify('تم طباعة عقد — %s' % project.name)
        return result


class Settings(models.TransientModel):
    _inherit = 'res.config.settings'

    abroj_notify_owner_ids = fields.Char(string='Notification owner user IDs', config_parameter='abroj.notify_owner_ids', help='Comma-separated user IDs. Leave unset to use administrators.')
    abroj_notify_accountant_ids = fields.Char(string='Notification accountant user IDs', config_parameter='abroj.notify_accountant_ids', help='Comma-separated user IDs. Leave unset to use accounting managers.')
