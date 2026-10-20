"""Destructive assertions run ONLY in disposable, rolled-back Odoo tests."""
import hashlib
import base64
import json
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from odoo import Command, fields, api, sql_db
from odoo.exceptions import AccessError, ValidationError, UserError
from odoo.tests import HttpCase, TransactionCase, tagged
from odoo.addons.baseer_bwork.contracts import ProtocolError
from odoo.addons.baseer_bwork.models.retention import _READY_KEY, _RETENTION_TOKEN
from odoo.addons.baseer_bwork.models.room import _GROUP_TOKEN
from odoo.addons.baseer_bwork.models.media import _MEDIA_TOKEN


from ..models.retention import _ADMIN_TOKEN


class RetentionFixtures:
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.admin = cls.env.ref('base.user_admin')
        cls.manager = cls.env.ref('baseer_bwork.group_bwork_manager')
        cls.retention_group = cls.env.ref('baseer_bwork_admin.group_bwork_retention_manager')
        cls.password = 'retention-test-' + uuid4().hex
        cls.admin.write({'group_ids': [Command.link(cls.manager.id)],
                         'bwork_chat_view': True, 'bwork_media': True})
        cls.reader = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Synthetic retention reader', 'login': 'retention-' + uuid4().hex,
            # Explicit file sender/reader under the fresh-closed default policy.
            'bwork_chat_view': True, 'bwork_chat_send': True, 'bwork_media': True,
            'password': cls.password,
            'company_id': cls.company.id, 'company_ids': [Command.set(cls.company.ids)],
            'group_ids': [Command.set([cls.env.ref('base.group_user').id])],
        })
        cls.room = cls.env['baseer.bwork.room'].with_user(cls.admin).create({
            'name': 'Synthetic retention room', 'company_id': cls.company.id})
        cls.member = cls.env['baseer.bwork.membership'].with_user(cls.admin).create({
            'room_id': cls.room.id, 'user_id': cls.reader.id})
        cls.source = cls.env['baseer.bwork.service'].with_user(cls.reader).with_context(allowed_company_ids=cls.company.ids)
        cls.service = cls.env['baseer.bwork.retention.service'].with_user(cls.admin).with_context(allowed_company_ids=cls.company.ids)

    def _file(self, text='Synthetic caption'):
        raw = b'SYNTHETIC_RETENTION_TRANSACTION_ONLY'
        upload = self.source._v2_upload(self.room.id, {
            'api_version': 2, 'membership_id': self.member.id, 'upload_uuid': str(uuid4()),
            'kind': 'file', 'mime': 'text/plain', 'name': 'synthetic.txt', 'size': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest(),
        }, raw)
        payload = {'api_version': 2, 'membership_id': self.member.id, 'client_uuid': str(uuid4()),
                   'text': text, 'media_id': upload['media_id']}
        ack = self.source._v2_send(self.room.id, payload)
        message = self.env['baseer.bwork.message'].sudo().browse(ack['message_id'])
        self.env.cr.execute("UPDATE baseer_bwork_message SET create_date=NOW()-INTERVAL '40 days' WHERE id=%s", [message.id])
        message.invalidate_recordset()
        return message, payload, ack

    def _preview(self, mode='messages_and_attachments'):
        return self.service._preview(self.company.id, 'rooms', self.room.ids, mode,
                                     fields.Datetime.now() - timedelta(days=30))


@tagged('post_install', '-at_install', 'bwork_retention')
class BWorkRetentionCase(RetentionFixtures, TransactionCase):
    def test_attachment_preview_latch_scrub_tombstones_and_replay(self):
        message, payload, ack = self._file()
        media, original = message.media_id, message.media_id.attachment_id
        digest, upload_uuid = message.payload_digest, media.upload_uuid
        run = self._preview()
        self.assertFalse(run.env.su)
        self.assertEqual((run.eligible_total, run.candidate_media), (1, 1))
        self.assertEqual(int(run.candidate_bytes), original.file_size)
        run.confirmation_checked = True
        with self.assertRaises(ValidationError):
            run.action_confirm()
        self.assertTrue(original.exists())
        self.assertEqual(message.text, payload['text'])
        # This activation exists only inside this test transaction and rolls back.
        self.env['ir.config_parameter'].sudo().set_param(_READY_KEY, '1')
        run.action_confirm()
        run.action_confirm()  # Same job; never a second manifest/execution.
        self.service._execute_batch(run)
        message.invalidate_recordset()
        media.invalidate_recordset()
        self.assertEqual(run.state, 'done')
        self.assertEqual((run.processed, run.removed, run.failed), (1, 1, 0))
        self.assertTrue(message.exists())
        self.assertTrue(media.exists())
        self.assertFalse(original.exists())
        self.assertFalse(message.text)
        self.assertEqual(message.payload_digest, digest)
        self.assertEqual(media.upload_uuid, upload_uuid)
        self.assertEqual(message.retention_state, 'content_removed')
        self.assertEqual(self.source._v2_send(self.room.id, payload), dict(ack, content_removed=True))
        room = self.room.sudo()
        self.assertEqual(room.content_revision, 1)
        state = self.source._v2_content_state(room.id, {'api_version': 2,
            'membership_id': self.member.id, 'content_revision': 1, 'media_ids': [media.id]})
        self.assertEqual(state['items'], [{'media_id': media.id, 'state': 'removed'}])
        with self.assertRaises(ProtocolError) as caught:
            self.source._v2_media_content(media.id)
        self.assertEqual(caught.exception.status, 410)
        self.assertTrue(run.audit_ids.filtered(lambda row: row.action == 'batch'))
        run.invalidate_recordset()
        self.assertEqual(run.read(['state', 'company_id'])[0]['state'], 'done')
        with self.assertRaises(AccessError):
            run.sudo().read(['audit_ids'])
        with self.assertRaises(AccessError):
            run.sudo().export_data(['state'])
        with self.assertRaises(AccessError):
            message.write({'text': 'forbidden'})
        with self.assertRaises(AccessError):
            message.unlink()

    def test_explicit_role_intersection_company_and_superuser_denials(self):
        self._file()
        delegated = self.reader
        delegated.sudo().write({'group_ids': [Command.link(self.retention_group.id)]})
        ordinary = self.service.with_user(delegated)
        with self.assertRaises(AccessError):
            ordinary._preview(self.company.id, 'company', [], 'attachments', fields.Datetime.now())
        delegated.sudo().write({'group_ids': [Command.link(self.manager.id)]})
        delegated_run = ordinary._preview(self.company.id, 'rooms', self.room.ids,
                                         'attachments', fields.Datetime.now())
        self.assertEqual(delegated_run.state, 'preview')
        policy = ordinary.env['baseer.bwork.retention.policy'].create({'company_id': self.company.id})
        wizard = ordinary.env['baseer.bwork.retention.wizard'].create({'company_id': self.company.id})
        records = [policy, wizard, delegated_run, delegated_run.item_ids, delegated_run.audit_ids]
        self.assertFalse(delegated.has_group('base.group_allow_export'))
        for record in records:
            record.read(['company_id'])  # Retention authority is valid already.
            with self.assertRaises(UserError) as denied:
                record.export_data(['id'])
            self.assertIs(type(denied.exception), UserError)  # Native export-role denial, not AccessError.
        # Explicit fixture capability only: no module ACL/group definition or
        # production actor is changed. Keep native export authorization intact.
        delegated.sudo().write({'group_ids': [Command.link(self.env.ref('base.group_allow_export').id)]})
        self.assertTrue(delegated.has_group('base.group_allow_export'))
        for record in records:
            self.assertTrue(record)
            record.read(['company_id'])  # Warm metadata before every negative.
            self.assertTrue(record.export_data(['id'])['datas'])
            with self.assertRaises(AccessError):
                record.sudo().export_data(['id'])
        switched = self.env['res.company'].create({'name': 'Synthetic retention scope switch'})
        delegated.sudo().write({'company_ids': [Command.link(switched.id)]})
        for record in records:
            with self.assertRaises(AccessError):
                record.with_context(allowed_company_ids=switched.ids).export_data(['id'])
            with self.assertRaises(AccessError):
                record.with_context(allowed_company_ids=switched.ids).export_data(['company_id'])
        delegated.sudo().write({'group_ids': [Command.unlink(self.retention_group.id)]})
        for record in records:
            with self.assertRaises(AccessError):
                record.export_data(['id'])
            with self.assertRaises(AccessError):
                record.export_data(['company_id'])
        with self.assertRaises(AccessError):
            ordinary._preview(self.company.id, 'company', [], 'attachments', fields.Datetime.now())
        foreign = self.env['res.company'].create({'name': 'Synthetic foreign retention company'})
        with self.assertRaises(AccessError):
            ordinary._preview(foreign.id, 'company', [], 'attachments', fields.Datetime.now())
        with self.assertRaises(AccessError):
            self.service.sudo()._preview(self.company.id, 'company', [], 'attachments', fields.Datetime.now())
        run = self._preview()
        run.invalidate_recordset()
        self.assertEqual(run.read(['state'])[0]['state'], 'preview')
        # A WRITE-only native rule must still deny acknowledgment while READ
        # remains allowed; substituting read rules would weaken this assertion.
        self.env['ir.rule'].create({'name': 'Synthetic retention write denial',
            'model_id': self.env.ref('baseer_bwork_admin.model_baseer_bwork_retention_run').id,
            'domain_force': "[('id', '=', 0)]", 'perm_read': False, 'perm_write': True,
            'perm_create': False, 'perm_unlink': False})
        self.assertEqual(run.read(['state'])[0]['state'], 'preview')
        with self.assertRaises(AccessError):
            run.write({'confirmation_checked': True})

    def test_shared_inverse_hold_and_external_reference_are_protected(self):
        message, _, _ = self._file()
        self.assertEqual(self.service.env['baseer.bwork.service']._retention_inspect(message, _RETENTION_TOKEN)[0], 'eligible')
        self.env.cr.execute('UPDATE baseer_bwork_message SET retention_preserved=TRUE WHERE id=%s', [message.id])
        message.invalidate_recordset()
        self.assertEqual(self._preview().protected_count, 1)
        self.env.cr.execute('UPDATE baseer_bwork_message SET retention_preserved=FALSE WHERE id=%s', [message.id])
        message.invalidate_recordset()
        other, _, _ = self._file()
        self.env.cr.execute('UPDATE baseer_bwork_media SET message_id=%s WHERE id=%s', [message.id, other.media_id.id])
        self.assertEqual(self.service.env['baseer.bwork.service']._retention_inspect(message, _RETENTION_TOKEN)[0], 'shared_media')
        self.env.cr.execute('UPDATE baseer_bwork_media SET message_id=%s WHERE id=%s', [other.id, other.media_id.id])
        # Real FK DDL/data in this rollback-only test. An external link to media
        # (without a link to message or attachment) must veto content erasure.
        self.env.cr.execute('CREATE TABLE brt_test_external_media_ref (id SERIAL PRIMARY KEY, media_id INTEGER REFERENCES baseer_bwork_media(id))')
        self.env.cr.execute('INSERT INTO brt_test_external_media_ref(media_id) VALUES (%s)', [message.media_id.id])
        self.assertEqual(self.service.env['baseer.bwork.service']._retention_inspect(message, _RETENTION_TOKEN, lock=True)[0], 'external_media_reference')

    def test_exact_large_byte_evidence_and_native_transient_vacuum(self):
        console = self.service.env['baseer.bwork.admin.console'].new({'company_ids': [Command.set(self.company.ids)]})
        self.assertEqual(console.display_name, 'BWork Administration')
        self.assertNotIn('NewId', console.display_name)
        message, _, _ = self._file()
        # Metadata only: no multi-GiB file is created. Exercise database storage
        # of candidate/item/audit counters above PostgreSQL int4 capacity.
        other, _, _ = self._file()
        each, large = 1500000000, 3000000000
        self.env.cr.execute('UPDATE ir_attachment SET file_size=%s WHERE id=ANY(%s)', [each, (message.media_id.attachment_id | other.media_id.attachment_id).ids])
        self.env['ir.attachment'].invalidate_model()
        run = self._preview()
        self.assertEqual(run.candidate_bytes, str(large))
        self.assertEqual(run.item_ids.mapped('logical_bytes'), [str(each), str(each)])
        self.assertEqual(run.audit_ids.bytes, str(large))
        self.assertEqual(run.candidate_bytes_display, '2.79 GiB')
        wizard = self.env['baseer.bwork.retention.wizard'].with_user(self.admin)
        fresh, aged = wizard.create([{'company_id': self.company.id}, {'company_id': self.company.id}])
        self.env.cr.execute("UPDATE baseer_bwork_retention_wizard SET write_date=NOW()-INTERVAL '2 days' WHERE id=%s", [aged.id])
        wizard.sudo()._transient_clean_rows_older_than(3600)
        self.env.cr.execute('SELECT id FROM baseer_bwork_retention_wizard WHERE id=ANY(%s)', [(fresh | aged).ids])
        self.assertEqual([row[0] for row in self.env.cr.fetchall()], [fresh.id])
        self.reader.sudo().write({'group_ids': [Command.link(self.manager.id), Command.link(self.retention_group.id)]})
        with self.assertRaises(AccessError):
            fresh.with_user(self.reader).read(['company_id'])
        self.assertFalse(wizard.with_user(self.reader).search([('id', '=', fresh.id)]))
        with self.assertRaises(AccessError):
            fresh.sudo().read(['company_id'])
        with self.assertRaises(AccessError):
            wizard.sudo().search([])

    def test_policy_schedule_default_off_one_local_day_and_configuration_revision(self):
        self._file()
        policy_model = self.service.env['baseer.bwork.retention.policy']
        policy = policy_model.create({'company_id': self.company.id, 'timezone': 'UTC',
            'schedule_hour': '00', 'schedule_minute': '00'})
        self.assertFalse(policy.enabled)
        self.assertEqual(policy.readiness_status, 'not_ready')
        with self.assertRaises(ValidationError):
            policy.action_confirm_readiness()
        policy.write({'enabled': True})
        now = fields.Datetime.now()
        policy._service_write({'next_run_at': now - timedelta(minutes=1)}, _ADMIN_TOKEN)
        self.service.sudo()._cron_tick()
        self.assertFalse(self.service.env['baseer.bwork.retention.run'].search([]))
        policy.write({'ack_clients_updated': True, 'ack_legacy_offline': True})
        policy.action_confirm_readiness()
        policy._service_write({'next_run_at': now - timedelta(minutes=1)}, _ADMIN_TOKEN)
        with patch.object(fields.Datetime, 'now', return_value=now):
            self.service.sudo()._cron_tick()
            self.service.sudo()._cron_tick()
        runs = self.service.env['baseer.bwork.retention.run'].search([('policy_id', '=', policy.id)])
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs.state, 'done')
        self.assertEqual(runs.scheduled_local_date, now.date())
        self.assertEqual(policy.last_local_date, now.date())
        policy.action_revoke_readiness()
        self.assertFalse(self.source._v2_bootstrap()['capabilities']['retention_ready'])

    def test_revoke_latch_role_and_configuration_before_batch_preserves_content(self):
        message, _, _ = self._file()
        policy = self.service.env['baseer.bwork.retention.policy'].create({'company_id': self.company.id})
        run = self.service._preview(self.company.id, 'company', [], 'attachments',
            fields.Datetime.now() - timedelta(days=30), policy=policy)
        run.confirmation_checked = True
        policy.write({'retention_days': 31})
        with self.assertRaises(ValidationError):
            run.action_confirm()
        run = self._preview()
        run.confirmation_checked = True
        self.env['ir.config_parameter'].sudo().set_param(_READY_KEY, '1')
        run.action_confirm()
        self.env['ir.config_parameter'].sudo().set_param(_READY_KEY, '0')
        with self.assertRaises(ValidationError):
            self.service._execute_batch(run)
        self.env['ir.config_parameter'].sudo().set_param(_READY_KEY, '1')
        self.admin.sudo().write({'bwork_manage_rooms': False})
        with self.assertRaises(AccessError):
            self.service._execute_batch(run)
        self.assertTrue(message.media_id.attachment_id.exists())
        self.assertEqual(message.retention_state, 'active')

    def test_preserve_canonical_label_search_literal_and_revision_cursor(self):
        owner_member = self.env['baseer.bwork.membership'].with_user(self.admin).create({
            'room_id': self.room.id, 'user_id': self.admin.id})
        message, _, _ = self._file()
        with self.assertRaises(AccessError):
            self.source._v2_preserve_message(self.room.id, message.id,
                {'api_version': 2, 'membership_id': self.member.id, 'preserved': True})
        source = self.service.env['baseer.bwork.service']
        held = source._v2_preserve_message(self.room.id, message.id,
            {'api_version': 2, 'membership_id': owner_member.id, 'preserved': True})
        self.assertTrue(held['message']['retention_preserved'])
        self.assertEqual(held['message']['media']['size_label'], '%s B' % message.media_id.size_bytes)
        self.assertEqual(self._preview().protected_count, 1)
        self.assertFalse(self.source._v2_gallery(self.room.id, q='%')['items'])
        self.assertEqual(self.source._v2_gallery(self.room.id, q='synthetic')['items'][0]['id'], message.id)
        self._file()
        page = self.source._v2_gallery(self.room.id, limit=1)
        self.env.cr.execute('UPDATE baseer_bwork_room SET content_revision=content_revision+1 WHERE id=%s', [self.room.id])
        self.room.invalidate_recordset()
        with self.assertRaises(ProtocolError):
            self.source._v2_gallery(self.room.id, limit=1, cursor=page['next_cursor'])

    def test_expired_unlinked_upload_manifest_uses_native_close_no_room_content_revision(self):
        raw = b'SYNTHETIC_EXPIRED_ONLY'
        upload = self.source._v2_upload(self.room.id, {
            'api_version': 2, 'membership_id': self.member.id, 'upload_uuid': str(uuid4()),
            'kind': 'file', 'mime': 'text/plain', 'name': 'expired.txt', 'size': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest(),
        }, raw)
        media = self.env['baseer.bwork.media'].sudo().browse(upload['media_id'])
        attachment = media.attachment_id
        self.env.cr.execute("UPDATE baseer_bwork_media SET create_date=NOW()-INTERVAL '40 days' WHERE id=%s", [media.id])
        media.invalidate_recordset()
        run = self._preview('expired_uploads')
        self.assertEqual((run.candidate_messages, run.candidate_media), (0, 1))
        run.confirmation_checked = True
        self.env['ir.config_parameter'].sudo().set_param(_READY_KEY, '1')
        run.action_confirm()
        self.service._execute_batch(run)
        media.invalidate_recordset()
        self.assertEqual(media.state, 'expired')
        self.assertTrue(media.exists())
        self.assertFalse(attachment.exists())
        self.assertEqual(self.room.sudo().content_revision, 0)

    def test_real_repeatable_read_phantom_requires_fresh_readonly_reference_probe(self):
        # Real independent physical transactions, not registry TestCursor. Only
        # synthetic metadata is committed; cleanup removes exactly those rows.
        database = sql_db.db_connect(self.env.cr.dbname)
        marker = str(uuid4())
        ids = {}
        table = 'brt_test_committed_external_media_ref'

        def cleanup():
            with database.cursor() as cr:
                cr.execute('DROP TABLE IF EXISTS brt_test_committed_external_media_ref')
                if ids:
                    cr.execute('DELETE FROM baseer_bwork_media WHERE id=%s AND upload_uuid=%s', [ids['media'], marker])
                    cr.execute('DELETE FROM baseer_bwork_membership WHERE id=%s AND room_id=%s', [ids['member'], ids['room']])
                    cr.execute('DELETE FROM baseer_bwork_room WHERE id=%s AND group_create_uuid=%s', [ids['room'], marker])
                cr.commit()

        self.addCleanup(cleanup)
        with database.cursor() as cr:
            env = api.Environment(cr, self.admin.id, {'allowed_company_ids': self.company.ids})
            room = env['baseer.bwork.room']._create_group_verified({
                'name': 'SYNTHETIC_BRT_CONCURRENCY_ONLY', 'company_id': self.company.id,
                'is_group': True, 'group_creator_user_id': self.admin.id,
                'group_create_uuid': marker, 'group_create_digest': '0' * 64}, _GROUP_TOKEN)
            member = env['baseer.bwork.membership']._create_group_verified({
                'room_id': room.id, 'company_id': self.company.id, 'user_id': self.admin.id,
                'joined_after_message_id': 0, 'active': True, 'is_group_admin': True}, _GROUP_TOKEN)
            media = env['baseer.bwork.media']._create_verified({
                'room_id': room.id, 'company_id': self.company.id, 'membership_id': member.id,
                'author_user_id': self.admin.id, 'upload_uuid': marker, 'kind': 'file',
                'mime': 'text/plain', 'size_bytes': 1, 'sha256': '0' * 64,
                'name': 'SYNTHETIC_METADATA_ONLY.txt'}, _MEDIA_TOKEN)
            ids.update(room=room.id, member=member.id, media=media.id)
            cr.execute('CREATE TABLE brt_test_committed_external_media_ref (id SERIAL PRIMARY KEY, media_id INTEGER REFERENCES baseer_bwork_media(id))')
            cr.commit()
        with database.cursor() as old:
            old.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            old.execute('SELECT count(*) FROM brt_test_committed_external_media_ref')
            self.assertEqual(old.fetchone()[0], 0)  # Freeze outer snapshot.
            with database.cursor() as writer:
                writer.execute('INSERT INTO brt_test_committed_external_media_ref(media_id) VALUES (%s)', [ids['media']])
                writer.commit()  # Committed after snapshot, before source lock.
            env = api.Environment(old, self.admin.id, {'allowed_company_ids': self.company.ids})
            service = env['baseer.bwork.service']
            service._retention_lock_sources(media=env['baseer.bwork.media'].sudo().browse(ids['media']))
            allowed = {'baseer_bwork_message', 'baseer_bwork_mobile_upload_grant', 'baseer_bwork_retention_item'}
            self.assertFalse(service._retention_foreign_reference('baseer_bwork_media', ids['media'], allowed))
            self.assertTrue(service._retention_foreign_reference('baseer_bwork_media', ids['media'], allowed, fresh=True))
            old.rollback()

    def test_same_attachment_id_changed_after_preview_is_skipped_in_both_modes(self):
        for mode in ('attachments', 'messages_and_attachments'):
            message, _, _ = self._file()
            attachment = message.media_id.attachment_id
            run = self._preview(mode)
            changed = b'SYNTHETIC_NEW_BYTES_NOT_IN_CONFIRMED_PREVIEW'
            attachment.sudo().write({'datas': base64.b64encode(changed)})
            run.confirmation_checked = True
            self.env['ir.config_parameter'].sudo().set_param(_READY_KEY, '1')
            run.action_confirm()
            self.service._execute_batch(run)
            self.assertGreaterEqual(run.skipped, 1)
            self.assertEqual(run.item_ids.filtered(lambda row: row.message_id.id == message.id).code, 'changed')
            self.assertTrue(attachment.exists())
            self.assertEqual(base64.b64decode(attachment.datas), changed)
            message.invalidate_recordset()
            self.assertEqual(message.retention_state, 'active')
            self.assertEqual(message.text, 'Synthetic caption')


@tagged('post_install', '-at_install', 'bwork_retention')
class BWorkRetentionHttpCase(RetentionFixtures, HttpCase):
    def test_reconcile_http_csrf_revision_permissions_and_no_content_leak(self):
        message, _, _ = self._file()
        payload = {'api_version': 2, 'membership_id': self.member.id,
                   'content_revision': 0, 'media_ids': [message.media_id.id]}
        self.assertEqual(self.source._v2_content_state(self.room.id, payload)['items'][0]['state'], 'live')
        self.authenticate(self.reader.login, self.password)
        bootstrap = self.url_open('/bwork/api/v2/bootstrap').json()
        self.assertEqual(bootstrap['capabilities']['retention_version'], 1)
        path = '/bwork/api/v2/rooms/%s/content-state' % self.room.id
        gallery = self.url_open('/bwork/api/v2/rooms/%s/media' % self.room.id).json()
        self.assertIn(message.id, [row['id'] for row in gallery['items']])
        def request(value):
            return self.url_open(path, data={'csrf_token': bootstrap['csrf_token'], 'payload': json.dumps(value)})
        response = request(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(response.json()['items'][0]['state'], 'live')
        self.assertEqual(request(dict(payload, content_revision=1)).status_code, 409)
        self.assertEqual(request(dict(payload, media_ids=[message.media_id.id] * 2)).status_code, 400)
        self.assertEqual(self.url_open(path, data={'payload': json.dumps(payload)}).status_code, 400)
        self.reader.sudo().write({'bwork_media': False})
        self.assertEqual(request(payload).status_code, 403)

    def test_unauthenticated_reconciliation_and_employee_preservation_denied(self):
        message, _, _ = self._file()
        path = '/bwork/api/v2/rooms/%s/content-state' % self.room.id
        self.assertNotEqual(self.url_open(path, data={}, allow_redirects=False).status_code, 200)
        self.authenticate(self.reader.login, self.password)
        csrf = self.url_open('/bwork/api/v2/bootstrap').json()['csrf_token']
        response = self.url_open('/bwork/api/v2/rooms/%s/messages/%s/preserve' % (self.room.id, message.id),
            data={'csrf_token': csrf, 'payload': json.dumps({'api_version': 2,
                'membership_id': self.member.id, 'preserved': True})})
        self.assertEqual(response.status_code, 403)
        message.invalidate_recordset()
        self.assertFalse(message.retention_preserved)
