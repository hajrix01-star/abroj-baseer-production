"""Atomic native bill splitting preserves financial items and kitchen routing."""

from copy import deepcopy
from uuid import uuid4

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged

from . import test_payment_integrity


@tagged('post_install', '-at_install', 'baseer_native_split')
class TestBaseerNativeSplit(TransactionCase):
    _line = test_payment_integrity.TestBaseerPaymentIntegrity._line
    _payload = test_payment_integrity.TestBaseerPaymentIntegrity._payload

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.currency = cls.company.currency_id
        cls.income = cls.env['account.account'].create({
            'name': 'Native split income', 'code': '987649', 'account_type': 'income',
            'company_ids': [Command.set(cls.company.ids)],
        })
        cls.tax = cls.env['account.tax'].create({
            'name': 'Native split VAT', 'amount': 15, 'amount_type': 'percent',
            'type_tax_use': 'sale', 'company_id': cls.company.id,
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Native split service', 'type': 'service', 'available_in_pos': True,
            'list_price': 100, 'property_account_income_id': cls.income.id,
            'taxes_id': [Command.set(cls.tax.ids)],
        })
        cls.agent = cls.env['baseer.print.agent'].create({
            'name': 'Native split agent', 'device_uid': 'split-' + uuid4().hex,
            'allowed_company_ids': [Command.set(cls.company.ids)],
        })
        cls.agent.with_context(baseer_print_internal=True).write({'state': 'online', 'agent_version': '1.4.6'})
        cls.printer = cls.env['baseer.print.printer'].with_context(baseer_print_discovery=True).create({
            'name': 'Native split printer', 'agent_id': cls.agent.id,
            'machine_identifier': 'SPLIT-' + uuid4().hex, 'active': True,
            'allowed_company_ids': [Command.set(cls.company.ids)],
        })
        cls.config = cls.env['pos.config'].create({
            'name': 'Native split POS', 'iface_splitbill': True,
            'baseer_direct_print_enabled': True, 'baseer_receipt_printer_id': cls.printer.id,
        })
        cls.env['baseer.print.route'].create({'pos_config_id': cls.config.id, 'printer_id': cls.printer.id})
        cls.config.open_ui()
        cls.session = cls.config.current_session_id
        cls.session.set_opening_control(0, 'Native split fixture')
        cls.method = cls.config.payment_method_ids[:1]
        cls.cashier = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Native split cashier', 'login': 'split-' + uuid4().hex,
            'company_id': cls.company.id, 'company_ids': [Command.set(cls.company.ids)],
            'group_ids': [Command.set([cls.env.ref('base.group_user').id,
                                     cls.env.ref('point_of_sale.group_pos_user').id])],
        })

    def setUp(self):
        super().setUp()
        self.Pos = self.env['pos.order'].with_user(self.cashier).with_context(allowed_company_ids=self.company.ids)
        self.assertFalse(self.Pos.env.su)

    def _draft_payload(self, order=None, lines=None, total=115, tax=15):
        values = self._payload(order=order, lines=lines, total=total, tax=tax)
        values.update({'state': 'draft', 'amount_paid': 0, 'payment_ids': []})
        return values

    def _split_case(self, sent=True):
        payload = self._draft_payload(lines=[Command.create(self._line(quantity=2))], total=230, tax=30)
        self.Pos.sync_from_ui([payload])
        source = self.Pos.search([('uuid', '=', payload['uuid'])])
        if sent:
            self.env['baseer.print.preparation.state']._enqueue_order(source, str(uuid4()))
        source_line = source.lines
        selected = self._line()
        request = {'source_uuid': source.uuid, 'target_uuid': str(uuid4()),
                   'baseline': source.baseer_prepare_bill_split(),
                   'lines': [{'source_uuid': source_line.uuid, 'target_uuid': selected['uuid'], 'quantity': 1}]}
        original = self._draft_payload(source, lines=[Command.update(source_line.id, {
            'qty': 1, 'price_subtotal': 100, 'price_subtotal_incl': 115,
        })])
        child = self._draft_payload(lines=[Command.create(selected)])
        child['uuid'] = request['target_uuid']
        return source, request, [original, child]

    def _apply(self, request, orders):
        return self.Pos.with_context(baseer_native_split=deepcopy(request)).sync_from_ui(deepcopy(orders))

    def _states(self, orders):
        return self.env['baseer.print.preparation.state']._states_for_orders(orders)

    def test_sent_split_transfers_state_without_new_kitchen_ticket(self):
        source, request, payloads = self._split_case()
        before_jobs = self.env['baseer.print.job'].search_count([])
        self._apply(request, payloads)
        child = self.Pos.search([('uuid', '=', request['target_uuid'])])
        self.assertEqual(source.lines.qty, 1)
        self.assertEqual(child.lines.qty, 1)
        self.assertEqual((source.amount_total, child.amount_total), (115, 115))
        states = self._states(source | child)
        self.assertEqual(len(states), 2)
        self.assertTrue(all(state.quantity == 1 for state in states))
        self.assertEqual(states.printer_id, self.printer)
        self.assertEqual(self.env['baseer.print.job'].search_count([]), before_jobs)
        self.assertEqual(child.baseer_split_receipt['source_uuid'], source.uuid)

    def test_unsent_split_does_not_invent_kitchen_history(self):
        source, request, payloads = self._split_case(sent=False)
        self._apply(request, payloads)
        child = self.Pos.search([('uuid', '=', request['target_uuid'])])
        self.assertFalse(self._states(source | child))
        self.assertEqual(source.lines.qty + child.lines.qty, 2)

    def test_exact_retry_after_child_payment_returns_canonical_without_reapplying(self):
        source, request, payloads = self._split_case()
        self._apply(request, payloads)
        child = self.Pos.search([('uuid', '=', request['target_uuid'])])
        child.write({'state': 'paid', 'amount_paid': 115})
        before_states = self._states(source | child).read(['order_id', 'line_uuid', 'quantity'])
        result = self._apply(request, payloads)
        self.assertEqual(child.state, 'paid')
        self.assertEqual(child.amount_paid, 115)
        self.assertEqual(self._states(source | child).read(['order_id', 'line_uuid', 'quantity']), before_states)
        self.assertEqual({item['uuid'] for item in result['pos.order']}, {source.uuid, child.uuid})

    def test_changed_retry_is_rejected(self):
        _source, request, payloads = self._split_case()
        self._apply(request, payloads)
        payloads[1]['amount_total'] = 1
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._apply(request, payloads)

    def test_stale_baseline_creates_no_child(self):
        source, request, payloads = self._split_case()
        source.lines.write({'price_unit': 101})
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._apply(request, payloads)
        self.assertFalse(self.Pos.search([('uuid', '=', request['target_uuid'])]))
        self.assertEqual(source.lines.qty, 2)

    def test_invalid_target_items_roll_back_native_pair_sync(self):
        source, request, payloads = self._split_case()
        payloads[1]['lines'][0][2]['qty'] = 2
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._apply(request, payloads)
        self.assertFalse(self.Pos.search([('uuid', '=', request['target_uuid'])]))
        self.assertEqual(source.lines.qty, 2)
        self.assertEqual(self._states(source).quantity, 2)

    def test_duplicate_map_and_forged_receipt_are_rejected(self):
        source, request, payloads = self._split_case()
        request['lines'].append(deepcopy(request['lines'][0]))
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._apply(request, payloads)
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            source.write({'baseer_split_receipt': {'digest': 'forged'}})
        payload = self._draft_payload()
        payload['baseer_split_receipt'] = {'digest': 'forged'}
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            self.Pos.sync_from_ui([payload])

    def test_forged_quantities_and_source_uuid_reuse_are_rejected(self):
        source, request, payloads = self._split_case()
        for quantity in (True, float('nan'), float('inf'), -1, 0, 3, 1.5):
            forged = deepcopy(request)
            forged['lines'][0]['quantity'] = quantity
            with self.subTest(quantity=quantity), self.assertRaises(ValidationError), self.env.cr.savepoint():
                self._apply(forged, payloads)
            self.assertEqual(source.lines.qty, 2)
            self.assertFalse(self.Pos.search([('uuid', '=', request['target_uuid'])]))
        forged = deepcopy(request)
        forged['lines'][0]['target_uuid'] = source.lines.uuid
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._apply(forged, payloads)

    def test_foreign_company_cannot_prepare_or_submit_split(self):
        source, request, payloads = self._split_case()
        other_company = self.env['res.company'].create({'name': 'Native split isolated other company'})
        other_cashier = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Other company split cashier', 'login': 'split-foreign-' + uuid4().hex,
            'company_id': other_company.id, 'company_ids': [Command.set(other_company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id,
                                     self.env.ref('point_of_sale.group_pos_user').id])],
        })
        other_source = source.with_user(other_cashier).with_context(allowed_company_ids=other_company.ids)
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            other_source.baseer_prepare_bill_split()
        other_pos = self.Pos.with_user(other_cashier).with_context(allowed_company_ids=other_company.ids)
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            other_pos.with_context(baseer_native_split=request).sync_from_ui(deepcopy(payloads))

    def test_full_selection_is_rejected_before_native_mutation(self):
        source, request, payloads = self._split_case()
        request['lines'][0]['quantity'] = 2
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._apply(request, payloads)
        self.assertEqual(source.lines.qty, 2)
        self.assertEqual(self._states(source).quantity, 2)
        self.assertFalse(self.Pos.search([('uuid', '=', request['target_uuid'])]))

    def test_paid_source_and_foreign_session_are_rejected(self):
        source, request, payloads = self._split_case()
        payloads[1]['session_id'] = 0
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._apply(request, payloads)
        source.write({'state': 'paid', 'amount_paid': 230})
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            source.baseer_prepare_bill_split()

    def test_disabled_feature_and_non_pos_user_are_rejected(self):
        source, _request, _payloads = self._split_case()
        source.config_id.sudo().write({'iface_splitbill': False})
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            source.baseer_prepare_bill_split()
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Native split non cashier', 'login': 'split-non-pos-' + uuid4().hex,
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        })
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            source.with_user(user).baseer_prepare_bill_split()

    def test_native_readonly_receipt_echo_is_accepted_but_changed_echo_is_not(self):
        _source, request, payloads = self._split_case()
        self._apply(request, payloads)
        child = self.Pos.search([('uuid', '=', request['target_uuid'])])
        echo = self._draft_payload(child, lines=[])
        echo['baseer_split_receipt'] = deepcopy(child.baseer_split_receipt)
        self.Pos.sync_from_ui([deepcopy(echo)])
        echo['baseer_split_receipt']['digest'] = 'forged'
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            self.Pos.sync_from_ui([echo])
