from copy import deepcopy
from uuid import uuid4

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'baseer_session_ticket')
class TestSessionTicket(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['pos.config'].create({'name': 'Session ticket fixture'})
        cls.config.open_ui()
        cls.session = cls.config.current_session_id
        cls.session.set_opening_control(0, 'Session ticket fixture')
        cls.product = cls.env['product.product'].create({
            'name': 'Session ticket service', 'type': 'service', 'available_in_pos': True,
            'taxes_id': [Command.clear()], 'list_price': 10,
        })

    def _line(self):
        return {'uuid': str(uuid4()), 'product_id': self.product.id, 'qty': 1,
                'price_unit': 10, 'price_subtotal': 10, 'price_subtotal_incl': 10}

    def _draft(self, session=None, empty=False):
        return {
            'uuid': str(uuid4()), 'session_id': (session or self.session).id, 'state': 'draft',
            'company_id': self.env.company.id, 'user_id': self.env.uid, 'payment_ids': [],
            'lines': [] if empty else [Command.create(self._line())], 'amount_total': 0 if empty else 10,
            'amount_paid': 0, 'amount_tax': 0, 'amount_return': 0,
        }

    def test_sync_retry_returns_original_number_and_references(self):
        Pos = self.env['pos.order']
        draft = self._draft()
        draft.update(tracking_number='8062', pos_reference='268-27-000062',
                     baseer_ticket_session_id=999, baseer_ticket_number=999)
        first = Pos.sync_from_ui([deepcopy(draft)])['pos.order'][0]
        self.assertEqual(first['baseer_ticket_label'], f'{self.session.id}-1')
        self.assertEqual(first['baseer_ticket_number'], 1)
        self.assertEqual(first['baseer_ticket_session_id'], self.session.id)
        retry = dict(draft, lines=[], baseer_ticket_number=0)
        again = Pos.sync_from_ui([retry])['pos.order'][0]
        for field in ('id', 'pos_reference', 'tracking_number', 'uuid', 'sequence_number', 'baseer_ticket_label'):
            self.assertEqual(again[field], first[field], field)
        self.assertEqual(Pos.read_pos_data_uuid(draft['uuid'])['pos.order'][0]['baseer_ticket_number'], 1)
        self.assertEqual(first['tracking_number'], '8062')
        self.assertEqual(first['pos_reference'], '268-27-000062')
        self.assertEqual(Pos.sync_from_ui([self._draft()])['pos.order'][0]['baseer_ticket_number'], 2)
        self.assertTrue(self.session._load_pos_data_read(self.session, self.config)[0]['baseer_ticket_enabled'])

    def test_empty_attachment_rollback_and_protected_fields(self):
        Pos = self.env['pos.order']
        a, b = Pos.create([self._draft(empty=True), self._draft(empty=True)])
        self.assertFalse(a.baseer_ticket_label)
        self.assertFalse(self.session.baseer_ticket_last_number)
        # The normal Odoo line model is also used by standalone backend writes.
        self.env['pos.order.line'].create(dict(self._line(), order_id=b.id))
        self.assertEqual(b.baseer_ticket_label, f'{self.session.id}-1')
        with self.assertRaises(RuntimeError), self.env.cr.savepoint():
            a.write({'lines': [Command.create(self._line())]})
            self.assertEqual(a.baseer_ticket_number, 2)
            raise RuntimeError('simulate aborted order')
        self.assertFalse(a.baseer_ticket_number)
        a.write({'lines': [Command.create(self._line())]})
        self.assertEqual(a.baseer_ticket_number, 2)
        for record, vals in ((a, {'baseer_ticket_number': 9}),
                             (a, {'baseer_ticket_session_id': False}),
                             (self.session, {'baseer_ticket_last_number': 0}),
                             (self.session, {'baseer_ticket_enabled': False})):
            with self.assertRaises(AccessError):
                record.write(vals)

    def test_rollover_keeps_legacy_or_frozen_number_and_starts_next_at_one(self):
        Pos = self.env['pos.order']
        old = Pos.create(self._draft())
        # Reproduce the exact persisted shape of a session/orders predating installation.
        self.env.cr.execute('UPDATE pos_session SET baseer_ticket_enabled = false WHERE id = %s',
                            [self.session.id])
        self.session.invalidate_recordset(['baseer_ticket_enabled'])
        legacy = Pos.create(self._draft())
        self.assertFalse(legacy.baseer_ticket_session_id)
        self.assertFalse(legacy.baseer_ticket_number)
        config = self.env['pos.config'].create({'name': 'Independent session ticket fixture'})
        config.open_ui()
        later = config.current_session_id
        for order in (old, legacy):
            order.write({'session_id': later.id})
            order.write({'lines': [Command.create(self._line())]})
        self.assertEqual(old.baseer_ticket_label, f'{self.session.id}-1')
        self.assertFalse(legacy.baseer_ticket_label)
        self.assertEqual(Pos.create(self._draft(later)).baseer_ticket_label, f'{later.id}-1')
