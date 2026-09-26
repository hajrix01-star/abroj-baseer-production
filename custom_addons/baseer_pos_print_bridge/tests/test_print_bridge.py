import base64
import io
from urllib.parse import parse_qs, urlparse
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4
from unittest.mock import patch
from PIL import Image

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBaseerPrintBridgeHybrid(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.config = cls.env['pos.config'].create({'name': 'Hybrid print QA'})
        cls.agent = cls.env['baseer.print.agent'].create({
            'name': 'QA Windows', 'device_uid': 'hybrid-qa-windows-agent-0001',
            'allowed_company_ids': [Command.set([cls.company.id])],
        })
        cls.agent.with_context(baseer_print_internal=True).write({'state': 'online'})
        cls.receipt = cls._printer('QA Receipt', 'HYBRID-RECEIPT-01')
        cls.kitchen_a = cls._printer('QA Kitchen A', 'HYBRID-KITCHEN-A')
        cls.kitchen_b = cls._printer('QA Kitchen B', 'HYBRID-KITCHEN-B')

    @classmethod
    def _printer(cls, name, identifier):
        return cls.env['baseer.print.printer'].with_context(baseer_print_discovery=True).create({
            'name': name, 'agent_id': cls.agent.id, 'machine_identifier': identifier, 'active': True,
            'allowed_company_ids': [Command.set([cls.company.id])],
        })

    def _enable(self):
        self.config.write({'baseer_receipt_printer_id': self.receipt.id, 'baseer_receipt_copies': 2,
                           'baseer_direct_print_enabled': True})

    def setUp(self):
        super().setUp()
        self.agent.with_context(baseer_print_internal=True).write({
            'state': 'online',
            # A test may enable the native Odoo receipt path.  Keep its
            # shared Agent fixture compatible with that explicitly-tested
            # protocol instead of inheriting a version from another test.
            'agent_version': '1.4.6',
        })

    def _order(self, quantity=1):
        if not self.config.current_session_id:
            self.config.open_ui()
        product = self.env['product.template'].create({
            'name': 'Hybrid print product', 'available_in_pos': True, 'list_price': 10,
        }).product_variant_id
        return self.env['pos.order'].create({
            'company_id': self.company.id, 'session_id': self.config.current_session_id.id,
            'amount_tax': 0, 'amount_total': 10 * quantity, 'amount_paid': 0, 'amount_return': 0,
            'lines': [Command.create({'product_id': product.id, 'qty': quantity, 'price_unit': 10,
                                      'price_subtotal': 10 * quantity, 'price_subtotal_incl': 10 * quantity,
                                      'full_product_name': product.display_name})],
        })

    def test_shared_hardware_is_authorized_server_side(self):
        other_company = self.env['res.company'].create({'name': 'Unapproved print company'})
        other_config = self.env['pos.config'].with_company(other_company).create({'name': 'Other POS'})
        self.assertFalse(self.receipt._allows_company(other_company))
        with self.assertRaises(ValidationError):
            self.env['baseer.print.route'].with_company(other_company).create({
                'pos_config_id': other_config.id, 'pos_category_id': False, 'printer_id': self.kitchen_a.id,
            })

    def test_guided_setup_configures_one_printer_and_one_default_kitchen_route(self):
        self.company.country_id = self.env.ref('base.us')
        wizard = self.env['baseer.print.setup.wizard'].with_context(
            baseer_pos_config_id=self.config.id,
        ).create({
            'pos_config_id': self.config.id,
            'agent_id': self.agent.id,
            'receipt_printer_id': self.receipt.id,
            'create_default_kitchen_route': True,
        })
        result = wizard.action_apply_and_test()
        self.config.invalidate_recordset()
        self.assertTrue(self.config.baseer_direct_print_enabled)
        self.assertTrue(self.config.baseer_native_receipt_enabled)
        self.assertEqual(self.config.baseer_receipt_printer_id, self.receipt)
        route = self.env['baseer.print.route'].search([
            ('pos_config_id', '=', self.config.id), ('pos_category_id', '=', False), ('active', '=', True),
        ])
        self.assertEqual(len(route), 1)
        self.assertEqual(route.printer_id, self.receipt)
        self.assertEqual(result['res_model'], 'baseer.print.job')

    def test_guided_setup_reuses_one_existing_computer_for_another_pos(self):
        self.company.country_id = self.env.ref('base.us')
        other_config = self.env['pos.config'].create({'name': 'Second cashier'})
        before_agents = self.env['baseer.print.agent'].search_count([])
        wizard = self.env['baseer.print.setup.wizard'].with_context(
            baseer_pos_config_id=other_config.id,
        ).create({
            'pos_config_id': other_config.id,
            'setup_mode': 'existing',
            'agent_id': self.agent.id,
            'receipt_printer_id': self.receipt.id,
            'create_default_kitchen_route': False,
        })
        result = wizard.action_apply_and_test()
        other_config.invalidate_recordset()
        self.assertEqual(self.env['baseer.print.agent'].search_count([]), before_agents)
        self.assertFalse(wizard.pairing_code)
        self.assertEqual(other_config.baseer_receipt_printer_id, self.receipt)
        self.assertEqual(result['res_model'], 'baseer.print.job')

    def test_company_primary_agent_is_the_only_pos_printer_source(self):
        self.company.write({'baseer_primary_print_agent_id': self.agent.id})
        self.config.invalidate_recordset()
        self.assertEqual(self.config.baseer_effective_print_agent_id, self.agent)
        self.config.write({
            'baseer_direct_print_enabled': True,
            'baseer_receipt_printer_id': self.receipt.id,
        })

        other_agent = self.env['baseer.print.agent'].create({
            'name': 'Other Windows', 'device_uid': 'hybrid-qa-other-windows-0001',
            'allowed_company_ids': [Command.set([self.company.id])],
        })
        other_agent.with_context(baseer_print_internal=True).write({'state': 'online'})
        other_printer = self.env['baseer.print.printer'].with_context(
            baseer_print_discovery=True,
        ).create({
            'name': 'Other receipt printer', 'agent_id': other_agent.id,
            'machine_identifier': 'HYBRID-OTHER-RECEIPT-01', 'paper_width': '80',
            'active': True, 'allowed_company_ids': [Command.set([self.company.id])],
        })
        with self.assertRaises(ValidationError):
            self.config.write({'baseer_receipt_printer_id': other_printer.id})

    def test_print_configuration_is_a_native_full_width_tab(self):
        view = self.env.ref('baseer_pos_print_bridge.view_pos_config_form_direct_print')
        self.assertIn('name="baseer_printing"', view.arch_db)
        self.assertIn('Printer settings', view.arch_db)
        self.assertIn('Copies and receipt layout', view.arch_db)
        self.assertIn('Print customization', view.arch_db)
        self.assertNotIn('action_baseer_open_guided_print_setup', view.arch_db)

    def test_guided_setup_selects_the_only_safe_receipt_printer(self):
        agent = self.env['baseer.print.agent'].create({
            'name': 'Single-printer Windows',
            'device_uid': 'hybrid-qa-single-printer-agent-0001',
            'allowed_company_ids': [Command.set([self.company.id])],
        })
        agent.with_context(baseer_print_internal=True).write({'state': 'online'})
        printer = self.env['baseer.print.printer'].with_context(
            baseer_print_discovery=True,
        ).create({
            'name': 'Single receipt printer',
            'agent_id': agent.id,
            'machine_identifier': 'HYBRID-SINGLE-RECEIPT-01',
            'paper_width': '80',
            'active': True,
            'allowed_company_ids': [Command.set([self.company.id])],
        })
        wizard = self.env['baseer.print.setup.wizard'].new({
            'pos_config_id': self.config.id,
            'agent_id': agent.id,
        })

        wizard._onchange_agent_id()

        self.assertEqual(wizard.receipt_printer_id, printer)

    def test_guided_setup_does_not_guess_between_multiple_receipt_printers(self):
        wizard = self.env['baseer.print.setup.wizard'].new({
            'pos_config_id': self.config.id,
            'agent_id': self.agent.id,
        })

        wizard._onchange_agent_id()

        self.assertFalse(wizard.receipt_printer_id)

    def test_guided_setup_rejects_missing_saudi_vat_before_applying(self):
        self.company.write({'country_id': self.env.ref('base.sa').id, 'vat': False})
        wizard = self.env['baseer.print.setup.wizard'].create({
            'pos_config_id': self.config.id, 'agent_id': self.agent.id,
            'receipt_printer_id': self.receipt.id,
        })
        with self.assertRaisesRegex(ValidationError, 'VAT'):
            wizard.action_apply_and_test()
        self.assertFalse(self.config.baseer_direct_print_enabled)

    def test_simple_setup_pairs_with_the_windows_identity_without_manual_device_entry(self):
        self.env['ir.config_parameter'].sudo().set_param('web.base.url', 'https://qa.example.test')
        wizard = self.env['baseer.print.setup.wizard'].with_context(
            baseer_pos_config_id=self.config.id,
        ).create({'pos_config_id': self.config.id, 'setup_mode': 'new'})
        wizard.action_start_pairing()
        pending_agent = wizard.agent_id
        self.assertTrue(pending_agent.device_uid.startswith('PENDING-'))
        self.assertTrue(wizard.pairing_code)

        paired, _token = self.env['baseer.print.agent']._pair_device(
            wizard.pairing_code, 'BASEER-SIMPLE-SETUP-01', '1.5.10',
        )
        self.assertEqual(paired, pending_agent)
        self.assertEqual(pending_agent.device_uid, 'BASEER-SIMPLE-SETUP-01')
        self.assertEqual(pending_agent.name, 'BASEER-SIMPLE-SETUP-01')
        self.assertEqual(pending_agent.state, 'online')

    def test_simple_setup_rejects_a_windows_identity_that_is_already_registered(self):
        self.env['ir.config_parameter'].sudo().set_param('web.base.url', 'https://qa.example.test')
        wizard = self.env['baseer.print.setup.wizard'].with_context(
            baseer_pos_config_id=self.config.id,
        ).create({'pos_config_id': self.config.id, 'setup_mode': 'new'})
        wizard.action_start_pairing()
        result = self.env['baseer.print.agent']._pair_device(
            wizard.pairing_code, self.agent.device_uid, '1.5.10',
        )
        wizard.agent_id.invalidate_recordset()
        self.assertFalse(result)
        self.assertTrue(wizard.agent_id.device_uid.startswith('PENDING-'))

    def test_existing_computer_choice_cannot_create_a_pairing_code(self):
        self.env['ir.config_parameter'].sudo().set_param('web.base.url', 'https://qa.example.test')
        wizard = self.env['baseer.print.setup.wizard'].create({
            'pos_config_id': self.config.id,
            'setup_mode': 'existing',
            'agent_id': self.agent.id,
        })
        with self.assertRaises(UserError):
            wizard.action_start_pairing()
        self.assertFalse(wizard.pairing_code)

    def test_native_bootstrap_keeps_all_fields_semantics(self):
        requested = self.config._load_pos_data_fields(self.config)
        data = self.config.read(requested)[0]
        for name in ('currency_id', 'company_id', 'pricelist_id', 'baseer_direct_print_enabled'):
            self.assertIn(name, data)

    def test_pos_user_bootstrap_never_reads_admin_kitchen_routes(self):
        """A POS-only cashier gets category metadata, never print routes."""
        category = self.env['pos.category'].create({'name': 'Cashier kitchen category'})
        self.env['baseer.print.route'].create({
            'pos_config_id': self.config.id,
            'printer_id': self.kitchen_a.id,
            'pos_category_id': category.id,
        })
        cashier = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'POS bootstrap cashier',
            'login': 'pos-bootstrap-cashier-%s' % uuid4().hex,
            'company_id': self.company.id,
            'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('point_of_sale.group_pos_user').id,
            ])],
        })
        config = self.config.with_user(cashier)
        requested = config._load_pos_data_fields(config)
        for field_name in (
            'baseer_effective_print_agent_id',
            'baseer_print_hardware_status',
            'baseer_receipt_printer_id',
            'baseer_receipt_copies',
            'baseer_print_session_close_report',
            'baseer_preparation_binding_ids',
            'minimal_employee_ids',
            'basic_employee_ids',
            'advanced_employee_ids',
        ):
            self.assertNotIn(field_name, requested)
        if not self.config.current_session_id:
            self.config.open_ui()
        payload = self.config.current_session_id.with_user(cashier).load_data([])
        self.assertTrue(payload['pos.config'])
        self.assertEqual(payload['pos.config'][0]['baseer_preparation_bindings'], [{
            'category_id': category.id,
            'category_name': category.display_name,
        }])

    def test_legacy_receipt_failure_does_not_rollback_native_payment(self):
        self._enable()
        order = self._order()
        order.amount_paid = order.amount_total
        Job = type(self.env['baseer.print.job'])
        with self.assertLogs('odoo.addons.baseer_pos_print_bridge.models.pos_order', level='ERROR'):
            with patch.object(Job, '_enqueue_receipt', side_effect=ValidationError('Printer unavailable')):
                order.action_pos_order_paid()
        self.assertEqual(order.state, 'paid')
        self.assertEqual(order.baseer_customer_receipt_status()['error'], 'Printer unavailable')

    def test_native_receipt_accepts_native_paid_posted_and_refund_orders(self):
        self._enable()
        self.config.baseer_native_receipt_enabled = True
        self.company.country_id = self.env.ref('base.us')
        image = self._native_receipt_sample()
        # Odoo 19 invoices are represented by account_move, never by an
        # 'invoiced' order state. Native final states remain paid / done.
        for state, refund in [('paid', False), ('done', False), ('paid', True), ('done', True)]:
            order = self._order(-1 if refund else 1)
            order.write({'state': state, 'is_refund': refund})
            result = order.baseer_enqueue_native_receipt(image)
            self.assertTrue(result['job_id'])
            self.assertEqual(order.state, state)

    def test_native_receipt_missing_vat_keeps_paid_order(self):
        self._enable()
        self.config.baseer_native_receipt_enabled = True
        self.company.write({'country_id': self.env.ref('base.sa').id, 'vat': False})
        order = self._order()
        order.state = 'paid'
        with self.assertRaisesRegex(ValidationError, 'VAT'):
            order.baseer_enqueue_native_receipt(self._native_receipt_sample())
        self.assertEqual(order.state, 'paid')
        self.assertFalse(order.nb_print)

    def test_kitchen_quantity_excludes_only_accepted_silent_allowance(self):
        self._enable()
        order = self._order(1)
        State = self.env['baseer.print.preparation.state']
        # Unit seam does not require the optional substitution addon installed.
        class SilentLine:
            _fields = {'baseer_substitution_silent_quantity': True}
            baseer_substitution_silent_quantity = 1
            qty = 1
        line = SilentLine()
        self.assertEqual(State._kitchen_quantity(line), 0)
        line.qty = 3
        self.assertEqual(State._kitchen_quantity(line), 2)
        self.assertEqual(State._kitchen_quantity(order.lines), 1)

    def test_silent_allowance_never_creates_ticket_but_later_increment_does(self):
        self._enable()
        self.env['baseer.print.route'].create({
            'pos_config_id': self.config.id, 'printer_id': self.kitchen_a.id,
            'pos_category_id': False,
        })
        order = self._order(1)
        State = self.env['baseer.print.preparation.state']
        with patch.object(type(State), '_kitchen_quantity', lambda model, line: max(0, line.qty - 1)):
            silent = State._enqueue_order(order, str(uuid4()))
            self.assertFalse(silent['job_ids'])
            self.assertFalse(silent['event_ids'])
            self.assertFalse(State.search([('order_id', '=', order.id)]))
            order.lines.qty = 3
            action = State._normalize_action({
                'action_uuid': str(uuid4()), 'action_type': 'send', 'lines': [{
                    'line_uuid': order.lines.uuid, 'expected_quantity': 0,
                    'new_quantity': 2, 'reason_code': '', 'reason_note': '',
                }],
            })
            added = State._apply_action(order, action)
            self.assertTrue(added['job_ids'])
            self.assertEqual(State.search([('order_id', '=', order.id)]).quantity, 2)

    def test_receipt_is_config_owned_not_a_route(self):
        self._enable()
        order = self._order(); order.write({'state': 'paid'})
        job = self.env['baseer.print.job']._enqueue_receipt(order)
        self.assertEqual(job.printer_id, self.receipt)
        self.assertEqual(job.pos_config_id, self.config)
        self.assertEqual(job.payload['printer']['copies'], 2)
        self.assertEqual(job.payload['schema'], 3)
        self.assertEqual(job.payload['receipt']['total'], '10.00')
        self.assertFalse(job.route_id)

    def test_customer_receipt_snapshots_discount_tax_payment_and_change(self):
        self._enable()
        order = self._order(2)
        order.lines.write({
            'discount': 25,
            'price_subtotal': 15,
            'price_subtotal_incl': 17.25,
        })
        order.write({
            'state': 'paid', 'amount_total': 17.25, 'amount_tax': 2.25,
            'amount_paid': 20, 'amount_return': 2.75,
        })
        method = self.config.payment_method_ids[:1]
        self.assertTrue(method)
        self.env['pos.payment'].create({
            'pos_order_id': order.id, 'payment_method_id': method.id, 'amount': 20,
        })
        self.env['pos.payment'].create({
            'pos_order_id': order.id, 'payment_method_id': method.id,
            'amount': -2.75, 'is_change': True,
        })
        Job = self.env['baseer.print.job']
        job = Job._enqueue_receipt(order)
        self.assertEqual(job, Job._enqueue_receipt(order))
        self.assertEqual(job.ticket_type, 'receipt')
        self.assertEqual(job.payload['lines'][0]['quantity'], 2)
        self.assertEqual(job.payload['lines'][0]['discount'], 25)
        self.assertEqual(job.payload['lines'][0]['price'], '17.25')
        self.assertEqual(job.payload['receipt']['currency'], order.currency_id.symbol)
        self.assertEqual(job.payload['receipt']['subtotal'], '15.00')
        self.assertEqual(job.payload['receipt']['tax'], '2.25')
        self.assertFalse(job.payload['receipt']['has_adjustment'])
        self.assertEqual(job.payload['receipt']['total'], '17.25')
        self.assertEqual(job.payload['receipt']['paid'], '20.00')
        self.assertEqual(job.payload['receipt']['change'], '2.75')
        self.assertEqual(job.payload['receipt']['payments'], [{
            'method': method.display_name, 'amount': '20.00',
        }])
        receipt = job.payload['receipt']
        self.assertEqual(
            Decimal(receipt['subtotal']) + Decimal(receipt['tax']) + Decimal(receipt['adjustment']),
            Decimal(receipt['total']),
        )

        lower_order = self._order(2)
        lower_order.write({'state': 'paid', 'amount_tax': 3, 'amount_total': 22.95})
        lower_receipt = self.env['baseer.print.job']._enqueue_receipt(lower_order).payload['receipt']
        self.assertEqual(lower_receipt['adjustment'], '-0.05')
        self.assertEqual(
            Decimal(lower_receipt['subtotal']) + Decimal(lower_receipt['tax'])
            + Decimal(lower_receipt['adjustment']),
            Decimal(lower_receipt['total']),
        )

    def test_customer_receipt_exposes_order_rounding_adjustment(self):
        self._enable()
        order = self._order(2)
        order.write({'state': 'paid', 'amount_tax': 3, 'amount_total': 23.05})
        job = self.env['baseer.print.job']._enqueue_receipt(order)
        self.assertEqual(job.payload['receipt']['subtotal'], '20.00')
        self.assertEqual(job.payload['receipt']['tax'], '3.00')
        self.assertEqual(job.payload['receipt']['adjustment'], '0.05')
        self.assertTrue(job.payload['receipt']['has_adjustment'])
        receipt = job.payload['receipt']
        self.assertEqual(
            Decimal(receipt['subtotal']) + Decimal(receipt['tax']) + Decimal(receipt['adjustment']),
            Decimal(receipt['total']),
        )

    def _native_receipt_sample(self, color='white', size=(300, 400)):
        output = io.BytesIO()
        Image.new('RGB', size, color).save(output, format='JPEG')
        return base64.b64encode(output.getvalue()).decode('ascii')

    def test_tall_native_receipt_survives_attachment_storage_and_fresh_claim(self):
        self._enable()
        self.config.baseer_native_receipt_enabled = True
        self.company.country_id = self.env.ref('base.us')
        # Native attachment processing would shrink this height to 1920 and
        # invalidate the already recorded receipt digest in a later RPC.
        self.env['ir.config_parameter'].sudo().set_param('base.image_autoresize_max_px', '1920x1920')
        image = self._native_receipt_sample(size=(576, 2600))
        order = self._order()
        order.state = 'paid'
        receipt = order.baseer_enqueue_native_receipt(image)
        job = self.env['baseer.print.job'].browse(receipt['job_id'])
        job.available_at = fields.Datetime.now() - timedelta(minutes=1)
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertEqual(base64.b64decode(job.receipt_image), base64.b64decode(image))
        with Image.open(io.BytesIO(base64.b64decode(job.receipt_image))) as stored:
            self.assertEqual(stored.size, (576, 2600))
        claim = self.env['baseer.print.job']._claim_for_agent(self.agent)
        self.assertEqual(claim['id'], job.id)
        self.assertEqual(claim['payload']['receipt_image']['base64'], image)

    def test_native_odoo_receipt_is_versioned_bounded_and_idempotent(self):
        self._enable()
        self.agent.with_context(baseer_print_internal=True).write({'agent_version': '1.4.0'})
        self.receipt.paper_width = '80'
        self.config.baseer_native_receipt_enabled = True
        order = self._order()
        order.state = 'paid'
        # This test exercises the print transport independently of Saudi EDI;
        # Phase 1 and Phase 2 fiscal rules have separate server guards.
        self.company.country_id = self.env.ref('base.us')
        image = self._native_receipt_sample()
        first = order.baseer_enqueue_native_receipt(image)
        self.assertEqual(order.nb_print, 1)
        second = order.baseer_enqueue_native_receipt(image)
        self.assertEqual(order.nb_print, 1)
        self.assertEqual(first['job_id'], second['job_id'])
        job = self.env['baseer.print.job'].browse(first['job_id'])
        self.assertEqual(job.payload['schema'], 4)
        self.assertEqual(job.payload['receipt_image']['width'], 300)
        self.assertNotIn('base64', job.payload['receipt_image'])
        self.assertTrue(job.receipt_image)
        self.assertNotEqual(job.idempotency_key, job._canonical_key('receipt', order.uuid))
        with self.assertRaises(ValidationError):
            order.baseer_enqueue_native_receipt(self._native_receipt_sample('black'))
        with self.assertRaises(ValidationError):
            order.baseer_enqueue_native_receipt('not-a-jpeg')
        job.sudo().write({'state': 'failed'})
        with self.assertRaises(ValidationError):
            order.baseer_enqueue_native_receipt(image)
        job.sudo().write({'state': 'pending'})
        # Agent polling is a later transaction in production. Make this
        # same-transaction unit claim eligible despite PostgreSQL NOW().
        job.sudo().write({'available_at': fields.Datetime.now() - timedelta(minutes=1)})
        claim = self.env['baseer.print.job']._claim_for_agent(self.agent)
        self.assertTrue(claim)
        self.assertEqual(claim['id'], job.id)
        self.assertEqual(claim['payload']['receipt_image']['base64'], image)
        job._complete_for_agent(self.agent, claim['lease_token'])
        self.assertEqual(order.nb_print, 1)
        job.sudo().write({'completed_at': fields.Datetime.now() - timedelta(hours=25)})
        self.env['baseer.print.job']._purge_accepted_native_receipt_images()
        self.assertFalse(job.receipt_image)
        self.assertTrue(job.receipt_image_purged_at)
        recaptured = order.baseer_enqueue_native_receipt(image)
        self.assertNotEqual(recaptured['job_id'], job.id)
        self.assertEqual(self.env['baseer.print.job'].browse(recaptured['job_id']).reprint_of_id, job)

    def test_native_receipt_rejects_draft_and_missing_jpeg(self):
        self._enable()
        self.agent.with_context(baseer_print_internal=True).write({'agent_version': '1.4.0'})
        self.receipt.paper_width = '80'
        self.config.baseer_native_receipt_enabled = True
        self.company.country_id = self.env.ref('base.us')
        order = self._order()
        with self.assertRaises(ValidationError):
            order.baseer_enqueue_native_receipt(self._native_receipt_sample())
        order.state = 'paid'
        with self.assertRaises(ValidationError):
            order.baseer_enqueue_native_receipt('')

    def test_offline_agent_keeps_preparation_job_pending(self):
        self._enable()
        binding = self.env['baseer.print.route'].create({
            'pos_config_id': self.config.id, 'printer_id': self.kitchen_a.id, 'pos_category_id': False, 'copies': 2,
        })
        self.agent.with_context(baseer_print_internal=True).write({'state': 'offline'})
        order = self._order()
        self.env['baseer.print.preparation.state']._enqueue_order(order, 'offline-accepted')
        job = self.env['baseer.print.job'].search([('source_order_id', '=', order.id), ('ticket_type', '=', 'preparation')])
        self.assertEqual(job.state, 'pending')
        self.assertEqual(job.route_id, binding)

    def test_pos_load_exposes_only_display_binding_metadata(self):
        category = self.env['pos.category'].create({'name': 'QA Kitchen Category'})
        self.env['baseer.print.route'].create({
            'pos_config_id': self.config.id, 'printer_id': self.kitchen_a.id,
            'pos_category_id': category.id, 'copies': 2,
        })
        payload = self.config._baseer_preparation_bindings_payload()
        self.assertEqual(payload, [{
            'category_id': category.id, 'category_name': category.display_name,
        }])
        self.assertNotIn('machine_identifier', payload[0])
        self.assertNotIn('agent_id', payload[0])

    def test_snapshot_keeps_original_kitchen_after_mapping_change(self):
        self._enable()
        binding = self.env['baseer.print.route'].create({
            'pos_config_id': self.config.id, 'printer_id': self.kitchen_a.id, 'pos_category_id': False, 'copies': 2,
        })
        order = self._order()
        State = self.env['baseer.print.preparation.state']
        State._enqueue_order(order, 'first')
        binding.write({'printer_id': self.kitchen_b.id, 'copies': 3})
        order.lines.write({'qty': 2})
        State._enqueue_order(order, 'after-remap')
        jobs = self.env['baseer.print.job'].search([
            ('source_order_id', '=', order.id), ('ticket_type', '=', 'preparation')], order='id')
        self.assertTrue(all(job.printer_id == self.kitchen_a for job in jobs))
        self.assertTrue(all(job.payload['printer']['copies'] == 2 for job in jobs))

    def test_regenerated_line_uuid_does_not_print_false_new_and_cancel(self):
        order = self._kitchen_order()
        original = order.lines
        original.ensure_one()
        product_id = original.product_id.id
        full_product_name = original.full_product_name
        before = self.env['baseer.print.job'].search_count([
            ('source_order_id', '=', order.id), ('ticket_type', '=', 'preparation')])
        original.unlink()
        replacement = self.env['pos.order.line'].create({
            'order_id': order.id,
            'product_id': product_id,
            'uuid': str(uuid4()),
            'qty': 1,
            'price_unit': 10,
            'price_subtotal': 10,
            'price_subtotal_incl': 10,
            'full_product_name': full_product_name,
        })
        self.env['baseer.print.preparation.state']._enqueue_order(order, 'regenerated-line')
        jobs = self.env['baseer.print.job'].search([
            ('source_order_id', '=', order.id), ('ticket_type', '=', 'preparation')])
        state = self.env['baseer.print.preparation.state'].search([('order_id', '=', order.id)])
        self.assertEqual(len(jobs), before)
        self.assertEqual(state.line_uuid, replacement.uuid)
        self.assertEqual(state.order_line_id, replacement)

    def test_zero_quantity_kitchen_line_requires_reason_then_prints_cancel(self):
        order = self._kitchen_order()
        order.lines.write({'qty': 0})
        order.write({'amount_total': 0, 'amount_tax': 0})
        with self.assertRaises(ValidationError):
            self.env['baseer.print.preparation.state']._enqueue_order(order, 'zero-quantity-cancel')
        self.env['baseer.print.preparation.state']._enqueue_order(
            order, 'zero-quantity-cancel', 'staff_error', False,
        )
        jobs = self.env['baseer.print.job'].search([
            ('source_order_id', '=', order.id), ('ticket_type', '=', 'preparation')], order='id')
        self.assertEqual(jobs[-1].payload['lines'][0]['action'], 'cancel')
        self.assertEqual(jobs[-1].payload['lines'][0]['delta_quantity'], -1)
        self.assertFalse(self.env['baseer.print.preparation.state'].search([('order_id', '=', order.id)]))
        self.assertFalse(order.lines)
        self.assertEqual(order.state, 'cancel')

    def test_discovery_does_not_disable_a_configured_printer(self):
        self.env['baseer.print.printer']._sync_from_agent(self.agent, [])
        self.assertTrue(self.receipt.active)

    def test_done_is_spooler_acceptance_and_paper_confirmation_is_audit(self):
        self._enable()
        job = self.env['baseer.print.job']._enqueue_test(self.receipt, self.config)
        job.write({'available_at': fields.Datetime.now() - timedelta(minutes=5)})
        claimed = self.env['baseer.print.job']._claim_for_agent(self.agent)
        self.assertEqual(claimed['id'], job.id)
        job._complete_for_agent(self.agent, claimed['lease_token'])
        self.assertEqual(job.state, 'done')
        self.assertGreaterEqual(job.queue_latency_seconds, 0)
        self.assertGreaterEqual(job.agent_latency_seconds, 0)
        self.assertGreaterEqual(job.acceptance_latency_seconds, 0)
        self.assertFalse(job.paper_confirmed_at)
        job.action_confirm_paper_output()
        self.assertTrue(job.paper_confirmed_at)

    def test_expired_lease_never_requeues_possible_output(self):
        self._enable()
        self.agent.invalidate_recordset(['state'])
        self.agent.with_context(baseer_print_internal=True).write({'state': 'online'})
        job = self.env['baseer.print.job']._enqueue_test(self.receipt, self.config)
        job.write({'available_at': fields.Datetime.now() - timedelta(minutes=5)})
        claimed = self.env['baseer.print.job']._claim_for_agent(self.agent)
        self.assertEqual(claimed['id'], job.id)
        job.lease_expires_at = fields.Datetime.now() - timedelta(seconds=1)
        self.env['baseer.print.job']._release_expired_leases()
        self.assertEqual(job.state, 'failed')
        self.assertEqual(job.error_code, 'outcome_unknown')

    def _kitchen_order(self, copies=2, quantity=1):
        self._enable()
        self.env['baseer.print.route'].create({
            'pos_config_id': self.config.id, 'printer_id': self.kitchen_a.id,
            'pos_category_id': False, 'copies': copies,
        })
        order = self._order(quantity)
        order.session_id.write({'state': 'opened'})
        self.env['baseer.print.preparation.state']._enqueue_order(order, 'kitchen-first-send')
        return order

    def _preparation_action(self, order, expected, target, reason_code=False, reason_note=''):
        line = order.lines.ensure_one()
        return {
            'action_uuid': str(uuid4()),
            'action_type': 'line_change',
            'lines': [{
                'line_uuid': line.uuid,
                'expected_quantity': expected,
                'new_quantity': target,
                'reason_code': reason_code or '',
                'reason_note': reason_note,
            }],
        }

    def test_preparation_event_records_new_quantity_five(self):
        self._enable()
        self.env['baseer.print.route'].create({
            'pos_config_id': self.config.id, 'printer_id': self.kitchen_a.id,
            'pos_category_id': False, 'copies': 2,
        })
        order = self._order(5)
        action = self._preparation_action(order, 0, 5)
        result = self.env['baseer.print.preparation.state']._apply_action(order, action)
        event = self.env['baseer.print.preparation.event'].sudo().browse(result['event_ids'])
        self.assertEqual(event.action, 'new')
        self.assertEqual(event.previous_quantity, 0)
        self.assertEqual(event.delta_quantity, 5)
        self.assertEqual(event.new_quantity, 5)
        self.assertEqual(event.job_ids.payload['lines'][0]['new_quantity'], 5)

    def test_send_intent_ignores_unrouted_lines_server_side(self):
        self._enable()
        category = self.env['pos.category'].create({'name': 'Routed kitchen items'})
        self.env['baseer.print.route'].create({
            'pos_config_id': self.config.id, 'printer_id': self.kitchen_a.id,
            'pos_category_id': category.id, 'copies': 1,
        })
        order = self._order(1)
        routed_line = order.lines.ensure_one()
        routed_line.product_id.product_tmpl_id.write({
            'pos_categ_ids': [Command.set([category.id])],
        })
        other_product = self.env['product.template'].create({
            'name': 'Not sent to kitchen', 'available_in_pos': True, 'list_price': 3,
        }).product_variant_id
        other_line = self.env['pos.order.line'].create({
            'order_id': order.id,
            'product_id': other_product.id,
            'qty': 1,
            'price_unit': 3,
            'price_subtotal': 3,
            'price_subtotal_incl': 3,
            'full_product_name': other_product.display_name,
        })
        action = {
            'action_uuid': str(uuid4()),
            'action_type': 'send',
            'lines': [{
                'line_uuid': line.uuid,
                'expected_quantity': 0,
                'new_quantity': 1,
                'reason_code': '',
                'reason_note': '',
            } for line in (routed_line | other_line)],
        }
        result = self.env['baseer.print.preparation.state']._apply_action(order, action)
        events = self.env['baseer.print.preparation.event'].sudo().browse(result['event_ids'])
        states = self.env['baseer.print.preparation.state'].sudo().search([('order_id', '=', order.id)])
        self.assertEqual(events.product_id, routed_line.product_id)
        self.assertEqual(states.product_id, routed_line.product_id)
        self.assertEqual(len(events.job_ids), 1)
        retry = self.env['baseer.print.preparation.event']._retry_events(action)
        self.assertEqual(retry, events)
        changed_retry = {
            **action,
            'lines': [dict(line) for line in action['lines']],
        }
        changed_retry['lines'][1]['new_quantity'] = 2
        with self.assertRaises(ValidationError):
            self.env['baseer.print.preparation.event']._retry_events(changed_retry)

    def test_send_groups_multiple_routed_lines_on_one_printer(self):
        self._enable()
        self.env['baseer.print.route'].create({
            'pos_config_id': self.config.id, 'printer_id': self.kitchen_a.id,
            'pos_category_id': False, 'copies': 1,
        })
        order = self._order(2)
        second_product = self.env['product.template'].create({
            'name': 'Second kitchen item', 'available_in_pos': True, 'list_price': 4,
        }).product_variant_id
        second_line = self.env['pos.order.line'].create({
            'order_id': order.id, 'product_id': second_product.id, 'qty': 3,
            'price_unit': 4, 'price_subtotal': 12, 'price_subtotal_incl': 12,
            'full_product_name': second_product.display_name,
        })
        action = {
            'action_uuid': str(uuid4()),
            'action_type': 'send',
            'lines': [{
                'line_uuid': line.uuid, 'expected_quantity': 0,
                'new_quantity': line.qty, 'reason_code': '', 'reason_note': '',
            } for line in order.lines],
        }
        result = self.env['baseer.print.preparation.state']._apply_action(order, action)
        events = self.env['baseer.print.preparation.event'].sudo().browse(result['event_ids'])
        jobs = self.env['baseer.print.job'].sudo().browse(result['job_ids'])
        self.assertEqual(len(events), 2)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(set(jobs.preparation_event_ids.ids), set(events.ids))
        self.assertEqual(len(jobs.payload['lines']), 2)
        self.assertEqual(
            {line['name'] for line in jobs.payload['lines']},
            {order.lines[0].product_id.display_name, second_line.product_id.display_name},
        )
        jobs.write({'state': 'done'})
        jobs.action_reprint()
        jobs.action_reprint()
        reprints = self.env['baseer.print.job'].sudo().search([
            ('reprint_of_id', '=', jobs.id),
        ], order='reprint_sequence')
        self.assertEqual(reprints.mapped('reprint_sequence'), [1, 2])
        self.assertTrue(all(set(reprint.preparation_event_ids.ids) == set(events.ids) for reprint in reprints))

    def test_preparation_event_records_reduce_five_to_one_without_reason(self):
        order = self._kitchen_order(quantity=5)
        order.lines.write({'qty': 1})
        action = self._preparation_action(order, 5, 1)
        result = self.env['baseer.print.preparation.state']._apply_action(order, action)
        event = self.env['baseer.print.preparation.event'].sudo().browse(result['event_ids'])
        self.assertEqual(event.action, 'reduce')
        self.assertEqual(event.previous_quantity, 5)
        self.assertEqual(event.delta_quantity, -4)
        self.assertEqual(event.new_quantity, 1)
        self.assertFalse(event.reason_code)
        self.assertEqual(event.job_ids.payload['lines'][0]['action'], 'reduce')

    def test_preparation_event_records_cancel_five_with_reason(self):
        order = self._kitchen_order(quantity=5)
        line_uuid = order.lines.uuid
        order.lines.write({'qty': 0})
        order.write({'amount_total': 0, 'amount_tax': 0})
        action = self._preparation_action(order, 5, 0, 'customer_cancelled')
        result = self.env['baseer.print.preparation.state']._apply_action(order, action)
        event = self.env['baseer.print.preparation.event'].sudo().browse(result['event_ids'])
        self.assertEqual(event.line_uuid, line_uuid)
        self.assertEqual(event.action, 'cancel')
        self.assertEqual(event.delta_quantity, -5)
        self.assertEqual(event.reason_code, 'customer_cancelled')
        self.assertFalse(order.lines)
        self.assertEqual(order.state, 'cancel')

    def test_regular_pos_user_can_confirm_own_company_kitchen_status(self):
        order = self._kitchen_order()
        event = self.env['baseer.print.preparation.event'].sudo().search([
            ('order_id', '=', order.id),
        ], limit=1)
        self.assertTrue(event)
        cashier = self.env['res.users'].create({
            'name': 'Kitchen status cashier',
            'login': 'kitchen-status-cashier',
            'company_id': self.company.id,
            'company_ids': [Command.set([self.company.id])],
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('point_of_sale.group_pos_user').id,
            ])],
        })
        status = self.env['baseer.print.preparation.event'].with_user(cashier).baseer_action_status(
            event.action_uuid, order.uuid,
        )
        self.assertTrue(status['accepted'])

    def test_last_kitchen_line_cancel_retains_draft_with_payment(self):
        order = self._kitchen_order()
        payment = self.env['pos.payment'].create({
            'pos_order_id': order.id, 'amount': 0,
            'payment_method_id': self.config.payment_method_ids[:1].id,
        })
        action = self._preparation_action(order, 1, 0, 'customer_cancelled')
        order.lines.qty = 0
        order.write({'amount_total': 0, 'amount_tax': 0})
        result = self.env['baseer.print.preparation.state']._apply_action(order, action)
        self.assertTrue(result['accepted'])
        self.assertTrue(result['event_ids'])
        self.assertFalse(order.lines)
        self.assertEqual(order.state, 'draft')
        self.assertEqual(order.payment_ids, payment)

    def test_last_kitchen_line_cancel_retains_nonzero_financial_balance(self):
        order = self._kitchen_order()
        order.lines.qty = 0
        # Deliberately stale financial total is not a safe empty order.
        self.assertNotEqual(order.amount_total, 0)
        self.env['baseer.print.preparation.state']._enqueue_order(
            order, str(uuid4()), 'customer_cancelled', '',
        )
        self.assertFalse(order.lines)
        self.assertEqual(order.state, 'draft')

    def test_cancel_five_then_add_one_has_complete_timeline(self):
        order = self._kitchen_order(quantity=5)
        original = order.lines.ensure_one()
        product = original.product_id
        keeper_product = self.env['product.template'].create({
            'name': 'Timeline keeper', 'available_in_pos': True, 'list_price': 1,
        }).product_variant_id
        self.env['pos.order.line'].create({
            'order_id': order.id,
            'product_id': keeper_product.id,
            'qty': 1,
            'price_unit': 1,
            'price_subtotal': 1,
            'price_subtotal_incl': 1,
            'full_product_name': keeper_product.display_name,
        })
        original.write({'qty': 0})
        cancel = {
            'action_uuid': str(uuid4()),
            'action_type': 'line_change',
            'lines': [{
                'line_uuid': original.uuid,
                'expected_quantity': 5,
                'new_quantity': 0,
                'reason_code': 'wrong_order',
                'reason_note': '',
            }],
        }
        State = self.env['baseer.print.preparation.state']
        State._apply_action(order, cancel)
        replacement = self.env['pos.order.line'].create({
            'order_id': order.id,
            'product_id': product.id,
            'uuid': str(uuid4()),
            'qty': 1,
            'price_unit': 10,
            'price_subtotal': 10,
            'price_subtotal_incl': 10,
            'full_product_name': product.display_name,
        })
        add_again = {
            'action_uuid': str(uuid4()),
            'action_type': 'line_change',
            'lines': [{
                'line_uuid': replacement.uuid,
                'expected_quantity': 0,
                'new_quantity': 1,
                'reason_code': '',
                'reason_note': '',
            }],
        }
        State._apply_action(order, add_again)
        timeline = self.env['baseer.print.preparation.event'].sudo().search([
            ('order_id', '=', order.id), ('product_id', '=', product.id),
        ], order='id')
        self.assertEqual(timeline.mapped('action'), ['new', 'cancel', 'new'])
        self.assertEqual(timeline.mapped('new_quantity'), [5, 0, 1])

    def test_preparation_action_is_idempotent_and_rejects_stale_quantity(self):
        self._enable()
        self.env['baseer.print.route'].create({
            'pos_config_id': self.config.id, 'printer_id': self.kitchen_a.id,
            'pos_category_id': False, 'copies': 1,
        })
        order = self._order(5)
        State = self.env['baseer.print.preparation.state']
        action = self._preparation_action(order, 0, 5)
        State._apply_action(order, action)
        retry = self.env['baseer.print.preparation.event']._retry_events(action)
        self.assertEqual(len(retry), 1)
        self.assertEqual(len(retry.job_ids), 1)
        stale = self._preparation_action(order, 4, 1)
        order.lines.write({'qty': 1})
        with self.assertRaises(ValidationError):
            State._apply_action(order, stale)

    def test_preparation_event_is_immutable_and_free_product_is_allowed(self):
        self._enable()
        self.env['baseer.print.route'].create({
            'pos_config_id': self.config.id, 'printer_id': self.kitchen_a.id,
            'pos_category_id': False, 'copies': 1,
        })
        order = self._order(1)
        order.lines.write({
            'price_unit': 0, 'price_subtotal': 0, 'price_subtotal_incl': 0,
        })
        action = self._preparation_action(order, 0, 1)
        result = self.env['baseer.print.preparation.state']._apply_action(order, action)
        event = self.env['baseer.print.preparation.event'].sudo().browse(result['event_ids'])
        self.assertEqual(event.action, 'new')
        with self.assertRaises(AccessError):
            event.write({'reason_note': 'changed'})
        with self.assertRaises(AccessError):
            event.unlink()
        with self.assertRaises(AccessError):
            self.env['baseer.print.preparation.event'].sudo().create({})

    def test_paid_and_refund_orders_reject_preparation_actions(self):
        self._enable()
        paid = self._order(1)
        paid.write({'state': 'paid'})
        with self.assertRaises(AccessError):
            self.env['baseer.print.preparation.state']._apply_action(
                paid, self._preparation_action(paid, 0, 1),
            )
        refund = self._order(1)
        refund.write({'is_refund': True})
        with self.assertRaises(AccessError):
            self.env['baseer.print.preparation.state']._apply_action(
                refund, self._preparation_action(refund, 0, 1),
            )

    def test_printed_kitchen_order_requires_atomic_cancellation(self):
        order = self._kitchen_order()
        with self.assertRaises(AccessError):
            order.action_pos_order_cancel()

        result = order.baseer_cancel_with_preparation(
            self.config.current_session_id.id, 'wrong_order', False)
        event = self.env['baseer.print.cancellation'].search([('order_id', '=', order.id)])
        jobs = self.env['baseer.print.job'].search([('cancellation_id', '=', event.id)])
        self.assertEqual(order.state, 'cancel')
        self.assertEqual(event.reason_code, 'wrong_order')
        self.assertEqual(len(jobs), 1)
        self.assertEqual(result['cancellation_ids'], [event.id])
        self.assertEqual(jobs.payload['cancellation']['reason_code'], 'wrong_order')
        self.assertEqual(jobs.payload['lines'][0]['action'], 'cancel')
        with self.assertRaises(AccessError):
            event.write({'reason_code': 'staff_error'})

    def test_batch_cancellation_keeps_each_order_reason(self):
        first = self._kitchen_order()
        second = self._order(1)
        second.session_id.write({'state': 'opened'})
        self.env['baseer.print.preparation.state']._enqueue_order(second, 'kitchen-second-send')
        (first | second).baseer_cancel_with_preparation_reasons(
            self.config.current_session_id.id,
            {
                str(first.id): {'reason_code': 'wrong_order', 'reason_note': ''},
                str(second.id): {'reason_code': 'staff_error', 'reason_note': ''},
            },
        )
        events = self.env['baseer.print.cancellation'].search([
            ('order_id', 'in', (first | second).ids),
        ])
        self.assertEqual(first.state, 'cancel')
        self.assertEqual(second.state, 'cancel')
        self.assertEqual(
            {event.order_id.id: event.reason_code for event in events},
            {first.id: 'wrong_order', second.id: 'staff_error'},
        )

    def test_batch_kitchen_cancel_rejects_payment_without_partial_cancellation(self):
        first = self._kitchen_order()
        second = self._order(1)
        self.env['baseer.print.preparation.state']._enqueue_order(second, str(uuid4()))
        payment = self.env['pos.payment'].create({
            'pos_order_id': second.id, 'amount': 0,
            'payment_method_id': self.config.payment_method_ids[:1].id,
        })
        with self.assertRaisesRegex(ValidationError, 'payments'):
            (first | second).baseer_cancel_with_preparation_reasons(
                first.session_id.id, {str(order.id): {'reason_code': 'wrong_order', 'reason_note': ''}
                                      for order in first | second},
            )
        self.assertEqual(first.state, 'draft')
        self.assertEqual(second.state, 'draft')
        self.assertEqual(second.payment_ids, payment)
        self.assertFalse(self.env['baseer.print.cancellation'].search([
            ('order_id', 'in', (first | second).ids),
        ]))

    def test_kitchen_cancel_rejects_refund_paid_balance_and_linked_move(self):
        order = self._kitchen_order()
        for vals in ({'amount_paid': 1}, {'amount_return': 1}, {'is_refund': True}):
            order.write(vals)
            with self.assertRaisesRegex(ValidationError, 'payments'):
                order.baseer_cancel_with_preparation(order.session_id.id, 'wrong_order', '')
            self.assertEqual(order.state, 'draft')
            order.write({'amount_paid': 0, 'amount_return': 0, 'is_refund': False})
        move = self.env['account.move'].create({
            'journal_id': self.config.invoice_journal_id.id, 'company_id': self.company.id,
        })
        order.account_move = move
        with self.assertRaisesRegex(ValidationError, 'invoice'):
            order.baseer_cancel_with_preparation(order.session_id.id, 'wrong_order', '')
        self.assertEqual(order.state, 'draft')
        self.assertFalse(self.env['baseer.print.cancellation'].search([('order_id', '=', order.id)]))

    def test_printed_kitchen_order_cannot_be_cancelled_by_direct_state_write(self):
        order = self._kitchen_order()
        with self.assertRaises(AccessError):
            order.write({'state': 'cancel'})
        self.assertEqual(order.state, 'draft')
        self.assertFalse(self.env['baseer.print.cancellation'].search([('order_id', '=', order.id)]))

    def test_printed_kitchen_order_cannot_be_deleted_without_cancellation_event(self):
        order = self._kitchen_order()
        with self.assertRaises(AccessError):
            order.unlink()
        self.assertTrue(order.exists())
        self.assertFalse(self.env['baseer.print.cancellation'].search([('order_id', '=', order.id)]))

    def test_other_cancellation_reason_requires_description(self):
        order = self._kitchen_order()
        with self.assertRaises(ValidationError):
            order.baseer_cancel_with_preparation(self.config.current_session_id.id, 'other', '')
        self.assertEqual(order.state, 'draft')
        self.assertFalse(self.env['baseer.print.cancellation'].search([('order_id', '=', order.id)]))

    def test_atomic_cancellation_rolls_back_when_native_cancel_fails(self):
        order = self._kitchen_order()
        with self.env.cr.savepoint(), patch.object(type(order), '_baseer_native_action_pos_order_cancel', side_effect=AccessError('native failure')):
            with self.assertRaises(AccessError):
                order.baseer_cancel_with_preparation(self.config.current_session_id.id, 'staff_error', False)
        self.assertEqual(order.state, 'draft')
        self.assertFalse(self.env['baseer.print.cancellation'].search([('order_id', '=', order.id)]))
        self.assertFalse(self.env['baseer.print.job'].search([('source_order_id', '=', order.id), ('cancellation_id', '!=', False)]))

    def test_cancellation_requires_the_matching_open_session(self):
        order = self._kitchen_order()
        other_config = self.env['pos.config'].create({'name': 'Cancellation other POS'})
        other_config.open_ui()
        with self.assertRaises(AccessError):
            order.baseer_cancel_with_preparation(other_config.current_session_id.id, 'staff_error', False)
        self.assertEqual(order.state, 'draft')

    def test_offline_agent_keeps_cancellation_job_pending(self):
        order = self._kitchen_order()
        self.agent.with_context(baseer_print_internal=True).write({'state': 'offline'})
        order.baseer_cancel_with_preparation(self.config.current_session_id.id, 'customer_cancelled', False)
        job = self.env['baseer.print.job'].search([('source_order_id', '=', order.id), ('cancellation_id', '!=', False)])
        self.assertEqual(job.state, 'pending')

    def _closed_session_with_report(self):
        self._enable()
        self.config.baseer_print_session_close_report = True
        order = self._order(3)
        payment_method = self.config.payment_method_ids[:1]
        self.assertTrue(payment_method)
        self.env['pos.payment'].create({
            'pos_order_id': order.id,
            'payment_method_id': payment_method.id,
            'amount': 30,
        })
        order.write({'state': 'done', 'amount_paid': 30})
        cancelled = self._order(1)
        cancelled.write({'state': 'cancel'})
        session = order.session_id
        session.write({
            'start_at': fields.Datetime.now() - timedelta(hours=2, minutes=15),
            'stop_at': fields.Datetime.now(),
            'state': 'closed',
        })
        return session, payment_method

    def test_session_closing_report_is_aggregate_idempotent_and_complete(self):
        session, payment_method = self._closed_session_with_report()
        Job = self.env['baseer.print.job']
        with patch.object(type(session), '_get_closed_orders', side_effect=AssertionError('must not load orders')):
            first = Job._enqueue_session_close(session)
            second = Job._enqueue_session_close(session)
        self.assertEqual(first, second)
        self.assertEqual(first.ticket_type, 'session_close')
        self.assertEqual(first.source_session_id, session)
        self.assertEqual(first.payload['printer']['copies'], 1)
        self.assertEqual(first.payload['summary']['invoice_count'], 1)
        self.assertEqual(first.payload['summary']['refund_count'], 0)
        self.assertEqual(first.payload['summary']['payment_total'], '30.00')
        self.assertEqual(first.payload['summary']['total_amount'], '30.00')
        self.assertEqual(first.payload['summary']['average_invoice'], '30.00')
        self.assertEqual(first.payload['summary']['cancelled_orders'], 1)
        self.assertEqual(first.payload['summary']['cancellation_count'], 1)
        self.assertEqual(first.payload['session']['duration_label'], '02:15')
        self.assertEqual(first.payload['payments'], [{
            'method': payment_method.display_name,
            'amount': '30.00',
        }])

    def test_whatsapp_closing_report_shows_invoice_and_guest_averages(self):
        session, _payment_method = self._closed_session_with_report()
        session.order_ids.filtered(lambda order: order.state != 'cancel').write({'customer_count': 3})

        action = session.action_baseer_open_whatsapp_closing_report()
        report = parse_qs(urlparse(action['url']).query)['text'][0]

        self.assertIn('معدل الفاتورة: 30.00', report)
        self.assertIn('إجمالي الضيوف: 3', report)
        self.assertIn('متوسط إنفاق الضيف: 10.00', report)

    def test_session_closing_report_can_be_enqueued_by_regular_pos_user(self):
        session, _payment_method = self._closed_session_with_report()
        pos_user = self.env['res.users'].create({
            'name': 'Closing report cashier',
            'login': 'closing-report-cashier',
            'company_id': self.company.id,
            'company_ids': [Command.set([self.company.id])],
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('point_of_sale.group_pos_user').id,
            ])],
        })
        job = self.env['baseer.print.job'].with_user(pos_user)._enqueue_session_close(
            session.with_user(pos_user)
        )
        self.assertEqual(job.source_session_id, session)
        self.assertEqual(job.payload['summary']['invoice_count'], 1)

    def test_session_closing_report_original_is_unique_when_printer_changes(self):
        session, _payment_method = self._closed_session_with_report()
        Job = self.env['baseer.print.job']
        original = Job._enqueue_session_close(session)
        original.idempotency_key = Job._canonical_key('session-close', session.id, self.receipt.id)
        self.config.baseer_receipt_printer_id = self.kitchen_b
        repeated = Job._enqueue_session_close(session)
        self.assertEqual(repeated, original)
        self.assertEqual(repeated.printer_id, self.receipt)

    def test_session_closing_report_is_not_created_before_successful_close(self):
        self._enable()
        self.config.baseer_print_session_close_report = True
        session = self._order().session_id
        self.assertNotEqual(session.state, 'closed')
        self.assertFalse(self.env['baseer.print.job']._enqueue_session_close(session))

    def test_session_closing_report_counts_authoritative_refund_flag(self):
        self._enable()
        self.config.baseer_print_session_close_report = True
        refund = self._order(1)
        refund.write({'state': 'done', 'amount_total': 0, 'is_refund': True})
        session = refund.session_id
        session.write({'state': 'closed', 'stop_at': fields.Datetime.now()})
        payload = self.env['baseer.print.job']._session_close_payload(session, self.receipt)
        self.assertEqual(payload['summary']['invoice_count'], 1)
        self.assertEqual(payload['summary']['refund_count'], 1)

    def test_manager_recovery_reprints_a_terminal_session_report_once(self):
        session, _payment_method = self._closed_session_with_report()
        original = self.env['baseer.print.job']._enqueue_session_close(session)
        original.write({'state': 'done', 'completed_at': fields.Datetime.now()})
        action = session.action_baseer_print_closing_report()
        reprint = self.env['baseer.print.job'].browse(action['res_id'])
        self.assertEqual(reprint.reprint_of_id, original)
        self.assertEqual(reprint.source_session_id, session)
        self.assertEqual(reprint.payload, original.payload)
