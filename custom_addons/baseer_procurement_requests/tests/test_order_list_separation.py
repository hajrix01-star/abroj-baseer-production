from uuid import uuid4

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError

from .test_procurement_flow import ProcurementFlowCase


class OrderListSeparationCase(ProcurementFlowCase):
    def _new_list(self):
        return self._route_requester().browse(self._route_requester().create_from_catalog(
            [{'option_id': self.option.id, 'quantity': '2'}], False, purchase_route='cash'))

    def test_list_without_warehouse_send_close_and_idempotency(self):
        requester = self._route_requester()
        token = str(uuid4())
        args = ([{'option_id': self.option.id, 'quantity': '2'}], False, False, False, token, False, 'cash')
        before = {model: self.env[model].search_count([]) for model in ('stock.picking', 'account.move', 'account.payment')}
        request_id = requester.create_from_catalog(*args)
        self.assertEqual(requester.create_from_catalog(*args), request_id)
        record = requester.browse(request_id)
        self.assertTrue(record.list_only)
        self.assertFalse(record.warehouse_id)
        record.action_mark_sent()
        self.assertEqual(record.state, 'sent')
        record.action_close_order_list()
        record.action_close_order_list()
        self.assertEqual(record.state, 'list_closed')
        self.assertTrue(record.list_closed_at)
        self.assertEqual(record.list_closed_by_id, requester.env.user)
        self.assertFalse(record.picking_id)
        for model, count in before.items():
            self.assertEqual(self.env[model].search_count([]), count)

    def test_client_defaults_cannot_forge_legacy_or_receipt_state(self):
        requester = self._route_requester().with_context(default_list_only=False, default_state='purchased',
                                                           default_picking_id=1, default_list_closed_at='2025-01-01')
        record = requester.create({'company_id': self.company.id, 'purchase_route': 'cash'})
        self.assertTrue(record.list_only)
        self.assertEqual(record.state, 'draft')
        self.assertFalse(record.picking_id)
        self.assertFalse(record.list_closed_at)
        with self.assertRaises(AccessError):
            requester.create({'company_id': self.company.id, 'purchase_route': 'cash', 'list_only': False})
        with self.assertRaises(AccessError):
            record.write({'list_only': False})

    def test_list_rejects_receipt_and_financial_links(self):
        request = self.env['baseer.procurement.request'].browse(self._route_requester().create_from_catalog(
            [{'option_id': self.option.id, 'quantity': '2'}], False, purchase_route='cash'))
        request.action_mark_sent()
        for method in (request.action_confirm_manager_receipt, request.action_open_manager_receipt_catalog,
                       request.action_confirm_actual_purchase, request.action_open_actual_catalog,
                       request.action_open_receipt_custody):
            with self.assertRaises(UserError):
                method()
        with self.assertRaises(AccessError):
            request.line_ids.write({'manager_received_qty': 1})
        with self.assertRaises(AccessError):
            request.line_ids.write({'actual_qty': 1})
        with self.assertRaises(UserError):
            self.env['baseer.purchase.batch'].create({'company_id': self.company.id, 'procurement_request_id': request.id})
        with self.assertRaises(UserError):
            self.env['baseer.procurement.representative.advance'].submit_funding(
                request.id, 1, 1, '10', str(uuid4()), '2025-01-01')
        self.assertFalse(request.picking_id)

    def test_close_requires_user_role_and_active_company(self):
        requester = self._route_requester()
        request = requester.browse(requester.create_from_catalog(
            [{'option_id': self.option.id, 'quantity': '1'}], False, purchase_route='cash'))
        request.action_mark_sent()
        outsider = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Order no permission', 'login': 'list-no-' + uuid4().hex,
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        })
        with self.assertRaises(AccessError):
            request.with_user(outsider).action_close_order_list()
        other = self.env['res.company'].create({'name': 'List other company'})
        self.env.user.company_ids |= other
        with self.assertRaises(AccessError):
            self.env['baseer.procurement.request'].with_company(other).close_order_list_from_catalog(request.id)
        self.assertEqual(request.state, 'sent')

    def test_receipt_context_defaults_cannot_inject_quantities_into_new_list(self):
        request = self.env['baseer.procurement.request'].create({'company_id': self.company.id, 'purchase_route': 'cash'})
        line = self.env['baseer.procurement.request.line'].with_context(
            default_manager_received_qty=7, default_actual_qty=8, default_actual_price=9).create({
                'request_id': request.id, 'option_id': self.option.id, 'requested_qty': 2})
        self.assertEqual((line.manager_received_qty, line.actual_qty, line.actual_price), (0, 0, 0))
        legacy = self.env['baseer.procurement.request'].create({'company_id': self.company.id, 'purchase_route': 'cash'})
        self.env.cr.execute('UPDATE baseer_procurement_request SET list_only = false WHERE id = %s', [legacy.id])
        legacy.invalidate_recordset(['list_only'])
        lines = self.env['baseer.procurement.request.line'].with_context(default_manager_received_qty=3).create([
            {'request_id': request.id, 'option_id': self.option.id, 'requested_qty': 1},
            {'request_id': legacy.id, 'option_id': self.option.id, 'requested_qty': 5},
        ])
        self.assertEqual(lines[0].manager_received_qty, 0)
        self.assertEqual(lines[1].manager_received_qty, 3)


    def test_preexisting_legacy_receipt_and_link_remain_accessible(self):
        request = self._request(purchase_route='cash')
        self.env.cr.execute('UPDATE baseer_procurement_request SET list_only = false WHERE id = %s', [request.id])
        request.invalidate_recordset(['list_only'])
        request.action_mark_sent()
        request.line_ids.manager_received_qty = 2
        request.action_confirm_manager_receipt()
        request.line_ids.write({'actual_qty': 2, 'actual_price': 4})
        request.action_confirm_actual_purchase()
        self.assertEqual(request.state, 'purchased')
        picking = request.picking_id
        self.assertTrue(picking)
        batch = self.env['baseer.purchase.batch'].search([('procurement_request_id', '=', request.id)])
        self.assertEqual(len(batch), 1)
        request.invalidate_recordset()
        batch.invalidate_recordset()
        self.assertFalse(request.list_only)
        self.assertEqual(request.picking_id, picking)
        self.assertEqual(batch.procurement_request_id, request)



import os
import threading
import time
from psycopg2.errors import SerializationFailure
from odoo import SUPERUSER_ID, api, sql_db
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class OrderListCloseRaceCase(TransactionCase):
    def test_two_closures_are_serialized_and_idempotent(self):
        if os.environ.get('BASEER_ORDER_LIST_CONCURRENCY') != '1':
            self.skipTest('Requires an explicitly enabled disposable order-list database')
        self.assertTrue(self.env.cr.dbname.startswith('orders_list_test_'))
        db = sql_db.db_connect(self.env.cr.dbname)
        suffix = uuid4().hex[:8]
        with db.cursor() as cr:
            initial = api.Environment(cr, SUPERUSER_ID, {})
            company = initial['res.company'].create({'name': 'Order close race ' + suffix})
            ctx = {'allowed_company_ids': company.ids}
            env = api.Environment(cr, SUPERUSER_ID, ctx)
            actor = env['res.users'].with_context(no_reset_password=True).create({
                'name': 'Order close race', 'login': 'order-close-' + suffix,
                'company_id': company.id, 'company_ids': [Command.set(company.ids)],
                'group_ids': [Command.set([env.ref('baseer_procurement_requests.group_procurement_user').id])],
            })
            product = env['product.product'].create({'name': 'Race ingredient', 'is_storable': True, 'company_id': company.id})
            option = env['baseer.procurement.purchase.option'].create({'name': 'Race item', 'company_id': company.id,
                'product_id': product.id, 'uom_id': product.uom_id.id})
            actor_env = api.Environment(cr, actor.id, ctx)
            rid = actor_env['baseer.procurement.request'].create_from_catalog(
                [{'option_id': option.id, 'quantity': '2'}], False, purchase_route='cash')
            actor_env['baseer.procurement.request'].browse(rid).action_mark_sent()
            company_id, actor_id = company.id, actor.id
            cr.commit()
        ctx = {'allowed_company_ids': [company_id]}
        with db.cursor() as win_cr, db.cursor() as wait_cr:
            for cr in (win_cr, wait_cr):
                cr.execute("SET LOCAL lock_timeout = '10s'")
            winner = api.Environment(win_cr, actor_id, ctx)
            waiter = api.Environment(wait_cr, actor_id, ctx)
            self.assertEqual(waiter['baseer.procurement.request'].browse(rid).state, 'sent')
            winner['baseer.procurement.request'].browse(rid).action_close_order_list()
            wait_cr.execute('SELECT pg_backend_pid()')
            pid = wait_cr.fetchone()[0]
            errors = []
            def compete():
                try:
                    waiter['baseer.procurement.request'].browse(rid).action_close_order_list()
                except Exception as error:
                    errors.append(error)
            thread = threading.Thread(target=compete, daemon=True)
            thread.start()
            blocked, deadline = False, time.monotonic() + 10
            with db.cursor() as observer:
                while time.monotonic() < deadline and thread.is_alive():
                    observer.execute('SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s', [pid])
                    row = observer.fetchone()
                    observer.rollback()
                    if row and row[0] == 'Lock':
                        blocked = True
                        break
                    time.sleep(.02)
            try:
                self.assertTrue(blocked)
            finally:
                win_cr.commit()
                thread.join(15)
            self.assertFalse(thread.is_alive())
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], SerializationFailure)
            wait_cr.rollback()
        with db.cursor() as cr:
            retry = api.Environment(cr, actor_id, ctx)
            order = retry['baseer.procurement.request'].browse(rid)
            self.assertEqual(order.state, 'list_closed')
            self.assertTrue(order.action_close_order_list())
            cr.rollback()
