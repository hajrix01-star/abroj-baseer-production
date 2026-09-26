import base64
import hashlib
import json
import struct
from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBaseerAgentOperations(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.config = cls.env['pos.config'].create({'name': 'Agent status QA'})
        cls.agent = cls.env['baseer.print.agent'].create({
            'name': 'Agent operations Windows',
            'device_uid': 'agent-operations-windows-0001',
            'allowed_company_ids': [Command.set([cls.company.id])],
        })
        cls.printer = cls.env['baseer.print.printer'].with_context(baseer_print_discovery=True).create({
            'name': 'Agent operations printer',
            'agent_id': cls.agent.id,
            'machine_identifier': 'AGENT-OPERATIONS-PRINTER',
            'allowed_company_ids': [Command.set([cls.company.id])],
            'active': True,
        })
        cls.config.write({
            'baseer_direct_print_enabled': True,
            'baseer_receipt_printer_id': cls.printer.id,
        })

    def test_status_is_server_derived_and_has_no_device_secret(self):
        now = fields.Datetime.now()
        self.agent.with_context(baseer_print_internal=True).write({
            'state': 'online', 'last_seen_at': now,
        })
        status = self.env['pos.config'].baseer_agent_status(self.config.id)
        self.assertEqual(status['state'], 'online')
        self.assertTrue(status['configured'])
        self.assertNotIn('token', status)
        self.assertNotIn('printer', status)

        self.agent.with_context(baseer_print_internal=True).write({
            'last_seen_at': now - timedelta(seconds=20),
        })
        self.assertEqual(self.env['pos.config'].baseer_agent_status(self.config.id)['state'], 'stale')

        self.agent.with_context(baseer_print_internal=True).write({
            'last_seen_at': now - timedelta(seconds=31),
        })
        status = self.env['pos.config'].baseer_agent_status(self.config.id)
        self.assertEqual(status['state'], 'offline')
        self.assertTrue(status['repair_uri_allowed'])

    def test_runtime_lease_allows_only_one_active_agent(self):
        """A copied pairing token must never let two agents print together."""
        first_runtime = 'runtime-owner-0001'
        second_runtime = 'runtime-owner-0002'

        self.assertTrue(self.agent._claim_runtime(first_runtime))
        self.assertFalse(self.agent._claim_runtime(second_runtime))
        # Older agents that do not send a runtime ID cannot run beside a
        # current owner either.
        self.assertFalse(self.agent._claim_runtime())

        # Use the same PostgreSQL clock as the lease predicate.  It is fixed
        # at the start of this transaction during a TransactionCase.
        self.env.cr.execute("""
            UPDATE baseer_print_agent
               SET runtime_lease_expires_at = NOW() - INTERVAL '5 minutes'
             WHERE id = %s
        """, [self.agent.id])
        self.assertTrue(self.agent._claim_runtime(second_runtime))
        self.assertFalse(self.agent._heartbeat(runtime_id=first_runtime))
        self.assertTrue(self.agent._heartbeat(runtime_id=second_runtime))

    def test_controlled_release_requires_the_exact_active_runtime(self):
        """Repair may hand over locally, but never force another owner out."""
        current_runtime = 'runtime-current-owner-0001'
        different_runtime = 'runtime-different-owner-0002'
        replacement_runtime = 'runtime-replacement-owner-0003'

        self.assertTrue(self.agent._claim_runtime(current_runtime))
        self.assertFalse(self.agent._release_runtime(different_runtime))
        self.assertFalse(self.agent._claim_runtime(replacement_runtime))

        self.assertTrue(self.agent._release_runtime(current_runtime))
        self.agent.invalidate_recordset(['runtime_instance_id', 'runtime_lease_expires_at'])
        self.assertFalse(self.agent.runtime_instance_id)
        self.assertFalse(self.agent.runtime_lease_expires_at)
        self.assertTrue(self.agent._claim_runtime(replacement_runtime))

    def test_approved_release_is_hashed_and_immutable(self):
        payload = b'QA Windows agent installer artifact'
        release = self.env['baseer.print.agent.release'].create({
            'name': 'QA Windows agent',
            'version': '9.9.9-qa',
            'artifact_filename': 'Baseer.PrintAgent.exe',
            'artifact': base64.b64encode(payload),
        })
        release.action_approve()
        self.assertEqual(release.state, 'approved')
        self.assertEqual(release.artifact_sha256, hashlib.sha256(payload).hexdigest())
        with self.assertRaises(UserError):
            release.write({'artifact': base64.b64encode(b'mutated')})
        self.assertIn('/baseer/print/agent-release/%s/download' % release.id, release.action_download()['url'])

    def test_one_click_download_uses_pending_agent_and_one_time_envelope(self):
        release = self.env['baseer.print.agent.release'].create({
            'name': 'Bootstrap QA Windows agent',
            'version': '9.9.10-qa',
            'artifact_filename': 'Baseer.PrintAgent.exe',
            'artifact': base64.b64encode(b'QA Windows agent installer artifact'),
        })
        release.action_approve()
        pending = self.env['baseer.print.agent'].create({
            'name': 'Pending bootstrap computer',
            'device_uid': 'PENDING-bootstrap-agent-0001',
            'allowed_company_ids': [Command.set([self.company.id])],
        })
        action = release.action_download_and_connect(pending)
        self.assertIn('bootstrap_agent_id=%s' % pending.id, action['url'])
        self.assertNotIn('pairing_code', action['url'])
        pairing_code = pending._generate_pairing_code()
        artifact = release._bootstrap_artifact('https://qa.example.test', pairing_code)
        self.assertTrue(artifact.endswith(b'BASEER-BOOTSTRAP-V1'))
        self.assertIn(pairing_code.encode(), artifact)
        envelope_size = struct.unpack('<I', artifact[-len(b'BASEER-BOOTSTRAP-V1') - 4:-len(b'BASEER-BOOTSTRAP-V1')])[0]
        envelope = json.loads(artifact[-len(b'BASEER-BOOTSTRAP-V1') - 4 - envelope_size:-len(b'BASEER-BOOTSTRAP-V1') - 4])
        self.assertEqual(envelope, {
            'ServerUrl': 'https://qa.example.test',
            'PairingCode': pairing_code,
        })
        self.assertNotEqual(pending.pairing_fingerprint, pairing_code)
        with self.assertRaises(ValidationError):
            release.action_download_and_connect(self.agent)

    def test_pos_print_tab_downloads_a_connection_file_without_the_release_center(self):
        self.env['ir.config_parameter'].sudo().set_param('web.base.url', 'https://qa.example.test')
        release = self.env['baseer.print.agent.release'].create({
            'name': 'POS tab bootstrap agent',
            'version': '9.9.11-qa',
            'artifact_filename': 'Baseer.PrintAgent.exe',
            'artifact': base64.b64encode(b'POS tab bootstrap installer'),
        })
        release.action_approve()

        action = self.config.action_baseer_download_and_connect_agent()
        pending = self.env['baseer.print.agent'].browse(int(action['url'].split('=')[-1]))

        self.assertTrue(pending.device_uid.startswith('PENDING-'))
        self.assertIn('bootstrap_agent_id=%s' % pending.id, action['url'])
        self.assertNotIn('pairing_code', action['url'])

    def test_discovered_windows_printer_is_immediately_available_to_the_pos(self):
        self.env['baseer.print.printer']._sync_from_agent(self.agent, [{
            'display_name': 'Discovered thermal receipt printer',
            'machine_identifier': 'DISCOVERED-THERMAL-80',
            'driver_name': 'Thermal driver',
        }])
        printer = self.env['baseer.print.printer'].search([
            ('agent_id', '=', self.agent.id),
            ('machine_identifier', '=', 'DISCOVERED-THERMAL-80'),
        ])
        self.assertTrue(printer.active)
        self.assertEqual(printer.driver_name, 'Thermal driver')

    def test_release_center_download_uses_the_same_connection_file(self):
        self.env['ir.config_parameter'].sudo().set_param('web.base.url', 'https://qa.example.test')
        release = self.env['baseer.print.agent.release'].create({
            'name': 'Release center bootstrap agent',
            'version': '9.9.12-qa',
            'artifact_filename': 'Baseer.PrintAgent.exe',
            'artifact': base64.b64encode(b'Release center bootstrap installer'),
        })
        release.action_approve()

        action = release.action_download_and_connect_current_company()
        pending = self.env['baseer.print.agent'].browse(int(action['url'].split('=')[-1]))

        self.assertTrue(pending.device_uid.startswith('PENDING-'))
        self.assertIn('bootstrap_agent_id=%s' % pending.id, action['url'])
        self.assertNotIn('pairing_code', action['url'])
