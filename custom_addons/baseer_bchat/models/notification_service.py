"""Installation-scoped preview choice and generic, rate-limited self tests."""
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError

from ..contracts import ProtocolError, canonical_uuid, positive_id
from .push import _PUSH_TOKEN, _uuid4


class BChatNotificationSettingsService(models.AbstractModel):
    _inherit = 'baseer.bchat.service'

    @api.model
    def _v2_bootstrap(self):
        result = super()._v2_bootstrap()
        result['notification_preferences_version'] = 1
        result['notification_diagnostics_version'] = 1
        return result

    @api.model
    def _social_replay_guard(self, action, intent):
        if action in ('notification_preferences', 'notification_test'):
            self._notification_device(intent['installation_id'], intent['account_key'])
            return
        return super()._social_replay_guard(action, intent)

    @api.model
    def _notification_device(self, installation_id, account_key=None, *, lock=False):
        user = self._require_any_bchat_permission('chat_view', 'task_view')
        installation_id = _uuid4(installation_id, 'installation ID')
        if account_key is not None:
            account_key = _uuid4(account_key, 'account key')
        device = self.env['baseer.bchat.push.device'].sudo().search([
            ('user_id', '=', user.id), ('installation_id', '=', installation_id), ('active', '=', True),
        ], limit=1)
        if not device:
            raise AccessError(self.env._('The current notification installation is unavailable.'))
        if lock:
            self.env.cr.execute('SELECT id FROM baseer_bchat_push_device WHERE id = %s FOR UPDATE', [device.id])
            device.invalidate_recordset()
        if (not device.active or device.user_id.id != user.id
                or (account_key is not None and device.account_key != account_key)):
            raise AccessError(self.env._('The current notification installation is unavailable.'))
        return device

    @staticmethod
    def _notification_stamp(value):
        return value.strftime('%Y-%m-%dT%H:%M:%SZ') if value else None

    @api.model
    def _notification_preference_data(self, device):
        return {'api_version': 2, 'installation_id': device.installation_id,
                'account_key': device.account_key, 'preview_mode': device.preview_mode,
                'revision': device.preference_revision, 'registration_active': bool(device.active)}

    @api.model
    def _v2_notification_preferences(self, installation_id):
        # Defaults are fields on an existing registration. GET never creates
        # a registration, preference, operation receipt or diagnostic event.
        return self._notification_preference_data(self._notification_device(installation_id))

    @api.model
    def _v2_notification_set_preferences(self, payload):
        if type(payload) is not dict or set(payload) != {
                'api_version', 'installation_id', 'account_key', 'client_uuid',
                'expected_revision', 'preview_mode'} or type(payload['api_version']) is not int or payload['api_version'] != 2:
            raise ProtocolError('invalid_payload', 'Invalid notification preference fields.')
        mode = payload['preview_mode']
        if type(mode) is not str or mode not in ('none', 'sender', 'full'):
            raise ProtocolError('invalid_payload', 'Choose a supported notification preview mode.')
        expected = positive_id(payload['expected_revision'], 'expected_revision')
        token = canonical_uuid(payload['client_uuid'])
        self._notification_device(payload['installation_id'], payload['account_key'])
        with self.env.cr.savepoint():
            digest, replay = self._social_lock_operation('notification_preferences', token, payload)
            device = self._notification_device(payload['installation_id'], payload['account_key'], lock=True)
            if replay is None:
                device._set_preview_verified(mode, expected, _PUSH_TOKEN)
                replay = {'revision': device.preference_revision}
                self._social_complete_operation('notification_preferences', token, digest, replay)
                repeated = False
            else:
                repeated = True
            return {**self._notification_preference_data(device),
                    'operation_revision': replay['revision'], 'client_uuid': token, 'replayed': repeated}

    @api.model
    def _notification_quota_rows(self, user_id, device_id, now):
        """Bounded union after the account quota lock, not a stale RR count.

        Waiting on an advisory lock does not refresh Odoo's transaction
        snapshot. A different installation may have consumed the final daily
        slot while we waited. The fresh cursor supplies committed rows; the
        caller's cursor supplies its own uncommitted tests in the same request.
        Neither cursor writes, authenticates another user or returns content.
        """
        latest_query = '''SELECT id,create_date FROM baseer_bchat_push_event
            WHERE recipient_id=%s AND device_id=%s AND event_kind='diagnostic'
            ORDER BY create_date DESC,id DESC LIMIT 1'''
        recent_query = '''SELECT id,create_date FROM baseer_bchat_push_event
            WHERE recipient_id=%s AND event_kind='diagnostic' AND create_date>%s
            ORDER BY create_date,id LIMIT 10'''
        recent_args = [user_id, now - timedelta(days=1)]
        latest, recent = {}, {}

        def read(cursor):
            cursor.execute(latest_query, [user_id, device_id])
            latest.update(cursor.fetchall())
            cursor.execute(recent_query, recent_args)
            recent.update(cursor.fetchall())

        read(self.env.cr)
        with self.env.registry.cursor() as fresh_cr:
            read(fresh_cr)
        return (max(latest.values()) if latest else None,
                sorted(recent.values()))

    @api.model
    def _v2_notification_test(self, payload):
        if type(payload) is not dict or set(payload) != {
                'api_version', 'installation_id', 'account_key', 'client_uuid'} or type(payload['api_version']) is not int or payload['api_version'] != 2:
            raise ProtocolError('invalid_payload', 'Invalid notification test fields.')
        token = canonical_uuid(payload['client_uuid'])
        user = self._require_any_bchat_permission('chat_view', 'task_view')
        self._notification_device(payload['installation_id'], payload['account_key'])
        with self.env.cr.savepoint():
            digest, replay = self._social_lock_operation('notification_test', token, payload)
            # Serialize the account-wide quota before locking one of its five
            # installations. No change cursor or business row is repurposed.
            self.env.cr.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))',
                                ['bchat-notification-test:%s' % user.id])
            device = self._notification_device(payload['installation_id'], payload['account_key'], lock=True)
            if replay is not None:
                return {**self._notification_test_data(device, replay['event_id']), 'replayed': True}
            now = fields.Datetime.now()
            events = self.env['baseer.bchat.push.event'].sudo()
            latest_at, recent = self._notification_quota_rows(user.id, device.id, now)
            retry_seconds = 0
            if latest_at and latest_at > now - timedelta(seconds=60):
                retry_seconds = max(1, int((latest_at + timedelta(seconds=60) - now).total_seconds()) + 1)
            if len(recent) >= 10:
                retry_seconds = max(retry_seconds, max(1, int((recent[0] + timedelta(days=1) - now).total_seconds()) + 1))
            if retry_seconds:
                error = ProtocolError('rate_limited', 'Wait before requesting another notification test.', 429)
                error.retry_after_seconds = retry_seconds
                raise error
            event = events._queue_verified([{
                'recipient_id': user.id, 'device_id': device.id,
                'company_id': user.company_id.id, 'event_kind': 'diagnostic',
                'diagnostic_uuid': token, 'state': 'pending', 'next_attempt_at': now,
            }], _PUSH_TOKEN)
            device._touch_diagnostic_verified(now, _PUSH_TOKEN)
            self._social_complete_operation('notification_test', token, digest, {'event_id': event.id})
            event._schedule_fast_dispatch(event.ids)
            return {**self._notification_test_data(device, event.id), 'replayed': False}

    @api.model
    def _notification_test_data(self, device, event_id):
        event = self.env['baseer.bchat.push.event'].sudo().browse(positive_id(event_id, 'event_id')).exists()
        user = self._require_any_bchat_permission('chat_view', 'task_view')
        if (not event or event.event_kind != 'diagnostic' or event.device_id != device
                or event.recipient_id != user or not self.env['baseer.bchat.push.event']._event_recipient_still_allowed(event)):
            raise AccessError(self.env._('This notification test is unavailable.'))
        return {
            'api_version': 2, 'installation_id': device.installation_id,
            'account_key': device.account_key, 'registration_active': True,
            'configuration_ready': bool(self.env['baseer.bchat.push.event']._fcm_config()),
            'test': {'event_id': event.id, 'diagnostic_uuid': event.diagnostic_uuid,
                     'state': event.state, 'provider_accepted_at': self._notification_stamp(event.sent_at),
                     'next_attempt_at': self._notification_stamp(event.next_attempt_at),
                     'last_error': event.last_error or None},
        }

    @api.model
    def _v2_notification_test_status(self, installation_id, event_id):
        return self._notification_test_data(self._notification_device(installation_id), event_id)
