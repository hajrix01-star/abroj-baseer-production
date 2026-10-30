from unittest.mock import patch
from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'abroj_contracting')
class AbrojContractingCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['project.project'].create({'name': 'مشروع اختبار', 'company_id': cls.env.company.id, 'contract_value': 10000, 'estimated_cost': 6000})
        cls.partner = cls.env['res.partner'].create({'name': 'مقاول اختبار'})
        cls.sub = cls.env['abroj.contracting.subcontractor'].create({'project_id': cls.project.id, 'partner_id': cls.partner.id, 'agreed_amount': 4000})
        cls.agent = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'وكيل اختبار', 'login': 'abroj-contracting-test-agent',
            'company_id': cls.env.company.id, 'company_ids': [Command.set(cls.env.company.ids)],
            'group_ids': [Command.set([cls.env.ref('abroj_contracting.group_extraction_agent').id])],
        })
        cls.env['ir.config_parameter'].sudo().set_param('abroj_contracting.agent_webhook_url', '')

    def voucher(self, **extra):
        vals = {'project_id': self.project.id, 'partner_id': self.partner.id, 'subcontractor_id': self.sub.id, 'amount': 1000}
        vals.update(extra)
        return self.env['abroj.contracting.voucher'].create(vals)

    def test_balances_and_profit(self):
        self.voucher().action_issue()
        self.voucher(kind='receipt', amount=200).action_issue()
        invoice = self.env['abroj.contracting.invoice'].create({'project_id': self.project.id, 'subcontractor_id': self.sub.id, 'number': 'INV1', 'amount': 3000})
        self.assertEqual(self.project.total_costs, 4000)
        invoice.action_confirm()
        self.assertEqual(self.sub.remaining, 3200)
        self.assertEqual(self.sub.invoiced, 3000)
        self.assertEqual(self.project.total_costs, 4000)
        self.assertEqual(self.project.profit, 6000)
        self.assertEqual(self.project.expected_profit, 4000)
        self.assertEqual(self.project.remaining, 9800)
        self.assertEqual(self.project.cash_balance, -800)

    def test_issue_and_cancel(self):
        v = self.voucher()
        self.assertEqual(v.name, '/')
        v.action_issue()
        self.assertEqual(v.state, 'issued')
        self.assertTrue(v.name.startswith('PAY/'))
        self.assertFalse(v.payment_id)
        with self.assertRaises(UserError):
            v.action_issue()
        with self.assertRaises(UserError):
            v.write({'amount': 5})
        v.action_cancel()
        self.assertEqual(self.project.total_paid, 0)
        self.assertEqual(self.sub.remaining, 4000)

    def test_agent_issue_denied(self):
        v = self.voucher().with_user(self.agent)
        v.write({'memo': 'مسودة مستخرجة'})
        with self.assertRaises(AccessError):
            v.action_issue()
        with self.assertRaises(AccessError):
            v.write({'state': 'issued'})
        with self.assertRaises(AccessError):
            self.voucher(state='issued')

    def test_agent_move_post_denied(self):
        journal = self.env['account.journal'].create({'name': 'اختبار المقاولات', 'code': 'ACT', 'type': 'general', 'company_id': self.env.company.id})
        move = self.env['account.move'].create({'journal_id': journal.id})
        with self.assertRaises(AccessError):
            move.with_user(self.agent).action_post()
        self.assertEqual(move.state, 'draft')

    def test_agent_payment_and_purchase_denied(self):
        with self.assertRaises(AccessError):
            self.env['account.payment'].with_user(self.agent).action_post()
        with self.assertRaises(AccessError):
            self.env['account.payment'].with_user(self.agent).action_validate()
        with self.assertRaises(AccessError):
            self.env['purchase.order'].with_user(self.agent).button_confirm()

    def test_agent_invoice_confirm_denied(self):
        invoice = self.env['abroj.contracting.invoice'].with_user(self.agent).create({'project_id': self.project.id, 'subcontractor_id': self.sub.id, 'number': 'DRAFT', 'amount': 100})
        with self.assertRaises(AccessError):
            invoice.action_confirm()

    def test_costs_and_duration(self):
        self.project.write({'contracting_start': '2026-01-01', 'contracting_end': '2026-01-31'})
        self.assertEqual(self.project.duration_days, 30)
        c = self.env['abroj.contracting.cost'].create({'project_id': self.project.id, 'name': 'مواد', 'amount': 500})
        c.action_confirm()
        self.assertEqual(self.project.total_costs, 4500)
        self.assertEqual(self.project.profit, 5500)

    def test_mismatched_subcontractor(self):
        other = self.env['project.project'].create({'name': 'مشروع آخر', 'company_id': self.env.company.id})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.voucher(project_id=other.id)

    def test_company_isolation(self):
        company = self.env['res.company'].create({'name': 'شركة معزولة'})
        project = self.env['project.project'].create({'name': 'خاص', 'company_id': company.id})
        inbox = self.env['abroj.contracting.inbox'].create({'project_id': project.id, 'filename': 'private.pdf'})
        self.assertFalse(self.env['abroj.contracting.inbox'].with_user(self.agent).search([('id', '=', inbox.id)]))
        with self.assertRaises(AccessError):
            inbox.with_user(self.agent).read(['filename'])

    def test_webhook_unset(self):
        inbox = self.env['abroj.contracting.inbox']
        with patch.object(type(inbox), '_send_webhook') as sender, patch.object(type(self.cr.postcommit), 'add') as add:
            inbox.create({'project_id': self.project.id, 'filename': 'note'})
            add.assert_not_called()
            sender.assert_not_called()

    def test_webhook_metadata_after_commit(self):
        self.env['ir.config_parameter'].sudo().set_param('abroj_contracting.agent_webhook_url', 'https://example.invalid/inbox')
        inbox = self.env['abroj.contracting.inbox']
        callbacks = []
        with patch.object(type(inbox), '_send_webhook') as sender, patch.object(type(self.cr.postcommit), 'add', side_effect=callbacks.append):
            record = inbox.create({'project_id': self.project.id, 'filename': 'invoice.pdf', 'mimetype': 'application/pdf', 'file': 'YWJj'})
            sender.assert_not_called()
            self.assertEqual(len(callbacks), 1)
            callbacks[0]()
            payload = sender.call_args.args[-1]
            self.assertEqual(payload['id'], record.id)
            self.assertEqual(set(payload), {'id', 'model', 'project_id', 'project_name', 'filename', 'mimetype', 'state', 'create_uid', 'create_date'})
            self.assertNotIn('YWJj', str(payload))

    def test_webhook_failure_never_raises(self):
        inbox = self.env['abroj.contracting.inbox']
        with patch('odoo.addons.abroj_contracting.models.inbox.requests.post', side_effect=RuntimeError('offline')):
            inbox._send_webhook('https://example.invalid', '', {'id': 1})

    def test_project_note_posts_chatter(self):
        before = self.project.message_ids
        note = self.env['abroj.contracting.project.note'].create({
            'project_id': self.project.id, 'body': 'تقدم العمل <جاهز>',
            'note_type': 'audio', 'attachment': 'YWJj',
            'filename': 'voice.ogg', 'mimetype': 'audio/ogg',
        })
        messages = self.project.message_ids - before
        self.assertEqual(len(messages), 1)
        self.assertIn('تقدم العمل &lt;جاهز&gt;', str(messages.body))
        attachment = messages.attachment_ids
        self.assertEqual(len(attachment), 1)
        self.assertEqual((attachment.res_model, attachment.res_id), ('project.project', self.project.id))
        self.assertEqual(attachment.datas, b'YWJj')
        self.assertEqual(attachment.name, 'voice.ogg')
        self.assertEqual(note.author_id, self.env.user)
        self.assertEqual(self.project.project_note_count, 1)
        # Empty notes still leave a meaningful chatter entry.
        self.env['abroj.contracting.project.note'].create({'project_id': self.project.id})
        self.assertEqual(len(self.project.message_ids - before), 2)

    def test_inbox_project_note_exactly_once(self):
        inbox = self.env['abroj.contracting.inbox'].with_user(self.agent).create({
            'project_id': self.project.id, 'filename': 'voice.ogg',
            'mimetype': 'audio/ogg', 'file': 'YWJj', 'note': 'ملاحظة صوتية',
        })
        note = inbox.project_note_ids
        self.assertEqual(len(note), 1)
        self.assertEqual(note.project_id, self.project)
        self.assertEqual(note.note_type, 'audio')
        self.assertEqual(note.body, inbox.note)
        self.assertEqual(note.attachment, inbox.file)
        self.assertEqual(note.author_id, self.agent)
        inbox.write({'project_id': self.project.id})
        inbox.write({'state': 'analyzed'})
        self.assertEqual(inbox.project_note_ids, note)
        self.assertEqual(self.env['abroj.contracting.project.note'].search_count([('inbox_id', '=', inbox.id)]), 1)

    def test_inbox_project_assigned_later(self):
        inbox = self.env['abroj.contracting.inbox'].with_user(self.agent).create({
            'filename': 'ملاحظة', 'note': 'زيارة الموقع',
        })
        self.assertFalse(inbox.project_note_ids)
        self.assertEqual(inbox.company_id, self.env.company)
        inbox.write({'project_id': self.project.id})
        self.assertEqual(len(inbox.project_note_ids), 1)
        self.assertEqual(inbox.project_note_ids.project_id, self.project)
        self.assertEqual(inbox.project_note_ids.note_type, 'text')
        self.assertEqual(inbox.project_note_ids.body, 'زيارة الموقع')
        inbox.write({'project_id': self.project.id})
        self.assertEqual(len(inbox.project_note_ids), 1)

    def material_invoice(self, amount=80000, **extra):
        vals = dict(project_id=self.project.id, subcontractor_id=self.sub.id,
                    number='MAT', amount=amount, invoice_kind='materials_company',
                    buyer_vat=self.env.company.vat)
        vals.update(extra)
        return self.env['abroj.contracting.invoice'].create(vals)

    def test_materials_settlement(self):
        self.env.company.vat = 'TEST-VAT'
        self.sub.agreed_amount = 100000
        invoice = self.material_invoice()
        self.assertEqual(self.sub.materials_total, 0)
        invoice.action_confirm()
        self.assertEqual(self.sub.materials_total, 80000)
        self.assertEqual(self.project.materials_purchase_total, 80000)
        self.assertEqual(self.sub.remaining, 20000)
        self.assertEqual(self.project.total_costs, 100000)
        self.voucher(amount=20000).action_issue()
        self.assertEqual(self.sub.remaining, 0)
        self.assertEqual(self.project.total_costs, 100000)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.material_invoice(amount=20001).action_confirm()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.sub.agreed_amount = 79999
        with self.assertRaises(UserError):
            invoice.write({'amount': 1})
        action = self.sub.with_context(discard_logo_check=True).action_settlement()
        self.assertEqual(action['report_name'], 'abroj_contracting.settlement')
        html, _ = self.env['ir.actions.report']._render_qweb_html(action['report_name'], self.sub.ids)
        self.assertIn(b'80000', html.replace(b',', b''))

    def test_supporting_materials_and_vat(self):
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.material_invoice(amount=100, buyer_vat='wrong').action_confirm()
        attachment = self.env['ir.attachment'].create({'name': 'material.pdf', 'datas': 'YWJj'})
        invoice = self.material_invoice(amount=90000, invoice_kind='materials_subcontractor',
                                        attachment_ids=[Command.set(attachment.ids)])
        invoice.action_confirm()
        self.assertEqual(self.sub.materials_total, 0)
        self.assertEqual(self.sub.remaining, 4000)
        self.assertEqual(self.project.total_costs, 4000)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.sub.retention_percent = 101
