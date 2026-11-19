import base64
import copy
import hashlib
import io
import subprocess
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from PIL import Image

from odoo import Command, fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestOdooKitchenDocument(TransactionCase):
    """Presentation ownership and immutable raster transport, without a POS sale."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.Job = cls.env['baseer.print.job']
        cls.agent = cls.env['baseer.print.agent'].create({
            'name': 'Odoo raster document QA',
            'device_uid': 'odoo-kitchen-document-qa-0001',
            'allowed_company_ids': [Command.set([cls.company.id])],
        })
        cls.agent.with_context(baseer_print_internal=True).write({
            'state': 'online', 'agent_version': '1.5.18',
        })
        cls.printer = cls.env['baseer.print.printer'].with_context(baseer_print_discovery=True).create({
            'name': 'Odoo kitchen document QA', 'agent_id': cls.agent.id,
            'machine_identifier': 'ODOO-KITCHEN-DOCUMENT-QA', 'paper_width': '80',
            'active': True, 'allowed_company_ids': [Command.set([cls.company.id])],
        })

    def _payload(self, width='80'):
        return {
            'schema': 2, 'ticket_type': 'preparation',
            'printer': {'machine_identifier': self.printer.machine_identifier,
                        'paper_width': width, 'copies': 2},
            'order': {'reference': 'POS/QA/001', 'tracking_number': '123',
                      'order_type': 'سفري / Takeaway', 'created_at': '2026-11-19 10:00:00',
                      'requested_by': 'Cashier QA', 'table': 'طاولة 12'},
            'lines': [{'name': 'قهوة / Coffee', 'action': 'new', 'quantity': '1.25',
                       'previous_quantity': '0', 'delta_quantity': '1.25', 'note': ''}],
        }

    def _job(self, payload=None, key=None):
        return self.Job._create_once({
            'company_id': self.company.id, 'agent_id': self.agent.id,
            'printer_id': self.printer.id, 'ticket_type': 'preparation',
            'payload': payload if payload is not None else self._payload(),
            'idempotency_key': key or str(uuid4()),
            # PostgreSQL NOW() is fixed at transaction start, while Python's
            # clock advances during a test: make the fixture unambiguously due.
            'available_at': fields.Datetime.now() - timedelta(days=1),
        })

    @staticmethod
    def _jpeg(width=576, height=300):
        image = Image.new('RGB', (width, height), 'white')
        output = io.BytesIO()
        image.save(output, format='JPEG')
        raw = output.getvalue()
        return raw, width, height, hashlib.sha256(raw).hexdigest()

    def test_new_job_freezes_escaped_bilingual_document_for_both_widths(self):
        for width, pixels in [('58', 384), ('80', 576)]:
            with self.subTest(width=width):
                payload = self._payload(width)
                name = ('صنف طويل / Long item ' * 12) + '<script>bad()</script>'
                payload['lines'][0].update({
                    'name': name,
                    'note': '[{"text":"بدون سكر <b>سكر</b>"},{"text":"سطر ثان"}]',
                })
                original = copy.deepcopy(payload)
                job = self._job(payload)
                self.assertEqual(job.state, 'pending')
                self.assertTrue(job.print_html)
                self.assertIn(f'width: {pixels}px;', job.print_html)
                self.assertIn('Long item', job.print_html)
                self.assertIn('&lt;script&gt;bad()&lt;/script&gt;', job.print_html)
                self.assertNotIn('<script>bad()', job.print_html)
                self.assertIn('بدون سكر', job.print_html)
                self.assertIn('&lt;b&gt;سكر&lt;/b&gt;', job.print_html)
                self.assertIn('سطر ثان', job.print_html)
                self.assertIn('Cashier QA', job.print_html)
                self.assertIn('Takeaway', job.print_html)
                self.assertIn('Qty', job.print_html)
                self.assertIn('+1.25', job.print_html)
                self.assertEqual(job.payload, original)
                self.assertFalse(job.receipt_image)

    def test_duplicate_key_keeps_original_html_and_business_snapshot(self):
        key = str(uuid4())
        first = self._job(key=key)
        original_html = first.print_html
        changed = self._payload()
        changed['lines'][0]['name'] = 'MUST NOT REPLACE ORIGINAL'
        second = self._job(changed, key)
        self.assertEqual(first, second)
        self.assertEqual(second.print_html, original_html)
        self.assertNotIn('MUST NOT REPLACE ORIGINAL', second.print_html)
        self.assertEqual(second.payload['lines'][0]['name'], 'قهوة / Coffee')

    def test_decimal_actions_and_local_time_use_original_snapshot(self):
        payload = self._payload()
        payload['lines'] = [
            {'name': 'Added', 'action': 'add', 'quantity': '3.75', 'delta_quantity': '2.5'},
            {'name': 'Reduced', 'action': 'update', 'quantity': '1.25', 'delta_quantity': '-2.50'},
            {'name': 'Cancelled', 'action': 'cancel', 'quantity': '0', 'previous_quantity': '1.25'},
        ]
        self.company.partner_id.tz = 'Asia/Riyadh'
        job = self._job(payload)
        values = job._kitchen_document_values()
        self.assertEqual([line['quantity_label'] for line in values['lines']], ['+2.5', '-2.5', '×1.25'])
        self.assertIn('ADD', values['lines'][0]['action_label'])
        self.assertIn('REDUCE', values['lines'][1]['action_label'])
        self.assertIn('CANCEL', values['lines'][2]['action_label'])
        self.assertEqual(values['lines'][0]['quantity_total_label'], 'الإجمالي / Total: 3.75')
        self.assertEqual(values['lines'][1]['quantity_total_label'], 'المتبقي / Remaining: 1.25')
        self.assertEqual(values['order']['created_at'], '2026-11-19 13:00:00')
        self.assertEqual(job.payload['order']['created_at'], '2026-11-19 10:00:00')

    def test_claim_only_sends_validated_raster_envelope(self):
        job = self._job()
        raster = self._jpeg()
        with patch.object(type(self.Job), '_render_kitchen_jpeg', return_value=raster) as render:
            claim = self.Job._claim_for_agent(self.agent)
            self.assertEqual(render.call_count, 1)
        self.assertEqual(claim['id'], job.id)
        wire = claim['payload']
        self.assertEqual(wire['schema'], 4)
        self.assertEqual(wire['ticket_type'], 'receipt')
        self.assertEqual(wire['document_kind'], 'preparation')
        self.assertEqual(wire['printer']['copies'], 2)
        self.assertEqual(wire['receipt_image']['base64'], base64.b64encode(raster[0]).decode())
        self.assertEqual(wire['receipt_image']['sha256'], raster[3])
        self.assertNotIn('print_html', wire)
        self.assertNotIn('order', wire)
        self.assertNotIn('lines', wire)
        self.assertEqual(job.ticket_type, 'preparation')
        self.assertEqual(job.payload['schema'], 2)
        self.assertEqual(job.payload['lines'][0]['quantity'], '1.25')
        self.assertEqual(job.receipt_image_sha256, raster[3])
        self.assertFalse(self.Job._claim_for_agent(self.agent))

    def test_old_agent_does_not_receive_kitchen_job(self):
        job = self._job()
        self.agent.with_context(baseer_print_internal=True).write({'agent_version': '1.3.9'})
        with patch.object(type(self.Job), '_render_kitchen_jpeg') as render:
            self.assertFalse(self.Job._claim_for_agent(self.agent))
            render.assert_not_called()
        self.assertEqual(job.state, 'pending')
        self.assertEqual(job.attempt_count, 0)

    def test_historical_text_receipt_cannot_reactivate_agent_side_template(self):
        # Existing DB rows can survive an upgrade. Even a complete old financial
        # snapshot must never be leased to the Windows receipt text renderer.
        payload = self._payload()
        payload.update({'schema': 3, 'ticket_type': 'receipt',
                        'receipt': {'currency': 'SAR', 'total': '11.50'}})
        job = self.Job.sudo().create({
            'company_id': self.company.id, 'agent_id': self.agent.id,
            'printer_id': self.printer.id, 'ticket_type': 'receipt',
            'payload': payload, 'idempotency_key': str(uuid4()),
            'available_at': fields.Datetime.now() - timedelta(days=1),
        })
        self.assertFalse(self.Job._claim_for_agent(self.agent))
        self.assertEqual(job.state, 'failed')
        self.assertFalse(job.lease_token)
        self.assertEqual(job.attempt_count, 0)
        self.assertEqual(job.error_code, 'legacy_receipt')
        self.assertEqual(job.payload, payload)
        with self.assertRaises(ValidationError):
            job.action_reprint()
        self.assertFalse(self.Job.search([('reprint_of_id', '=', job.id)]))

    def test_transport_retry_reuses_original_raster_without_rendering_again(self):
        job = self._job()
        with patch.object(type(self.Job), '_render_kitchen_jpeg', return_value=self._jpeg()):
            first = self.Job._claim_for_agent(self.agent)
        original_hash = job.receipt_image_sha256
        job._fail_for_agent(self.agent, first['lease_token'], 'transport_error', retryable=True)
        self.assertEqual(job.state, 'pending')
        job.write({'available_at': fields.Datetime.now() - timedelta(days=1)})
        with patch.object(type(self.Job), '_render_kitchen_jpeg') as render:
            second = self.Job._claim_for_agent(self.agent)
            render.assert_not_called()
        self.assertEqual(second['id'], first['id'])
        self.assertNotEqual(second['lease_token'], first['lease_token'])
        self.assertEqual(second['payload']['receipt_image']['sha256'], original_hash)
        self.assertEqual(job.attempt_count, 2)

    def test_renderer_failure_is_saved_before_leasing_without_losing_intent(self):
        job = self._job()
        original = copy.deepcopy(job.payload)
        with patch.object(type(self.Job), '_render_kitchen_jpeg',
                          side_effect=subprocess.TimeoutExpired('wkhtmltoimage', 20)):
            self.assertFalse(self.Job._claim_for_agent(self.agent))
        self.assertEqual(job.state, 'failed')
        self.assertEqual(job.error_code, 'document_render_failed')
        self.assertEqual(job.attempt_count, 0)
        self.assertFalse(job.lease_token)
        self.assertFalse(job.receipt_image)
        self.assertEqual(job.payload, original)
        self.assertTrue(job.print_html)

    def test_corrupt_cached_image_is_rejected_without_rerender(self):
        job = self._job()
        with patch.object(type(self.Job), '_render_kitchen_jpeg', return_value=self._jpeg()):
            self.assertTrue(job._ensure_kitchen_image())
        job.with_context(image_no_postprocess=True).write({'receipt_image': base64.b64encode(b'corrupted')})
        with patch.object(type(self.Job), '_render_kitchen_jpeg') as render:
            self.assertFalse(self.Job._claim_for_agent(self.agent))
            render.assert_not_called()
        self.assertEqual(job.state, 'failed')
        self.assertEqual(job.error_code, 'invalid_receipt')
        self.assertEqual(job.attempt_count, 0)

    def test_reprint_uses_original_html_and_raster_after_template_edit(self):
        job = self._job()
        with patch.object(type(self.Job), '_render_kitchen_jpeg', return_value=self._jpeg()):
            self.assertTrue(job._ensure_kitchen_image())
        job.write({'state': 'done', 'completed_at': fields.Datetime.now()})
        view = self.env.ref('baseer_pos_print_bridge.kitchen_document')
        view.arch_db = view.arch_db.replace('End of order', 'CHANGED TEMPLATE MUST NOT REPRINT')
        self.assertTrue(job.action_reprint())
        reprint = self.Job.search([('reprint_of_id', '=', job.id)])
        self.assertEqual(len(reprint), 1)
        self.assertEqual(reprint.ticket_type, 'preparation')
        self.assertEqual(reprint.print_html, job.print_html)
        self.assertNotIn('CHANGED TEMPLATE MUST NOT REPRINT', reprint.print_html)
        self.assertEqual(reprint.receipt_image, job.receipt_image)
        self.assertEqual(reprint.receipt_image_sha256, job.receipt_image_sha256)
        reprint.available_at = fields.Datetime.now() - timedelta(days=1)
        with patch.object(type(self.Job), '_render_kitchen_jpeg') as render:
            claim = self.Job._claim_for_agent(self.agent)
            render.assert_not_called()
        self.assertEqual(claim['id'], reprint.id)
        self.assertEqual(claim['payload']['receipt_image']['sha256'], job.receipt_image_sha256)

    def test_expired_original_cannot_be_silently_recreated_for_reprint(self):
        job = self._job()
        with patch.object(type(self.Job), '_render_kitchen_jpeg', return_value=self._jpeg()):
            self.assertTrue(job._ensure_kitchen_image())
        job.write({'state': 'done', 'completed_at': fields.Datetime.now(),
                   'receipt_image': False, 'receipt_image_purged_at': fields.Datetime.now()})
        with self.assertRaises(ValidationError), patch.object(type(self.Job), '_render_kitchen_jpeg') as render:
            job.action_reprint()
        render.assert_not_called()
        self.assertFalse(self.Job.search([('reprint_of_id', '=', job.id)]))

    def test_kitchen_retention_keeps_recent_original_and_purges_after_30_days(self):
        recent = self._job()
        expired = self._job()
        with patch.object(type(self.Job), '_render_kitchen_jpeg', return_value=self._jpeg()):
            self.assertTrue(recent._ensure_kitchen_image())
            self.assertTrue(expired._ensure_kitchen_image())
        recent.write({'state': 'done', 'completed_at': fields.Datetime.now() - timedelta(days=2)})
        expired.write({'state': 'done', 'completed_at': fields.Datetime.now() - timedelta(days=31)})
        self.Job._purge_accepted_native_receipt_images()
        self.assertTrue(recent.receipt_image)
        self.assertFalse(recent.receipt_image_purged_at)
        self.assertFalse(expired.receipt_image)
        self.assertTrue(expired.receipt_image_purged_at)
        self.assertTrue(expired.receipt_image_sha256)

    def test_invalid_or_oversized_source_fails_visibly_without_truncation(self):
        for changes in [
            {'lines': [{'name': 'Bad quantity', 'quantity': 'NaN'}]},
            {'lines': [{'name': 'Too many', 'quantity': '1'}] * 201},
            {'lines': [{'name': 'X' * 31_000, 'quantity': '1'}]},
        ]:
            with self.subTest(changes=list(changes)):
                payload = self._payload()
                payload.update(changes)
                job = self._job(payload)
                self.assertEqual(job.state, 'failed')
                self.assertEqual(job.error_code, 'document_render_failed')
                self.assertFalse(job.print_html)
                self.assertFalse(job.receipt_image)
                self.assertEqual(job.payload, payload)

    def test_converter_is_bounded_and_validates_actual_output(self):
        job = self._job(self._payload('58'))
        raster = self._jpeg(384)

        def convert(command, **kwargs):
            kwargs['stdout'].write(raster[0])
            return subprocess.CompletedProcess(command, 0)

        with patch('odoo.addons.baseer_pos_print_bridge.models.kitchen_document.find_in_path',
                   return_value='/usr/bin/wkhtmltoimage'), patch(
                       'odoo.addons.baseer_pos_print_bridge.models.kitchen_document.subprocess.run',
                       side_effect=convert) as run:
            self.assertEqual(job._render_kitchen_jpeg(), raster)
        args, kwargs = run.call_args
        command = args[0]
        self.assertIn('--disable-local-file-access', command)
        self.assertIn('--disable-javascript', command)
        self.assertEqual(command[command.index('--width') + 1], '384')
        self.assertEqual(command[command.index('--height') + 1], '0')
        self.assertEqual(kwargs['timeout'], 20)
        self.assertTrue(kwargs['check'])
        self.assertEqual(kwargs['input'], job.print_html.encode())

    def test_missing_converter_and_timeout_do_not_produce_image(self):
        job = self._job()
        with patch('odoo.addons.baseer_pos_print_bridge.models.kitchen_document.find_in_path',
                   side_effect=OSError('binary unavailable')):
            self.assertFalse(job._ensure_kitchen_image())
        self.assertEqual(job.state, 'failed')
        self.assertFalse(job.receipt_image)
        job.write({'state': 'pending', 'completed_at': False})
        with patch('odoo.addons.baseer_pos_print_bridge.models.kitchen_document.find_in_path',
                   return_value='/usr/bin/wkhtmltoimage'), patch(
                       'odoo.addons.baseer_pos_print_bridge.models.kitchen_document.subprocess.run',
                       side_effect=subprocess.TimeoutExpired('wkhtmltoimage', 20)):
            self.assertFalse(job._ensure_kitchen_image())
        self.assertEqual(job.state, 'failed')
        self.assertEqual(job.error_code, 'document_render_failed')
        self.assertFalse(job.receipt_image_sha256)
