from odoo.tests import tagged
from odoo.addons.baseer_bwork.contracts import ProtocolError

from .test_receipts import BWorkReceiptCase


@tagged('post_install', '-at_install', 'baseer_bwork_procurement')
class BWorkListReceiptBoundaryCase(BWorkReceiptCase):
    def test_new_order_is_excluded_from_all_receipt_entry_points(self):
        self.assertTrue(self.order.list_only)
        self.assertNotIn(self.order_id, [row['id'] for row in self.service._v2_receipts(self.company.id)['orders']])
        self.assertNotIn(self.order_id, [row['id'] for row in self.service._v2_receipts_all(company_id=self.company.id)['orders']])
        with self.assertRaises(ProtocolError):
            self.service._v2_receipt_detail(self.company.id, self.order_id)
        with self.assertRaises(ProtocolError):
            self.service._v2_receipt_confirm(self.order_id, self._payload())
        self.assertFalse(self.order.picking_id)

    def test_closing_bwork_list_publishes_one_change(self):
        from unittest.mock import patch
        self.env.user.company_ids |= self.company
        self.env.user.group_ids |= self.env.ref('baseer_procurement_requests.group_procurement_user')
        order = self.order.with_user(self.env.user).with_context(allowed_company_ids=self.company.ids).with_company(self.company)
        self.assertEqual(order.state, 'sent')
        with patch('odoo.addons.baseer_bwork_procurement.models.service.BWorkProcurementService._order_publish_change') as publish:
            order.action_close_order_list()
            order.action_close_order_list()
            self.assertEqual(publish.call_count, 1)
        self.assertEqual(order.state, 'list_closed')

    def test_legacy_replay_only_returns_identical_old_order_without_write(self):
        from uuid import uuid4
        payload = {'api_version': 2, 'company_id': self.company.id, 'warehouse_id': self.warehouse.id,
                   'representative_partner_id': None, 'client_uuid': self.order.client_token,
                   'lines': [{'option_id': self.option.id, 'quantity': '2.00'}]}
        legacy_service = self.service.with_context(bwork_legacy_replay_only=True)
        self.assertNotIn(self.order.id, [row['id'] for row in legacy_service._v2_orders(self.company.id)['orders']])
        with self.assertRaises(ProtocolError):
            legacy_service._v2_order_create(payload)
        self.env.cr.execute('UPDATE baseer_procurement_request SET list_only=false WHERE id=%s', [self.order.id])
        self.order.invalidate_recordset(['list_only'])
        self.assertFalse(self.order.list_only)
        before = self.order.write_date
        count = self.env['baseer.procurement.request'].search_count([])
        replay = legacy_service._v2_order_create(payload)
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['order']['id'], self.order.id)
        self.order.invalidate_recordset(['write_date'])
        self.assertEqual(self.order.write_date, before)
        for altered in (dict(payload, client_uuid=str(uuid4())),
                        dict(payload, lines=[{'option_id': self.option.id, 'quantity': '3.00'}])):
            with self.assertRaises(ProtocolError):
                legacy_service._v2_order_create(altered)
        self.assertEqual(self.env['baseer.procurement.request'].search_count([]), count)
