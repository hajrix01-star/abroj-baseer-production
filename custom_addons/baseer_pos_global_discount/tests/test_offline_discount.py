from copy import deepcopy
import json
from uuid import uuid4
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged



@tagged('post_install', '-at_install', 'baseer_offline_discount')
class TestOfflineDiscountSync(TransactionCase):
    def setUp(self):
        super().setUp()
        self.account = self.env['account.account'].create({
            'name': 'Offline discount income', 'code': 'OFFGD001', 'account_type': 'income',
            'company_ids': [Command.set(self.env.company.ids)],
        })
        self.tax = self.env['account.tax'].create({
            'name': 'Offline VAT', 'amount': 15, 'amount_type': 'percent',
            'type_tax_use': 'sale', 'company_id': self.env.company.id,
        })
        self.product = self.env['product.product'].create({
            'name': 'Offline service', 'type': 'service', 'available_in_pos': True,
            'list_price': 100, 'property_account_income_id': self.account.id,
            'taxes_id': [Command.set(self.tax.ids)],
        })
        self.config = self.env['pos.config'].create({
            'name': 'Offline discount fixture', 'baseer_global_discount_account_id': self.account.id,
        })
        self.config.action_baseer_setup_global_discount()
        self.cash = self.config.payment_method_ids.filtered('is_cash_count')[:1]
        if not self.cash:
            journal = self.env['account.journal'].search([
                ('company_id', '=', self.env.company.id), ('type', '=', 'cash'),
                ('pos_payment_method_ids', '=', False),
            ], limit=1)
            if not journal:
                journal = self.env['account.journal'].create({
                    'name': 'Offline Cash', 'code': 'OFC', 'type': 'cash',
                    'company_id': self.env.company.id,
                })
            self.cash = self.env['pos.payment.method'].create({'name': 'Offline Cash', 'journal_id': journal.id})
            self.config.payment_method_ids = [Command.link(self.cash.id)]
        self.other_method = self.config.payment_method_ids.filtered(lambda method: method != self.cash)[:1]
        if not self.other_method:
            self.other_method = self.env['pos.payment.method'].create({'name': 'Offline Other'})
            self.config.payment_method_ids = [Command.link(self.other_method.id)]
        self.config.open_ui()
        self.session = self.config.current_session_id
        self.session.set_opening_control(0, 'Offline test')
        self.method = self.config.payment_method_ids[:1]

    def _payload(self, *, value='20', kind='fixed', total='95.00', tax='12.39'):
        order_uuid, preview_uuid = str(uuid4()), str(uuid4())
        product = self.product
        intent = {
            'version': 1, 'order_uuid': order_uuid, 'action_uuid': str(uuid4()),
            'kind': kind, 'value': value, 'expected_total': total, 'expected_tax': tax,
            'preview_line_uuids': [preview_uuid],
            'account_proof': self.config._gd_offline_account_proof(self.env['account.fiscal.position']),
        }
        return {
            'uuid': order_uuid, 'session_id': self.session.id, 'company_id': self.env.company.id,
            'user_id': self.env.uid, 'state': 'paid', 'to_invoice': False,
            'amount_total': float(total), 'amount_tax': float(tax), 'amount_paid': float(total), 'amount_return': 0,
            'baseer_offline_discount_intent': intent,
            'payment_ids': [Command.create({'payment_method_id': self.method.id, 'amount': float(total),
                                            'payment_date': fields.Datetime.now()})],
            'lines': [Command.create({
                'uuid': str(uuid4()), 'product_id': product.id, 'qty': 1, 'price_unit': 100,
                'price_subtotal': 100, 'price_subtotal_incl': 115, 'tax_ids': self.tax.ids,
            }), Command.create({
                'uuid': preview_uuid, 'product_id': self.config.baseer_global_discount_product_id.id,
                'qty': 1, 'price_unit': -17.39, 'price_subtotal': -17.39, 'price_subtotal_incl': -20,
                'tax_ids': self.tax.ids,
            })],
        }

    def test_paid_fixed_sync_rebuilds_and_retry_does_not_duplicate(self):
        payload = self._payload()
        self.env['pos.order'].sync_from_ui([deepcopy(payload)])
        order = self.env['pos.order'].search([('uuid', '=', payload['uuid'])])
        self.assertEqual(len(order), 1)
        self.assertEqual(order.baseer_global_discount_kind, 'fixed')
        self.assertEqual(len(order.lines.filtered('baseer_global_discount_line')), 1)
        self.assertAlmostEqual(order.amount_total, 95, places=2)
        self.assertAlmostEqual(order.amount_tax, 12.39, places=2)
        self.env['pos.order'].sync_from_ui([deepcopy(payload)])
        self.assertEqual(len(self.env['pos.order'].search([('uuid', '=', payload['uuid'])])), 1)
        self.assertEqual(len(order.payment_ids), 1)

    def test_paid_retry_rejects_changed_product_or_tender(self):
        payload = self._payload()
        self.env['pos.order'].sync_from_ui([deepcopy(payload)])
        for section in ('lines', 'payment_ids'):
            changed = deepcopy(payload)
            if section == 'lines':
                changed['lines'][0][2]['qty'] = 2
            else:
                changed['payment_ids'][0][2]['amount'] = 96
            with self.assertRaises(ValidationError), self.env.cr.savepoint():
                self.env['pos.order'].sync_from_ui([changed])
        order = self.env['pos.order'].search([('uuid', '=', payload['uuid'])])
        self.assertEqual(len(order.payment_ids), 1)
        self.assertAlmostEqual(order.amount_total, 95, places=2)

    def test_paid_retry_rejects_changed_command_replay(self):
        payload = self._payload()
        payload['payment_ids'][0][2]['uuid'] = str(uuid4())
        self.env['pos.order'].sync_from_ui([deepcopy(payload)])
        order = self.env['pos.order'].search([('uuid', '=', payload['uuid'])])
        source = order.lines.filtered(lambda line: not line.baseer_global_discount_line).ensure_one()
        payment = order.payment_ids.ensure_one()
        retry = deepcopy(payload)
        line_values = dict(retry['lines'][0][2], id=source.id)
        payment_values = dict(retry['payment_ids'][0][2], id=payment.id)
        retry['lines'][0] = Command.update(source.id, line_values)
        retry['payment_ids'][0] = Command.update(payment.id, payment_values)
        # Native frontend must replay its frozen original request after restart;
        # a regenerated payload cannot prove the exact collected sale.
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.env['pos.order'].sync_from_ui([json.loads(json.dumps(retry, default=str))])
        self.assertEqual(len(self.env['pos.order'].search([('uuid', '=', payload['uuid'])])), 1)
        self.assertEqual(len(order.payment_ids), 1)

    def test_cash_change_is_counted_once_in_net_paid(self):
        payload = self._payload()
        payload['amount_paid'] = 100
        payload['amount_return'] = -5
        payload['payment_ids'][0][2].update(payment_method_id=self.cash.id, amount=100)
        self.env['pos.order'].sync_from_ui([deepcopy(payload)])
        order = self.env['pos.order'].search([('uuid', '=', payload['uuid'])])
        self.assertEqual(len(order.payment_ids), 2)
        self.assertEqual(len(order.payment_ids.filtered('is_change')), 1)
        self.assertAlmostEqual(order.payment_ids.filtered('is_change').amount, -5, places=2)
        self.assertAlmostEqual(sum(order.payment_ids.mapped('amount')), 95, places=2)

    def test_split_cash_and_other_payment(self):
        payload = self._payload()
        payload['payment_ids'] = [
            Command.create({'payment_method_id': method.id, 'amount': amount,
                            'payment_date': fields.Datetime.now()})
            for method, amount in ((self.cash, 40), (self.other_method, 55))
        ]
        self.env['pos.order'].sync_from_ui([deepcopy(payload)])
        order = self.env['pos.order'].search([('uuid', '=', payload['uuid'])])
        self.assertEqual(len(order.payment_ids), 2)
        self.assertEqual(set(order.payment_ids.mapped('payment_method_id').ids), {self.cash.id, self.other_method.id})
        self.assertAlmostEqual(sum(order.payment_ids.mapped('amount')), 95, places=2)

    def test_full_discount_accepts_zero_tender(self):
        payload = self._payload(kind='percent', value='100', total='0.00', tax='0.00')
        payload['payment_ids'] = []
        payload['lines'][1][2].update(price_unit=-100, price_subtotal=-100, price_subtotal_incl=-115)
        self.env['pos.order'].sync_from_ui([deepcopy(payload)])
        order = self.env['pos.order'].search([('uuid', '=', payload['uuid'])])
        self.assertTrue(order.baseer_global_discount_locked)
        self.assertAlmostEqual(order.amount_total, 0, places=2)
        self.assertFalse(order.payment_ids)

    def test_synchronized_draft_can_change_then_pay(self):
        payload = self._payload()
        draft = deepcopy(payload)
        draft['state'] = 'draft'
        draft['payment_ids'] = []
        draft['amount_paid'] = 0
        draft['baseer_offline_draft_command'] = {'revision': 0, 'command_uuid': str(uuid4()), 'operation': 'set'}
        self.env['pos.order'].sync_from_ui([json.loads(json.dumps(draft, default=str))])
        existing = self.env['pos.order'].search([('uuid', '=', payload['uuid'])])
        self.assertEqual(existing.state, 'draft')
        self.assertFalse(existing.baseer_global_discount_locked)
        self.assertAlmostEqual(existing.amount_total, 95, places=2)
        paid = deepcopy(payload)
        paid['baseer_offline_draft_command'] = {'revision': 1, 'command_uuid': str(uuid4()), 'operation': 'keep'}
        paid['lines'][0][2].update(qty=2, price_subtotal=200, price_subtotal_incl=230)
        paid.update(amount_total=210, amount_tax=27.39, amount_paid=210)
        paid['payment_ids'][0][2]['amount'] = 210
        paid['baseer_offline_discount_intent'].update(expected_total='210.00', expected_tax='27.39')
        self.env['pos.order'].sync_from_ui([json.loads(json.dumps(paid, default=str))])
        self.assertTrue(existing.baseer_global_discount_locked)
        self.assertEqual(len(existing.lines.filtered(lambda line: not line.baseer_global_discount_line)), 1)
        self.assertAlmostEqual(existing.amount_total, 210, places=2)

    def test_synchronized_draft_removes_saved_line_before_paid_sync(self):
        payload = self._payload()
        draft = deepcopy(payload)
        draft.update(state='draft', payment_ids=[], amount_paid=0, amount_total=210, amount_tax=27.39)
        second = deepcopy(draft['lines'][0][2])
        second['uuid'] = str(uuid4())
        draft['lines'].insert(1, Command.create(second))
        draft['baseer_offline_discount_intent'].update(expected_total='210.00', expected_tax='27.39')
        draft['baseer_offline_draft_command'] = {'revision': 0, 'command_uuid': str(uuid4()), 'operation': 'set'}
        self.env['pos.order'].sync_from_ui([json.loads(json.dumps(draft, default=str))])
        existing = self.env['pos.order'].search([('uuid', '=', payload['uuid'])])
        removed = existing.lines.filtered(lambda line: line.uuid == second['uuid']).ensure_one()
        paid = deepcopy(payload)
        paid['baseer_offline_draft_command'] = {'revision': 1, 'command_uuid': str(uuid4()), 'operation': 'keep'}
        paid['lines'].append(Command.delete(removed.id))
        self.env['pos.order'].sync_from_ui([json.loads(json.dumps(paid, default=str))])
        self.assertTrue(existing.baseer_global_discount_locked)
        self.assertFalse(existing.lines.filtered(lambda line: line.uuid == second['uuid']))
        self.assertAlmostEqual(existing.amount_total, 95, places=2)

    def test_shared_draft_retry_conflict_removal_and_old_client(self):
        draft = self._payload()
        draft.update(state='draft', payment_ids=[], amount_paid=0)
        draft['baseer_offline_draft_command'] = {'revision': 0, 'command_uuid': str(uuid4()), 'operation': 'set'}
        draft = json.loads(json.dumps(draft, default=str))
        Pos = self.env['pos.order']
        Pos.sync_from_ui([deepcopy(draft)])
        order = Pos.search([('uuid', '=', draft['uuid'])])
        self.assertEqual(order.baseer_offline_draft_revision, 1)
        self.assertAlmostEqual(order.amount_total, 95, places=2)
        self.assertEqual(len(order.lines.filtered('baseer_global_discount_line')), 1)
        Pos.sync_from_ui([deepcopy(draft)])
        self.assertEqual(order.baseer_offline_draft_revision, 1)
        changed_retry = deepcopy(draft)
        changed_retry['lines'][0][2]['qty'] = 2
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            Pos.sync_from_ui([changed_retry])
        remove = deepcopy(draft)
        remove.pop('baseer_offline_discount_intent')
        remove['lines'] = []
        remove.update(amount_total=115, amount_tax=15)
        remove['baseer_offline_draft_command'] = {'revision': 1, 'command_uuid': str(uuid4()), 'operation': 'remove'}
        Pos.sync_from_ui([deepcopy(remove)])
        self.assertEqual(order.baseer_offline_draft_revision, 2)
        self.assertFalse(order.baseer_offline_draft_kind)
        self.assertAlmostEqual(order.amount_total, 115, places=2)
        self.assertFalse(order.lines.filtered('baseer_global_discount_line'))
        for stale in (draft, dict(remove, baseer_offline_draft_command={'revision': 1, 'command_uuid': str(uuid4()), 'operation': 'remove'})):
            with self.assertRaises(ValidationError), self.env.cr.savepoint():
                Pos.sync_from_ui([deepcopy(stale)])
        old_client = dict(remove)
        old_client.pop('baseer_offline_draft_command')
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            Pos.sync_from_ui([old_client])
        self.assertEqual(order.baseer_offline_draft_revision, 2)

    def test_shared_draft_change_and_protected_crud(self):
        draft = self._payload()
        draft.update(state='draft', payment_ids=[], amount_paid=0)
        draft['baseer_offline_draft_command'] = {'revision': 0, 'command_uuid': str(uuid4()), 'operation': 'set'}
        draft = json.loads(json.dumps(draft, default=str))
        Pos = self.env['pos.order']
        Pos.sync_from_ui([deepcopy(draft)])
        order = Pos.search([('uuid', '=', draft['uuid'])])
        with self.assertRaises(Exception), self.env.cr.savepoint():
            order.with_context(_baseer_draft_apply=True).write({'baseer_offline_draft_revision': 88})
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            order.lines.filtered('baseer_global_discount_line').unlink()
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.env['pos.payment'].create({'pos_order_id': order.id, 'payment_method_id': self.method.id, 'amount': 95})
        change = deepcopy(draft)
        change['baseer_offline_draft_command'] = {'revision': 1, 'command_uuid': str(uuid4()), 'operation': 'set'}
        change['baseer_offline_discount_intent'].update(kind='percent', value='10', expected_total='103.50', expected_tax='13.50')
        change['lines'][1][2].update(price_unit=-10, price_subtotal=-10, price_subtotal_incl=-11.50)
        change.update(amount_total=103.50, amount_tax=13.50)
        Pos.sync_from_ui([change])
        self.assertEqual(order.baseer_offline_draft_revision, 2)
        self.assertEqual(order.baseer_offline_draft_kind, 'percent')
        self.assertEqual(len(order.lines.filtered('baseer_global_discount_line')), 1)
        self.assertAlmostEqual(order.amount_total, 103.50, places=2)

    def test_shared_draft_stale_metadata_rejected_then_filtered_update_succeeds(self):
        draft = self._payload()
        draft.update(state='draft', payment_ids=[], amount_paid=0)
        draft['baseer_offline_draft_command'] = {'revision': 0, 'command_uuid': str(uuid4()), 'operation': 'set'}
        draft = json.loads(json.dumps(draft, default=str))
        Pos = self.env['pos.order']
        Pos.sync_from_ui([deepcopy(draft)])
        order = Pos.search([('uuid', '=', draft['uuid'])])
        before = (order.baseer_offline_draft_revision, order.amount_total, order.amount_tax,
                  sorted((line.id, line.uuid, line.qty, line.price_subtotal_incl) for line in order.lines))

        update = deepcopy(draft)
        update['baseer_offline_draft_command'] = {'revision': 1, 'command_uuid': str(uuid4()), 'operation': 'keep'}
        update['lines'][0][2].update(qty=2, price_subtotal=200, price_subtotal_incl=230)
        update.update(amount_total=210, amount_tax=27.39)
        update['baseer_offline_discount_intent'].update(expected_total='210.00', expected_tax='27.39')
        stale = deepcopy(update)
        stale.update(baseer_global_discount_kind=order.baseer_global_discount_kind,
                     baseer_global_discount_value=order.baseer_global_discount_value,
                     baseer_global_discount_gross=order.baseer_global_discount_gross)
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            Pos.sync_from_ui([stale])
        order.invalidate_recordset()
        self.assertEqual(before, (order.baseer_offline_draft_revision, order.amount_total, order.amount_tax,
                                  sorted((line.id, line.uuid, line.qty, line.price_subtotal_incl) for line in order.lines)))

        # A new command keeps intent and CAS, but omits server-owned fields.
        update['baseer_offline_draft_command']['command_uuid'] = str(uuid4())
        Pos.sync_from_ui([deepcopy(update)])
        self.assertEqual(order.baseer_offline_draft_revision, 2)
        self.assertEqual(order.baseer_offline_draft_kind, 'fixed')
        self.assertAlmostEqual(order.amount_total, 210, places=2)
        self.assertAlmostEqual(order.amount_tax, 27.39, places=2)
        self.assertEqual(len(order.lines.filtered('baseer_global_discount_line')), 1)
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            order.write({'baseer_global_discount_value': '99'})

    def test_shared_draft_terminal_status_and_payment_amount_guard(self):
        draft = self._payload()
        draft.update(state='draft', payment_ids=[], amount_paid=0)
        draft['baseer_offline_draft_command'] = {'revision': 0, 'command_uuid': str(uuid4()), 'operation': 'set'}
        draft = json.loads(json.dumps(draft, default=str))
        Pos = self.env['pos.order']
        Pos.sync_from_ui([deepcopy(draft)])
        order = Pos.search([('uuid', '=', draft['uuid'])])
        payment_draft = deepcopy(draft)
        payment_draft['baseer_offline_draft_command'] = {'revision': 1, 'command_uuid': str(uuid4()), 'operation': 'keep'}
        payment_draft['payment_ids'] = [[0, 0, {'uuid': str(uuid4()), 'payment_method_id': self.method.id,
                                                  'amount': 95, 'payment_status': 'waiting'}]]
        payment_draft['amount_paid'] = 95
        Pos.sync_from_ui([deepcopy(payment_draft)])
        payment = order.payment_ids.ensure_one()
        payment.write({'payment_status': 'done', 'transaction_id': 'synthetic-terminal-reference'})
        self.assertEqual(payment.payment_status, 'done')
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            payment.write({'amount': 94})
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            payment.unlink()
        self.assertEqual(payment.amount, 95)
        with self.assertRaisesRegex(ValidationError, 'payment or kitchen') , self.env.cr.savepoint():
            Pos.baseer_cancel_offline_draft(order.uuid, 2, str(uuid4()))
        self.assertEqual(order.state, 'draft')

    def test_shared_draft_cancellation_is_revisioned_and_idempotent(self):
        draft = self._payload()
        draft.update(state='draft', payment_ids=[], amount_paid=0)
        draft['baseer_offline_draft_command'] = {'revision': 0, 'command_uuid': str(uuid4()), 'operation': 'set'}
        draft = json.loads(json.dumps(draft, default=str))
        Pos = self.env['pos.order']
        Pos.sync_from_ui([deepcopy(draft)])
        order = Pos.search([('uuid', '=', draft['uuid'])])
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            Pos.baseer_cancel_offline_draft(order.uuid, 2, str(uuid4()))
        cancel_uuid = str(uuid4())
        result = Pos.baseer_cancel_offline_draft(order.uuid, 1, cancel_uuid)
        self.assertEqual(result, {'uuid': order.uuid, 'state': 'cancel', 'revision': 2})
        self.assertEqual(Pos.baseer_cancel_offline_draft(order.uuid, 1, cancel_uuid), result)
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            Pos.baseer_cancel_offline_draft(order.uuid, 2, str(uuid4()))
        legacy = deepcopy(draft)
        legacy.pop('baseer_offline_draft_command')
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            Pos.sync_from_ui([legacy])
        self.assertEqual(order.state, 'cancel')

    def test_shared_draft_cancellation_rejects_kitchen_history(self):
        draft = self._payload()
        draft.update(state='draft', payment_ids=[], amount_paid=0)
        draft['baseer_offline_draft_command'] = {'revision': 0, 'command_uuid': str(uuid4()), 'operation': 'set'}
        draft = json.loads(json.dumps(draft, default=str))
        Pos = self.env['pos.order']
        Pos.sync_from_ui([draft])
        order = Pos.search([('uuid', '=', draft['uuid'])])
        agent = self.env['baseer.print.agent'].create({
            'name': 'Synthetic kitchen', 'device_uid': str(uuid4()),
            'allowed_company_ids': [Command.set(self.env.company.ids)],
        })
        printer = self.env['baseer.print.printer'].with_context(baseer_print_discovery=True).create({
            'name': 'Synthetic kitchen printer', 'agent_id': agent.id, 'machine_identifier': str(uuid4()),
            'active': True, 'allowed_company_ids': [Command.set(self.env.company.ids)],
        })
        source = order.lines.filtered(lambda line: not line.baseer_global_discount_line).ensure_one()
        self.env['baseer.print.preparation.state'].sudo().create({
            'company_id': order.company_id.id, 'order_id': order.id, 'order_line_id': source.id,
            'line_uuid': source.uuid, 'product_id': source.product_id.id, 'printer_id': printer.id,
            'quantity': 1, 'details': {'line_uuid': source.uuid},
        })
        with self.assertRaisesRegex(ValidationError, 'payment or kitchen'), self.env.cr.savepoint():
            Pos.baseer_cancel_offline_draft(order.uuid, 1, str(uuid4()))
        self.assertEqual(order.state, 'draft')

    def _shared_kitchen_draft(self):
        draft = self._payload()
        draft.update(state='draft', payment_ids=[], amount_paid=0)
        draft['baseer_offline_draft_command'] = {'revision': 0, 'command_uuid': str(uuid4()), 'operation': 'set'}
        draft = json.loads(json.dumps(draft, default=str))
        self.env['pos.order'].sync_from_ui([draft])
        order = self.env['pos.order'].search([('uuid', '=', draft['uuid'])])
        agent = self.env['baseer.print.agent'].create({
            'name': 'Shared kitchen agent', 'device_uid': str(uuid4()),
            'allowed_company_ids': [Command.set(self.env.company.ids)],
        })
        agent.with_context(baseer_print_internal=True).write({'agent_version': '1.5.16'})
        printers = self.env['baseer.print.printer']
        for name in ('Kitchen A', 'Kitchen B'):
            printers |= printers.with_context(baseer_print_discovery=True).create({
                'name': name, 'agent_id': agent.id, 'machine_identifier': str(uuid4()),
                'active': True, 'paper_width': '80',
                'allowed_company_ids': [Command.set(self.env.company.ids)],
            })
        self.config.write({'baseer_receipt_printer_id': printers[0].id, 'baseer_direct_print_enabled': True})
        line = order.lines.filtered(lambda item: not item.baseer_global_discount_line).ensure_one()
        for printer in printers:
            self.env['baseer.print.preparation.state'].sudo().create({
                'company_id': order.company_id.id, 'order_id': order.id, 'order_line_id': line.id,
                'line_uuid': line.uuid, 'product_id': line.product_id.id, 'printer_id': printer.id,
                'quantity': 1, 'details': {'line_uuid': line.uuid, 'name': line.product_id.display_name},
            })
        return order

    def test_shared_kitchen_cancellation_is_atomic_and_idempotent(self):
        order = self._shared_kitchen_draft()
        Pos = self.env['pos.order']
        command_uuid = str(uuid4())
        kitchen = {'session_id': self.session.id, 'reason_code': 'wrong_order', 'reason_note': ''}
        # A command persisted by an older client was definitively rejected by
        # the old route. Reuse its exact UUID with the now-protected command.
        with self.assertRaisesRegex(ValidationError, 'payment or kitchen'), self.env.cr.savepoint():
            Pos.baseer_cancel_offline_draft(order.uuid, 1, command_uuid)
        result = Pos.baseer_cancel_offline_draft(order.uuid, 1, command_uuid, kitchen)
        self.assertEqual(result, {'uuid': order.uuid, 'state': 'cancel', 'revision': 2})
        Cancellation = self.env['baseer.print.cancellation'].sudo()
        Job = self.env['baseer.print.job'].sudo()
        cancellation = Cancellation.search([('order_id', '=', order.id)])
        self.assertEqual(len(cancellation), 1)
        self.assertEqual(cancellation.reason_code, 'wrong_order')
        jobs = Job.search([('cancellation_id', '=', cancellation.id)])
        self.assertEqual(len(jobs), 2)
        self.assertEqual(len(jobs.mapped('printer_id')), 2)
        self.assertEqual(Pos.baseer_cancel_offline_draft(order.uuid, 1, command_uuid, kitchen), result)
        self.assertEqual(Job.search_count([('cancellation_id', '=', cancellation.id)]), 2)
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            Pos.baseer_cancel_offline_draft(order.uuid, 1, command_uuid, dict(kitchen, reason_code='staff_error'))

    def test_shared_kitchen_cancellation_rejects_stale_and_invalid_context(self):
        order = self._shared_kitchen_draft()
        Pos = self.env['pos.order']
        kitchen = {'session_id': self.session.id, 'reason_code': 'wrong_order', 'reason_note': ''}
        cases = ((2, kitchen, ValidationError),
                 (1, dict(kitchen, session_id=self.session.id + 999999), AccessError),
                 (1, dict(kitchen, reason_code='other'), ValidationError))
        for revision, details, expected_error in cases:
            with self.subTest(revision=revision, details=details), self.assertRaises(expected_error), self.env.cr.savepoint():
                Pos.baseer_cancel_offline_draft(order.uuid, revision, str(uuid4()), details)
        self.assertEqual(order.state, 'draft')
        self.assertEqual(order.baseer_offline_draft_revision, 1)
        self.assertFalse(self.env['baseer.print.cancellation'].sudo().search([('order_id', '=', order.id)]))

    def test_shared_kitchen_cancellation_rejects_paid_balance(self):
        order = self._shared_kitchen_draft()
        order._gd_internal().write({'amount_paid': 1})
        kitchen = {'session_id': self.session.id, 'reason_code': 'wrong_order', 'reason_note': ''}
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.env['pos.order'].baseer_cancel_offline_draft(order.uuid, 1, str(uuid4()), kitchen)
        order.invalidate_recordset()
        self.assertEqual(order.state, 'draft')
        self.assertEqual(order.baseer_offline_draft_revision, 1)
        self.assertFalse(self.env['baseer.print.cancellation'].sudo().search([('order_id', '=', order.id)]))

    def test_shared_kitchen_cancellation_after_synchronized_discount_removal(self):
        order = self._shared_kitchen_draft()
        Pos = self.env['pos.order']
        remove = self._payload()
        remove.update(uuid=order.uuid, state='draft', payment_ids=[], amount_paid=0,
                      amount_total=115, amount_tax=15, lines=[])
        remove.pop('baseer_offline_discount_intent')
        remove['baseer_offline_draft_command'] = {
            'revision': 1, 'command_uuid': str(uuid4()), 'operation': 'remove',
        }
        Pos.sync_from_ui([json.loads(json.dumps(remove, default=str))])
        self.assertEqual(order.baseer_offline_draft_revision, 2)
        self.assertFalse(order.lines.filtered('baseer_global_discount_line'))
        kitchen = {'session_id': self.session.id, 'reason_code': 'wrong_order', 'reason_note': ''}
        result = Pos.baseer_cancel_offline_draft(order.uuid, 2, str(uuid4()), kitchen)
        self.assertEqual(result['state'], 'cancel')
        self.assertEqual(result['revision'], 3)
        self.assertEqual(self.env['baseer.print.cancellation'].sudo().search_count([('order_id', '=', order.id)]), 1)

    def test_resolve_legacy_kitchen_cancellation_fences_delayed_rpc(self):
        order = self._shared_kitchen_draft()
        Pos = self.env['pos.order']
        command_uuid = str(uuid4())
        result = Pos.baseer_resolve_offline_draft_cancel(order.uuid, 1, command_uuid, self.session.id)
        self.assertEqual(result, {'uuid': order.uuid, 'state': 'draft', 'revision': 2, 'outcome': 'fenced'})
        self.assertEqual(Pos.baseer_resolve_offline_draft_cancel(order.uuid, 1, command_uuid, self.session.id), result)
        self.assertEqual(order.state, 'draft')
        self.assertFalse(self.env['baseer.print.cancellation'].sudo().search([('order_id', '=', order.id)]))
        self.assertFalse(self.env['baseer.print.job'].sudo().search([('source_order_id', '=', order.id)]))
        kitchen = {'session_id': self.session.id, 'reason_code': 'wrong_order', 'reason_note': ''}
        for args in ((order.uuid, 1, command_uuid), (order.uuid, 1, command_uuid, kitchen)):
            with self.assertRaises(ValidationError), self.env.cr.savepoint():
                Pos.baseer_cancel_offline_draft(*args)
        # Once the next draft sync replaces the receipt, monotonic revision
        # still rejects a delayed copy of the old cancellation command.
        remove = self._payload()
        remove.update(uuid=order.uuid, state='draft', payment_ids=[], amount_paid=0,
                      amount_total=115, amount_tax=15, lines=[])
        remove.pop('baseer_offline_discount_intent')
        remove['baseer_offline_draft_command'] = {
            'revision': 2, 'command_uuid': str(uuid4()), 'operation': 'remove',
        }
        Pos.sync_from_ui([json.loads(json.dumps(remove, default=str))])
        self.assertEqual(order.baseer_offline_draft_revision, 3)
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            Pos.baseer_cancel_offline_draft(order.uuid, 1, command_uuid)
        self.assertEqual(Pos.baseer_resolve_offline_draft_cancel(order.uuid, 1, command_uuid, self.session.id)['outcome'], 'review')

    def test_resolve_legacy_cancellation_recognizes_committed_and_conflict(self):
        draft = self._payload()
        draft.update(state='draft', payment_ids=[], amount_paid=0)
        draft['baseer_offline_draft_command'] = {'revision': 0, 'command_uuid': str(uuid4()), 'operation': 'set'}
        self.env['pos.order'].sync_from_ui([json.loads(json.dumps(draft, default=str))])
        order = self.env['pos.order'].search([('uuid', '=', draft['uuid'])])
        Pos = self.env['pos.order']
        command_uuid = str(uuid4())
        Pos.baseer_cancel_offline_draft(order.uuid, 1, command_uuid)
        result = Pos.baseer_resolve_offline_draft_cancel(order.uuid, 1, command_uuid, self.session.id)
        self.assertEqual(result, {'uuid': order.uuid, 'state': 'cancel', 'revision': 2, 'outcome': 'committed'})
        self.assertEqual(Pos.baseer_resolve_offline_draft_cancel(order.uuid, 1, str(uuid4()), self.session.id)['outcome'], 'review')

    def test_resolve_legacy_cancellation_rejects_mismatched_session_without_changes(self):
        order = self._shared_kitchen_draft()
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            self.env['pos.order'].baseer_resolve_offline_draft_cancel(order.uuid, 1, str(uuid4()), self.session.id + 999999)
        order.invalidate_recordset()
        self.assertEqual(order.state, 'draft')
        self.assertEqual(order.baseer_offline_draft_revision, 1)
        self.assertFalse(self.env['baseer.print.cancellation'].sudo().search([('order_id', '=', order.id)]))

    def test_resolve_legacy_cancellation_rejects_other_company_and_non_pos(self):
        order = self._shared_kitchen_draft()
        other = self.env['res.company'].create({'name': 'Other fence company'})
        groups = [self.env.ref('base.group_user').id, self.env.ref('point_of_sale.group_pos_user').id]
        other_user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Other fence cashier', 'login': 'other-fence-%s' % uuid4().hex,
            'company_id': other.id, 'company_ids': [Command.set(other.ids)], 'group_ids': [Command.set(groups)],
        })
        non_pos = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'No fence POS', 'login': 'nonpos-fence-%s' % uuid4().hex,
            'company_id': self.env.company.id, 'company_ids': [Command.set(self.env.company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        })
        for user, company_ids in ((other_user, other.ids), (non_pos, self.env.company.ids)):
            denied = False
            with self.env.cr.savepoint():
                try:
                    self.env['pos.order'].with_user(user).with_context(
                        allowed_company_ids=company_ids
                    ).baseer_resolve_offline_draft_cancel(order.uuid, 1, str(uuid4()), self.session.id)
                except (AccessError, ValidationError):
                    denied = True
            self.assertTrue(denied)
        order.invalidate_recordset()
        self.assertEqual(order.state, 'draft')
        self.assertEqual(order.baseer_offline_draft_revision, 1)
        self.assertFalse(self.env['baseer.print.cancellation'].sudo().search([('order_id', '=', order.id)]))
        self.assertFalse(self.env['baseer.print.job'].sudo().search([('source_order_id', '=', order.id)]))

    def test_shared_kitchen_cancellation_rejects_user_without_pos_permission(self):
        order = self._shared_kitchen_draft()
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'No POS permission', 'login': 'no-pos-kitchen-%s' % uuid4().hex,
            'company_id': self.env.company.id, 'company_ids': [Command.set(self.env.company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        })
        kitchen = {'session_id': self.session.id, 'reason_code': 'wrong_order', 'reason_note': ''}
        # Record rules may conceal the order before the explicit POS group
        # check, so denial can surface as inaccessible or unavailable.
        denied = False
        with self.env.cr.savepoint():
            try:
                self.env['pos.order'].with_user(user).with_context(
                    allowed_company_ids=self.env.company.ids
                ).baseer_cancel_offline_draft(order.uuid, 1, str(uuid4()), kitchen)
            except (AccessError, ValidationError):
                denied = True
        self.assertTrue(denied, 'A user without POS access must not cancel a kitchen order')
        order.invalidate_recordset()
        self.assertEqual(order.state, 'draft')
        self.assertEqual(order.baseer_offline_draft_revision, 1)
        self.assertFalse(self.env['baseer.print.cancellation'].sudo().search([('order_id', '=', order.id)]))
        self.assertFalse(self.env['baseer.print.job'].sudo().search([('source_order_id', '=', order.id)]))

    def test_shared_kitchen_cancellation_rejects_other_company_cashier(self):
        order = self._shared_kitchen_draft()
        other = self.env['res.company'].create({'name': 'Other kitchen cancellation company'})
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Other company cashier', 'login': 'other-kitchen-%s' % uuid4().hex,
            'company_id': other.id, 'company_ids': [Command.set(other.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id,
                                       self.env.ref('point_of_sale.group_pos_user').id])],
        })
        kitchen = {'session_id': self.session.id, 'reason_code': 'wrong_order', 'reason_note': ''}
        denied = False
        with self.env.cr.savepoint():
            try:
                self.env['pos.order'].with_user(user).with_context(
                    allowed_company_ids=other.ids
                ).baseer_cancel_offline_draft(order.uuid, 1, str(uuid4()), kitchen)
            except (AccessError, ValidationError):
                denied = True
        self.assertTrue(denied, 'A cashier in another company must not cancel this kitchen order')
        order.invalidate_recordset()
        self.assertEqual(order.state, 'draft')
        self.assertEqual(order.baseer_offline_draft_revision, 1)
        self.assertFalse(self.env['baseer.print.cancellation'].sudo().search([('order_id', '=', order.id)]))
        self.assertFalse(self.env['baseer.print.job'].sudo().search([('source_order_id', '=', order.id)]))

    def test_shared_kitchen_cancellation_rolls_back_all_on_queue_failure(self):
        order = self._shared_kitchen_draft()
        kitchen = {'session_id': self.session.id, 'reason_code': 'wrong_order', 'reason_note': ''}
        State = type(self.env['baseer.print.preparation.state'])
        with self.assertRaises(ValidationError), self.env.cr.savepoint(), patch.object(
                State, '_enqueue_cancellation_jobs', side_effect=ValidationError('queue failure')):
            self.env['pos.order'].baseer_cancel_offline_draft(order.uuid, 1, str(uuid4()), kitchen)
        order.invalidate_recordset()
        self.assertEqual(order.state, 'draft')
        self.assertEqual(order.baseer_offline_draft_revision, 1)
        self.assertFalse(self.env['baseer.print.cancellation'].sudo().search([('order_id', '=', order.id)]))

    def test_server_mismatch_rolls_back_order_and_payment(self):
        payload = self._payload(total='94.00')
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.env['pos.order'].sync_from_ui([deepcopy(payload)])
        self.assertFalse(self.env['pos.order'].search([('uuid', '=', payload['uuid'])]))

    def test_percentage_sync_recalculates_tax_and_records_allocation(self):
        payload = self._payload(kind='percent', value='10', total='103.50', tax='13.50')
        payload['lines'][1][2].update(price_unit=-10, price_subtotal=-10, price_subtotal_incl=-11.50)
        self.env['pos.order'].sync_from_ui([deepcopy(payload)])
        order = self.env['pos.order'].search([('uuid', '=', payload['uuid'])])
        self.assertEqual(order.baseer_global_discount_kind, 'percent')
        self.assertAlmostEqual(order.amount_total, 103.50, places=2)
        self.assertAlmostEqual(order.amount_tax, 13.50, places=2)
        self.assertEqual(order.lines.filtered('baseer_global_discount_line').baseer_global_discount_source_id.product_id, self.product)

    def test_tax_category_evidence_tampering_rolls_back(self):
        payload = self._payload()
        payload['lines'][1][2]['tax_ids'] = [Command.clear()]
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.env['pos.order'].sync_from_ui([deepcopy(payload)])
        self.assertFalse(self.env['pos.order'].search([('uuid', '=', payload['uuid'])]))

    def test_tax_drift_is_rejected_without_server_order(self):
        payload = self._payload()
        self.tax.amount = 10
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.env['pos.order'].sync_from_ui([deepcopy(payload)])
        self.assertFalse(self.env['pos.order'].search([('uuid', '=', payload['uuid'])]))

    def test_changed_discount_income_account_is_rejected_atomically(self):
        payload = self._payload()
        replacement = self.env['account.account'].create({
            'name': 'Other offline discount income', 'code': 'OFFGD002', 'account_type': 'income',
            'company_ids': [Command.set(self.env.company.ids)],
        })
        self.config.baseer_global_discount_account_id = replacement
        self.config.baseer_global_discount_product_id.property_account_income_id = replacement
        with self.assertRaisesRegex(ValidationError, 'discount account changed'), self.env.cr.savepoint():
            self.env['pos.order'].sync_from_ui([deepcopy(payload)])
        self.assertFalse(self.env['pos.order'].search([('uuid', '=', payload['uuid'])]))

    def test_missing_or_forged_account_proof_is_rejected(self):
        for proof in (None, '', '0' * 64):
            payload = self._payload()
            if proof is None:
                payload['baseer_offline_discount_intent'].pop('account_proof')
            else:
                payload['baseer_offline_discount_intent']['account_proof'] = proof
            with self.assertRaises(ValidationError), self.env.cr.savepoint():
                self.env['pos.order'].sync_from_ui([deepcopy(payload)])
            self.assertFalse(self.env['pos.order'].search([('uuid', '=', payload['uuid'])]))

    def test_changed_discount_fiscal_account_mapping_is_rejected(self):
        position = self.env['account.fiscal.position'].create({
            'name': 'Offline account mapping', 'company_id': self.env.company.id,
        })
        payload = self._payload()
        payload['fiscal_position_id'] = position.id
        payload['baseer_offline_discount_intent']['account_proof'] = self.config._gd_offline_account_proof(position)
        replacement = self.env['account.account'].create({
            'name': 'Mapped offline discount income', 'code': 'OFFGD003', 'account_type': 'income',
            'company_ids': [Command.set(self.env.company.ids)],
        })
        position.account_ids = [Command.create({
            'account_src_id': self.account.id, 'account_dest_id': replacement.id,
        })]
        with self.assertRaisesRegex(ValidationError, 'discount account changed'), self.env.cr.savepoint():
            self.env['pos.order'].sync_from_ui([deepcopy(payload)])
        self.assertFalse(self.env['pos.order'].search([('uuid', '=', payload['uuid'])]))

    def test_cashier_can_read_company_account_proofs_without_account_data(self):
        position = self.env['account.fiscal.position'].create({
            'name': 'Offline enabled position', 'company_id': self.env.company.id,
        })
        cashier = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Offline POS cashier', 'login': 'offline-proof-%s' % uuid4().hex,
            'company_id': self.env.company.id, 'company_ids': [Command.set(self.env.company.ids)],
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('point_of_sale.group_pos_user').id,
            ])],
        })
        config = self.config.with_user(cashier).with_context(allowed_company_ids=self.env.company.ids)
        self.assertIn('baseer_offline_discount_account_proofs', config._load_pos_data_fields(config))
        proofs = config.read(['baseer_offline_discount_account_proofs'])[0]['baseer_offline_discount_account_proofs']
        self.assertEqual(proofs['0'], self.config._gd_offline_account_proof(self.env['account.fiscal.position']))
        self.assertEqual(proofs[str(position.id)], self.config._gd_offline_account_proof(position))
        self.assertEqual(len(proofs['0']), 64)

    def test_phase2_sale_without_invoice_is_rejected_atomically(self):
        if 'baseer_zatca_phase2_enabled' not in self.config._fields:
            self.skipTest('Saudi POS scope is not installed in this database')
        self.config.baseer_zatca_phase2_enabled = True
        payload = self._payload()
        with self.assertRaisesRegex(ValidationError, 'invoice is required'), self.env.cr.savepoint():
            self.env['pos.order'].sync_from_ui([deepcopy(payload)])
        self.assertFalse(self.env['pos.order'].search([('uuid', '=', payload['uuid'])]))
