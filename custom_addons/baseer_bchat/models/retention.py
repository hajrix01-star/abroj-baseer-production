"""Retention protocol and narrow content-erasure capability; no public delete ACL.

The administration addon owns policy, manifests and execution. This base layer
never imports it, enables retention, or schedules destructive work itself.
"""
import hashlib
import json
from datetime import timedelta

from odoo import api, fields, models, sql_db
from odoo.exceptions import AccessError
from odoo.tools import SQL

from .. import retention_contracts as wire
from ..gallery_contracts import size_label
from ..contracts import ProtocolError, positive_id

_RETENTION_TOKEN = object()
_READY_KEY = 'baseer_bchat.retention_ready'
_INTERNAL_FKS = {
    'baseer_bchat_message': {
        ('baseer_bchat_message', 'reply_to_message_id'), ('baseer_bchat_media', 'message_id'),
        ('baseer_bchat_message_receipt', 'message_id'), ('baseer_bchat_change', 'message_id'),
        ('baseer_bchat_push_event', 'message_id'), ('baseer_bwork_retention_item', 'message_id')},
    'baseer_bchat_media': {
        ('baseer_bchat_message', 'media_id'), ('baseer_bwork_retention_item', 'media_id'),
        ('baseer_bchat_mobile_upload_grant', 'media_id')},
    'ir_attachment': {('baseer_bchat_media', 'attachment_id'), ('baseer_bchat_media', 'thumbnail_attachment_id')},
}


class BChatRetentionRoom(models.Model):
    _inherit = 'baseer.bchat.room'

    content_revision = fields.Integer(default=0, readonly=True, copy=False)


class BChatRetentionMessage(models.Model):
    _inherit = 'baseer.bchat.message'

    retention_state = fields.Selection([('active', 'Available'), ('content_removed', 'Content removed')],
                                       default='active', required=True, readonly=True, index=True)
    retention_preserved = fields.Boolean(default=False, readonly=True, copy=False)
    content_removed_at = fields.Datetime(readonly=True, copy=False)


class BChatRetentionMedia(models.Model):
    _inherit = 'baseer.bchat.media'

    retention_state = fields.Selection([('active', 'Available'), ('content_removed', 'Content removed')],
                                       default='active', required=True, readonly=True, index=True)
    content_removed_at = fields.Datetime(readonly=True, copy=False)


class BChatRetentionService(models.AbstractModel):
    _inherit = 'baseer.bchat.service'

    @api.model
    def _retention_ready(self, lock=False):
        # Technical readiness only, not a source/content ACL or policy default.
        self.env.cr.execute('SELECT value FROM ir_config_parameter WHERE key=%s' + (' FOR SHARE' if lock else ''), [_READY_KEY])
        row = self.env.cr.fetchone()
        return bool(row and row[0] == '1')

    @api.model
    def _retention_guard(self, company_id):
        user = self._require_user()
        allowed = self._retention_actor_allowed()
        company_id = positive_id(company_id, 'company_id')
        if not allowed or company_id not in (set(user.company_ids.ids) & set(self.env.companies.ids)):
            raise AccessError(self.env._('Retention requires owner authority or both explicit retention and existing room-manager roles in the current company.'))
        return user

    def _retention_actor_allowed(self):
        user = self._require_user()
        group = self.env.ref('baseer_bwork_admin.group_bwork_retention_manager', raise_if_not_found=False)
        manager = self.env.ref('baseer_bchat.group_bchat_manager')
        return user._bchat_effective_permissions()['room_admin'] or bool(
            group and group in user.group_ids and manager in user.group_ids)

    def _retention_admin_available(self):
        return False

    def _retention_audit_preserve(self, message, preserved):
        raise ProtocolError('retention_unavailable', 'Retention administration is unavailable.', 409)

    @api.model
    def _v2_bootstrap(self):
        result = super()._v2_bootstrap()
        result['capabilities'].update(retention_version=1, retention_ready=self._retention_ready())
        result['capabilities']['can_manage_retention'] = bool(
            self._retention_admin_available() and self._retention_actor_allowed())
        return result

    @api.model
    def _v2_room_rows(self, memberships):
        rows = super()._v2_room_rows(memberships)
        revision = {m.room_id.id: m.room_id.content_revision for m in memberships}
        for row in rows:
            row['content_revision'] = revision[row['id']]
        return rows

    @api.model
    def _v2_history(self, room_id, before_id=None):
        result = super()._v2_history(room_id, before_id)
        result['content_revision'] = self.env['baseer.bchat.room'].sudo().browse(room_id).content_revision
        return result

    @api.model
    def _v2_message(self, room_id, message_id):
        result = super()._v2_message(room_id, message_id)
        result['content_revision'] = self.env['baseer.bchat.room'].sudo().browse(room_id).content_revision
        return result

    @api.model
    def _v2_history_payload(self, page, more, author_names, parent_by_id=None):
        result = super()._v2_history_payload(page, more, author_names, parent_by_id)
        sources = {m.id: m for m in page}
        for row in result['messages']:
            message = sources[row['id']]
            row['retention_preserved'] = bool(message.retention_preserved)
            if message.retention_state == 'content_removed':
                row.update(text='', content_removed=True)
                row.pop('media', None)
                row.pop('reply', None)
            elif message.media_id and message.media_id.retention_state == 'content_removed':
                row.pop('media', None)
                row['media_removed'] = True
            if message.reply_to_message_id.retention_state == 'content_removed':
                row['reply'] = {'unavailable': True}
        return result

    @api.model
    def _v2_preserve_message(self, room_id, message_id, payload):
        self._require_bchat_permission('chat_view')
        self._require_bchat_permission('media')
        if (type(payload) is not dict or set(payload) != {'api_version', 'membership_id', 'preserved'}
                or type(payload['api_version']) is not int or payload['api_version'] != 2
                or type(payload['membership_id']) is not int or type(payload['preserved']) is not bool):
            raise ProtocolError('invalid_payload', 'Invalid preservation request.')
        room = self._v2_lock_room(room_id, mutate=True)
        self._retention_guard(room.company_id.id)
        member = self._v2_current_member(room)
        message = self.env['baseer.bchat.message'].sudo().browse(positive_id(message_id, 'message_id')).exists()
        if (member.id != payload['membership_id'] or not message or message.room_id != room
                or message.company_id != room.company_id or message.id <= member.joined_after_message_id):
            raise AccessError('This message is unavailable.')
        if message.retention_state != 'active':
            raise ProtocolError('message_removed', 'Removed content cannot be restored.', 410)
        if message.retention_preserved != payload['preserved']:
            self._retention_audit_preserve(message, payload['preserved'])
            self.env.cr.execute('UPDATE baseer_bchat_message SET retention_preserved=%s WHERE id=%s', [payload['preserved'], message.id])
            message.invalidate_recordset(['retention_preserved'])
            room._publish_room_change()
        canonical = self._v2_history_payload([message], False, self._v2_author_names([message]))['messages'][0]
        if canonical.get('media'):
            canonical['media']['size_label'] = size_label(canonical['media']['size'])
        return dict(api_version=2, room_id=room.id, company_id=room.company_id.id,
                    membership_id=member.id, content_revision=room.content_revision, message=canonical)

    @api.model
    def _v2_content_state(self, room_id, payload):
        self._require_bchat_permission('chat_view')
        self._require_bchat_permission('media')
        member_id, revision, ids, cursor = wire.reconcile_payload(payload)
        room = self._v2_lock_room(room_id)
        member = self._v2_current_member(room)
        if member.id != member_id:
            raise ProtocolError('membership_changed', 'The room membership period changed.', 409)
        if room.content_revision != revision:
            error = ProtocolError('content_changed', 'Refresh this room before reconciling content.', 409)
            error.content_revision = room.content_revision
            raise error
        scope = [self.env.uid, room.company_id.id, room.id, member.id, revision, wire.ids_digest(ids)]
        start = wire.cursor_index(cursor, scope, len(ids))
        # Match the gallery's exact sparse association query, including both
        # directions and both company/room fences. No history/receipt writes.
        self.env['baseer.bchat.media'].flush_model()
        self.env['baseer.bchat.message'].flush_model()
        self.env.cr.execute('''SELECT media.id FROM baseer_bchat_media media
            JOIN baseer_bchat_message message ON message.id=media.message_id AND message.media_id=media.id
            WHERE media.id=ANY(%s) AND media.room_id=%s AND media.company_id=%s
              AND message.room_id=%s AND message.company_id=%s AND message.id>%s
              AND media.state='attached' AND media.retention_state='active'
              AND message.retention_state='active' ORDER BY media.id LIMIT %s''',
            [ids[start:], room.id, room.company_id.id, room.id, room.company_id.id,
             member.joined_after_message_id, wire.MAX_IDS])
        media = self.env['baseer.bchat.media'].sudo().browse([row[0] for row in self.env.cr.fetchall()])
        live = {m.id: m for m in media}
        messages = list({m.message_id.id: m.message_id for m in live.values()}.values())
        names = self._v2_author_names(messages)
        canonical = {m['id']: m for m in self._v2_history_payload(messages, False, names)['messages']}
        result = dict(api_version=2, retention_version=1, room_id=room.id,
                      company_id=room.company_id.id, membership_id=member.id,
                      content_revision=revision, items=[], next_cursor=None)
        for index in range(start, len(ids)):
            mid = ids[index]
            item = {'media_id': mid, 'state': 'removed'}
            if mid in live:
                item.update(state='live', message=canonical[live[mid].message_id.id])
            result['items'].append(item)
            result['next_cursor'] = wire.cursor_for(scope, index + 1) if index + 1 < len(ids) else None
            if wire.encoded_size(result) > wire.MAX_BYTES:
                result['items'].pop()
                if not result['items']:
                    raise ProtocolError('payload_too_large', 'A content-state item is too large.', 413)
                result['next_cursor'] = wire.cursor_for(scope, index)
                break
        return result

    @api.model
    def _retention_foreign_reference(self, table, row_id, internal_tables, fresh=False):
        """Only a boolean ownership veto, never content/IDs from private ERP."""
        if self._retention_reference_exists(self.env.cr, table, row_id, internal_tables):
            return True
        if fresh:
            # Outer REPEATABLE READ sees our uncommitted refs/DDL; this second
            # READ COMMITTED read sees refs committed before source locks were
            # acquired but after that outer snapshot. Neither may be omitted.
            # A real connection intentionally bypasses registry TestCursor, NOT
            # any user/content authority. Fixed tables + exact id -> bool only.
            with sql_db.db_connect(self.env.cr.dbname).cursor() as probe:
                probe.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED READ ONLY')
                return self._retention_reference_exists(probe, table, row_id, internal_tables)
        return False

    def _retention_reference_exists(self, cursor, table, row_id, internal_tables):
        if table not in {'baseer_bchat_message', 'baseer_bchat_media', 'ir_attachment'} or type(row_id) is not int:
            raise AccessError('Invalid private retention reference probe.')
        cursor.execute('''SELECT c.conrelid::regclass::text, a.attname, cardinality(c.conkey), target.attname
            FROM pg_constraint c JOIN pg_attribute a ON a.attrelid=c.conrelid
              AND a.attnum=c.conkey[1]
            JOIN pg_attribute target ON target.attrelid=c.confrelid AND target.attnum=c.confkey[1]
            WHERE c.contype='f' AND c.confrelid=%s::regclass''', [table])
        for relation, column, columns, target in cursor.fetchall():
            if relation in internal_tables and (relation, column) in _INTERNAL_FKS[table] and columns == 1 and target == 'id':
                continue
            if columns != 1 or target != 'id':
                # Unknown composite ownership contracts are never deletion permission.
                return True
            cursor.execute(SQL('SELECT 1 FROM %s WHERE %s = %s LIMIT 1',
                                   SQL.identifier(*relation.split('.')), SQL.identifier(column), row_id))
            if cursor.fetchone():
                return True
        return False

    def _retention_lock_sources(self, message=None, media=None):
        # Prevent new FK DDL between schema discovery and scrubbing. Ordinary
        # DML is not table-blocked; exact source rows serialize FK inserts.
        self.env.cr.execute('LOCK TABLE baseer_bchat_message,baseer_bchat_media,ir_attachment IN ROW EXCLUSIVE MODE')
        if message:
            self.env.cr.execute('SELECT id FROM baseer_bchat_message WHERE id=%s FOR UPDATE', [message.id])
            message.invalidate_recordset()
            media = message.media_id
        if media:
            self.env.cr.execute('SELECT id FROM baseer_bchat_media WHERE id=%s FOR UPDATE', [media.id])
            media.invalidate_recordset()
            ids = (media.attachment_id | media.thumbnail_attachment_id).ids
            self.env.cr.execute('SELECT id FROM ir_attachment WHERE id=ANY(%s) ORDER BY id FOR UPDATE', [ids])
            self.env['ir.attachment'].sudo().browse(ids).invalidate_recordset()

    @api.model
    def _retention_inspect(self, message, token, lock=False):
        if token is not _RETENTION_TOKEN:
            raise AccessError('Verified retention capability required.')
        self._retention_guard(message.company_id.id)
        if lock:
            self._retention_lock_sources(message=message)
        if message.retention_preserved:
            return 'preserved', [], 0
        self.env.cr.execute('SELECT 1 FROM baseer_bchat_media WHERE message_id=%s AND id != %s LIMIT 1', [message.id, message.media_id.id or 0])
        if self.env.cr.fetchone():
            return 'shared_media', [], 0
        if self._retention_foreign_reference('baseer_bchat_message', message.id, {
                'baseer_bchat_message', 'baseer_bchat_message_receipt',
                'baseer_bchat_change', 'baseer_bchat_push_event', 'baseer_bchat_media',
                'baseer_bwork_retention_item'}, fresh=lock):
            return 'external_reference', [], 0
        media = message.media_id
        if not media or media.retention_state == 'content_removed':
            return 'eligible', [], 0
        if (media.state != 'attached' or media.message_id != message or media.room_id != message.room_id
                or media.company_id != message.company_id):
            return 'integrity_error', [], 0
        return self._retention_inspect_media(media, token, lock=lock)

    def _retention_inspect_media(self, media, token, lock=False):
        if token is not _RETENTION_TOKEN:
            raise AccessError('Verified retention capability required.')
        self._retention_guard(media.company_id.id)
        if lock:
            self._retention_lock_sources(media=media)
        self.env.cr.execute('SELECT 1 FROM baseer_bchat_message WHERE media_id=%s AND id!=%s LIMIT 1', [media.id, media.message_id.id or 0])
        if self.env.cr.fetchone() or self._retention_foreign_reference('baseer_bchat_media', media.id, {
                'baseer_bchat_message', 'baseer_bwork_retention_item', 'baseer_bchat_mobile_upload_grant'}, fresh=lock):
            return 'external_media_reference', [], 0
        if self.env['baseer.bchat.mobile.upload.grant'].sudo().search_count([
                ('user_id', '=', media.author_user_id.id), ('upload_uuid', '=', media.upload_uuid),
                ('state', 'in', ['issued', 'uploading'])], limit=1):
            return 'active_upload', [], 0
        if media.document_file_id or media.document_type != 'other':
            return 'protected_document', [], 0
        attachments = (media.attachment_id | media.thumbnail_attachment_id).sudo().exists()
        if not media.attachment_id or not attachments:
            return 'integrity_error', [], 0
        if lock:
            self.env.cr.execute('SELECT id FROM ir_attachment WHERE id=ANY(%s) ORDER BY id FOR UPDATE', [attachments.ids])
            attachments.invalidate_recordset()
        for attachment in attachments:
            if (attachment.res_model != 'baseer.bchat.media' or attachment.res_id != media.id
                    or attachment.company_id != media.company_id or attachment.type != 'binary'
                    or attachment.public or attachment.access_token or attachment.res_field
                    or ('baseer_invoice_source_held' in attachment._fields and attachment.baseer_invoice_source_held)):
                return 'protected_attachment', [], 0
            self.env.cr.execute('''SELECT 1 FROM baseer_bchat_media
                WHERE id != %s AND (attachment_id=%s OR thumbnail_attachment_id=%s) LIMIT 1''',
                                [media.id, attachment.id, attachment.id])
            if self.env.cr.fetchone() or self._retention_foreign_reference('ir_attachment', attachment.id, {'baseer_bchat_media'}, fresh=lock):
                return 'shared_attachment', [], 0
        return 'eligible', attachments.ids, sum(attachments.mapped('file_size'))

    def _retention_staged_fingerprint(self, media, token):
        if token is not _RETENTION_TOKEN:
            raise AccessError('Verified retention capability required.')
        value = [media.id, media.company_id.id, media.room_id.id, media.author_user_id.id,
                 media.membership_id.id, media.upload_uuid, media.sha256, media.state,
                 fields.Datetime.to_string(media.create_date),
                 media.message_id.id, media.attachment_id.id, media.thumbnail_attachment_id.id,
                 media.document_file_id, media.document_type,
                 self._retention_attachment_fingerprint(media, token)]
        return hashlib.sha256(json.dumps(value, separators=(',', ':')).encode()).hexdigest()

    def _retention_inspect_staged(self, media, token, lock=False):
        if token is not _RETENTION_TOKEN:
            raise AccessError('Verified retention capability required.')
        self._retention_guard(media.company_id.id)
        if (media.state != 'staged' or media.message_id or media.retention_state != 'active'
                or media.create_date > fields.Datetime.now() - timedelta(hours=24)
                or media.room_id.company_id != media.company_id
                or media.membership_id.room_id != media.room_id
                or media.membership_id.user_id != media.author_user_id
                or media.membership_id.company_id != media.company_id):
            return 'changed', [], 0
        # Any extant active upload capability is a veto, even if its timer
        # appears expired. Its owner/lease reconciler must close it first.
        grants = self.env['baseer.bchat.mobile.upload.grant'].sudo().search([
            ('user_id', '=', media.author_user_id.id), ('upload_uuid', '=', media.upload_uuid),
            ('state', 'in', ['issued', 'uploading']),
        ], limit=1)
        if grants or self._retention_foreign_reference('baseer_bchat_media', media.id,
                {'baseer_bchat_message', 'baseer_bwork_retention_item', 'baseer_bchat_mobile_upload_grant'}):
            return 'active_or_external_reference', [], 0
        self.env.cr.execute('SELECT 1 FROM baseer_bchat_message WHERE media_id=%s LIMIT 1', [media.id])
        if self.env.cr.fetchone():
            return 'shared_media', [], 0
        return self._retention_inspect_media(media, token, lock=lock)

    def _retention_expire_staged(self, media, fingerprint, token):
        if token is not _RETENTION_TOKEN:
            raise AccessError('Verified retention capability required.')
        self._retention_guard(media.company_id.id)
        self.env['baseer.bchat.room']._lock_for_mutation(media.room_id.id)
        media.invalidate_recordset()
        self._retention_lock_sources(media=media)
        if not self._retention_ready(lock=True):
            raise ProtocolError('retention_not_ready', 'Server retention is not activated.', 409)
        if fingerprint != self._retention_staged_fingerprint(media, token):
            return 'changed', 0
        reason, attachments, size = self._retention_inspect_staged(media, token, lock=True)
        if reason != 'eligible':
            return reason, 0
        self._v2_close_staged_media(media, 'expired')
        return 'removed', size

    @api.model
    def _retention_fingerprint(self, message, token):
        if token is not _RETENTION_TOKEN:
            raise AccessError('Verified retention capability required.')
        media = message.media_id
        value = [message.id, message.company_id.id, message.retention_state,
                 message.retention_preserved, message.payload_digest,
                 fields.Datetime.to_string(message.create_date),
                 media.id, media.retention_state if media else None,
                 media.attachment_id.id, media.thumbnail_attachment_id.id,
                 media.document_file_id, media.document_type,
                 self._retention_attachment_fingerprint(media, token)]
        return hashlib.sha256(json.dumps(value, separators=(',', ':')).encode()).hexdigest()

    def _retention_attachment_fingerprint(self, media, token):
        if token is not _RETENTION_TOKEN:
            raise AccessError('Verified retention capability required.')
        attachments = (media.attachment_id | media.thumbnail_attachment_id).sudo().exists()
        names = ['checksum', 'file_size', 'write_date', 'type', 'res_model', 'res_id',
                 'company_id', 'public', 'access_token', 'res_field']
        if 'baseer_invoice_source_held' in attachments._fields:
            names.append('baseer_invoice_source_held')
        attachments.flush_recordset(names)
        return [[row.id, row.checksum, row.file_size, fields.Datetime.to_string(row.write_date),
                 row.type, row.res_model, row.res_id, row.company_id.id, row.public,
                 bool(row.access_token), row.res_field,
                 bool(row.baseer_invoice_source_held) if 'baseer_invoice_source_held' in row._fields else False]
                for row in attachments.sorted('id')]

    @api.model
    def _retention_scrub(self, message, mode, fingerprint, token):
        if token is not _RETENTION_TOKEN or mode not in ('attachments', 'messages_and_attachments'):
            raise AccessError('Verified retention capability required.')
        self._retention_guard(message.company_id.id)
        if not self._retention_ready(lock=True):
            raise ProtocolError('retention_not_ready', 'Server retention is not activated.', 409)
        self.env['baseer.bchat.room']._lock_for_mutation(message.room_id.id)
        message.invalidate_recordset()
        self._retention_lock_sources(message=message)
        if fingerprint != self._retention_fingerprint(message, token):
            return 'changed', 0
        reason, attachment_ids, size = self._retention_inspect(message, token, lock=True)
        if reason != 'eligible':
            return reason, 0
        # Never wait on push while holding a room lock. An in-flight event owns
        # its row first; skipping that message avoids inversion and late previews.
        self.env.cr.execute("SELECT id FROM baseer_bchat_push_event WHERE message_id=%s AND state IN ('pending','retry','configuration')", [message.id])
        expected = {r[0] for r in self.env.cr.fetchall()}
        self.env.cr.execute("SELECT id FROM baseer_bchat_push_event WHERE message_id=%s AND state IN ('pending','retry','configuration') ORDER BY id FOR UPDATE SKIP LOCKED", [message.id])
        if {r[0] for r in self.env.cr.fetchall()} != expected:
            return 'push_busy', 0
        media = message.media_id
        if media and media.retention_state != 'content_removed':
            self.env.cr.execute("UPDATE baseer_bchat_media SET attachment_id=NULL,thumbnail_attachment_id=NULL,name='',retention_state='content_removed',content_removed_at=NOW() WHERE id=%s", [media.id])
            media.invalidate_recordset()
            self.env['ir.attachment'].sudo().browse(attachment_ids).unlink()
        if mode == 'messages_and_attachments':
            self.env.cr.execute("UPDATE baseer_bchat_message SET text=NULL,retention_state='content_removed',content_removed_at=NOW() WHERE id=%s", [message.id])
            message.invalidate_recordset()
        if expected:
            self.env.cr.execute("UPDATE baseer_bchat_push_event SET state='discarded',last_error='content_removed',next_attempt_at=NULL WHERE id=ANY(%s)", [sorted(expected)])
            self.env['baseer.bchat.push.event'].invalidate_model()
        return 'removed', size

    @api.model
    def _retention_publish_rooms(self, rooms, token):
        if token is not _RETENTION_TOKEN:
            raise AccessError('Verified retention capability required.')
        for room in rooms.sorted('id'):
            self._retention_guard(room.company_id.id)
            self.env.cr.execute('UPDATE baseer_bchat_room SET content_revision=content_revision+1 WHERE id=%s', [room.id])
            room.invalidate_recordset(['content_revision'])
            room._publish_room_change()
