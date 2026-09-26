from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestReceiptLayoutProfile(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.agent = cls.env['baseer.print.agent'].create({
            'name': 'Receipt profile agent',
            'device_uid': 'receipt-profile-agent-0001',
            'allowed_company_ids': [Command.set([cls.company.id])],
        })
        # Professional layout uses the immutable native Odoo receipt capture.
        # The bridge deliberately requires a capable agent for that path.
        cls.agent.with_context(baseer_print_internal=True).write({
            'agent_version': '1.4.0',
        })
        cls.printer = cls.env['baseer.print.printer'].with_context(
            baseer_print_discovery=True,
        ).create({
            'name': 'Receipt profile 80 mm',
            'agent_id': cls.agent.id,
            'machine_identifier': 'RECEIPT-PROFILE-80',
            'paper_width': '80',
            'active': True,
            'allowed_company_ids': [Command.set([cls.company.id])],
        })

    def test_disabled_company_profile_keeps_native_default(self):
        self.company.write({'baseer_receipt_profile_enabled': False})
        config = self.env['pos.config'].create({'name': 'Native receipt POS'})
        self.assertEqual(config.baseer_receipt_layout_mode, 'native')
        self.assertFalse(config.baseer_direct_print_enabled)

    def test_new_pos_inherits_explicit_company_profile(self):
        self.company.write({
            'baseer_receipt_profile_enabled': True,
            'baseer_receipt_profile_printer_id': self.printer.id,
            'baseer_receipt_profile_copies': 2,
            'baseer_receipt_profile_layout_mode': 'baseer_80',
            'baseer_receipt_profile_close_report': True,
        })
        config = self.env['pos.config'].create({'name': 'Professional receipt POS'})
        self.assertTrue(config.baseer_direct_print_enabled)
        self.assertTrue(config.baseer_native_receipt_enabled)
        self.assertEqual(config.baseer_receipt_printer_id, self.printer)
        self.assertEqual(config.baseer_receipt_copies, 2)
        self.assertEqual(config.baseer_receipt_layout_mode, 'baseer_80')
        self.assertTrue(config.baseer_print_session_close_report)

    def test_professional_layout_rejects_non_native_receipt_path(self):
        # The company profile is intentionally mutable in the inheritance test.
        # Reset it here so this validation covers the non-profile path itself.
        self.company.write({'baseer_receipt_profile_enabled': False})
        config = self.env['pos.config'].create({'name': 'Receipt validation POS'})
        with self.assertRaises(ValidationError):
            config.write({'baseer_receipt_layout_mode': 'baseer_80'})

    def test_pos_partner_loader_uses_native_phone(self):
        fields_to_load = self.env['res.partner']._load_pos_data_fields(
            self.env['pos.config'].browse()
        )
        self.assertIn('phone', fields_to_load)
