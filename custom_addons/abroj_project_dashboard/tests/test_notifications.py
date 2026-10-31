from datetime import timedelta
from odoo import Command, fields
from odoo.tests import TransactionCase


class NotificationsCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        groups = [cls.env.ref('base.group_user').id, cls.env.ref('project.group_project_user').id]
        cls.engineer = cls.env['res.users'].create({'name': 'Notification engineer', 'login': 'notification_engineer', 'group_ids': [Command.set(groups)]})
        cls.other = cls.env['res.users'].create({'name': 'Notification owner', 'login': 'notification_owner', 'group_ids': [Command.set(groups)]})
        cls.accountant = cls.env['res.users'].create({'name': 'Notification accountant', 'login': 'notification_accountant', 'group_ids': [Command.set(groups)]})
        cls.partner = cls.env['res.partner'].create({'name': 'Notification partner'})
        cls.project = cls.env['project.project'].create({'name': 'Notification project', 'user_id': cls.engineer.id, 'company_id': cls.env.company.id, 'partner_id': cls.partner.id})
        cls.env['ir.config_parameter'].sudo().set_param('abroj.notify_owner_ids', str(cls.other.id))
        cls.env['ir.config_parameter'].sudo().set_param('abroj.notify_accountant_ids', str(cls.accountant.id))

    def messages(self, project=None):
        return self.env['mail.message'].sudo().search([('model', '=', 'project.project'), ('res_id', '=', (project or self.project).id), ('abroj_notification_category', '!=', False)])

    def test_recipients_and_scope_and_read(self):
        self.project._abroj_notify('مرحبا', 'done')
        msg = self.messages()[-1]
        notifications = self.env['mail.notification'].sudo().search([('mail_message_id', '=', msg.id), ('notification_type', '=', 'inbox')])
        self.assertTrue({self.engineer.partner_id.id, self.other.partner_id.id} <= set(notifications.mapped('res_partner_id').ids))
        self.assertTrue({self.engineer.partner_id.id, self.other.partner_id.id} <= set(self.project.message_partner_ids.ids))
        hidden = self.env['project.project'].create({'name': 'Hidden notification', 'user_id': self.other.id})
        hidden._abroj_notify('hidden')
        feed = self.env['project.project'].with_user(self.engineer)._abroj_notification_feed()
        self.assertIn(msg.id, [row['id'] for row in feed['items']])
        self.assertNotIn(self.messages(hidden).id, [row['id'] for row in feed['items']])
        self.env['project.project'].with_user(self.engineer)._abroj_notification_feed(msg.id, mark=True)
        self.assertNotIn(msg.id, [row['id'] for row in self.env['project.project'].with_user(self.engineer)._abroj_notification_feed()['items']])
        self.assertFalse(notifications.filtered(lambda n: n.res_partner_id == self.other.partner_id).is_read)

    def test_phase_and_overdue_once(self):
        task = self.env['project.task'].create({'name': 'Phase', 'project_id': self.project.id, 'date_deadline': fields.Datetime.now() - timedelta(days=3)})
        task._cron_abroj_overdue()
        task._cron_abroj_overdue()
        self.assertEqual(len(self.messages().filtered(lambda m: m.abroj_notification_category == 'overdue')), 1)
        task.write({'state': '1_done'})
        task.write({'state': '1_done'})
        self.assertEqual(len(self.messages().filtered(lambda m: m.abroj_notification_category == 'done')), 1)

    def test_contract_vouchers_and_promissory(self):
        sub = self.env['abroj.contracting.subcontractor'].create({'project_id': self.project.id, 'partner_id': self.partner.id, 'agreed_amount': 50000})
        for kind in ('receipt', 'payment'):
            voucher = self.env['abroj.contracting.voucher'].create({'project_id': self.project.id, 'partner_id': self.partner.id, 'kind': kind, 'amount': 15000, **({'subcontractor_id': sub.id} if kind == 'payment' else {})})
            voucher.action_issue()
        note = self.env['abroj.promissory.note'].create({'project_id': self.project.id, 'partner_id': self.partner.id, 'amount': 100, 'due_date': fields.Date.today()})
        note.action_issue()
        messages = self.messages()
        self.assertEqual(len(messages), 4)
        self.assertTrue(any('15,000' in m.body for m in messages))

    def assert_notification(self, text, category):
        message = self.messages().filtered(lambda m: text in m.body)
        self.assertEqual(len(message), 1)
        self.assertEqual(message.abroj_notification_category, category)
        recipients = self.env['mail.notification'].sudo().search([
            ('mail_message_id', '=', message.id), ('notification_type', '=', 'inbox')
        ]).mapped('res_partner_id')
        self.assertTrue({self.engineer.partner_id.id, self.other.partner_id.id, self.accountant.partner_id.id} <= set(recipients.ids))

    def test_invoice_posting_notification(self):
        receivable = self.env['account.account'].create({'name': 'Notification receivable', 'code': 'NOTREC', 'account_type': 'asset_receivable', 'reconcile': True})
        self.partner.property_account_receivable_id = receivable
        account = self.env['account.account'].create({'name': 'Notification revenue', 'code': 'NOTREV', 'account_type': 'income'})
        journal = self.env['account.journal'].create({'name': 'Notification sales', 'code': 'NTS', 'type': 'sale'})
        analytic = self.env['account.analytic.account'].create({'name': 'Notification analytic', 'plan_id': self.env.ref('analytic.analytic_plan_projects').id})
        self.project.account_id = analytic
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': self.partner.id, 'journal_id': journal.id,
            'invoice_line_ids': [Command.create({'name': 'Work', 'quantity': 1, 'price_unit': 100, 'account_id': account.id, 'analytic_distribution': {str(analytic.id): 100}})],
        })
        invoice.action_post()
        self.assert_notification('تم ترحيل فاتورة', 'financial')

    def test_native_payment_notification(self):
        from unittest.mock import patch
        journal = self.env['account.journal'].create({'name': 'Notification bank', 'code': 'NTB', 'type': 'bank'})
        receivable = self.env['account.account'].create({'name': 'Payment receivable', 'code': 'PAYREC', 'account_type': 'asset_receivable', 'reconcile': True})
        outstanding = self.env['account.account'].create({'name': 'Payment outstanding', 'code': 'PAYOUT', 'account_type': 'asset_current'})
        self.partner.property_account_receivable_id = receivable
        journal.inbound_payment_method_line_ids.payment_account_id = outstanding
        payment = self.env['account.payment'].create({'payment_type': 'inbound', 'partner_type': 'customer', 'partner_id': self.partner.id, 'amount': 150, 'journal_id': journal.id})
        # Link the native payment's accounting move to a project through the same
        # resolver used for analytic and inbox links.
        with patch.object(type(self.env['account.move']), '_abroj_projects', return_value=self.project):
            payment.action_post()
        self.assert_notification('تم استلام مبلغ 150', 'financial')
