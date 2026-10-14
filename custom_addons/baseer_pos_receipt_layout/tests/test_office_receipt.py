from copy import deepcopy
import base64
import hashlib
import io
from unittest.mock import patch

from PIL import Image

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestOfficeReceipt(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.company.baseer_receipt_profile_enabled = False
        cls.config = cls.env['pos.config'].create({'name': 'Office receipt test'})
        cls.session = cls.env['pos.session'].create({'config_id': cls.config.id})
        cls.product = cls.env['product.product'].create({
            'name': 'Original office receipt product', 'list_price': 10,
        })
        cls.order = cls.env['pos.order'].create({
            'session_id': cls.session.id, 'state': 'paid',
            'amount_total': 10, 'amount_tax': 0, 'amount_paid': 10, 'amount_return': 0,
            'lines': [Command.create({
                'product_id': cls.product.id, 'qty': 1, 'price_unit': 10,
                'price_subtotal': 10, 'price_subtotal_incl': 10,
                'tax_ids': [Command.clear()],
            })],
        })
        cls.snapshot = {
            'total': 10, 'tax': 0, 'paid': 10, 'change': 0,
            'lines': [{'id': cls.order.lines.id, 'excl': 10, 'incl': 10}],
        }

    def test_action_reads_closed_session_without_print_jobs(self):
        # Changing the fixture session state is confined to this rolled-back test.
        self.session.write({'state': 'closed', 'stop_at': fields.Datetime.now()})
        jobs = self.env['baseer.print.job'].search_count([])
        before = self.order.read(['state', 'nb_print', 'amount_total', 'session_id', 'write_date'])
        action = self.order.action_baseer_office_receipt()
        self.assertEqual(action['target'], 'new')
        self.assertTrue(action['url'].endswith('/%s' % self.order.id))
        payload = self.order.baseer_office_receipt_data()
        self.assertEqual([r['id'] for r in payload['data']['pos.order']], self.order.ids)
        self.assertEqual([r['id'] for r in payload['data']['pos.session']], self.session.ids)
        self.assertEqual([r['id'] for r in payload['data']['pos.config']], self.config.ids)
        self.assertEqual(before, self.order.read(['state', 'nb_print', 'amount_total', 'session_id', 'write_date']))
        self.assertEqual(jobs, self.env['baseer.print.job'].search_count([]))

    def test_draft_cannot_be_printed(self):
        draft = self.env['pos.order'].create({
            'session_id': self.session.id, 'amount_total': 0,
            'amount_tax': 0, 'amount_paid': 0, 'amount_return': 0,
        })
        with self.assertRaises(UserError):
            draft.action_baseer_office_receipt()
        with self.assertRaises(UserError):
            draft.baseer_office_receipt_data()

    def test_parity_rejects_amount_change_and_missing_lines(self):
        self.assertTrue(self.order.baseer_validate_office_receipt(self.snapshot))
        for field in ('total', 'tax', 'paid', 'change'):
            changed = deepcopy(self.snapshot)
            changed[field] += 1
            with self.assertRaises(UserError):
                self.order.baseer_validate_office_receipt(changed)
        changed = deepcopy(self.snapshot)
        changed['lines'][0]['incl'] = 11
        with self.assertRaises(UserError):
            self.order.baseer_validate_office_receipt(changed)
        with self.assertRaises(ValidationError):
            self.order.baseer_validate_office_receipt({**self.snapshot, 'lines': []})

    def test_unselected_company_and_non_pos_user_are_denied(self):
        other = self.env['res.company'].create({'name': 'Office inaccessible company'})
        with self.assertRaises(AccessError):
            self.order.with_context(allowed_company_ids=other.ids).baseer_office_receipt_data()
        employee = self.env['res.users'].create({
            'name': 'Office non POS user', 'login': 'office-receipt-non-pos-test',
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
            'company_id': self.env.company.id, 'company_ids': [Command.set(self.env.company.ids)],
        })
        with self.assertRaises(AccessError):
            self.order.with_user(employee).action_baseer_office_receipt()

    def test_original_image_is_exact_and_corruption_is_rejected(self):
        agent = self.env['baseer.print.agent'].create({
            'name': 'Office original-image test', 'device_uid': 'office-receipt-test-agent',
            'allowed_company_ids': [Command.set(self.env.company.ids)],
        })
        printer = self.env['baseer.print.printer'].with_context(baseer_print_discovery=True).create({
            'name': 'Office offline image-test printer', 'agent_id': agent.id,
            'machine_identifier': 'OFFICE-IMAGE-TEST', 'paper_width': '80',
            'allowed_company_ids': [Command.set(self.env.company.ids)],
        })
        buffer = io.BytesIO()
        Image.new('RGB', (300, 100), 'white').save(buffer, format='JPEG')
        raw = buffer.getvalue()
        image = base64.b64encode(raw)
        job = self.env['baseer.print.job']._create_once({
            'company_id': self.env.company.id, 'pos_config_id': self.config.id,
            'agent_id': agent.id, 'printer_id': printer.id,
            'source_order_id': self.order.id, 'ticket_type': 'receipt',
            'payload': {'schema': 4}, 'receipt_image': image,
            'receipt_image_sha256': hashlib.sha256(raw).hexdigest(),
            'idempotency_key': 'office-original-image-unit-test',
        })
        before = self.order.read(['nb_print', 'state', 'write_date'])
        self.assertEqual(self.order.baseer_office_receipt_data()['image'], image.decode('ascii'))
        self.assertEqual(before, self.order.read(['nb_print', 'state', 'write_date']))
        job.write({'receipt_image_sha256': '0' * 64})
        with self.assertRaises(UserError):
            self.order.baseer_office_receipt_data()

    def test_sa_phase_two_requires_accepted_signed_invoice(self):
        self.env.company.country_id = self.env.ref('base.sa')
        with patch.object(type(self.env['ir.module.module']), 'search_count', return_value=1):
            with self.assertRaises(UserError):
                self.order.action_baseer_office_receipt()
            with self.assertRaises(UserError):
                self.order.baseer_office_receipt_data()
