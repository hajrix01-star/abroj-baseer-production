"""BChat media boundary: staged upload and membership-gated byte reads."""
import base64
import hashlib
import logging
import secrets
import uuid
from datetime import timedelta

from psycopg2.errors import UniqueViolation

from odoo import SUPERUSER_ID, api, fields, models
from odoo.exceptions import AccessError

from .. import media_contracts
from ..contracts import ProtocolError, canonical_uuid, positive_id
from .media import _MEDIA_TOKEN
from .mobile_upload_grant import _MOBILE_UPLOAD_GRANT_TOKEN, _UPLOAD_LEASE_SECONDS


_logger = logging.getLogger(__name__)


class BChatMediaService(models.AbstractModel):
    _inherit = 'baseer.bchat.service'

    @api.model
    def _v2_issue_mobile_upload_grant(self, room_id, metadata):
        """Create the short-lived capability used by Android's native HTTPS uploader."""
        normalized = self._v2_upload_scope(room_id, metadata)
        room = self._v2_lock_room(room_id)
        member = self._v2_current_member(room)
        if member.id != normalized['membership_id']:
            raise ProtocolError('membership_changed', 'The room membership period changed.', 409)
        grants = self.env['baseer.bchat.mobile.upload.grant'].sudo()
        secret = secrets.token_urlsafe(32)
        now = fields.Datetime.now()
        grant = grants._issue_verified({
            'grant_id': str(uuid.uuid4()),
            'secret_hash': hashlib.sha256(secret.encode('ascii')).hexdigest(),
            'user_id': self.env.uid, 'company_id': room.company_id.id, 'room_id': room.id,
            'membership_id': member.id, 'upload_uuid': normalized['upload_uuid'],
            'kind': normalized['kind'], 'mime': normalized['mime'], 'name': normalized['name'],
            'size_bytes': normalized['size'], 'sha256': normalized['sha256'],
            'state': 'issued', 'expires_at': now + timedelta(seconds=120),
        }, _MOBILE_UPLOAD_GRANT_TOKEN)
        return {
            'api_version': 2, 'grant_id': grant.grant_id, 'secret': secret,
            'expires_at': fields.Datetime.to_string(grant.expires_at),
        }

    @api.model
    def _v2_mobile_upload_from_capability(self, snapshot, raw):
        """Recheck all room rights at redemption, then reuse the verified v2 upload path."""
        if not isinstance(snapshot, dict):
            raise ProtocolError('invalid_capability', 'The upload capability is invalid.', 401)
        self.env['baseer.bchat.mobile.upload.grant']._ensure_claim_current(snapshot)
        room_id = positive_id(snapshot.get('room_id'), 'room_id')
        metadata = {
            'api_version': 2, 'membership_id': positive_id(snapshot.get('membership_id'), 'membership_id'),
            'upload_uuid': snapshot.get('upload_uuid'), 'kind': snapshot.get('kind'),
            'mime': snapshot.get('mime'), 'size': snapshot.get('size'),
            'sha256': snapshot.get('sha256'), 'name': snapshot.get('name'),
        }
        # _v2_upload calls _v2_upload_scope again: permissions, active user, company, room and
        # membership are deliberately re-evaluated after the byte stream has arrived.
        return self._v2_upload(room_id, metadata, raw)

    @api.model
    def _v2_reconcile_native_upload(self, room_id, upload_uuid):
        """Return only this member epoch's persisted media after a lost native response."""
        self._require_bchat_permission('chat_send')
        self._require_media_right('upload')
        room = self._v2_lock_room(room_id)
        member = self._v2_current_member(room)
        upload_uuid = canonical_uuid(upload_uuid)
        media = self.env['baseer.bchat.media'].sudo().search([
            ('room_id', '=', room.id), ('company_id', '=', room.company_id.id),
            ('membership_id', '=', member.id), ('author_user_id', '=', self.env.uid),
            ('upload_uuid', '=', upload_uuid), ('state', 'in', ('staged', 'attached')),
        ], limit=1)
        payload = {
            'api_version': 2, 'room_id': room.id, 'membership_id': member.id,
            'upload_uuid': upload_uuid, 'state': 'missing',
        }
        if media:
            payload.update({'media_id': media.id, 'state': media.state})
            return payload
        # A process restart can lose the Android response while its raw native body is still
        # arriving.  Report this scoped, short lease so the client keeps reconciling instead
        # of offering an early second POST for the same upload UUID.
        uploading = self.env['baseer.bchat.mobile.upload.grant'].sudo().search([
            ('user_id', '=', self.env.uid), ('company_id', '=', room.company_id.id),
            ('room_id', '=', room.id), ('membership_id', '=', member.id),
            ('upload_uuid', '=', upload_uuid), ('state', '=', 'uploading'),
            ('upload_started_at', '>=', fields.Datetime.now() - timedelta(seconds=_UPLOAD_LEASE_SECONDS)),
        ], limit=1)
        if uploading:
            payload['state'] = 'uploading'
        return payload

    @api.model
    def _v2_upload_scope(self, room_id, metadata):
        """Cheap preflight before decoding an uploaded file; commit path checks again."""
        self._require_bchat_permission('chat_send')
        self._require_media_right('upload')
        normalized = media_contracts.normalize_metadata(metadata)
        user = self._require_user()
        room = self.env['baseer.bchat.room'].sudo().browse(positive_id(room_id, 'room_id')).exists()
        if not room or room.company_id.id not in user.company_ids.ids:
            raise AccessError(self.env._('This room is unavailable.'))
        member = self.env['baseer.bchat.membership'].sudo().search([
            ('room_id', '=', room.id), ('user_id', '=', user.id), ('active', '=', True),
        ], limit=1)
        if not member or member.id != normalized['membership_id']:
            raise ProtocolError('membership_changed', 'The room membership period changed.', 409)
        return normalized

    @api.model
    def _v2_upload(self, room_id, metadata, raw):
        normalized = self._v2_upload_scope(room_id, metadata)
        thumbnail = media_contracts.validate_bytes(normalized, raw)
        with self.env.cr.savepoint():
            room = self._v2_lock_room(room_id, mutate=True)
            member = self._v2_current_member(room)
            if member.id != normalized['membership_id']:
                raise ProtocolError('membership_changed', 'The room membership period changed.', 409)
            media_model = self.env['baseer.bchat.media'].sudo()
            existing = media_model.search([
                ('author_user_id', '=', self.env.uid),
                ('upload_uuid', '=', normalized['upload_uuid']),
            ], limit=1)
            if existing:
                return self._v2_upload_replay(existing, room, member, normalized, raw)
            # Distinct uploads are bounded even if a client never sends them.
            # A row lock alone is insufficient under Odoo's REPEATABLE READ:
            # another room's transaction could keep an older quota snapshot.
            # A no-value-change UPDATE makes the second writer fail with 40001
            # (and retry its request with a fresh snapshot) before counting.
            self.env.cr.execute('''
                UPDATE res_users SET write_date = write_date
                WHERE id = %s RETURNING id
            ''', [self.env.uid])
            if not self.env.cr.fetchone():
                raise AccessError(self.env._('This account is unavailable.'))
            self.env.cr.execute('''
                SELECT COUNT(*), COALESCE(SUM(size_bytes), 0)
                FROM baseer_bchat_media
                WHERE author_user_id = %s AND state = 'staged'
            ''', [self.env.uid])
            staged_count, staged_bytes = self.env.cr.fetchone()
            if staged_count >= 20 or staged_bytes + normalized['size'] > 50 * 1024 * 1024:
                raise ProtocolError('media_quota', 'Pending media storage is full.', 429)
            values = {
                'room_id': room.id, 'company_id': room.company_id.id,
                'membership_id': member.id, 'author_user_id': self.env.uid,
                'upload_uuid': normalized['upload_uuid'],
                'kind': normalized['kind'], 'mime': normalized['mime'],
                'size_bytes': normalized['size'], 'sha256': normalized['sha256'],
                'name': normalized['name'], 'state': 'staged',
            }
            try:
                with self.env.cr.savepoint():
                    media = media_model._create_verified(values, _MEDIA_TOKEN)
            except UniqueViolation as error:
                if error.diag.constraint_name != 'baseer_bchat_media_user_upload_uuid_unique':
                    raise
                raise ProtocolError('idempotency_conflict', 'The upload UUID belongs to another file.', 409) from None
            # The uploader must not become an ir.attachment owner who can use
            # /web/content outside the BChat membership boundary.
            # BChat stores the uploaded original byte-for-byte. Odoo otherwise
            # resizes JPEG/PNG attachments above its image-autoresize threshold.
            attachment_model = self.env['ir.attachment'].with_user(SUPERUSER_ID).sudo().with_company(
                room.company_id).with_context(image_no_postprocess=True)
            attachment = attachment_model.create({
                'name': normalized['name'], 'type': 'binary',
                'res_model': 'baseer.bchat.media', 'res_id': media.id,
                'mimetype': normalized['mime'], 'public': False,
                'company_id': room.company_id.id,
                'datas': base64.b64encode(raw),
            })
            if base64.b64decode(attachment.datas or b'', validate=True) != raw:
                raise ProtocolError('media_storage_failed', 'The original upload was not preserved.', 503)
            updates = {'attachment_id': attachment.id}
            if thumbnail is not None:
                preview = attachment_model.create({
                    'name': 'bchat-thumbnail.jpg', 'type': 'binary',
                    'res_model': 'baseer.bchat.media', 'res_id': media.id,
                    'mimetype': 'image/jpeg', 'public': False,
                    'company_id': room.company_id.id,
                    'datas': base64.b64encode(thumbnail),
                })
                updates['thumbnail_attachment_id'] = preview.id
            media._write_verified(updates, _MEDIA_TOKEN)
            return {'api_version': 2, 'media_id': media.id,
                    'upload_uuid': normalized['upload_uuid'], 'state': 'staged'}

    @api.model
    def _v2_upload_replay(self, media, room, member, normalized, raw):
        if media.state == 'expired':
            raise ProtocolError('upload_expired', 'This upload UUID has expired.', 409)
        if media.state == 'cancelled':
            raise ProtocolError('upload_closed', 'This upload UUID is closed.', 409)
        if (media.room_id.id != room.id or media.company_id.id != room.company_id.id
                or media.membership_id.id != member.id
                or any(getattr(media, field) != normalized[name] for field, name in (
                    ('kind', 'kind'), ('mime', 'mime'), ('size_bytes', 'size'),
                    ('sha256', 'sha256'), ('name', 'name')))
                or not (media.attachment_id or (media.state == 'attached' and media.document_file_id))):
            raise ProtocolError('idempotency_conflict', 'The upload UUID belongs to another file.', 409)
        if media.state == 'staged':
            attachment = media.attachment_id.sudo()
            if (not attachment or attachment.res_model != 'baseer.bchat.media'
                    or attachment.res_id != media.id
                    or attachment.company_id.id != room.company_id.id
                    or attachment.public or attachment.access_token):
                raise AccessError(self.env._('This media is unavailable.'))
            stored = base64.b64decode(attachment.datas or b'', validate=True)
            if len(stored) != media.size_bytes or hashlib.sha256(stored).hexdigest() != media.sha256:
                # Recover only a caller-owned, still-unattached upload from the
                # identical original bytes supplied by its UUID replay.
                attachment.with_context(image_no_postprocess=True).write({
                    'datas': base64.b64encode(raw),
                })
                attachment.invalidate_recordset(['datas', 'file_size'])
                if base64.b64decode(attachment.datas or b'', validate=True) != raw:
                    raise ProtocolError('media_storage_failed', 'The original upload was not preserved.', 503)
        return {'api_version': 2, 'media_id': media.id,
                'upload_uuid': normalized['upload_uuid'], 'state': media.state}

    @api.model
    def _v2_cancel_upload(self, media_id):
        """Close only the caller's unbound upload; keep its UUID as a tombstone."""
        user = self._require_user()
        media_id = positive_id(media_id, 'media_id')
        media = self.env['baseer.bchat.media'].sudo().browse(media_id).exists()
        if not media or media.author_user_id.id != user.id:
            raise AccessError(self.env._('This media is unavailable.'))
        with self.env.cr.savepoint():
            self._v2_lock_room(media.room_id.id, mutate=True)
            media.invalidate_recordset()
            if media.author_user_id.id != user.id:
                raise AccessError(self.env._('This media is unavailable.'))
            if media.state == 'cancelled':
                return {'api_version': 2, 'media_id': media.id, 'state': 'cancelled'}
            if media.state != 'staged' or media.message_id:
                raise ProtocolError('upload_closed', 'This upload cannot be cancelled.', 409)
            self._v2_close_staged_media(media, 'cancelled')
            return {'api_version': 2, 'media_id': media.id, 'state': 'cancelled'}

    @api.model
    def _v2_close_staged_media(self, media, state):
        """Room mutation lock must be held before removing either private byte source."""
        if state not in ('cancelled', 'expired') or media.state != 'staged' or media.message_id:
            raise ProtocolError('upload_closed', 'This upload cannot be closed.', 409)
        attachments = (media.attachment_id | media.thumbnail_attachment_id).sudo()
        media._write_verified({
            'state': state, 'attachment_id': False, 'thumbnail_attachment_id': False,
        }, _MEDIA_TOKEN)
        if attachments:
            attachments.with_user(SUPERUSER_ID).unlink()

    @api.model
    def _v2_expire_staged_uploads(self, limit=100):
        """Expire at most one bounded batch of uploads older than 24 hours."""
        if self.env.uid != SUPERUSER_ID:
            raise AccessError(self.env._('A service account is required.'))
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ProtocolError('invalid_payload', 'Invalid cleanup limit.')
        cutoff = fields.Datetime.now() - timedelta(hours=24)
        stale = self.env['baseer.bchat.media'].sudo().search([
            ('state', '=', 'staged'), ('create_date', '<', cutoff),
        ], order='id', limit=limit + 1)
        closed = 0
        for candidate in stale[:limit]:
            with self.env.cr.savepoint():
                self.env['baseer.bchat.room']._lock_for_mutation(candidate.room_id.id)
                candidate.invalidate_recordset()
                if (candidate.state == 'staged' and not candidate.message_id
                        and candidate.create_date < cutoff):
                    self._v2_close_staged_media(candidate, 'expired')
                    closed += 1
        if len(stale) > limit:
            _logger.warning(
                'BChat staged-upload cleanup backlog exceeds batch: '
                'stale_candidates_at_least=%s batch_limit=%s expired_count=%s',
                len(stale), limit, closed,
            )
        return {'api_version': 2, 'expired_count': closed}

    @api.model
    def _v2_media_metadata(self, media):
        return {'id': media.id, 'kind': media.kind, 'mime': media.mime,
                'size': media.size_bytes, 'name': media.name, 'sha256': media.sha256,
                'document_type': media.document_type,
                'thumbnail_available': bool(media.thumbnail_attachment_id)}

    @api.model
    def _v2_media_original_bytes(self, media):
        """Read the legacy source; DMS bridge replaces this for finalized media."""
        attachment = media.attachment_id
        if not attachment or attachment.res_model != 'baseer.bchat.media' or attachment.res_id != media.id:
            raise AccessError(self.env._('This media is unavailable.'))
        return base64.b64decode(attachment.sudo().datas or b'', validate=True)

    @api.model
    def _v2_media_content(self, media_id, thumbnail=False):
        self._require_bchat_permission('chat_view')
        self._require_media_right('view' if thumbnail else 'download')
        media_id = positive_id(media_id, 'media_id')
        media = self.env['baseer.bchat.media'].sudo().browse(media_id).exists()
        if not media or media.state != 'attached' or not media.message_id:
            raise AccessError(self.env._('This media is unavailable.'))
        room = self._v2_lock_room(media.room_id.id)
        member = self._v2_current_member(room)
        if (room.company_id.id != media.company_id.id
                or media.message_id.room_id.id != room.id
                or media.message_id.company_id.id != room.company_id.id
                or media.message_id.media_id.id != media.id
                or media.message_id.id <= member.joined_after_message_id):
            raise AccessError(self.env._('This media is unavailable.'))
        if thumbnail and media.kind != 'image':
            raise AccessError(self.env._('This media is unavailable.'))
        if thumbnail:
            attachment = media.thumbnail_attachment_id
            if not attachment or attachment.res_model != 'baseer.bchat.media' or attachment.res_id != media.id:
                raise AccessError(self.env._('This media is unavailable.'))
            raw = base64.b64decode(attachment.sudo().datas or b'', validate=True)
        else:
            raw = self._v2_media_original_bytes(media)
        limit = 128 * 1024 if thumbnail else media_contracts.size_limit(media.kind, media.mime)
        if not raw or len(raw) > limit or (not thumbnail and len(raw) != media.size_bytes):
            raise AccessError(self.env._('This media is unavailable.'))
        return raw, ('image/jpeg' if thumbnail else media.mime), media.name
