from copy import deepcopy
from uuid import uuid4

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
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

    def test_reservation_retry_then_sync_and_late_retry(self):
        Pos = self.env['pos.order']
        draft = self._draft()
        first = Pos.baseer_reserve_session_ticket(self.session.id, draft['uuid'])
        self.assertEqual(first, Pos.baseer_reserve_session_ticket(self.session.id, draft['uuid']))
        self.assertEqual(first['number'], 1)
        # The client can add more items while the reservation is in flight.
        draft['lines'].append(Command.create(self._line()))
        synced = Pos.sync_from_ui([deepcopy(draft)])['pos.order'][0]
        self.assertEqual(synced['baseer_ticket_label'], first['label'])
        self.assertEqual(len(Pos.search([('uuid', '=', draft['uuid'])]).lines), 2)
        self.assertEqual(first, Pos.baseer_reserve_session_ticket(self.session.id, draft['uuid']))
        self.assertEqual(self.session.baseer_ticket_last_number, 1)

    def test_sync_first_and_late_reservation_does_not_change_order(self):
        Pos = self.env['pos.order']
        draft = self._draft()
        result = Pos.sync_from_ui([deepcopy(draft)])['pos.order'][0]
        saved = Pos.search([('uuid', '=', draft['uuid'])])
        before = saved.lines.ids
        ticket = Pos.baseer_reserve_session_ticket(self.session.id, draft['uuid'])
        self.assertEqual(ticket['label'], result['baseer_ticket_label'])
        self.assertEqual(saved.lines.ids, before)
        self.assertEqual(self.session.baseer_ticket_last_number, 1)

    def test_ticket_reservation_denies_invalid_input_and_other_session_owner(self):
        Pos = self.env['pos.order']
        with self.assertRaises(Exception), self.env.cr.savepoint():
            Pos.baseer_reserve_session_ticket(self.session.id, 'invalid-uuid')
        other = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Other cashier', 'login': 'other-ticket-cashier',
            'group_ids': [Command.set([self.env.ref('point_of_sale.group_pos_user').id])],
        })
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            Pos.with_user(other).baseer_reserve_session_ticket(self.session.id, str(uuid4()))

    def test_unused_reservation_limit_keeps_retry_and_native_sync_available(self):
        Pos = self.env['pos.order']
        draft = self._draft()
        uuids = [draft['uuid']] + [str(uuid4()) for _ in range(499)]
        self.env['baseer.pos.ticket.reservation'].sudo().create([
            {'order_uuid': item, 'session_id': self.session.id, 'number': index + 1}
            for index, item in enumerate(uuids)
        ])
        self.env.cr.execute('UPDATE pos_session SET baseer_ticket_last_number = 500 WHERE id = %s', [self.session.id])
        self.session.invalidate_recordset(['baseer_ticket_last_number'])
        self.assertEqual(Pos.baseer_reserve_session_ticket(self.session.id, draft['uuid'])['number'], 1)
        next_uuid = str(uuid4())
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            Pos.baseer_reserve_session_ticket(self.session.id, next_uuid)
        fallback = self._draft()
        self.assertEqual(Pos.sync_from_ui([deepcopy(fallback)])['pos.order'][0]['baseer_ticket_number'], 501)
        saved = Pos.sync_from_ui([deepcopy(draft)])['pos.order'][0]
        self.assertEqual(saved['baseer_ticket_number'], 1)
        self.assertEqual(Pos.baseer_reserve_session_ticket(self.session.id, next_uuid)['number'], 502)

    def test_reservation_admin_read_obeys_allowed_companies(self):
        other_company = self.env['res.company'].create({'name': 'Ticket isolation company'})
        other_config = self.env['pos.config'].with_company(other_company).create({
            # This fixture only tests record visibility; no sale or payment is
            # opened, so avoid generating default journals/payment methods.
            'name': 'Other company ticket POS', 'company_id': other_company.id,
            'payment_method_ids': [Command.clear()],
        })
        other_session = self.env['pos.session'].with_company(other_company).create({
            'config_id': other_config.id, 'user_id': self.env.uid,
        })
        Reservation = self.env['baseer.pos.ticket.reservation'].sudo()
        own = Reservation.create({'order_uuid': str(uuid4()), 'session_id': self.session.id, 'number': 1})
        foreign = Reservation.create({'order_uuid': str(uuid4()), 'session_id': other_session.id, 'number': 1})
        admin = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Restricted ticket admin', 'login': 'restricted-ticket-admin',
            'group_ids': [Command.set([self.env.ref('base.group_system').id])],
            'company_id': self.env.company.id, 'company_ids': [Command.set(self.env.company.ids)],
        })
        visible = Reservation.with_user(admin).with_context(allowed_company_ids=self.env.company.ids).search([
            ('id', 'in', (own.id, foreign.id)),
        ])
        self.assertEqual(visible.ids, own.ids)

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
