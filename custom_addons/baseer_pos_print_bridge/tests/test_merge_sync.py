"""Native UI serialization cannot write protected restaurant merge state."""

from copy import deepcopy
from uuid import uuid4

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged

from . import test_payment_integrity, test_print_bridge


MERGE_FIELDS = (
    'baseer_merged_into_order_id', 'baseer_merge_destination_id',
    'baseer_merge_expected_quantities', 'baseer_merge_expected_total',
)


@tagged('post_install', '-at_install', 'baseer_merge_sync')
class TestBaseerMergeSync(TransactionCase):
    _line = test_payment_integrity.TestBaseerPaymentIntegrity._line
    _draft = test_payment_integrity.TestBaseerPaymentIntegrity._draft
    _payload = test_payment_integrity.TestBaseerPaymentIntegrity._payload
    _native_receipt_sample = test_print_bridge.TestBaseerPrintBridgeHybrid._native_receipt_sample

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.currency = cls.company.currency_id
        cls.income = cls.env['account.account'].create({
            'name': 'Merge sync synthetic income', 'code': '987641',
            'account_type': 'income', 'company_ids': [Command.set(cls.company.ids)],
        })
        cls.tax = cls.env['account.tax'].create({
            'name': 'Merge sync synthetic VAT', 'amount': 15, 'amount_type': 'percent',
            'type_tax_use': 'sale', 'company_id': cls.company.id,
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Merge sync synthetic service', 'type': 'service',
            'available_in_pos': True, 'list_price': 100,
            'property_account_income_id': cls.income.id,
            'taxes_id': [Command.set(cls.tax.ids)],
        })
        cls.agent = cls.env['baseer.print.agent'].create({
            'name': 'Merge sync synthetic agent', 'device_uid': 'merge-sync-agent-' + uuid4().hex,
            'allowed_company_ids': [Command.set(cls.company.ids)],
        })
        cls.agent.with_context(baseer_print_internal=True).write({
            'state': 'online', 'agent_version': '1.4.6',
        })
        cls.printer = cls.env['baseer.print.printer'].with_context(baseer_print_discovery=True).create({
            'name': 'Merge sync synthetic printer', 'agent_id': cls.agent.id,
            'machine_identifier': 'MERGE-SYNC-' + uuid4().hex, 'active': True,
            'allowed_company_ids': [Command.set(cls.company.ids)],
        })
        cls.config = cls.env['pos.config'].create({
            'name': 'Merge sync native POS', 'baseer_direct_print_enabled': True,
            'baseer_receipt_printer_id': cls.printer.id, 'baseer_native_receipt_enabled': False,
        })
        cls.env['baseer.print.route'].create({
            'pos_config_id': cls.config.id, 'printer_id': cls.printer.id,
        })
        cls.config.open_ui()
        cls.session = cls.config.current_session_id
        cls.session.set_opening_control(0, 'Merge sync native fixture')
        cls.method = cls.config.payment_method_ids[:1]
        cls.cashier = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Merge sync POS cashier', 'login': 'merge-sync-' + uuid4().hex,
            'company_id': cls.company.id, 'company_ids': [Command.set(cls.company.ids)],
            'group_ids': [Command.set([
                cls.env.ref('base.group_user').id,
                cls.env.ref('point_of_sale.group_pos_user').id,
            ])],
        })

    def setUp(self):
        super().setUp()
        self.Pos = self.env['pos.order'].with_user(self.cashier).with_context(
            allowed_company_ids=self.company.ids,
        )
        self.assertFalse(self.Pos.env.su)
        self.assertFalse(self.cashier.has_group('point_of_sale.group_pos_manager'))

    @staticmethod
    def _empty_echo(total=False):
        return {**dict.fromkeys(MERGE_FIELDS, False), 'baseer_merge_expected_total': total}

    def _draft_payload(self, order=None, lines=None, total=115, tax=15):
        payload = self._payload(order, lines=lines, total=total, tax=tax)
        payload.update({'state': 'draft', 'amount_paid': 0, 'payment_ids': []})
        return payload

    def _sync(self, payload):
        self.Pos.sync_from_ui([deepcopy(payload)])
        order = self.Pos.search([('uuid', '=', payload['uuid'])])
        self.assertEqual(len(order), 1)
        return order

    def _merge_values(self, order):
        return {
            'baseer_merged_into_order_id': order.baseer_merged_into_order_id.id or False,
            'baseer_merge_destination_id': order.baseer_merge_destination_id.id or False,
            'baseer_merge_expected_quantities': deepcopy(order.baseer_merge_expected_quantities),
            'baseer_merge_expected_total': order.baseer_merge_expected_total,
        }

    def test_native_empty_serialization_creates_draft_order(self):
        payload = {**self._draft_payload(), **self._empty_echo()}
        order = self._sync(payload)
        self.assertEqual(order.state, 'draft')
        self.assertEqual((order.amount_total, order.amount_tax), (115, 15))
        self.assertEqual(len(order.lines), 1)
        self.assertFalse(order.baseer_merge_destination_id)
        self.assertFalse(order.baseer_merge_expected_quantities)
        self.assertEqual(order.baseer_merge_expected_total, 0)

    def test_draft_update_and_kitchen_action_accept_explicit_zero_defaults(self):
        order = self._sync({**self._draft_payload(), **self._empty_echo()})
        line = order.lines
        action = {
            'action_uuid': str(uuid4()), 'action_type': 'send',
            'lines': [{'line_uuid': line.uuid, 'expected_quantity': 0,
                       'new_quantity': 2, 'reason_code': '', 'reason_note': ''}],
        }
        payload = self._draft_payload(order, total=230, tax=30, lines=[Command.update(line.id, {
            'qty': 2, 'price_subtotal': 200, 'price_subtotal_incl': 230,
        })])
        payload.update(self._empty_echo(total=0))
        payload['baseer_preparation_action'] = action
        updated = self._sync(payload)
        self.assertEqual(updated, order)
        self.assertEqual((order.state, order.amount_total, order.lines.qty), ('draft', 230, 2))
        state = self.env['baseer.print.preparation.state'].search([('order_id', '=', order.id)])
        self.assertTrue(state)
        self.assertEqual(state.quantity, 2)
        attempt = self.env['baseer.print.preparation.attempt']._for_action(action['action_uuid'])
        self.assertEqual(attempt.outcome, 'accepted')

    def test_native_paid_sync_accepts_defaults_and_receipt_status(self):
        self.company.country_id = self.env.ref('base.us')
        self.config.baseer_native_receipt_enabled = True
        payload = {**self._payload(), **self._empty_echo()}
        order = self._sync(payload)
        self.assertEqual((order.state, order.amount_total, order.amount_tax, order.amount_paid),
                         ('paid', 115, 15, 115))
        self.assertFalse(self.printer.with_user(self.cashier).has_access('read'))
        financial_fields = [
            'state', 'amount_total', 'amount_tax', 'amount_paid', 'amount_return',
            'lines', 'payment_ids', 'account_move',
        ]
        financial = order.read(financial_fields)
        # Native POS prints after paid sync by uploading its original JPEG.
        # Its public RPC keeps hardware metadata private from the cashier.
        receipt = order.baseer_enqueue_native_receipt(self._native_receipt_sample())
        self.assertTrue(receipt['job_id'])
        status = order.baseer_customer_receipt_status()
        self.assertTrue(status['job_id'])
        self.assertEqual(status['job_id'], receipt['job_id'])
        self.assertFalse(status['error'])
        job = self.env['baseer.print.job'].browse(status['job_id'])
        self.assertEqual(job.source_order_id.id, order.id)
        self.assertEqual(job.ticket_type, 'receipt')
        self.assertEqual(job.payload['schema'], 4)
        self.assertEqual(order.read(financial_fields), financial)

    def test_exact_pending_merge_echo_preserves_server_values_and_rejects_changes(self):
        source = self._draft()
        # Keep a native POS line shape while making the merged quantity 1.0;
        # the JS serializer will echo that server float as the integer 1.
        destination = self._draft(lines=[self._line(quantity=0)])
        source.baseer_enqueue_preparation_jobs(str(uuid4()))
        result = source.baseer_begin_restaurant_merge(destination.id)
        self.assertTrue(result['requires_transfer'])
        expected = self._merge_values(source)
        self.assertEqual(expected['baseer_merge_destination_id'], destination.id)
        js_quantities = {
            key: int(value) if isinstance(value, float) and value.is_integer() else value
            for key, value in expected['baseer_merge_expected_quantities'].items()
        }
        one_key = next(key for key, value in js_quantities.items() if type(value) is int and value == 1)
        self.assertIs(type(expected['baseer_merge_expected_quantities'][one_key]), float)
        payload = {
            **self._draft_payload(source, lines=[]), **expected,
            'baseer_merge_expected_quantities': js_quantities,
        }
        self.assertEqual(self._sync(payload), source)
        self.assertEqual(self._merge_values(source), expected)
        bool_payload = {
            **payload, 'baseer_merge_expected_quantities': {**js_quantities, one_key: True},
        }
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            self.Pos.sync_from_ui([deepcopy(bool_payload)])
        self.assertEqual(self._merge_values(source), expected)
        changes = {
            'baseer_merged_into_order_id': destination.id,
            'baseer_merge_destination_id': False,
            'baseer_merge_expected_quantities': {},
            'baseer_merge_expected_total': expected['baseer_merge_expected_total'] + .01,
        }
        for field, value in changes.items():
            with self.subTest(field=field):
                altered = {**payload, field: value}
                with self.assertRaises(AccessError), self.env.cr.savepoint():
                    self.Pos.sync_from_ui([deepcopy(altered)])
                self.assertEqual(self._merge_values(source), expected)

    def test_nondefault_merge_payloads_and_direct_orm_presence_stay_protected(self):
        existing = self._draft()
        for field, value in (
                ('baseer_merged_into_order_id', existing.id),
                ('baseer_merge_destination_id', existing.id),
                ('baseer_merge_expected_quantities', {str(self.product.id): 1}),
                ('baseer_merge_expected_total', 1)):
            with self.subTest(field=field):
                payload = {**self._draft_payload(), **self._empty_echo(), field: value}
                with self.assertRaises(AccessError), self.env.cr.savepoint():
                    self.Pos.sync_from_ui([deepcopy(payload)])
                self.assertFalse(self.Pos.search([('uuid', '=', payload['uuid'])]))
                with self.assertRaises(AccessError), self.env.cr.savepoint():
                    self.Pos.create({'session_id': self.session.id, field: False})
                with self.assertRaises(AccessError), self.env.cr.savepoint():
                    existing.write({field: False})

    def test_monetary_defaults_reject_strings_booleans_and_nonfinite_values(self):
        for value in ('0', 'False', '', True, float('nan'), float('inf'), -float('inf')):
            with self.subTest(value=repr(value)):
                payload = {**self._draft_payload(), **self._empty_echo(total=value)}
                with self.assertRaises(AccessError), self.env.cr.savepoint():
                    self.Pos.sync_from_ui([deepcopy(payload)])
                self.assertFalse(self.Pos.search([('uuid', '=', payload['uuid'])]))
