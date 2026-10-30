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

    def accountant(self, group='account.group_account_invoice'):
        return self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'محاسب اختبار', 'login': 'abroj-accountant-' + group,
            'company_id': self.env.company.id, 'company_ids': [Command.set(self.env.company.ids)],
            'group_ids': [Command.set([self.env.ref(group).id])],
        })

    def test_accounting_approval_permissions(self):
        accountant = self.accountant()
        voucher = self.voucher()
        with self.assertRaises(UserError):
            voucher.with_user(accountant).action_accounting_approve()
        voucher.with_user(accountant).action_issue()
        with self.assertRaises(AccessError):
            voucher.with_user(accountant).action_accounting_approve()
        user = self.accountant('base.group_user')
        with self.assertRaises(AccessError):
            voucher.with_user(user).action_accounting_approve()
        self.agent.group_ids = [Command.link(self.env.ref('account.group_account_manager').id)]
        with self.assertRaises(AccessError):
            voucher.with_user(self.agent).action_accounting_approve()
        with self.assertRaises(AccessError):
            voucher.with_user(self.agent).sudo().action_accounting_approve()
        with self.assertRaises(AccessError):
            voucher.write({'payment_id': False})
        self.assertFalse(voucher.payment_id)

    def test_accounting_payment_and_receipt(self):
        accountant = self.accountant()
        plan = self.env['account.analytic.plan'].create({'name': 'اختبار المشاريع'})
        self.project.account_id = self.env['account.analytic.account'].create({
            'name': 'حساب المشروع', 'plan_id': plan.id, 'company_id': self.env.company.id,
        })
        accounts = {}
        for suffix, kind in [('1', 'asset_receivable'), ('2', 'liability_payable'), ('3', 'asset_current')]:
            accounts[kind] = self.env['account.account'].create({
                'name': 'اختبار ' + kind, 'code': 'ABR544' + suffix,
                'account_type': kind, 'reconcile': True,
            })
        self.partner.property_account_receivable_id = accounts['asset_receivable']
        self.partner.property_account_payable_id = accounts['liability_payable']
        journal = self.env['account.journal'].create({
            'name': 'دفتر الاختبار', 'code': 'AB54', 'type': 'bank',
            'company_id': self.env.company.id,
        })
        (journal.inbound_payment_method_line_ids | journal.outbound_payment_method_line_ids).payment_account_id = accounts['asset_current']
        manager = self.accountant('account.group_account_manager')
        self.env['account.journal'].search([('type', '=', 'bank'), ('id', '!=', journal.id)]).active = False
        for kind, direction in [('payment', 'outbound'), ('receipt', 'inbound')]:
            approver = accountant if kind == 'payment' else manager
            voucher = self.voucher(kind=kind, method='bank', journal_id=journal.id if kind == 'payment' else False, create_payment=True)
            voucher.action_issue()
            self.assertFalse(voucher.payment_id)
            voucher.with_user(approver).action_accounting_approve()
            payment = voucher.payment_id
            self.assertEqual(payment.journal_id, journal)
            self.assertEqual(payment.move_id.state, 'posted')
            self.assertEqual(payment.payment_type, direction)
            self.assertEqual(payment.amount, voucher.amount)
            self.assertEqual(payment.partner_id, self.partner)
            self.assertEqual(payment.company_id, voucher.company_id)
            counterpart = payment.move_id.line_ids.filtered(lambda line: line.account_id == payment.destination_account_id)
            self.assertEqual(counterpart.analytic_distribution, {str(self.project.account_id.id): 100})
            with self.assertRaises(UserError):
                voucher.with_user(accountant).action_accounting_approve()
            with self.assertRaises(UserError):
                voucher.action_cancel()

    def test_optional_expense_guards(self):
        methods = {
            'hr.expense': ['action_approve', 'action_approve_duplicates', 'action_post', '_do_approve', '_post_without_wizard'],
            'hr.expense.sheet': ['action_approve_expense_sheets', 'approve_expense_sheets', 'action_sheet_move_create', 'action_post', 'action_approve'],
        }
        self.agent.group_ids = [Command.link(self.env.ref('account.group_account_manager').id)]
        for model, names in methods.items():
            if model not in self.env.registry:
                continue
            records = self.env[model].with_user(self.agent)
            for name in names:
                if hasattr(records, name):
                    with self.subTest(model=model, method=name), self.assertRaises(AccessError):
                        getattr(records, name)()

    def test_capture_requires_project(self):
        from types import SimpleNamespace
        from werkzeug.exceptions import BadRequest
        from odoo.addons.abroj_contracting.controllers.capture import Capture
        request = SimpleNamespace(env=self.env, httprequest=SimpleNamespace(method='POST'))
        with patch('odoo.addons.abroj_contracting.controllers.capture.request', request):
            for value in (None, '', '0', 'invalid', '-1'):
                with self.subTest(value=value), self.assertRaises(BadRequest):
                    Capture().capture(project_id=value)
        from lxml import etree
        template = etree.fromstring(self.env.ref('abroj_contracting.capture').arch_db.encode())
        select = template.xpath('//select[@name="project_id"]')[0]
        self.assertEqual(select.get('required'), 'required')
        self.assertEqual(select[0].get('value'), '')

    def test_bilingual_pdf_reports(self):
        from io import BytesIO
        from pypdf import PdfReader
        self.project.partner_id = self.partner
        self.project.company_id.write({'contracting_name_en': 'Report Company English', 'company_registry': '544-TEST'})
        self.project.contract_payment_schedule = '50% advance / مقدم، 50% completion / إنجاز'
        for report, record, text in [
            ('agreement', self.project, 'CLIENT CONTRACT'),
            ('subcontract', self.sub, 'SUBCONTRACT'),
            ('voucher', self.voucher(), 'VOUCHER'),
            ('voucher', self.voucher(kind='receipt', subcontractor_id=False), 'VOUCHER'),
        ]:
            name = 'abroj_contracting.' + report
            html, _ = self.env['ir.actions.report']._render_qweb_html(name, record.ids)
            self.assertIn(b'dir="rtl"', html)
            self.assertIn(b'class="en"', html)
            pdf, kind = self.env['ir.actions.report'].with_context(force_report_rendering=True)._render_qweb_pdf(name, record.ids)
            self.assertEqual(kind, 'pdf')
            self.assertTrue(pdf.startswith(b'%PDF-'))
            pages = PdfReader(BytesIO(pdf)).pages
            self.assertGreater(len(pages), 0)
            self.assertIn(text, ''.join(page.extract_text() for page in pages))
            for page in pages:
                self.assertIn('Report Company English', page.extract_text())
                self.assertIn('544-TEST', page.extract_text())

    def test_report_header_company_contacts(self):
        from lxml import html
        self.project.partner_id = self.partner
        company = self.project.company_id
        reports = [
            ('agreement', self.project), ('subcontract', self.sub),
            ('voucher', self.voucher()),
            ('voucher', self.voucher(kind='receipt', subcontractor_id=False)),
        ]
        for website, email in [
            ('https://header.example.com', 'header@example.com'),
            ('https://header.example.com', False),
            (False, 'header@example.com'), (False, False),
        ]:
            company.write({'website': website, 'email': email})
            for report, record in reports:
                with self.subTest(report=report, record=record.id, website=website, email=email):
                    rendered, _ = self.env['ir.actions.report']._render_qweb_html(
                        'abroj_contracting.' + report, record.ids)
                    tree = html.fromstring(rendered)
                    for field, value in [('website', website), ('email', email)]:
                        nodes = tree.xpath('//small[@class="header-contact"]/span[@class="header-%s"]' % field)
                        self.assertEqual([node.text_content() for node in nodes], [value] if value else [])
                    contact = tree.xpath('//small[@class="header-contact"]')
                    self.assertEqual(len(contact), int(bool(website or email)))
                    if contact:
                        self.assertEqual(' · ' in contact[0].text_content(), bool(website and email))

    def test_both_voucher_memos_and_layout(self):
        from lxml import html
        self.project.company_id.currency_id = self.env.ref('base.SAR')
        for kind in ('payment', 'receipt'):
            voucher = self.voucher(kind=kind, memo='دفعة وفق العقد / Payment under contract')
            rendered, _ = self.env['ir.actions.report']._render_qweb_html(
                'abroj_contracting.voucher', voucher.ids)
            tree = html.fromstring(rendered)
            memo = tree.xpath('//div[@class="memo"]')
            self.assertEqual(len(memo), 1)
            self.assertIn(voucher.memo, memo[0].text_content())
            self.assertIn('Saudi Riyals only', tree.text_content())
            voucher.memo = False
            rendered, _ = self.env['ir.actions.report']._render_qweb_html(
                'abroj_contracting.voucher', voucher.ids)
            self.assertFalse(html.fromstring(rendered).xpath('//div[@class="memo"]'))

    def test_report_column_languages(self):
        from lxml import html
        import re
        self.project.write({
            'contracting_goal': 'نطاق العمل / Work scope',
            'contract_payment_schedule_en': '30% advance; 70% handover',
            'contract_payment_schedule_ar': '30% مقدم؛ 70% عند التسليم',
        })
        self.sub.write({'scope': 'التشطيبات / Fit-out',
                        'payment_terms': '20% مقدم\n20% advance',
                        'penalties': '500 ريال\nSAR 500'})
        self.sub.scope_en = 'Supply/install fit-out'
        self.assertEqual(self.sub.report_text('scope', 'en'), 'Supply/install fit-out')
        self.assertEqual(self.sub.report_text('payment_terms', 'en'), '20% advance')
        self.assertEqual(self.sub.report_text('payment_terms', 'ar'), '20% مقدم')
        self.assertEqual(self.project.report_text('contract_payment_schedule', 'en'),
                         '30% advance; 70% handover')
        for report, record in [('agreement', self.project), ('subcontract', self.sub),
                               ('voucher', self.voucher(memo='دفعة / Payment'))]:
            rendered, _ = self.env['ir.actions.report']._render_qweb_html(
                'abroj_contracting.' + report, record.ids)
            tree = html.fromstring(rendered)
            for language, pattern in [('en', r'[\u0600-\u06ff]'), ('ar', r'[A-Za-z]')]:
                for cell in tree.xpath('//td[@class="%s"]' % language):
                    # Names and identifiers are intentionally preserved as entered.
                    text = cell.text_content()
                    for name in [self.project.name, self.partner.name, self.env.company.name,
                                 self.env.company.contracting_name_en or '',
                                 self.env.company.contracting_name_ar or '', self.env.company.currency_id.name]:
                        if name:
                            text = text.replace(name, '')
                    self.assertFalse(re.search(pattern, text), text)

    def test_voucher_contract_balances(self):
        self.project.partner_id = self.partner
        first = self.voucher(amount=500)
        first.action_issue()
        invoice = self.env['abroj.contracting.invoice'].create({
            'project_id': self.project.id, 'subcontractor_id': self.sub.id,
            'number': 'MAT-BAL', 'amount': 800, 'invoice_kind': 'materials_company',
            'buyer_vat': '300000000000003'})
        self.project.company_id.vat = '300000000000003'
        invoice.action_confirm()
        second = self.voucher(amount=700)
        self.assertEqual(second.balance_before, 500)
        self.assertEqual(second.balance_remaining, 2000)
        self.assertIn(first.name, second.balance_html)
        second.action_issue()
        self.assertEqual(second.previous_vouchers(), first)
        self.assertEqual(second.balance_remaining, 2000)
        third = self.voucher(amount=100)
        third.action_issue()
        second.invalidate_recordset()
        self.assertEqual(second.balance_remaining, 2000)
        third.action_cancel()
        receipt = self.voucher(kind='receipt', subcontractor_id=False, amount=1200)
        receipt.action_issue()
        next_receipt = self.voucher(kind='receipt', subcontractor_id=False, amount=300)
        self.assertEqual(next_receipt.balance_before, 1200)
        self.assertEqual(next_receipt.balance_remaining, 8500)
        receipt.action_cancel()
        self.assertEqual(next_receipt.balance_remaining, 9700)
        vendor = self.voucher(subcontractor_id=False, vendor_contract_reference='PO-1', vendor_contract_value=5000, amount=500)
        vendor.action_issue()
        other = self.voucher(subcontractor_id=False, vendor_contract_reference='PO-2', vendor_contract_value=3000, amount=100)
        self.assertFalse(other.previous_vouchers())
        self.assertEqual(other.balance_remaining, 2900)

    def test_voucher_contract_party_guards(self):
        self.project.partner_id = self.partner
        stranger = self.env['res.partner'].create({'name': 'Other client'})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.voucher(kind='receipt', subcontractor_id=False, partner_id=stranger.id)
        vendor = self.voucher(subcontractor_id=False)
        with self.assertRaises(ValidationError):
            vendor.action_issue()
        with self.assertRaises(ValidationError):
            vendor.write({'issued_at': '2026-01-01 00:00:00'})
        earlier_draft = self.voucher(amount=100)
        later_draft = self.voucher(amount=200)
        later_draft.action_issue()
        earlier_draft.action_issue()
        self.assertEqual(earlier_draft.previous_vouchers(), later_draft)
        self.assertFalse(later_draft.previous_vouchers())

    def test_clause_default_copy_edit_reload(self):
        template = self.env['abroj.contract.clause.template'].create({
            'title_ar': 'بند تجريبي', 'title_en': 'Test clause',
            'body_ar': 'نص تجريبي', 'body_en': 'Original body', 'contract_type': 'both',
        })
        project = self.env['project.project'].create({'name': 'Clause copy', 'company_id': self.env.company.id})
        sub = self.env['abroj.contracting.subcontractor'].create({'project_id': project.id, 'partner_id': self.partner.id})
        for record in (project, sub):
            template.body_en = 'Original body'
            line = record.clause_line_ids.filtered(lambda l: l.title_en == 'Test clause')
            self.assertEqual(len(line), 1)
            line.write({'body_en': 'Edited per contract', 'sequence': 1})
            self.assertEqual(record.contract_clauses()[0], line)
            report = 'agreement' if record._name == 'project.project' else 'subcontract'
            html, _ = self.env['ir.actions.report']._render_qweb_html('abroj_contracting.' + report, record.ids)
            self.assertIn(b'Edited per contract', html)
            self.assertEqual(template.body_en, 'Original body')
            template.body_en = 'Updated default'
            self.assertEqual(line.body_en, 'Edited per contract')
            line.unlink()
            record.action_reload_default_clauses()
            self.assertEqual(record.clause_line_ids.filtered(lambda l: l.title_en == 'Test clause').body_en, 'Updated default')
        explicit = self.env['project.project'].create({'name': 'Empty clauses', 'clause_line_ids': []})
        self.assertFalse(explicit.clause_line_ids)

    def test_voucher_amount_words(self):
        self.project.company_id.currency_id = self.env.ref('base.SAR')
        voucher = self.voucher(amount=8000.25)
        self.assertTrue(voucher.amount_in_words('en').startswith('Eight thousand'))
        self.assertTrue(voucher.amount_in_words('en').endswith(' Saudi Riyals only'))
        self.assertIn('ثمانية', voucher.amount_in_words('ar'))
        self.assertIn('خمس', voucher.amount_in_words('ar'))
        self.assertNotRegex(voucher.amount_in_words('ar'), '[A-Za-z]')
        self.assertIn('twenty-five', voucher.amount_in_words('en'))
        voucher.amount = 8000
        self.assertEqual(voucher.amount_in_words('en'), 'Eight thousand Saudi Riyals only')

    def test_clause_filtering_and_migration(self):
        templates = self.env['abroj.contract.clause.template']
        values = {'title_ar': 'عنوان', 'title_en': 'Title', 'body_ar': 'النص', 'body_en': 'Body'}
        client = templates.create(dict(values, contract_type='client'))
        sub = templates.create(dict(values, contract_type='subcontract'))
        inactive = templates.create(dict(values, active=False))
        optional = templates.create(dict(values, is_default=False))
        for model, included, excluded in [('project.project', client, sub), ('abroj.contracting.subcontractor', sub, client)]:
            # Give each template a distinct body to verify the selection.
            included.body_en = 'Included'
            excluded.body_en = 'Excluded'
            inactive.body_en = 'Inactive'
            optional.body_en = 'Optional'
            bodies = [command[2]['body_en'] for command in self.env[model]._default_clause_commands()]
            self.assertIn('Included', bodies)
            for body in ('Excluded', 'Inactive', 'Optional'):
                self.assertNotIn(body, bodies)
        legacy = self.env['abroj.contracting.clause'].create({
            'name': 'Legacy / قديم', 'kind': 'client', 'text_ar': 'نص مخصص',
            'text_en': 'Custom authored legacy body', 'sequence': 123, 'active': False,
        })
        templates.migrate_defaults()
        migrated = templates.with_context(active_test=False).search([('legacy_id', '=', legacy.id)])
        self.assertEqual(len(migrated), 1)
        self.assertEqual(migrated.title_ar, 'قديم')
        self.assertEqual(migrated.body_en, legacy.text_en)
        self.assertEqual(migrated.sequence, 123)
        self.assertFalse(migrated.active)
        templates.migrate_defaults()
        self.assertEqual(templates.with_context(active_test=False).search_count([('legacy_id', '=', legacy.id)]), 1)
        migrated.unlink()
        templates.migrate_defaults()
        self.assertFalse(templates.with_context(active_test=False).search([('legacy_id', '=', legacy.id)]))
