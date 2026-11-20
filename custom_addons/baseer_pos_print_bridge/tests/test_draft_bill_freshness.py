import base64
import io
from datetime import timedelta
from uuid import uuid4

from PIL import Image

from odoo import Command, fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'baseer_draft_bill_freshness')
class TestDraftBillFreshness(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.agent = cls.env['baseer.print.agent'].create({
            'name': 'Draft freshness virtual agent', 'device_uid': 'draft-freshness-' + uuid4().hex,
            'allowed_company_ids': [Command.set(cls.company.ids)],
        })
        cls.agent.with_context(baseer_print_internal=True).write({
            'state': 'online', 'agent_version': '1.5.18',
        })
        cls.printer = cls.env['baseer.print.printer'].with_context(baseer_print_discovery=True).create({
            'name': 'Draft freshness virtual printer', 'agent_id': cls.agent.id,
            'machine_identifier': 'draft-freshness-' + uuid4().hex, 'active': True,
            'paper_width': '80', 'allowed_company_ids': [Command.set(cls.company.ids)],
        })
        cls.company.baseer_primary_print_agent_id = cls.agent
        cls.config = cls.env['pos.config'].create({
            'name': 'Draft freshness ordinary register', 'iface_printbill': True,
            'baseer_receipt_printer_id': cls.printer.id, 'baseer_direct_print_enabled': True,
        })
        cls.config.open_ui()
        cls.session = cls.config.current_session_id
        cls.session.state = 'opened'
        cls.product = cls.env['product.product'].create({
            'name': 'Draft freshness service', 'type': 'service', 'available_in_pos': True,
            'list_price': 10, 'taxes_id': [Command.clear()],
        })

    def _order(self, quantity=3, order_uuid=None):
        return self.env['pos.order'].create({
            'uuid': order_uuid or str(uuid4()), 'company_id': self.company.id,
            'session_id': self.session.id, 'amount_total': 10 * quantity,
            'amount_tax': 0, 'amount_paid': 0, 'amount_return': 0,
            'lines': [Command.create({
                'product_id': self.product.id, 'full_product_name': self.product.name,
                'qty': quantity, 'price_unit': 10, 'price_subtotal': 10 * quantity,
                'price_subtotal_incl': 10 * quantity, 'tax_ids': [Command.clear()],
            })],
        })

    @staticmethod
    def _image(color='white'):
        output = io.BytesIO()
        Image.new('RGB', (300, 400), color).save(output, format='JPEG')
        return base64.b64encode(output.getvalue()).decode()

    def _enqueue(self, order_uuid, image=None, request_uuid=None):
        result = self.session.baseer_enqueue_draft_bill(
            order_uuid, request_uuid or str(uuid4()), image or self._image(),
        )
        return self.env['baseer.print.job'].browse(result['job_id'])

    def _due(self, job):
        job.available_at = fields.Datetime.now() - timedelta(minutes=5)

    def test_line_change_invalidates_pending_image_before_claim(self):
        order = self._order()
        job = self._enqueue(order.uuid)
        # Same ORM transaction: a timestamp-only binding is insufficient.
        order.lines.write({'qty': 1, 'price_subtotal': 10, 'price_subtotal_incl': 10})
        order.write({'amount_total': 10})
        self.assertFalse(job._is_current_draft_bill())
        self._due(job)
        self.assertFalse(self.env['baseer.print.job']._claim_for_agent(self.agent))
        self.assertEqual(job.state, 'cancelled')
        self.assertFalse(job.receipt_image)
        self.assertEqual(order.state, 'draft')
        self.assertFalse(order.payment_ids)

    def test_fresh_request_replaces_changed_pending_image(self):
        order = self._order()
        old = self._enqueue(order.uuid)
        order.lines.write({'qty': 1, 'price_subtotal': 10, 'price_subtotal_incl': 10})
        order.write({'amount_total': 10})
        fresh = self._enqueue(order.uuid, self._image('black'))
        self.assertNotEqual(old, fresh)
        self.assertEqual(old.state, 'cancelled')
        self.assertNotEqual(old.receipt_image_sha256, fresh.receipt_image_sha256)
        self.assertTrue(fresh._is_current_draft_bill())
        self._due(fresh)
        self.assertEqual(self.env['baseer.print.job']._claim_for_agent(self.agent)['id'], fresh.id)

    def test_changed_local_image_replaces_pending_without_creating_order(self):
        order_uuid = str(uuid4())
        old = self._enqueue(order_uuid)
        fresh = self._enqueue(order_uuid, self._image('black'))
        self.assertNotEqual(old, fresh)
        self.assertEqual(old.state, 'cancelled')
        self.assertTrue(fresh._is_current_draft_bill())
        self.assertFalse(self.env['baseer.print.job']._draft_bill_order(order_uuid))

    def test_local_image_is_invalid_when_split_sync_creates_the_order(self):
        order_uuid = str(uuid4())
        old = self._enqueue(order_uuid)
        self.assertTrue(old._is_current_draft_bill())
        self._order(quantity=1, order_uuid=order_uuid)
        self.assertFalse(old._is_current_draft_bill())
        fresh = self._enqueue(order_uuid)
        self.assertEqual(old.state, 'cancelled')
        self.assertNotEqual(old, fresh)
        self.assertTrue(fresh._is_current_draft_bill())

    def test_unchanged_request_and_image_remain_idempotent(self):
        order = self._order()
        request_uuid = str(uuid4())
        first = self._enqueue(order.uuid, request_uuid=request_uuid)
        self.assertEqual(self._enqueue(order.uuid, request_uuid=request_uuid), first)
        self.assertEqual(self._enqueue(order.uuid), first)
        self.assertEqual(self.env['baseer.print.job'].search_count([
            ('draft_order_uuid', '=', order.uuid), ('state', '=', 'pending'),
        ]), 1)

    def test_leased_image_is_not_replaced_or_reported_as_updated(self):
        order = self._order()
        job = self._enqueue(order.uuid)
        self._due(job)
        claim = self.env['baseer.print.job']._claim_for_agent(self.agent)
        self.assertEqual(claim['id'], job.id)
        self.assertEqual(job.state, 'leased')
        order.lines.write({'qty': 1, 'price_subtotal': 10, 'price_subtotal_incl': 10})
        order.write({'amount_total': 10})
        with self.assertRaises(ValidationError):
            self._enqueue(order.uuid, self._image('black'))
        self.assertEqual(job.state, 'leased')

    def test_notes_invalidate_the_saved_order_image(self):
        order = self._order()
        job = self._enqueue(order.uuid)
        order.lines.customer_note = 'No salt'
        self.assertFalse(job._is_current_draft_bill())

    def test_paid_order_never_keeps_an_unpaid_job_current(self):
        order = self._order()
        job = self._enqueue(order.uuid)
        order.state = 'paid'
        self.assertFalse(job._is_current_draft_bill())
