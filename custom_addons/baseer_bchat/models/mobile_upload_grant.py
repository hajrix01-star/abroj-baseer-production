"""One-purpose, short-lived capabilities for native BChat media uploads."""
import hashlib
import hmac
import re
from datetime import timedelta

from odoo import SUPERUSER_ID, api, fields, models
from odoo.exceptions import AccessError

from ..contracts import ProtocolError, canonical_uuid, positive_id


_MOBILE_UPLOAD_GRANT_TOKEN = object()
_GRANT_ID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')
_SECRET_RE = re.compile(r'^[A-Za-z0-9_-]{43,128}$')
_UPLOAD_LEASE_SECONDS = 90
_TOMBSTONE_RETENTION_HOURS = 24
_MAX_ACTIVE_GRANTS_PER_USER = 1


class BChatMobileUploadGrant(models.Model):
    _name = 'baseer.bchat.mobile.upload.grant'
    _description = 'BChat native media upload capability'
    _check_company_auto = True
    _order = 'id desc'

    grant_id = fields.Char(required=True, readonly=True, size=36, index=True)
    secret_hash = fields.Char(required=True, readonly=True, size=64)
    user_id = fields.Many2one('res.users', required=True, readonly=True, ondelete='restrict', index=True)
    company_id = fields.Many2one('res.company', required=True, readonly=True, ondelete='restrict', index=True)
    room_id = fields.Many2one('baseer.bchat.room', required=True, readonly=True, ondelete='restrict', index=True)
    membership_id = fields.Many2one('baseer.bchat.membership', required=True, readonly=True,
                                    ondelete='restrict', index=True)
    upload_uuid = fields.Char(required=True, readonly=True, size=36)
    kind = fields.Selection([('image', 'Image'), ('file', 'File'), ('audio', 'Audio')],
                            required=True, readonly=True)
    mime = fields.Char(required=True, readonly=True, size=127)
    name = fields.Char(required=True, readonly=True, size=160)
    size_bytes = fields.Integer(required=True, readonly=True)
    sha256 = fields.Char(required=True, readonly=True, size=64)
    state = fields.Selection([
        ('issued', 'Issued'), ('uploading', 'Uploading'), ('resolved', 'Resolved'),
        ('expired', 'Expired'), ('denied', 'Denied'),
    ], required=True, readonly=True, default='issued', index=True)
    media_id = fields.Many2one('baseer.bchat.media', readonly=True, ondelete='restrict', index=True)
    failure_code = fields.Char(readonly=True, size=64)
    expires_at = fields.Datetime(required=True, readonly=True, index=True)
    upload_started_at = fields.Datetime(readonly=True, index=True)
    result_expires_at = fields.Datetime(readonly=True, index=True)

    _grant_id_unique = models.Constraint(
        'UNIQUE(grant_id)', 'A native media capability identifier must be unique.',
    )
    _secret_hash_format = models.Constraint(
        "CHECK(secret_hash ~ '^[0-9a-f]{64}$')", 'A capability secret digest is required.',
    )

    def init(self):
        self.env.cr.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS baseer_bchat_mobile_upload_grant_active_uniq
            ON baseer_bchat_mobile_upload_grant (user_id, upload_uuid)
            WHERE state IN ('issued', 'uploading')
        ''')
        self.env.cr.execute('''
            CREATE INDEX IF NOT EXISTS baseer_bchat_mobile_upload_grant_cleanup_idx
            ON baseer_bchat_mobile_upload_grant (state, expires_at, result_expires_at, id)
        ''')
        self.env.cr.execute('''
            CREATE INDEX IF NOT EXISTS baseer_bchat_mobile_upload_grant_purge_idx
            ON baseer_bchat_mobile_upload_grant (write_date, id) WHERE state = 'expired'
        ''')

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError(self.env._('Direct BChat upload capability creation is unavailable.'))

    @api.model
    def _create_verified(self, vals, token):
        if token is not _MOBILE_UPLOAD_GRANT_TOKEN:
            raise AccessError(self.env._('A verified BChat service operation is required.'))
        return super(BChatMobileUploadGrant, self.sudo()).create(vals)

    @api.model
    def _issue_verified(self, vals, token):
        """Issue one scoped capability without racing an upload already in flight.

        The advisory lock is per user rather than just per UUID: it bounds a compromised
        session to the same single active native body that the Android UI can produce.
        It is held only during issuance, never during a file stream.
        """
        if token is not _MOBILE_UPLOAD_GRANT_TOKEN:
            raise AccessError(self.env._('A verified BChat service operation is required.'))
        user_id = positive_id(vals.get('user_id'), 'user_id')
        upload_uuid = canonical_uuid(vals.get('upload_uuid'))
        now = fields.Datetime.now()
        self.env.cr.execute('SELECT pg_advisory_xact_lock(%s)', [user_id])
        self.env.cr.execute('''
            SELECT id FROM baseer_bchat_mobile_upload_grant
            WHERE user_id = %s AND state IN ('issued', 'uploading')
            ORDER BY id FOR UPDATE
        ''', [user_id])
        active = self.sudo().browse([row[0] for row in self.env.cr.fetchall()]).exists()
        for grant in active:
            if grant.state == 'issued' and grant.expires_at < now:
                grant._write_verified({'state': 'expired'}, _MOBILE_UPLOAD_GRANT_TOKEN)
            elif (grant.state == 'uploading' and grant.upload_started_at
                  and grant.upload_started_at < now - timedelta(seconds=_UPLOAD_LEASE_SECONDS)):
                grant._write_verified({'state': 'expired', 'failure_code': 'upload_timeout'},
                                      _MOBILE_UPLOAD_GRANT_TOKEN)
        # PostgreSQL checks the partial unique index when a replacement is inserted.
        # Flush under the advisory lock so an ORM-deferred expiry cannot look like a
        # duplicate active grant for the same logical upload.
        self.flush_model(['state', 'failure_code'])
        active.invalidate_recordset(['state', 'upload_started_at', 'expires_at'])
        active = active.filtered(lambda grant: grant.state in ('issued', 'uploading'))
        same_upload = active.filtered(lambda grant: grant.upload_uuid == upload_uuid)
        if same_upload:
            grant = same_upload[0]
            if grant.state == 'uploading':
                raise ProtocolError('upload_in_progress', 'This media upload is already in progress.', 409)
            grant._write_verified({'state': 'expired'}, _MOBILE_UPLOAD_GRANT_TOKEN)
            self.flush_model(['state'])
            active -= grant
        if len(active) >= _MAX_ACTIVE_GRANTS_PER_USER:
            raise ProtocolError('upload_in_progress', 'Another media upload is already in progress.', 429)
        return self._create_verified(vals, _MOBILE_UPLOAD_GRANT_TOKEN)

    def _write_verified(self, vals, token):
        allowed = {'state', 'media_id', 'failure_code', 'upload_started_at', 'result_expires_at'}
        if token is not _MOBILE_UPLOAD_GRANT_TOKEN or set(vals) - allowed:
            raise AccessError(self.env._('A verified BChat service operation is required.'))
        return super(BChatMobileUploadGrant, self.sudo()).write(vals)

    def write(self, vals):
        raise AccessError(self.env._('BChat upload capabilities are immutable outside their service.'))

    def unlink(self):
        raise AccessError(self.env._('BChat upload capabilities cannot be deleted directly.'))

    def _purge_verified(self, token):
        if token is not _MOBILE_UPLOAD_GRANT_TOKEN or any(grant.state != 'expired' for grant in self):
            raise AccessError(self.env._('A verified BChat cleanup operation is required.'))
        return super(BChatMobileUploadGrant, self.sudo()).unlink()

    def copy_data(self, default=None):
        raise AccessError(self.env._('BChat upload capabilities cannot be copied.'))

    @staticmethod
    def _secret_hash(secret):
        if not isinstance(secret, str) or not _SECRET_RE.fullmatch(secret):
            raise ProtocolError('invalid_capability', 'The upload capability is invalid.', 401)
        return hashlib.sha256(secret.encode('ascii')).hexdigest()

    @classmethod
    def _check_grant_id(cls, grant_id):
        if not isinstance(grant_id, str) or not _GRANT_ID_RE.fullmatch(grant_id):
            raise ProtocolError('invalid_capability', 'The upload capability is invalid.', 401)
        return grant_id

    def _matches_capability(self, grant_id, secret):
        grant_id = self._check_grant_id(grant_id)
        expected = self._secret_hash(secret)
        if self.grant_id != grant_id or not hmac.compare_digest(self.secret_hash, expected):
            raise ProtocolError('invalid_capability', 'The upload capability is invalid.', 401)

    def _snapshot(self):
        self.ensure_one()
        return {
            'id': self.id, 'grant_id': self.grant_id, 'user_id': self.user_id.id,
            'company_id': self.company_id.id, 'room_id': self.room_id.id,
            'membership_id': self.membership_id.id, 'upload_uuid': self.upload_uuid,
            'kind': self.kind, 'mime': self.mime, 'name': self.name,
            'size': self.size_bytes, 'sha256': self.sha256, 'state': self.state,
            'media_id': self.media_id.id, 'failure_code': self.failure_code or '',
            'expires_at': self.expires_at, 'upload_started_at': self.upload_started_at,
            'result_expires_at': self.result_expires_at,
        }

    @api.model
    def _claim_capability(self, grant_id, secret):
        """Atomically claim a capability in an isolated, committed transaction.

        The short row lock is released before the request reads the file body.  A normal Odoo
        request transaction would otherwise retain the lock while 10 MiB streams from Android.
        """
        grant_id = self._check_grant_id(grant_id)
        expected = self._secret_hash(secret)
        with self.env.registry.cursor() as cursor:
            env = api.Environment(cursor, SUPERUSER_ID, {})
            cursor.execute('''
                SELECT id FROM baseer_bchat_mobile_upload_grant
                WHERE grant_id = %s FOR UPDATE
            ''', [grant_id])
            row = cursor.fetchone()
            if not row:
                raise ProtocolError('invalid_capability', 'The upload capability is invalid.', 401)
            grant = env['baseer.bchat.mobile.upload.grant'].sudo().browse(row[0]).exists()
            if not grant or not hmac.compare_digest(grant.secret_hash, expected):
                raise ProtocolError('invalid_capability', 'The upload capability is invalid.', 401)
            now = fields.Datetime.now()
            if grant.state == 'resolved' and grant.result_expires_at and grant.result_expires_at >= now:
                result = grant._snapshot()
                result['claimed'] = False
                cursor.commit()
                return result
            if grant.state == 'uploading':
                result = grant._snapshot()
                result['claimed'] = False
                cursor.commit()
                return result
            if grant.state != 'issued' or grant.expires_at < now:
                if grant.state == 'issued':
                    grant._write_verified({'state': 'expired'}, _MOBILE_UPLOAD_GRANT_TOKEN)
                cursor.commit()
                raise ProtocolError('grant_expired', 'The upload capability expired.', 410)
            grant._write_verified({
                'state': 'uploading', 'upload_started_at': now,
            }, _MOBILE_UPLOAD_GRANT_TOKEN)
            result = grant._snapshot()
            result['claimed'] = True
            cursor.commit()
            return result

    @api.model
    def _status_capability(self, grant_id, secret):
        grant_id = self._check_grant_id(grant_id)
        expected = self._secret_hash(secret)
        grant = self.sudo().search([('grant_id', '=', grant_id)], limit=1)
        if not grant or not hmac.compare_digest(grant.secret_hash, expected):
            raise ProtocolError('invalid_capability', 'The upload capability is invalid.', 401)
        now = fields.Datetime.now()
        if grant.state == 'resolved' and grant.result_expires_at and grant.result_expires_at >= now:
            return grant._snapshot()
        if grant.state == 'issued' and grant.expires_at < now:
            grant._write_verified({'state': 'expired'}, _MOBILE_UPLOAD_GRANT_TOKEN)
            raise ProtocolError('grant_expired', 'The upload capability is no longer usable.', 410)
        elif (grant.state == 'uploading' and grant.upload_started_at
              and grant.upload_started_at < now - timedelta(seconds=_UPLOAD_LEASE_SECONDS)):
            grant._write_verified({'state': 'expired', 'failure_code': 'upload_timeout'},
                                  _MOBILE_UPLOAD_GRANT_TOKEN)
            raise ProtocolError('grant_expired', 'The upload capability is no longer usable.', 410)
        elif grant.state == 'resolved':
            grant._write_verified({'state': 'expired'}, _MOBILE_UPLOAD_GRANT_TOKEN)
            raise ProtocolError('grant_expired', 'The upload capability is no longer usable.', 410)
        if grant.state in ('expired', 'denied'):
            raise ProtocolError('grant_%s' % grant.state,
                                'The upload capability is no longer usable.', 410)
        return grant._snapshot()

    @api.model
    def _ensure_claim_current(self, snapshot):
        """Fence a body that outlived its short server-side upload lease before persisting it."""
        if not isinstance(snapshot, dict):
            raise ProtocolError('invalid_capability', 'The upload capability is invalid.', 401)
        grant_id = positive_id(snapshot.get('id'), 'grant_id')
        self.env.cr.execute('SELECT id FROM baseer_bchat_mobile_upload_grant WHERE id = %s FOR UPDATE',
                            [grant_id])
        grant = self.sudo().browse(grant_id).exists()
        if (not grant or grant.grant_id != snapshot.get('grant_id')
                or grant.state != 'uploading'):
            raise ProtocolError('grant_expired', 'The upload capability is no longer usable.', 410)
        now = fields.Datetime.now()
        if (not grant.upload_started_at
                or grant.upload_started_at < now - timedelta(seconds=_UPLOAD_LEASE_SECONDS)):
            grant._write_verified({'state': 'expired', 'failure_code': 'upload_timeout'},
                                  _MOBILE_UPLOAD_GRANT_TOKEN)
            raise ProtocolError('grant_expired', 'The upload capability is no longer usable.', 410)
        return grant._snapshot()

    @api.model
    def _resolve_claimed_capability(self, snapshot, media_id):
        if not isinstance(snapshot, dict) or not isinstance(media_id, int) or media_id <= 0:
            raise ProtocolError('invalid_capability', 'The upload capability is invalid.', 401)
        grant = self.sudo().browse(positive_id(snapshot.get('id'), 'grant_id')).exists()
        if not grant or grant.grant_id != snapshot.get('grant_id') or grant.state != 'uploading':
            raise ProtocolError('grant_expired', 'The upload capability is no longer usable.', 410)
        now = fields.Datetime.now()
        grant._write_verified({
            'state': 'resolved', 'media_id': media_id,
            'result_expires_at': now + timedelta(minutes=15),
        }, _MOBILE_UPLOAD_GRANT_TOKEN)
        return grant._snapshot()

    @api.model
    def _release_claimed_capability(self, snapshot):
        """Release an unpersisted body attempt before Odoo retries its transaction."""
        if not isinstance(snapshot, dict):
            return False
        try:
            grant_id = positive_id(snapshot.get('id'), 'grant_id')
        except ProtocolError:
            return False
        started_at = snapshot.get('upload_started_at')
        if not started_at:
            return False
        with self.env.registry.cursor() as cursor:
            env = api.Environment(cursor, SUPERUSER_ID, {})
            cursor.execute('''
                SELECT id FROM baseer_bchat_mobile_upload_grant WHERE id = %s FOR UPDATE
            ''', [grant_id])
            row = cursor.fetchone()
            grant = row and env['baseer.bchat.mobile.upload.grant'].sudo().browse(row[0]).exists()
            released = bool(
                grant and grant.grant_id == snapshot.get('grant_id')
                and grant.state == 'uploading' and grant.upload_started_at == started_at
            )
            if released:
                grant._write_verified({
                    'state': 'issued', 'upload_started_at': False,
                }, _MOBILE_UPLOAD_GRANT_TOKEN)
            cursor.commit()
            return released

    @api.model
    def _deny_claimed_capability(self, snapshot, code):
        if not isinstance(snapshot, dict) or not isinstance(code, str) or not re.fullmatch(r'[a-z_]{1,64}', code):
            return
        grant = self.sudo().browse(positive_id(snapshot.get('id'), 'grant_id')).exists()
        if grant and grant.grant_id == snapshot.get('grant_id') and grant.state == 'uploading':
            grant._write_verified({
                'state': 'denied', 'failure_code': code,
                'result_expires_at': fields.Datetime.now() + timedelta(minutes=15),
            }, _MOBILE_UPLOAD_GRANT_TOKEN)

    @api.model
    def _cron_expire_mobile_upload_grants(self, limit=100):
        if self.env.uid != SUPERUSER_ID:
            raise AccessError(self.env._('A service account is required.'))
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ProtocolError('invalid_payload', 'Invalid cleanup limit.')
        now = fields.Datetime.now()
        stale = self.sudo().search([
            '|', '|', '|',
            '&', ('state', '=', 'issued'), ('expires_at', '<', now),
            '&', ('state', '=', 'uploading'),
                 ('upload_started_at', '<', now - timedelta(seconds=_UPLOAD_LEASE_SECONDS)),
            '&', ('state', '=', 'resolved'), ('result_expires_at', '<', now),
            '&', ('state', '=', 'denied'), ('result_expires_at', '<', now),
        ], order='id', limit=limit)
        for grant in stale:
            values = {'state': 'expired'}
            if grant.state == 'uploading': values['failure_code'] = 'upload_timeout'
            grant._write_verified(values, _MOBILE_UPLOAD_GRANT_TOKEN)
        purge = self.sudo().search([
            ('state', '=', 'expired'),
            ('write_date', '<', now - timedelta(hours=_TOMBSTONE_RETENTION_HOURS)),
        ], order='write_date, id', limit=limit)
        purge._purge_verified(_MOBILE_UPLOAD_GRANT_TOKEN)
        return {'api_version': 2, 'expired_count': len(stale), 'purged_count': len(purge)}
