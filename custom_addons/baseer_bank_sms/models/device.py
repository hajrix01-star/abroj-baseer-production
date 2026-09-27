import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


PBKDF2_ITERATIONS = 310_000
# The Android client sends one complete message per acknowledged request.
# A historical month import is sequential and already authenticated, encrypted
# locally, and idempotent at the server.  360/min remains bounded while avoiding
# a needless retry pause after roughly one minute of normal phone throughput.
REQUESTS_PER_MINUTE = 360
# A message receipt is not a connection heartbeat.  These short windows are
# reserved for the v2 health contract and are never inferred from queue state.
HEARTBEAT_ONLINE_SECONDS = 120
HEARTBEAT_DEGRADED_SECONDS = 600


class BaseerBankSmsDevice(models.Model):
    _name = 'baseer.bank.sms.device'
    _description = 'Bank SMS device'
    _order = 'name, id'

    name = fields.Char(required=True, translate=True)
    device_code = fields.Char(required=True, copy=False, index=True,
                              help='Non-secret identifier configured in the Android app.')
    installation_id = fields.Char(copy=False, readonly=True, index=True,
                                  help='Random identifier persisted by the Android app after QR pairing.')
    active = fields.Boolean(default=True)
    secret_salt = fields.Char(copy=False, readonly=True, groups='base.group_system')
    secret_hash = fields.Char(copy=False, readonly=True, groups='base.group_system')
    last_seen_at = fields.Datetime(readonly=True)
    last_heartbeat_at = fields.Datetime(readonly=True, copy=False)
    last_message_ingested_at = fields.Datetime(readonly=True, copy=False)
    last_acknowledged_at = fields.Datetime(readonly=True, copy=False)
    app_version = fields.Char(readonly=True, copy=False)
    protocol_version = fields.Char(readonly=True, copy=False)
    monitoring_enabled = fields.Boolean(readonly=True, copy=False)
    queued_count = fields.Integer(readonly=True, copy=False)
    retry_count = fields.Integer(readonly=True, copy=False)
    blocked_count = fields.Integer(readonly=True, copy=False)
    oldest_pending_at = fields.Datetime(readonly=True, copy=False)
    last_error_code = fields.Char(readonly=True, copy=False)
    last_error_at = fields.Datetime(readonly=True, copy=False)
    connection_state = fields.Selection([
        ('online', 'Online'),
        ('degraded', 'Degraded'),
        ('offline', 'Offline'),
    ], compute='_compute_connection_state', readonly=True,
       help='Derived only from an authenticated v2 heartbeat, never from an empty message queue.')

    _device_code_unique = models.Constraint('UNIQUE(device_code)', 'The device code must be unique.')
    _installation_unique = models.Constraint('UNIQUE(installation_id)', 'The Android installation must be unique.')

    @api.depends('last_heartbeat_at')
    def _compute_connection_state(self):
        now = fields.Datetime.now()
        for device in self:
            if not device.last_heartbeat_at:
                device.connection_state = 'offline'
                continue
            age = (now - device.last_heartbeat_at).total_seconds()
            if age <= HEARTBEAT_ONLINE_SECONDS:
                device.connection_state = 'online'
            elif age <= HEARTBEAT_DEGRADED_SECONDS:
                device.connection_state = 'degraded'
            else:
                device.connection_state = 'offline'

    @staticmethod
    def _digest(secret, salt):
        value = hashlib.pbkdf2_hmac('sha256', secret.encode(), salt.encode(), PBKDF2_ITERATIONS)
        return base64.b64encode(value).decode()

    def action_rotate_secret(self):
        self.ensure_one()
        secret = secrets.token_urlsafe(32)
        salt = secrets.token_hex(16)
        self.write({'secret_salt': salt, 'secret_hash': self._digest(secret, salt)})
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'baseer.bank.sms.device.secret.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_device_id': self.id, 'default_secret': secret},
        }

    def verify_secret(self, secret):
        self.ensure_one()
        return bool(self.active and self.secret_salt and self.secret_hash and hmac.compare_digest(
            self.secret_hash, self._digest(secret, self.secret_salt),
        ))

    def ingest_payload(self, payload):
        self.ensure_one()
        if not self.active:
            raise ValueError('device_inactive')
        expected = {'device_code', 'idempotency_key', 'sender', 'body', 'received_at'}
        if set(payload) - expected:
            raise ValueError('unsupported_field')
        if payload.get('device_code') != self.device_code:
            raise ValueError('device_mismatch')
        key = payload.get('idempotency_key')
        sender = payload.get('sender')
        body = payload.get('body')
        if not isinstance(key, str) or not 8 <= len(key) <= 160:
            raise ValueError('invalid_idempotency_key')
        if not isinstance(sender, str) or not 1 <= len(sender) <= 100:
            raise ValueError('invalid_sender')
        if not self.env['baseer.bank.sms.sender'].sudo().search_count([('active', '=', True), ('sender', '=', sender)]):
            raise ValueError('sender_not_allowed')
        if not isinstance(body, str) or not 1 <= len(body) <= 4096:
            raise ValueError('invalid_body')
        received_at = payload.get('received_at')
        if not isinstance(received_at, str) or not 1 <= len(received_at) <= 40:
            raise ValueError('invalid_received_at')
        try:
            parsed_at = datetime.fromisoformat(received_at.replace('Z', '+00:00'))
            if parsed_at.tzinfo:
                parsed_at = parsed_at.astimezone(timezone.utc).replace(tzinfo=None)
            received_at = fields.Datetime.to_string(parsed_at)
        except (TypeError, ValueError):
            raise ValueError('invalid_received_at')
        Message = self.env['baseer.bank.sms.message'].sudo()
        cutoff = fields.Datetime.now() - timedelta(minutes=1)
        if Message.search_count([('source_device_id', '=', self.device_code), ('create_date', '>=', cutoff)]) >= REQUESTS_PER_MINUTE:
            raise ValueError('rate_limit_exceeded')
        message = Message.ingest(
            source_device_id=self.device_code,
            idempotency_key=key,
            sender=sender,
            body=body,
            received_at=received_at,
        )
        now = fields.Datetime.now()
        self.sudo().write({
            'last_seen_at': now,
            'last_message_ingested_at': now,
            'last_acknowledged_at': now,
            'last_error_code': False,
            'last_error_at': False,
        })
        return message

    def allowed_senders(self):
        self.ensure_one()
        return self.env['baseer.bank.sms.sender'].sudo().search([('active', '=', True)]).mapped('sender')

    def mark_seen(self):
        """Compatibility marker for the v1 client.  It is not a live heartbeat."""
        self.ensure_one()
        self.sudo().write({'last_seen_at': fields.Datetime.now()})

    def record_heartbeat(self, payload):
        """Persist an authenticated v2 health snapshot without SMS text or secrets."""
        self.ensure_one()
        allowed = {
            'device_code', 'app_version', 'protocol_version', 'monitoring_enabled',
            'queued_count', 'retry_count', 'blocked_count', 'oldest_pending_at',
            'last_error_code',
        }
        if not isinstance(payload, dict) or set(payload) - allowed:
            raise ValueError('unsupported_field')
        if payload.get('device_code') != self.device_code:
            raise ValueError('device_mismatch')

        def count(name):
            value = payload.get(name, 0)
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1_000_000:
                raise ValueError('invalid_%s' % name)
            return value

        def text(name, limit):
            value = payload.get(name, '')
            if value is None:
                return False
            if not isinstance(value, str) or len(value) > limit:
                raise ValueError('invalid_%s' % name)
            return value or False

        oldest = payload.get('oldest_pending_at')
        if oldest:
            if not isinstance(oldest, str) or len(oldest) > 40:
                raise ValueError('invalid_oldest_pending_at')
            try:
                parsed = datetime.fromisoformat(oldest.replace('Z', '+00:00'))
                if parsed.tzinfo:
                    parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
                oldest = fields.Datetime.to_string(parsed)
            except (TypeError, ValueError):
                raise ValueError('invalid_oldest_pending_at')
        now = fields.Datetime.now()
        error_code = text('last_error_code', 80)
        self.sudo().write({
            'last_seen_at': now,
            'last_heartbeat_at': now,
            'app_version': text('app_version', 40),
            'protocol_version': text('protocol_version', 20),
            'monitoring_enabled': bool(payload.get('monitoring_enabled', False)),
            'queued_count': count('queued_count'),
            'retry_count': count('retry_count'),
            'blocked_count': count('blocked_count'),
            'oldest_pending_at': oldest or False,
            'last_error_code': error_code,
            'last_error_at': now if error_code else False,
        })
        return {
            'environment_label': self.env['ir.config_parameter'].sudo().get_param(
                'baseer_bank_sms.environment_label', 'QA'),
            'device_active': bool(self.active),
            'heartbeat_ttl_seconds': HEARTBEAT_ONLINE_SECONDS,
            'server_time': fields.Datetime.to_string(now),
            'connection_state': self.connection_state,
        }


class BaseerBankSmsDeviceSecretWizard(models.TransientModel):
    _name = 'baseer.bank.sms.device.secret.wizard'
    _description = 'Bank SMS device secret'

    device_id = fields.Many2one('baseer.bank.sms.device', required=True, readonly=True)
    secret = fields.Char(required=True, readonly=True)

    def action_close(self):
        return {'type': 'ir.actions.act_window_close'}
