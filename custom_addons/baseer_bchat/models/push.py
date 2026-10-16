"""Private, durable BChat FCM delivery.

The database records who may be woken, while Firebase remains only a best-effort
transport.  Payloads may include an opted-in, sanitised, bounded preview for the
system notification; Android still fetches the referenced event through its
authenticated session before opening anything.
"""
import base64
from concurrent.futures import ThreadPoolExecutor
import json
import logging
import os
import re
import threading
import time
import unicodedata
from datetime import timedelta
from uuid import UUID, uuid4

from odoo import SUPERUSER_ID, api, fields, models
from odoo.exceptions import AccessError
from odoo.modules.registry import Registry

from ..contracts import ProtocolError, positive_id


_PUSH_TOKEN = object()
_LOGGER = logging.getLogger(__name__)
_OAUTH_LOCK = threading.Lock()
_OAUTH_CACHE = {'key': None, 'token': None, 'expires_at': 0}
_FCM_SCOPE = 'https://www.googleapis.com/auth/firebase.messaging'
_FCM_TOKEN_URI = 'https://oauth2.googleapis.com/token'
_FAST_DISPATCH_WORKERS = 8
# This bounds queued *lanes*, not individual device events. A large room is
# divided over at most eight lanes so its tail is not silently left for cron.
_FAST_DISPATCH_CAPACITY = 128
_FAST_DISPATCH_EXECUTOR = ThreadPoolExecutor(
    max_workers=_FAST_DISPATCH_WORKERS, thread_name_prefix='bchat-push')
_FAST_DISPATCH_SLOTS = threading.BoundedSemaphore(_FAST_DISPATCH_CAPACITY)


def _uuid4(value, name):
    try:
        parsed = UUID(value)
    except (TypeError, ValueError, AttributeError):
        raise ProtocolError('invalid_payload', 'Invalid %s.' % name) from None
    if parsed.version != 4 or str(parsed) != value:
        raise ProtocolError('invalid_payload', 'Invalid %s.' % name)
    return value


def _fcm_token(value):
    if not isinstance(value, str) or not 32 <= len(value) <= 4096:
        raise ProtocolError('invalid_payload', 'Invalid FCM token.')
    if any(ord(char) < 33 or ord(char) > 126 for char in value):
        raise ProtocolError('invalid_payload', 'Invalid FCM token.')
    return value


def _notification_text(value, limit):
    """Return a small, non-formatting preview suitable for an opted-in FCM payload."""
    if not isinstance(value, str):
        return ''
    value = re.sub(r'<[^>\r\n]{0,256}>', '', value)
    cleaned = []
    for char in value:
        if unicodedata.category(char).startswith('C'):
            cleaned.append(' ' if char in '\r\n\t' else '')
        else:
            cleaned.append(char)
    return ' '.join(''.join(cleaned).split())[:limit]


class _PushTransportError(Exception):
    def __init__(self, code, retry=True, invalid_token=False):
        self.code = code
        self.retry = retry
        self.invalid_token = invalid_token
        super().__init__(code)


def _fast_dispatch_event(dbname, event_id):
    """Best-effort post-commit lane; the durable cron owns recovery.

    The callback intentionally creates its own cursor and environment.  A
    request cursor must never escape its transaction or be shared with a
    background thread.
    """
    try:
        registry = Registry(dbname)
        with registry.cursor() as cursor:
            env = api.Environment(cursor, SUPERUSER_ID, {})
            env['baseer.bchat.push.event']._dispatch_event_ids([event_id])
            # Firebase may have accepted the payload. Persist its resulting
            # event state before releasing this independent cursor, otherwise
            # cron can retry an already-delivered notification.
            cursor.commit()
    except Exception:
        _LOGGER.warning('BChat fast push dispatch failed for event %s', event_id,
                        exc_info=False)


def _fast_dispatch_events(dbname, event_ids):
    """Drain one fair fast-lane shard, persisting each durable event."""
    for event_id in event_ids:
        _fast_dispatch_event(dbname, event_id)


class BChatPushDevice(models.Model):
    _name = 'baseer.bchat.push.device'
    _description = 'BChat private push installation'
    _order = 'last_seen_at desc, id desc'

    user_id = fields.Many2one('res.users', required=True, readonly=True, ondelete='cascade', index=True)
    installation_id = fields.Char(required=True, readonly=True, size=36, index=True)
    account_key = fields.Char(required=True, readonly=True, size=36, index=True)
    fcm_token = fields.Char(required=True, readonly=True, size=4096, index=True)
    active = fields.Boolean(required=True, readonly=True, default=True, index=True)
    last_seen_at = fields.Datetime(required=True, readonly=True, default=fields.Datetime.now, index=True)
    inactive_reason = fields.Selection([
        ('logout', 'Logout'), ('provider_invalid', 'Provider token invalid'),
        ('replaced', 'Replaced by another account'),
    ], readonly=True, index=True)
    inactive_at = fields.Datetime(readonly=True, index=True)

    _user_installation_unique = models.Constraint(
        'UNIQUE(user_id, installation_id)', 'One BChat push registration exists per user installation.',
    )
    _account_key_unique = models.Constraint('UNIQUE(account_key)', 'A BChat account key must be unique.')
    _fcm_token_unique = models.Constraint('UNIQUE(fcm_token)', 'An FCM token belongs to one BChat user.')

    def init(self):
        self.env.cr.execute('''
            CREATE INDEX IF NOT EXISTS baseer_bchat_push_device_user_active_idx
            ON baseer_bchat_push_device (user_id, active, last_seen_at DESC)
        ''')

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError(self.env._('Direct BChat push registration is unavailable.'))

    def write(self, vals):
        raise AccessError(self.env._('Direct BChat push registration is unavailable.'))

    def unlink(self):
        raise AccessError(self.env._('Direct BChat push registration is unavailable.'))

    @api.model
    def _register_verified(self, user, installation_id, fcm_token, token):
        if token is not _PUSH_TOKEN:
            raise AccessError(self.env._('A verified BChat push registration is required.'))
        # A prior logout deliberately makes the device inactive.  Odoo's
        # implicit ``active_test`` filter would then hide that same row here,
        # making a subsequent sign-in try to INSERT an already-owned
        # (user, installation_id) pair.  Registration is an upsert, so it
        # must include inactive history and reactivate the existing row.
        devices = self.sudo().with_context(active_test=False)
        existing = devices.search([
            ('user_id', '=', user.id), ('installation_id', '=', installation_id),
        ], limit=1)
        token_owner = devices.search([('fcm_token', '=', fcm_token)], limit=1)
        if token_owner and token_owner.id != existing.id:
            # A physical app installation must never keep receiving its former
            # user's notifications after another user signs in on the device.
            # Keep the deactivation audit without retaining a deliverable token.
            super(BChatPushDevice, token_owner).write({
                'fcm_token': 'revoked:' + str(uuid4()), 'active': False,
                'last_seen_at': fields.Datetime.now(), 'inactive_reason': 'replaced',
                'inactive_at': fields.Datetime.now(),
            })
        now = fields.Datetime.now()
        if existing:
            super(BChatPushDevice, existing).write({
                'fcm_token': fcm_token, 'active': True, 'last_seen_at': now,
                'inactive_reason': False, 'inactive_at': False,
            })
            return existing
        # Keep the number of active destinations bounded without retaining a
        # hidden sixth device indefinitely.  Old events have device_id SET NULL.
        active = devices.search([('user_id', '=', user.id), ('active', '=', True)],
                                order='last_seen_at asc, id asc')
        if len(active) >= 5:
            super(BChatPushDevice, active[:len(active) - 4]).unlink()
        return super(BChatPushDevice, devices).create({
            'user_id': user.id, 'installation_id': installation_id,
            'account_key': str(uuid4()), 'fcm_token': fcm_token,
            'active': True, 'last_seen_at': now,
        })

    def _unregister_verified(self, user, installation_id, token):
        if token is not _PUSH_TOKEN:
            raise AccessError(self.env._('A verified BChat push registration is required.'))
        rows = self.sudo().with_context(active_test=False).search([
            ('user_id', '=', user.id), ('installation_id', '=', installation_id),
        ])
        if rows:
            now = fields.Datetime.now()
            super(BChatPushDevice, rows).write({'active': False, 'last_seen_at': now,
                                                 'inactive_reason': 'logout', 'inactive_at': now})

    def copy_data(self, default=None):
        raise AccessError(self.env._('BChat push registrations cannot be copied.'))


class BChatPushEvent(models.Model):
    _name = 'baseer.bchat.push.event'
    _description = 'BChat private push event'
    _order = 'id desc'

    recipient_id = fields.Many2one('res.users', required=True, readonly=True, ondelete='cascade', index=True)
    device_id = fields.Many2one('baseer.bchat.push.device', readonly=True,
                                ondelete='set null', index=True)
    task_id = fields.Many2one('baseer.bchat.task', readonly=True, ondelete='restrict', index=True)
    message_id = fields.Many2one('baseer.bchat.message', readonly=True, ondelete='restrict', index=True)
    company_id = fields.Many2one('res.company', required=True, readonly=True, ondelete='restrict', index=True)
    event_kind = fields.Selection([
        ('assigned', 'Assigned'), ('updated', 'Updated'), ('message', 'Message'),
    ], required=True, readonly=True)
    task_revision = fields.Integer(readonly=True)
    state = fields.Selection([
        ('pending', 'Pending'), ('retry', 'Retry'), ('configuration', 'Configuration'),
        ('sent', 'Sent'), ('discarded', 'Discarded'), ('failed', 'Failed'),
    ], required=True, readonly=True, default='pending', index=True)
    attempts = fields.Integer(required=True, readonly=True, default=0)
    next_attempt_at = fields.Datetime(readonly=True, index=True)
    last_error = fields.Char(readonly=True, size=64)
    sent_at = fields.Datetime(readonly=True)

    _task_device_revision_unique = models.Constraint(
        'UNIQUE(task_id, device_id, event_kind, task_revision)',
        'One BChat push event exists for each task revision and device.',
    )
    _event_source_shape = models.Constraint(
        """CHECK (
            (task_id IS NOT NULL AND message_id IS NULL
             AND task_revision IS NOT NULL AND event_kind IN ('assigned', 'updated'))
            OR
            (task_id IS NULL AND message_id IS NOT NULL
             AND task_revision IS NULL AND event_kind = 'message')
        )""",
        'A BChat push event must have one valid source.',
    )

    def init(self):
        # Existing task-only databases must accept the new message event shape.
        self.env.cr.execute('''
            ALTER TABLE baseer_bchat_push_event
            ALTER COLUMN task_id DROP NOT NULL,
            ALTER COLUMN task_revision DROP NOT NULL
        ''')
        self.env.cr.execute('''
            CREATE INDEX IF NOT EXISTS baseer_bchat_push_event_dispatch_idx
            ON baseer_bchat_push_event (state, next_attempt_at, id)
        ''')
        self.env.cr.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS baseer_bchat_push_event_message_device_unique
            ON baseer_bchat_push_event (message_id, device_id)
            WHERE message_id IS NOT NULL
        ''')

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError(self.env._('Direct BChat push event creation is unavailable.'))

    def write(self, vals):
        raise AccessError(self.env._('Direct BChat push event updates are unavailable.'))

    def unlink(self):
        raise AccessError(self.env._('BChat push events cannot be deleted.'))

    @api.model
    def _queue_verified(self, vals_list, token):
        if token is not _PUSH_TOKEN:
            raise AccessError(self.env._('A verified BChat push event is required.'))
        if not vals_list:
            return self.browse()
        return super(BChatPushEvent, self.sudo()).create(vals_list)

    def _write_verified(self, vals, token):
        if token is not _PUSH_TOKEN:
            raise AccessError(self.env._('A verified BChat push event is required.'))
        return super(BChatPushEvent, self.sudo()).write(vals)

    @api.model
    def _fcm_config(self):
        raw = os.getenv('BCHAT_FCM_SERVICE_ACCOUNT_JSON')
        path = os.getenv('BCHAT_FCM_SERVICE_ACCOUNT_FILE')
        if bool(raw) == bool(path):
            return None
        try:
            if path:
                with open(path, 'r', encoding='utf-8') as source:
                    raw = source.read(65537)
                if len(raw) > 65536:
                    return None
            config = json.loads(raw)
        except (OSError, TypeError, ValueError):
            return None
        if not isinstance(config, dict) or config.get('type') != 'service_account':
            return None
        project = config.get('project_id')
        email = config.get('client_email')
        private_key = config.get('private_key')
        token_uri = config.get('token_uri')
        if (not isinstance(project, str) or not 1 <= len(project) <= 128
                or not isinstance(email, str) or '@' not in email or len(email) > 320
                or not isinstance(private_key, str) or len(private_key) > 8192
                or not private_key.startswith('-----BEGIN PRIVATE KEY-----')
                or token_uri != _FCM_TOKEN_URI):
            return None
        return {'project_id': project, 'client_email': email,
                'private_key': private_key, 'token_uri': token_uri}

    @staticmethod
    def _base64url(raw):
        return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')

    @api.model
    def _fcm_access_token(self, config):
        key = (config['project_id'], config['client_email'], config['private_key'])
        now = int(time.time())
        with _OAUTH_LOCK:
            if _OAUTH_CACHE['key'] == key and _OAUTH_CACHE['token'] and _OAUTH_CACHE['expires_at'] > now + 60:
                return _OAUTH_CACHE['token']
            try:
                from cryptography.hazmat.primitives import hashes, serialization
                from cryptography.hazmat.primitives.asymmetric import padding
                import requests
                header = self._base64url(b'{"alg":"RS256","typ":"JWT"}')
                claims = self._base64url(json.dumps({
                    'iss': config['client_email'], 'scope': _FCM_SCOPE,
                    'aud': config['token_uri'], 'iat': now, 'exp': now + 3600,
                }, separators=(',', ':'), sort_keys=True).encode('utf-8'))
                signing_input = ('%s.%s' % (header, claims)).encode('ascii')
                key_object = serialization.load_pem_private_key(
                    config['private_key'].encode('utf-8'), password=None)
                signature = key_object.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
                assertion = '%s.%s' % (header, claims) + '.' + self._base64url(signature)
                response = requests.post(config['token_uri'], data={
                    'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
                    'assertion': assertion,
                }, timeout=(3.05, 10))
                if response.status_code != 200:
                    raise _PushTransportError('configuration', retry=False)
                payload = response.json()
                access_token = payload.get('access_token')
                expires_in = payload.get('expires_in')
                if (not isinstance(access_token, str) or not 20 <= len(access_token) <= 4096
                        or not isinstance(expires_in, int) or expires_in < 120):
                    raise _PushTransportError('configuration', retry=False)
            except _PushTransportError:
                raise
            except Exception:
                raise _PushTransportError('transport', retry=True) from None
            _OAUTH_CACHE.update(key=key, token=access_token, expires_at=now + expires_in)
            return access_token

    @api.model
    def _fcm_send(self, event, config):
        try:
            import requests
            access_token = self._fcm_access_token(config)
            data = {'account_key': event.device_id.account_key,
                    'kind': 'chat' if event.message_id else 'task',
                    'event_id': str(event.id)}
            if event.message_id:
                message = event.message_id
                sender = _notification_text(message.author_user_id.name, 120)
                preview = _notification_text(message.text, 160)
                if sender:
                    data['sender_name'] = sender
                if preview:
                    data['message_preview'] = preview
                elif message.media_id:
                    data['message_preview_kind'] = 'attachment'
            response = requests.post(
                'https://fcm.googleapis.com/v1/projects/%s/messages:send' % config['project_id'],
                headers={'Authorization': 'Bearer %s' % access_token},
                json={'message': {
                    'token': event.device_id.fcm_token,
                    'data': data,
                    'android': {'priority': 'high'},
                }}, timeout=(3.05, 10))
            if response.status_code == 200:
                return
            status = ''
            try:
                status = response.json().get('error', {}).get('status', '')
            except (TypeError, ValueError):
                pass
            if status == 'UNREGISTERED':
                raise _PushTransportError('unregistered', retry=False, invalid_token=True)
            if response.status_code in (400, 401, 403):
                raise _PushTransportError('configuration', retry=False)
            raise _PushTransportError('transport', retry=True)
        except _PushTransportError:
            raise
        except Exception:
            raise _PushTransportError('transport', retry=True) from None

    @api.model
    def _event_recipient_still_allowed(self, event):
        user = event.recipient_id
        if (not event.device_id or not event.device_id.active or not user.active
                or not user._is_internal()):
            return False
        if event.message_id:
            message = event.message_id
            if (not message or event.company_id != message.company_id
                    or message.company_id not in user.company_ids
                    or not user._bchat_effective_permissions().get('chat_view')
                    or message.author_user_id == user):
                return False
            return bool(self.env['baseer.bchat.membership'].sudo().search([
                ('room_id', '=', message.room_id.id), ('user_id', '=', user.id),
                ('active', '=', True), ('joined_after_message_id', '<', message.id),
            ], limit=1))
        task = event.task_id
        if (not task or event.company_id != task.company_id
                or task.company_id not in user.company_ids
                or not user._bchat_effective_permissions().get('task_view')):
            return False
        # Assignment wake-ups are useful only for the current revision. This
        # also revokes a queued (or already tapped) notification for an
        # assignee who was superseded by a later assignment.
        if event.event_kind == 'assigned' and event.task_revision != task.revision:
            return False
        if task.room_id:
            return bool(self.env['baseer.bchat.membership'].sudo().search([
                ('room_id', '=', task.room_id.id), ('user_id', '=', user.id), ('active', '=', True),
            ], limit=1))
        return user in (task.creator_id, task.assignee_id)

    @api.model
    def _schedule_fast_dispatch(self, event_ids):
        """Submit only after the creating transaction has committed.

        A saturated or restarted worker does not lose a notification: the
        durable event remains pending and the regular cron will recover it.
        """
        ids = sorted({event_id for event_id in event_ids if isinstance(event_id, int) and event_id > 0})
        if not ids:
            return
        dbname = self.env.cr.dbname
        lane_count = min(_FAST_DISPATCH_WORKERS, len(ids))
        lanes = [ids[lane_index::lane_count] for lane_index in range(lane_count)]

        def submit():
            for lane in lanes:
                if not _FAST_DISPATCH_SLOTS.acquire(blocking=False):
                    _LOGGER.info('BChat fast push lane is full; cron will recover a pending lane')
                    continue
                try:
                    future = _FAST_DISPATCH_EXECUTOR.submit(_fast_dispatch_events, dbname, lane)
                except RuntimeError:
                    _FAST_DISPATCH_SLOTS.release()
                    _LOGGER.warning('BChat fast push lane is unavailable; cron will recover pending events')
                    continue
                future.add_done_callback(lambda _future: _FAST_DISPATCH_SLOTS.release())

        self.env.cr.postcommit.add(submit)

    @api.model
    def _dispatch_selected(self, rows, now=None):
        now = now or fields.Datetime.now()
        config = self._fcm_config()
        for event in rows:
            if not self._event_recipient_still_allowed(event):
                event._write_verified({'state': 'discarded', 'last_error': 'access_revoked',
                                       'next_attempt_at': False}, _PUSH_TOKEN)
                continue
            if not config:
                event._write_verified({'state': 'configuration', 'last_error': 'configuration',
                                       'next_attempt_at': now + timedelta(minutes=30)}, _PUSH_TOKEN)
                continue
            try:
                self._fcm_send(event, config)
                event._write_verified({'state': 'sent', 'sent_at': now,
                                       'last_error': False, 'next_attempt_at': False}, _PUSH_TOKEN)
            except _PushTransportError as error:
                if error.invalid_token and event.device_id:
                    super(BChatPushDevice, event.device_id).write({
                        'active': False, 'last_seen_at': now,
                        'inactive_reason': 'provider_invalid', 'inactive_at': now,
                    })
                if error.code == 'configuration':
                    event._write_verified({'state': 'configuration', 'last_error': error.code,
                                           'next_attempt_at': now + timedelta(minutes=30)}, _PUSH_TOKEN)
                elif not error.retry or event.attempts >= 3:
                    event._write_verified({'state': 'failed', 'attempts': event.attempts + 1,
                                           'last_error': error.code, 'next_attempt_at': False}, _PUSH_TOKEN)
                else:
                    attempts = event.attempts + 1
                    event._write_verified({'state': 'retry', 'attempts': attempts,
                                           'last_error': error.code,
                                           'next_attempt_at': now + timedelta(minutes=min(60, 2 ** attempts))},
                                          _PUSH_TOKEN)
        return True

    @api.model
    def _dispatch_event_ids(self, event_ids):
        ids = sorted({event_id for event_id in event_ids if isinstance(event_id, int) and event_id > 0})
        if not ids:
            return True
        now = fields.Datetime.now()
        self.env.cr.execute('''
            SELECT id FROM baseer_bchat_push_event
            WHERE id = ANY(%s)
              AND state IN ('pending', 'retry', 'configuration')
              AND (next_attempt_at IS NULL OR next_attempt_at <= %s)
            ORDER BY id
            FOR UPDATE SKIP LOCKED
        ''', [ids, now])
        rows = self.sudo().browse([row[0] for row in self.env.cr.fetchall()]).exists()
        return self._dispatch_selected(rows, now)

    @api.model
    def _cron_dispatch(self):
        now = fields.Datetime.now()
        # Do not let two Odoo workers deliver the same durable event.  The locks
        # live until this cron transaction completes, so another worker skips them.
        self.env.cr.execute('''
            SELECT id FROM baseer_bchat_push_event
            WHERE state IN ('pending', 'retry', 'configuration')
              AND (next_attempt_at IS NULL OR next_attempt_at <= %s)
            ORDER BY id
            FOR UPDATE SKIP LOCKED
            LIMIT 100
        ''', [now])
        rows = self.sudo().browse([row[0] for row in self.env.cr.fetchall()]).exists()
        return self._dispatch_selected(rows, now)

    def copy_data(self, default=None):
        raise AccessError(self.env._('BChat push events cannot be copied.'))


class BChatPushService(models.AbstractModel):
    _inherit = 'baseer.bchat.service'

    @api.model
    def _v2_push_register(self, payload):
        if not isinstance(payload, dict) or set(payload) != {'api_version', 'installation_id', 'fcm_token'}:
            raise ProtocolError('invalid_payload', 'Invalid BChat push registration.')
        if payload['api_version'] != 2:
            raise ProtocolError('invalid_payload', 'Unsupported BChat API version.')
        user = self._require_any_bchat_permission('chat_view', 'task_view')
        installation = _uuid4(payload['installation_id'], 'installation ID')
        token = _fcm_token(payload['fcm_token'])
        device = self.env['baseer.bchat.push.device']._register_verified(
            user, installation, token, _PUSH_TOKEN)
        # This confirms only secure registration.  FCM delivery remains best-effort
        # and may be held by the server's protected runtime configuration.
        return {'api_version': 2, 'installation_id': installation,
                'account_key': device.account_key, 'push_enabled': True}

    @api.model
    def _v2_push_unregister(self, payload):
        if not isinstance(payload, dict) or set(payload) != {'api_version', 'installation_id'}:
            raise ProtocolError('invalid_payload', 'Invalid BChat push registration.')
        if payload['api_version'] != 2:
            raise ProtocolError('invalid_payload', 'Unsupported BChat API version.')
        user = self._require_user()
        installation = _uuid4(payload['installation_id'], 'installation ID')
        self.env['baseer.bchat.push.device']._unregister_verified(user, installation, _PUSH_TOKEN)
        return {'api_version': 2, 'installation_id': installation}

    @api.model
    def _v2_push_event(self, event_id):
        event = self.env['baseer.bchat.push.event'].sudo().browse(positive_id(event_id, 'event_id')).exists()
        self._require_bchat_permission('chat_view' if event and event.message_id else 'task_view')
        if not event or event.recipient_id.id != self.env.uid or not self.env['baseer.bchat.push.event']._event_recipient_still_allowed(event):
            raise AccessError(self.env._('This BChat notification is unavailable.'))
        if event.message_id:
            return {'api_version': 2, 'notification': {
                'id': event.id, 'kind': 'chat',
                'source_ref': {'destination': 'room_message',
                               'room_id': event.message_id.room_id.id,
                               'message_id': event.message_id.id},
            }}
        return {'api_version': 2, 'notification': {
            'id': event.id, 'kind': 'task',
            'source_ref': {'destination': 'task', 'task_id': event.task_id.id},
        }}

    @api.model
    def _task_queue_push(self, task, action, actor_id=None):
        event_kind = 'assigned' if action in ('created', 'reassign', 'rescue') else 'updated'
        if task.room_id:
            members = self.env['baseer.bchat.membership'].sudo().search([
                ('room_id', '=', task.room_id.id), ('active', '=', True),
            ], limit=2049)
            if len(members) > 2048:
                raise AccessError(self.env._('This BChat room exceeds its member limit.'))
            recipient_ids = set(members.mapped('user_id').ids)
        else:
            # The existing task-read contract deliberately keeps standalone
            # tasks private to their creator and current assignee.
            recipient_ids = {task.creator_id.id, task.assignee_id.id}
        if isinstance(actor_id, int):
            recipient_ids.discard(actor_id)
        recipients = self.env['res.users'].sudo().browse(sorted(recipient_ids)).exists()
        rows = []
        devices = self.env['baseer.bchat.push.device'].sudo()
        for recipient in recipients:
            if not recipient.active or not recipient._is_internal() or task.company_id not in recipient.company_ids:
                continue
            if task.room_id and not self.env['baseer.bchat.membership'].sudo().search([
                ('room_id', '=', task.room_id.id), ('user_id', '=', recipient.id), ('active', '=', True),
            ], limit=1):
                continue
            if not recipient._bchat_effective_permissions().get('task_view'):
                continue
            for device in devices.search([('user_id', '=', recipient.id), ('active', '=', True)], limit=5):
                rows.append({'recipient_id': recipient.id, 'device_id': device.id,
                             'task_id': task.id, 'company_id': task.company_id.id,
                             'event_kind': event_kind, 'task_revision': task.revision,
                             'state': 'pending', 'next_attempt_at': fields.Datetime.now()})
        if rows:
            queued = self.env['baseer.bchat.push.event']._queue_verified(rows, _PUSH_TOKEN)
            queued._schedule_fast_dispatch(queued.ids)

    @api.model
    def _message_queue_push(self, message, recipients):
        rows = []
        devices = self.env['baseer.bchat.push.device'].sudo()
        for recipient in recipients:
            user = recipient.user_id
            if (not user.active or not user._is_internal()
                    or message.company_id not in user.company_ids
                    or not user._bchat_effective_permissions().get('chat_view')):
                continue
            for device in devices.search([('user_id', '=', user.id), ('active', '=', True)], limit=5):
                rows.append({'recipient_id': user.id, 'device_id': device.id,
                             'message_id': message.id, 'company_id': message.company_id.id,
                             'event_kind': 'message', 'state': 'pending',
                             'next_attempt_at': fields.Datetime.now()})
        if rows:
            queued = self.env['baseer.bchat.push.event']._queue_verified(rows, _PUSH_TOKEN)
            queued._schedule_fast_dispatch(queued.ids)
