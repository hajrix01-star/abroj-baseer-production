"""Bounded directory, atomic multi-add and append-only group metadata audit."""
import json

from odoo import api, fields, models
from odoo.exceptions import AccessError

from ..contracts import ProtocolError, canonical_uuid, positive_id
from .push import _notification_text
from .room import _GROUP_TOKEN


_GROUP_EVENT_TOKEN = object()
_GROUP_ACTIONS = ('create', 'add_member', 'add_members', 'remove_member', 'leave',
                  'promote_admin', 'demote_admin', 'rename', 'set_description', 'avatar', 'recover', 'invoice_policy')


class BChatGroupEvent(models.Model):
    _name = 'baseer.bchat.group.event'
    _description = 'BChat immutable group administration audit'
    _order = 'id desc'

    room_id = fields.Many2one('baseer.bchat.room', required=True, readonly=True, ondelete='restrict', index=True)
    company_id = fields.Many2one('res.company', required=True, readonly=True, ondelete='restrict', index=True)
    actor_id = fields.Many2one('res.users', required=True, readonly=True, ondelete='restrict')
    actor_membership_id = fields.Many2one('baseer.bchat.membership', readonly=True, ondelete='restrict')
    action = fields.Selection([(item, item.replace('_', ' ').title()) for item in _GROUP_ACTIONS], required=True, readonly=True)
    target_user_id = fields.Many2one('res.users', readonly=True, ondelete='restrict')
    client_uuid = fields.Char(readonly=True, size=36)
    metadata_json = fields.Text(required=True, readonly=True, default='{}')

    def init(self):
        self.env.cr.execute('''CREATE INDEX IF NOT EXISTS baseer_bchat_group_event_room_desc_idx
                               ON baseer_bchat_group_event (room_id,id DESC)''')

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError(self.env._('Group administration audit is service-owned.'))

    def write(self, vals):
        raise AccessError(self.env._('Group administration audit is immutable.'))

    def unlink(self):
        raise AccessError(self.env._('Group administration audit cannot be deleted.'))

    def copy_data(self, default=None):
        raise AccessError(self.env._('Group administration audit cannot be copied.'))

    @api.model
    def _create_verified(self, values, token):
        if token is not _GROUP_EVENT_TOKEN or set(values) != {
                'room_id', 'company_id', 'actor_id', 'actor_membership_id', 'action',
                'target_user_id', 'client_uuid', 'metadata_json'}:
            raise AccessError(self.env._('A verified group audit event is required.'))
        if len(values['metadata_json'].encode('utf-8')) > 2048:
            raise ProtocolError('audit_too_large', 'Group metadata audit exceeds its supported size.', 413)
        return super(BChatGroupEvent, self.sudo()).create(values)


class BChatGroupAuditService(models.AbstractModel):
    _inherit = 'baseer.bchat.service'

    @api.model
    def _group_last_event_id(self, room):
        return self.env['baseer.bchat.group.event'].sudo().search([
            ('room_id', '=', room.id)], order='id desc', limit=1).id or 0

    @api.model
    def _group_record_event(self, room, action, target_user_id=None, *, metadata=None,
                            actor_membership_id=None, client_uuid=None):
        actor = self._require_user()
        if not room.is_group:
            return self.env['baseer.bchat.group.event']
        if action not in _GROUP_ACTIONS:
            raise ValueError('Unknown internal group audit action')
        member = (self.env['baseer.bchat.membership'].sudo().browse(actor_membership_id)
                  if actor_membership_id else self._v2_group_member(room))
        if member and (member.user_id != actor or member.room_id != room):
            raise AccessError(self.env._('The group audit actor epoch is inconsistent.'))
        return self.env['baseer.bchat.group.event']._create_verified({
            'room_id': room.id, 'company_id': room.company_id.id, 'actor_id': actor.id,
            'actor_membership_id': member.id or False, 'action': action,
            'target_user_id': target_user_id or False, 'client_uuid': client_uuid or False,
            'metadata_json': json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True, separators=(',', ':')),
        }, _GROUP_EVENT_TOKEN)

    @api.model
    def _v2_social_member_candidates(self, company_id, query='', after_user_id=None):
        self._require_any_bchat_permission('group_create', 'group_manage', 'room_admin')
        scoped = self._company_scope(company_id)
        try:
            size = len(query.encode('utf-8')) if type(query) is str else 0
        except UnicodeError:
            raise ProtocolError('invalid_payload', 'Member search text must be UTF-8.') from None
        if (type(query) is not str or len(query) > 80 or size > 256
                or any(ord(char) < 32 for char in query)):
            raise ProtocolError('invalid_payload', 'Invalid member search text.')
        domain = [('active', '=', True), ('share', '=', False),
                  ('company_ids', 'in', [scoped.env.company.id]), ('bchat_chat_view', '=', True),
                  ('id', '!=', self.env.uid)]
        if query.strip():
            domain.append(('name', 'ilike', query.strip()))
        if after_user_id is not None:
            domain.append(('id', '>', positive_id(after_user_id, 'after_user_id')))
        found = scoped.env['res.users'].sudo().search(domain, order='id', limit=41)
        processed = list(found[:40])
        while True:
            result = {'api_version': 2, 'users': [
                {'user_id': row.id, 'name': _notification_text(row.name, 120) or 'User'}
                for row in processed if row._is_internal()
            ], 'next_after_user_id': processed[-1].id if processed and len(processed) < len(found) else None}
            if len(json.dumps(result, ensure_ascii=False).encode('utf-8')) <= 65536:
                return result
            if len(processed) <= 1:
                raise ProtocolError('page_too_large', 'Member page exceeds its supported size.', 413)
            processed.pop()

    @api.model
    def _group_manage_scope_unlocked(self, room_id, membership_id):
        user = self._require_any_bchat_permission('group_manage', 'room_admin')
        room = self.env['baseer.bchat.room'].sudo().browse(room_id).exists()
        if not room or not room.is_group or room.company_id not in user.company_ids:
            raise AccessError(self.env._('This group is unavailable.'))
        member = self._v2_group_member(room)
        if not self._v2_group_can_manage(room, member):
            raise AccessError(self.env._('Only group administrators may manage this group.'))
        if (member and membership_id != member.id) or (not member and membership_id is not None):
            raise ProtocolError('membership_changed', 'The group membership period changed.', 409)
        return room, member

    @api.model
    def _social_replay_guard(self, action, intent):
        if action == 'group_add_members':
            self._group_manage_scope_unlocked(intent['room_id'], intent['membership_id'])
            return
        return super()._social_replay_guard(action, intent)

    @api.model
    def _v2_group_add_members(self, room_id, payload):
        if (type(payload) is not dict or set(payload) != {'api_version', 'membership_id', 'client_uuid', 'user_ids'}
                or type(payload['api_version']) is not int or payload['api_version'] != 2
                or type(payload['user_ids']) is not list or not 1 <= len(payload['user_ids']) <= 49):
            raise ProtocolError('invalid_payload', 'Choose 1–49 group members.')
        room_id = positive_id(room_id, 'room_id')
        member_id = payload['membership_id']
        if member_id is not None:
            member_id = positive_id(member_id, 'membership_id')
        ids = [positive_id(value, 'user_id') for value in payload['user_ids']]
        if len(set(ids)) != len(ids):
            raise ProtocolError('invalid_payload', 'A colleague appears more than once.')
        ids.sort()
        token = canonical_uuid(payload['client_uuid'])
        self._group_manage_scope_unlocked(room_id, member_id)
        with self.env.cr.savepoint():
            digest, replay = self._social_lock_operation('group_add_members', token, {
                **payload, 'room_id': room_id, 'user_ids': ids})
            room, caller = self._v2_group_room(room_id, mutate=True, manager=True)
            if (caller and caller.id != member_id) or (not caller and member_id is not None):
                raise ProtocolError('membership_changed', 'The group membership period changed.', 409)
            if replay is not None:
                return {'api_version': 2, 'room_id': room.id, 'added_user_ids': replay['added_user_ids'],
                        'client_uuid': token, 'replayed': True}
            active = self.env['baseer.bchat.membership'].sudo().search([
                ('room_id', '=', room.id), ('active', '=', True)], limit=51)
            if len(active) + len(ids) > 50:
                raise ProtocolError('too_many_members', 'This group is full.', 409)
            if set(active.mapped('user_id').ids) & set(ids):
                raise ProtocolError('already_member', 'A selected colleague is already a member.', 409)
            users = self.env['res.users'].sudo().browse(ids).exists()
            if len(users) != len(ids) or any(not user.active or not user._is_internal()
                    or room.company_id not in user.company_ids
                    or not user._bchat_effective_permissions()['chat_view'] for user in users):
                raise AccessError(self.env._('One or more selected colleagues are unavailable.'))
            self.env['baseer.bchat.membership']._assert_room_capacity_for_users(ids)
            last = self.env['baseer.bchat.message'].sudo().search([('room_id', '=', room.id)], order='id desc', limit=1)
            boundary = self._group_last_event_id(room)
            self.env['baseer.bchat.membership']._create_group_verified([{
                'room_id': room.id, 'company_id': room.company_id.id, 'user_id': user_id,
                'joined_after_message_id': last.id or 0, 'joined_after_group_event_id': boundary,
                'active': True, 'is_group_admin': False,
            } for user_id in ids], _GROUP_TOKEN)
            self._group_record_event(room, 'add_members', metadata={'user_ids': ids},
                                     actor_membership_id=caller.id if caller else None, client_uuid=token)
            self._social_complete_operation('group_add_members', token, digest, {'added_user_ids': ids})
            room._publish_room_change()
            return {'api_version': 2, 'room_id': room.id, 'added_user_ids': ids,
                    'client_uuid': token, 'replayed': False}

    @api.model
    def _v2_group_events(self, room_id, membership_id=None, before_id=None):
        self._require_any_bchat_permission('group_manage', 'room_admin')
        if membership_id is not None:
            membership_id = positive_id(membership_id, 'membership_id')
        if before_id is not None:
            before_id = positive_id(before_id, 'before_id')
        room = self._v2_lock_room(room_id)
        room, caller = self._group_manage_scope_unlocked(room.id, membership_id)
        domain = [('room_id', '=', room.id)]
        if caller:
            domain.append(('id', '>', caller.joined_after_group_event_id))
        if before_id is not None:
            domain.append(('id', '<', before_id))
        events = self.env['baseer.bchat.group.event'].sudo()
        first = events.search([('room_id', '=', room.id)], order='id', limit=1)
        found = events.search(domain, order='id desc', limit=31)
        page = list(found[:30])
        more = len(found) > 30
        while True:
            result = {'api_version': 2, 'room_id': room.id, 'membership_id': caller.id if caller else None,
                      'audit_started_at': self._notification_stamp(first.create_date if first else None),
                      'historical_actions_backfilled': False,
                      'events': [{'id': row.id, 'action': row.action, 'actor_user_id': row.actor_id.id,
                                  'actor_membership_id': row.actor_membership_id.id or None,
                                  'target_user_id': row.target_user_id.id or None,
                                  'metadata': json.loads(row.metadata_json),
                                  'created_at': self._notification_stamp(row.create_date)} for row in page],
                      'next_before_id': page[-1].id if more and page else None}
            if len(json.dumps(result, ensure_ascii=False).encode('utf-8')) <= 65536:
                return result
            if len(page) <= 1:
                raise ProtocolError('page_too_large', 'Group audit page exceeds its supported size.', 413)
            page.pop()
            more = True
