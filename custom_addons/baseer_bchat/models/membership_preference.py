"""Personal epoch settings, intentionally outside manager-readable membership."""
import base64
from datetime import datetime, timedelta
import hashlib
import json
import re

from odoo import api, fields, models, sql_db
from odoo.exceptions import AccessError

from ..contracts import ProtocolError, canonical_uuid, positive_id


_PREFERENCE_TOKEN = object()


class BChatMembershipPreference(models.Model):
    _name = 'baseer.bchat.membership.preference'
    _description = 'BChat private membership preferences'

    membership_id = fields.Many2one('baseer.bchat.membership', required=True, readonly=True, ondelete='restrict', index=True)
    user_id = fields.Many2one(related='membership_id.user_id', store=True, readonly=True, index=True)
    room_id = fields.Many2one(related='membership_id.room_id', store=True, readonly=True, index=True)
    company_id = fields.Many2one(related='membership_id.company_id', store=True, readonly=True, index=True)
    muted_until = fields.Datetime(readonly=True)
    mute_forever = fields.Boolean(readonly=True, default=False)
    pinned_at = fields.Datetime(readonly=True)
    archived = fields.Boolean(readonly=True, default=False)
    revision = fields.Integer(required=True, readonly=True, default=1)

    _membership_unique = models.Constraint('UNIQUE(membership_id)', 'One private preference row belongs to one membership epoch.')
    _revision_positive = models.Constraint('CHECK(revision > 0)', 'A preference revision must be positive.')
    _mute_shape = models.Constraint('CHECK(NOT mute_forever OR muted_until IS NULL)', 'Choose one mute duration.')

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError(self.env._('Personal BChat preferences are service-owned.'))

    def write(self, vals):
        raise AccessError(self.env._('Personal BChat preferences are service-owned.'))

    def unlink(self):
        raise AccessError(self.env._('Personal BChat preferences cannot be deleted directly.'))

    def copy_data(self, default=None):
        raise AccessError(self.env._('Personal BChat preferences cannot be copied.'))

    @api.model
    def _create_verified(self, values, token):
        if token is not _PREFERENCE_TOKEN or set(values) != {
                'membership_id', 'muted_until', 'mute_forever', 'pinned_at', 'archived', 'revision'}:
            raise AccessError(self.env._('A verified personal preference is required.'))
        return super(BChatMembershipPreference, self.sudo()).create(values)

    def _write_verified(self, values, token):
        self.ensure_one()
        if token is not _PREFERENCE_TOKEN or set(values) != {
                'muted_until', 'mute_forever', 'pinned_at', 'archived', 'revision'}:
            raise AccessError(self.env._('A verified personal preference is required.'))
        return super(BChatMembershipPreference, self.sudo()).write(values)

    @api.model
    def _room_is_muted_verified(self, user_id, room_id, now, token):
        return user_id in self._muted_user_ids_verified([user_id], room_id, now, token)

    @api.model
    def _muted_user_ids_verified(self, user_ids, room_id, now, token):
        if token is not _PREFERENCE_TOKEN:
            raise AccessError(self.env._('A verified notification preference read is required.'))
        ids = sorted(set(user_ids))
        if len(ids) > 2048 or any(type(value) is not int or value <= 0 for value in ids):
            raise AccessError(self.env._('Notification recipient scope exceeds its supported limit.'))
        rows = self.sudo().search([
            ('user_id', 'in', ids), ('room_id', '=', room_id), ('membership_id.active', '=', True),
        ], limit=2049)
        if len(rows) > 2048:
            raise AccessError(self.env._('Notification recipient scope exceeds its supported limit.'))
        return {row.user_id.id for row in rows if row.mute_forever or (row.muted_until and row.muted_until > now)}


class BChatMembershipPreferenceService(models.AbstractModel):
    _inherit = 'baseer.bchat.service'

    @api.model
    def _social_replay_guard(self, action, intent):
        if action == 'room_preferences':
            self._room_preference_replay_scope(intent)
            return
        return super()._social_replay_guard(action, intent)

    @api.model
    def _room_preference_replay_scope(self, intent):
        """Current scope without a room lock, including inside a fresh cursor."""
        user = self._require_bchat_permission('chat_view')
        room = self.env['baseer.bchat.room'].sudo().browse(intent['room_id']).exists()
        if not room or room.company_id not in user.company_ids:
            raise AccessError(self.env._('This room is unavailable.'))
        member = self._v2_current_member(room)
        if member.id != intent['membership_id']:
            raise ProtocolError('membership_changed', 'The membership period changed.', 409)
        return room, member

    @api.model
    def _room_preference_scope(self, room_id, membership_id, *, mutate=False):
        self._require_bchat_permission('chat_view')
        room = self._v2_lock_room(room_id, mutate=mutate)
        member = self._v2_current_member(room)
        if member.id != positive_id(membership_id, 'membership_id'):
            raise ProtocolError('membership_changed', 'The membership period changed.', 409)
        return room, member

    @api.model
    def _room_preference_row(self, member):
        return self.env['baseer.bchat.membership.preference'].sudo().search([
            ('membership_id', '=', member.id), ('user_id', '=', self.env.uid),
        ], limit=1)

    @api.model
    def _room_preference_data(self, member, row=None, now=None):
        now = now or fields.Datetime.now()
        until = row.muted_until if row else None
        forever = bool(row and row.mute_forever)
        return {
            'api_version': 2, 'room_id': member.room_id.id, 'membership_id': member.id,
            'revision': row.revision if row else 1,
            'muted_until': self._notification_stamp(until), 'mute_forever': forever,
            'muted': bool(forever or (until and until > now)),
            'pinned': bool(row and row.pinned_at),
            'pinned_at': self._notification_stamp(row.pinned_at if row else None),
            'archived': bool(row and row.archived),
        }

    @api.model
    def _v2_room_preferences(self, room_id, membership_id):
        _room, member = self._room_preference_scope(room_id, membership_id)
        return self._room_preference_data(member, self._room_preference_row(member))

    @api.model
    def _room_preference_intent(self, room_id, payload):
        """Original/cancel share canonical shape; future-expiry is apply-only."""
        required = {'api_version', 'membership_id', 'client_uuid', 'expected_revision',
                    'muted_until', 'mute_forever', 'pinned', 'archived'}
        if (type(payload) is not dict or set(payload) != required
                or type(payload['api_version']) is not int or payload['api_version'] != 2
                or any(type(payload[key]) is not bool for key in ('mute_forever', 'pinned', 'archived'))):
            raise ProtocolError('invalid_payload', 'Invalid personal room preference fields.')
        room_id = positive_id(room_id, 'room_id')
        positive_id(payload['membership_id'], 'membership_id')
        token = canonical_uuid(payload['client_uuid'])
        expected = positive_id(payload['expected_revision'], 'expected_revision')
        until = payload['muted_until']
        if until is not None:
            if (type(until) is not str or not re.fullmatch(
                    r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z', until)):
                raise ProtocolError('invalid_payload', 'Mute expiry must be a UTC timestamp or null.')
            try:
                until = datetime.strptime(until, '%Y-%m-%dT%H:%M:%SZ')
            except ValueError:
                raise ProtocolError('invalid_payload', 'Mute expiry must be a UTC timestamp or null.') from None
        if until is not None and payload['mute_forever']:
            raise ProtocolError('invalid_payload', 'Choose one mute duration.')
        return room_id, token, expected, until

    @api.model
    def _room_preference_receipt_kind(self, result):
        """This strict result union belongs only to action=room_preferences."""
        if type(result) is dict:
            if set(result) == {'cancelled'} and result['cancelled'] is True:
                return 'cancelled'
            if (set(result) == {'revision'} and type(result['revision']) is int
                    and 0 < result['revision'] <= 2147483647):
                return 'applied'
        raise AccessError(self.env._('This personal preference receipt is unavailable.'))

    @api.model
    def _room_preference_cancellation(self, room_id, payload, token):
        return {'api_version': 2, 'room_id': room_id, 'membership_id': payload['membership_id'],
                'client_uuid': token, 'expected_revision': payload['expected_revision'], 'cancelled': True}

    @api.model
    def _room_preference_applied_replay(self, intent, token, operation_revision):
        """Primary fresh auth+snapshot; only proven own-uncommitted may use MAIN.

        Called under the exact actor/action/UUID advisory lock. Immutable,
        never-deleted journal rows visible to MAIN cannot be missing from a
        later primary snapshot unless MAIN itself has not committed that row.
        Use a real independent connection even in Odoo's shared TestCursor mode.
        """
        digest = hashlib.sha256(json.dumps(intent, ensure_ascii=False, sort_keys=True,
                                          separators=(',', ':')).encode('utf-8')).hexdigest()
        query = '''SELECT payload_digest,result_json FROM baseer_bchat_social_operation
                   WHERE actor_id=%s AND action='room_preferences' AND client_uuid=%s'''
        arguments = [self.env.uid, token]

        def validate(receipt):
            if not receipt or receipt[0] != digest:
                raise AccessError(self.env._('This personal preference receipt is unavailable.'))
            try:
                result = json.loads(receipt[1])
            except (ValueError, TypeError):
                raise AccessError(self.env._('This personal preference receipt is unavailable.')) from None
            if (self._room_preference_receipt_kind(result) != 'applied'
                    or result['revision'] != operation_revision
                    or operation_revision != intent['expected_revision'] + 1):
                raise AccessError(self.env._('This personal preference receipt is unavailable.'))

        def snapshot(service):
            _room, member = service._room_preference_replay_scope(intent)
            data = service._room_preference_data(member, service._room_preference_row(member))
            if (type(data['revision']) is not int or not operation_revision <= data['revision'] <= 2147483647):
                raise AccessError(service.env._('This personal preference snapshot is unavailable.'))
            return {**data, 'replayed': True, 'client_uuid': token, 'operation_revision': operation_revision}

        # readonly=True may choose a lagging replica; the terminal decision must
        # read the same PRIMARY as the request, made read-only before any query.
        with sql_db.db_connect(self.env.cr.dbname, readonly=False).cursor() as fresh_cr:
            fresh_cr.execute('SET TRANSACTION READ ONLY')
            fresh_cr.execute(query, arguments)
            fresh_receipt = fresh_cr.fetchone()
            if fresh_receipt:
                validate(fresh_receipt)
                fresh = api.Environment(fresh_cr, self.env.uid, {
                    'allowed_company_ids': self.env.context.get('allowed_company_ids', []),
                })
                return snapshot(fresh['baseer.bchat.service'])
        # Never use a MAIN row in the independent cursor, nor a room lock here.
        # A missing fresh row alone is NOT proof: MAIN must see this exact row.
        self.env.cr.execute(query, arguments)
        validate(self.env.cr.fetchone())
        return snapshot(self)

    @api.model
    def _v2_cancel_room_preferences(self, room_id, payload):
        room_id, token, _expected, _until = self._room_preference_intent(room_id, payload)
        self._require_bchat_permission('chat_view')
        intent = {'room_id': room_id, **payload}
        with self.env.cr.savepoint():
            digest, replay = self._social_lock_operation('room_preferences', token, intent)
            if replay is not None:
                if self._room_preference_receipt_kind(replay) == 'applied':
                    return self._room_preference_applied_replay(intent, token, replay['revision'])
                self._room_preference_replay_scope(intent)
                return self._room_preference_cancellation(room_id, payload, token)
            self._room_preference_scope(room_id, payload['membership_id'], mutate=True)
            self._social_complete_operation('room_preferences', token, digest, {'cancelled': True})
            return self._room_preference_cancellation(room_id, payload, token)

    @api.model
    def _v2_set_room_preferences(self, room_id, payload):
        room_id, token, expected, until = self._room_preference_intent(room_id, payload)
        self._require_bchat_permission('chat_view')
        with self.env.cr.savepoint():
            digest, replay = self._social_lock_operation('room_preferences', token, {'room_id': room_id, **payload})
            if replay is not None:
                if self._room_preference_receipt_kind(replay) == 'cancelled':
                    self._room_preference_replay_scope({'room_id': room_id, **payload})
                    return self._room_preference_cancellation(room_id, payload, token)
                return self._room_preference_applied_replay({'room_id': room_id, **payload}, token, replay['revision'])
            room, member = self._room_preference_scope(room_id, payload['membership_id'], mutate=True)
            row = self._room_preference_row(member)
            now = fields.Datetime.now()
            if until is not None and not now < until <= now + timedelta(days=365):
                raise ProtocolError('invalid_payload', 'Choose a future mute expiry within one year.')
            revision = row.revision if row else 1
            if revision != expected:
                raise ProtocolError('revision_conflict', 'Room preferences changed; refresh before continuing.', 409)
            values = {'muted_until': until, 'mute_forever': payload['mute_forever'],
                      'pinned_at': (row.pinned_at if row and row.pinned_at else now) if payload['pinned'] else None,
                      'archived': payload['archived'], 'revision': revision + 1}
            if row:
                row._write_verified(values, _PREFERENCE_TOKEN)
            else:
                row = self.env['baseer.bchat.membership.preference']._create_verified({
                    'membership_id': member.id, **values,
                }, _PREFERENCE_TOKEN)
            self._social_complete_operation('room_preferences', token, digest, {'revision': row.revision})
            self._change_publish([self.env.uid], 'room', room_id=room.id, company_id=room.company_id.id,
                                 memberships={self.env.uid: member.id})
            return {**self._room_preference_data(member, row, now), 'replayed': False,
                    'client_uuid': token, 'operation_revision': row.revision}

    @api.model
    def _v2_social_rooms(self, archived=False, cursor=None):
        user = self._require_bchat_permission('chat_view')
        if type(archived) is not bool:
            raise ProtocolError('invalid_payload', 'Choose one room archive filter.')
        # The existing authorized snapshot is already bounded to 100 rooms.
        rooms = self._v2_rooms()['rooms']
        member_ids = [row['membership_id'] for row in rooms]
        preferences = self.env['baseer.bchat.membership.preference'].sudo().search([
            ('membership_id', 'in', member_ids), ('user_id', '=', user.id),
        ], limit=100)
        by_member = {row.membership_id.id: row for row in preferences}
        members = self.env['baseer.bchat.membership'].sudo().browse(member_ids)
        member_by_id = {row.id: row for row in members}
        scope = hashlib.sha256(json.dumps(sorted(member_ids)).encode('ascii')).hexdigest()[:24]
        after_key = None
        if cursor is not None:
            try:
                if (type(cursor) is not str or not cursor or len(cursor) > 512 or not cursor.isascii()
                        or any(not (char.isalnum() or char in '-_') for char in cursor)):
                    raise ValueError()
                decoded = json.loads(base64.urlsafe_b64decode(cursor + '=' * (-len(cursor) % 4)).decode('utf-8'))
                if (type(decoded) is not dict or set(decoded) != {'user_id', 'archived', 'scope', 'key'}
                        or type(decoded['user_id']) is not int or decoded['user_id'] != user.id
                        or type(decoded['archived']) is not bool or decoded['archived'] != archived):
                    raise ValueError()
                if decoded['scope'] != scope:
                    raise ProtocolError('membership_changed', 'Room membership changed; refresh the list.', 409)
                key = decoded['key']
                if (type(key) is not list or len(key) != 4 or type(key[0]) is not bool
                        or type(key[1]) is not str or len(key[1]) > 20
                        or type(key[2]) is not int or not 0 <= key[2] <= 2147483647):
                    raise ValueError()
                positive_id(key[3], 'room_id')
                after_key = tuple(key)
            except ProtocolError:
                raise
            except (ValueError, TypeError, UnicodeError):
                raise ProtocolError('invalid_payload', 'Invalid room list cursor.') from None
        now = fields.Datetime.now()
        candidates = []
        for room in rooms:
            preference = self._room_preference_data(member_by_id[room['membership_id']], by_member.get(room['membership_id']), now)
            if preference['archived'] != archived:
                continue
            key = (preference['pinned'], preference['pinned_at'] or '', room['last_message_id'], room['id'])
            if after_key is None or key < after_key:
                candidates.append((key, {**room, 'preferences': preference}))
        candidates.sort(key=lambda pair: pair[0], reverse=True)
        page = candidates[:30]
        while True:
            next_cursor = None
            if page and len(page) < len(candidates):
                encoded = json.dumps({'user_id': user.id, 'archived': archived, 'scope': scope,
                                      'key': page[-1][0]}, separators=(',', ':')).encode('utf-8')
                next_cursor = base64.urlsafe_b64encode(encoded).decode('ascii').rstrip('=')
            result = {'api_version': 2, 'rooms': [row for _key, row in page], 'next_cursor': next_cursor}
            if len(json.dumps(result, ensure_ascii=False).encode('utf-8')) <= 131072:
                return result
            if len(page) <= 1:
                raise ProtocolError('page_too_large', 'Room list exceeds its supported size.', 413)
            page.pop()
