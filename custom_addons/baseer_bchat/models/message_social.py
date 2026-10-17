"""Private, service-owned metadata; immutable business messages stay untouched.

No public ACL or administrative view is intentional. The caller's current
message/room/epoch authorization precedes every privileged projection read.
"""
import json

from odoo import api, fields, models
from odoo.exceptions import AccessError
from odoo.tools import SQL

from .. import social_contracts, v2_contracts
from ..contracts import ProtocolError, positive_id


_MESSAGE_SOCIAL_TOKEN = object()


class BChatMessageProjection(models.AbstractModel):
    _name = 'baseer.bchat.message.projection.private'
    _description = 'BChat private message projection boundary'

    message_id = fields.Many2one('baseer.bchat.message', required=True, readonly=True, ondelete='restrict')
    room_id = fields.Many2one('baseer.bchat.room', required=True, readonly=True, ondelete='restrict')
    company_id = fields.Many2one('res.company', required=True, readonly=True, ondelete='restrict')

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError(self.env._('Private message metadata is service-owned.'))

    def write(self, values):
        raise AccessError(self.env._('Private message metadata is service-owned.'))

    def unlink(self):
        raise AccessError(self.env._('Private message metadata cannot be deleted directly.'))

    def copy_data(self, default=None):
        raise AccessError(self.env._('Private message metadata cannot be copied.'))

    @api.model
    def _create_verified(self, values, token):
        rows = values if type(values) is list else [values]
        if (token is not _MESSAGE_SOCIAL_TOKEN or not rows
                or any(type(row) is not dict or set(row) != self._social_create_fields for row in rows)):
            raise AccessError(self.env._('A verified message metadata operation is required.'))
        return super(BChatMessageProjection, self.sudo()).create(values)

    def _write_verified(self, values, token):
        self.ensure_one()
        if (token is not _MESSAGE_SOCIAL_TOKEN or not values
                or set(values) != self._social_write_fields):
            raise AccessError(self.env._('A verified message metadata operation is required.'))
        return super(BChatMessageProjection, self.sudo()).write(values)


class BChatMessageReaction(models.Model):
    _name = 'baseer.bchat.message.reaction'
    _inherit = 'baseer.bchat.message.projection.private'
    _description = 'BChat private message reaction'

    actor_id = fields.Many2one('res.users', required=True, readonly=True, ondelete='restrict')
    membership_id = fields.Many2one('baseer.bchat.membership', required=True, readonly=True, ondelete='restrict')
    emoji = fields.Selection([(value, value) for value in social_contracts.EMOJIS], readonly=True)
    active = fields.Boolean(default=True, readonly=True)
    revision = fields.Integer(required=True, readonly=True, default=1)
    _social_create_fields = {'message_id', 'room_id', 'company_id', 'actor_id', 'membership_id', 'emoji', 'active', 'revision'}
    _social_write_fields = {'emoji', 'active', 'revision'}
    _actor_message_epoch_unique = models.Constraint('UNIQUE(message_id,actor_id,membership_id)', 'One reaction per message and personal epoch.')
    _revision_positive = models.Constraint('CHECK(revision>0)', 'A reaction revision must be positive.')
    _active_shape = models.Constraint('CHECK(NOT active OR emoji IS NOT NULL)', 'An active reaction needs an emoji.')

    def init(self):
        self.env.cr.execute('CREATE INDEX IF NOT EXISTS baseer_bchat_reaction_message_active_idx '
                            'ON baseer_bchat_message_reaction(message_id,active)')


class BChatMessageSaved(models.Model):
    _name = 'baseer.bchat.message.saved'
    _inherit = 'baseer.bchat.message.projection.private'
    _description = 'BChat private saved-message reference'
    _order = 'id desc'

    user_id = fields.Many2one('res.users', required=True, readonly=True, ondelete='restrict')
    membership_id = fields.Many2one('baseer.bchat.membership', required=True, readonly=True, ondelete='restrict')
    active = fields.Boolean(default=True, readonly=True)
    revision = fields.Integer(required=True, readonly=True, default=1)
    saved_at = fields.Datetime(readonly=True)
    _social_create_fields = {'message_id', 'room_id', 'company_id', 'user_id', 'membership_id', 'active', 'revision', 'saved_at'}
    _social_write_fields = {'active', 'revision', 'saved_at'}
    _user_message_epoch_unique = models.Constraint('UNIQUE(user_id,message_id,membership_id)', 'One private saved reference per message epoch.')
    _revision_positive = models.Constraint('CHECK(revision>0)', 'A saved-reference revision must be positive.')

    def init(self):
        self.env.cr.execute('CREATE INDEX IF NOT EXISTS baseer_bchat_saved_user_active_id_idx '
                            'ON baseer_bchat_message_saved(user_id,active,id DESC)')


class BChatMessageMention(models.Model):
    _name = 'baseer.bchat.message.mention'
    _inherit = 'baseer.bchat.message.projection.private'
    _description = 'BChat immutable explicit message mention'

    recipient_user_id = fields.Many2one('res.users', required=True, readonly=True, ondelete='restrict')
    recipient_membership_id = fields.Many2one('baseer.bchat.membership', required=True, readonly=True, ondelete='restrict')
    _social_create_fields = {'message_id', 'room_id', 'company_id', 'recipient_user_id', 'recipient_membership_id'}
    _social_write_fields = frozenset()
    _message_epoch_unique = models.Constraint('UNIQUE(message_id,recipient_membership_id)', 'One explicit mention per recipient epoch.')

    def init(self):
        self.env.cr.execute('CREATE INDEX IF NOT EXISTS baseer_bchat_mention_recipient_message_idx '
                            'ON baseer_bchat_message_mention(recipient_membership_id,message_id DESC)')


class BChatMessageSocialService(models.AbstractModel):
    _inherit = 'baseer.bchat.service'

    @api.model
    def _social_message_scope(self, room_id, membership_id, message_id=None, *, mutate=False, fresh=False):
        user = self._require_bchat_permission('chat_view')
        room_id = positive_id(room_id, 'room_id')
        if fresh:
            # A fresh replay cursor must not wait on this request's own room lock.
            room = self.env['baseer.bchat.room'].sudo().browse(room_id).exists()
            if not room or room.company_id not in user.company_ids:
                raise AccessError(self.env._('This message is unavailable.'))
        else:
            room = self._v2_lock_room(room_id, mutate=mutate)
        member = self._v2_current_member(room)
        if member.id != positive_id(membership_id, 'membership_id'):
            raise ProtocolError('membership_changed', 'The membership period changed.', 409)
        message = None
        if message_id is not None:
            message = self.env['baseer.bchat.message'].sudo().browse(positive_id(message_id, 'message_id')).exists()
            if (not message or message.room_id != room or message.company_id != room.company_id
                    or message.id <= member.joined_after_message_id):
                raise AccessError(self.env._('This message is unavailable.'))
        return room, member, message

    @api.model
    def _social_replay_guard(self, action, intent):
        if action in ('message_reaction', 'message_saved'):
            self._require_bchat_permission('chat_send' if action == 'message_reaction' else 'chat_view')
            self._social_message_scope(intent['room_id'], intent['membership_id'], intent['message_id'], fresh=True)
            return
        return super()._social_replay_guard(action, intent)

    @api.model
    def _social_projection_rows(self, messages, members_by_room):
        """One bounded projection batch; no person-name directory or originals."""
        ids = messages.ids
        if not ids:
            return []
        if len(ids) > 30:
            raise ProtocolError('invalid_payload', 'Social metadata exceeds its page bound.')
        reactions = self.env['baseer.bchat.message.reaction'].sudo().with_context(active_test=False)
        saved = self.env['baseer.bchat.message.saved'].sudo().with_context(active_test=False)
        mentions = self.env['baseer.bchat.message.mention']
        reactions.flush_model()
        saved.flush_model()
        mentions.flush_model()
        users = self.env['res.users']
        users.flush_model(['active', 'share', 'bchat_chat_view', 'company_ids'])
        self.env['baseer.bchat.membership'].flush_model(['active'])
        company_field = users._fields['company_ids']
        # Identifiers come only from Odoo's installed field definition.
        eligible = SQL('''u.active AND NOT u.share AND u.bchat_chat_view AND m.active
            AND m.user_id=u.id AND m.room_id=r.room_id AND m.company_id=r.company_id
            AND r.message_id>m.joined_after_message_id
            AND EXISTS(SELECT 1 FROM %s AS c WHERE c.%s=u.id AND c.%s=r.company_id)''',
            SQL.identifier(company_field.relation), SQL.identifier(company_field.column1), SQL.identifier(company_field.column2))
        self.env.cr.execute(SQL('''SELECT r.message_id,r.emoji,COUNT(*)
            FROM baseer_bchat_message_reaction r
            JOIN baseer_bchat_membership m ON m.id=r.membership_id
            JOIN res_users u ON u.id=r.actor_id
            WHERE r.message_id=ANY(%s) AND r.active AND %s
            GROUP BY r.message_id,r.emoji''', ids, eligible))
        counts = {}
        for message_id, emoji, count in self.env.cr.fetchall():
            counts.setdefault(message_id, {})[emoji] = count
        member_ids = [row.id for row in members_by_room.values()]
        own = {row.message_id.id: row for row in reactions.search([
            ('message_id', 'in', ids), ('actor_id', '=', self.env.uid), ('membership_id', 'in', member_ids)], limit=30)}
        own_saved = {row.message_id.id: row for row in saved.search([
            ('message_id', 'in', ids), ('user_id', '=', self.env.uid), ('membership_id', 'in', member_ids)], limit=30)}
        self.env.cr.execute(SQL('''SELECT r.message_id,r.recipient_user_id
            FROM baseer_bchat_message_mention r
            JOIN baseer_bchat_membership m ON m.id=r.recipient_membership_id
            JOIN res_users u ON u.id=r.recipient_user_id
            WHERE r.message_id=ANY(%s) AND %s ORDER BY r.message_id,r.recipient_user_id''', ids, eligible))
        mentioned = {}
        for message_id, user_id in self.env.cr.fetchall():
            mentioned.setdefault(message_id, []).append(user_id)
        rows = []
        for message in messages:
            reaction, reference = own.get(message.id), own_saved.get(message.id)
            rows.append({'message_id': message.id,
                'reaction_counts': [{'emoji': emoji, 'count': counts[message.id][emoji]}
                                    for emoji in social_contracts.EMOJIS if emoji in counts.get(message.id, {})],
                'own_reaction': reaction.emoji if reaction and reaction.active else None,
                'reaction_revision': reaction.revision if reaction else 0,
                'saved': bool(reference and reference.active), 'saved_revision': reference.revision if reference else 0,
                'mention_user_ids': mentioned.get(message.id, [])})
        return rows

    @api.model
    def _v2_social_metadata(self, room_id, membership_id, message_ids):
        ids = social_contracts.message_ids(message_ids)
        room, member, _message = self._social_message_scope(room_id, membership_id)
        messages = self.env['baseer.bchat.message'].sudo().browse(ids).exists()
        if len(messages) != len(ids) or any(message.room_id != room or message.company_id != room.company_id
                or message.id <= member.joined_after_message_id for message in messages):
            raise AccessError(self.env._('This message metadata is unavailable.'))
        result = {'api_version': 2, 'social_contract_version': 1, 'message_edit_policy': 'immutable',
                  'room_id': room.id, 'membership_id': member.id,
                  'rows': self._social_projection_rows(messages, {room.id: member})}
        if len(json.dumps(result, ensure_ascii=False).encode('utf-8')) > 65536:
            raise ProtocolError('page_too_large', 'Social metadata exceeds its supported byte bound.', 413)
        return result

    @api.model
    def _message_social_mutation(self, room_id, message_id, payload, value_key):
        data = social_contracts.mutation(payload, value_key)
        room_id, message_id = positive_id(room_id, 'room_id'), positive_id(message_id, 'message_id')
        action = 'message_reaction' if value_key == 'emoji' else 'message_saved'
        self._require_bchat_permission('chat_send' if value_key == 'emoji' else 'chat_view')
        intent = {'room_id': room_id, 'message_id': message_id, **data}
        with self.env.cr.savepoint():
            digest, replay = self._social_lock_operation(action, data['client_uuid'], intent)
            room, member, message = self._social_message_scope(room_id, data['membership_id'], message_id, mutate=True)
            model = self.env['baseer.bchat.message.reaction' if value_key == 'emoji' else 'baseer.bchat.message.saved']
            user_field = 'actor_id' if value_key == 'emoji' else 'user_id'
            row = model.sudo().with_context(active_test=False).search([
                ('message_id', '=', message.id), ('membership_id', '=', member.id), (user_field, '=', self.env.uid)], limit=1)
            revision = row.revision if row else 0
            if replay is None:
                if revision != data['expected_revision']:
                    raise ProtocolError('revision_conflict', 'Personal message metadata changed; refresh it.', 409)
                if value_key == 'emoji':
                    values = {'emoji': data['emoji'], 'active': data['emoji'] is not None, 'revision': revision + 1}
                else:
                    values = {'active': data['saved'], 'revision': revision + 1,
                              'saved_at': fields.Datetime.now() if data['saved'] else (row.saved_at if row else None)}
                if row:
                    row._write_verified(values, _MESSAGE_SOCIAL_TOKEN)
                else:
                    row = model._create_verified({'message_id': message.id, 'room_id': room.id,
                        'company_id': room.company_id.id, 'membership_id': member.id,
                        user_field: self.env.uid, **values}, _MESSAGE_SOCIAL_TOKEN)
                self._social_complete_operation(action, data['client_uuid'], digest,
                    {'room_id': room.id, 'membership_id': member.id, 'message_id': message.id, 'revision': row.revision})
                if value_key == 'emoji':
                    members = self.env['baseer.bchat.membership'].sudo().search([
                        ('room_id', '=', room.id), ('active', '=', True)], order='user_id', limit=2049)
                    if len(members) > 2048:
                        raise ProtocolError('too_many_members', 'This room exceeds its supported member limit.', 409)
                else:
                    members = member
                self._change_publish(members.mapped('user_id').ids, 'room', room_id=room.id,
                    company_id=room.company_id.id, memberships={item.user_id.id: item.id for item in members})
            projection = self._social_projection_rows(message, {room.id: member})[0]
            return {'api_version': 2, 'social_contract_version': 1, 'message_edit_policy': 'immutable',
                    'room_id': room.id, 'membership_id': member.id, 'client_uuid': data['client_uuid'],
                    'replayed': replay is not None, 'operation_revision': replay['revision'] if replay is not None else row.revision,
                    **projection}

    @api.model
    def _v2_message_reaction(self, room_id, message_id, payload):
        return self._message_social_mutation(room_id, message_id, payload, 'emoji')

    @api.model
    def _v2_message_saved(self, room_id, message_id, payload):
        return self._message_social_mutation(room_id, message_id, payload, 'saved')

    @api.model
    def _v2_social_send(self, room_id, payload):
        self._require_bchat_permission('chat_send')
        return self._v2_send_normalized(room_id, v2_contracts.normalize_social_send(payload))

    @api.model
    def _v2_send_metadata_scope(self, room, member, normalized):
        inherited = super()._v2_send_metadata_scope(room, member, normalized)
        ids = normalized.get('mention_user_ids')
        if not ids:
            return inherited
        targets = self.env['baseer.bchat.membership'].sudo().search([
            ('room_id', '=', room.id), ('user_id', 'in', ids), ('active', '=', True)], limit=50)
        if len(targets) != len(ids) or any(not row.user_id.active or not row.user_id._is_internal()
                or room.company_id not in row.user_id.company_ids
                or not row.user_id._bchat_effective_permissions()['chat_view'] for row in targets):
            raise AccessError(self.env._('Mention recipients must be current eligible room members.'))
        return targets

    @api.model
    def _v2_create_send_metadata(self, room, member, message, normalized, metadata):
        super()._v2_create_send_metadata(room, member, message, normalized, metadata)
        if normalized.get('mention_user_ids'):
            self.env['baseer.bchat.message.mention']._create_verified([{
                'message_id': message.id, 'room_id': room.id, 'company_id': room.company_id.id,
                'recipient_user_id': target.user_id.id, 'recipient_membership_id': target.id,
            } for target in metadata], _MESSAGE_SOCIAL_TOKEN)

    @api.model
    def _v2_saved_messages(self, before_id=None):
        user = self._require_bchat_permission('chat_view')
        if before_id is not None:
            before_id = positive_id(before_id, 'before_id')
        self.env['baseer.bchat.message.saved'].flush_model()
        self.env['baseer.bchat.membership'].flush_model(['active'])
        query = '''SELECT s.id,s.message_id,s.membership_id,s.room_id,s.saved_at
            FROM baseer_bchat_message_saved s
            JOIN baseer_bchat_membership m ON m.id=s.membership_id AND m.active
                AND m.user_id=s.user_id AND m.room_id=s.room_id AND m.company_id=s.company_id
            JOIN baseer_bchat_message msg ON msg.id=s.message_id AND msg.room_id=s.room_id
                AND msg.company_id=s.company_id AND msg.id>m.joined_after_message_id
            JOIN baseer_bchat_room r ON r.id=s.room_id AND r.company_id=s.company_id
            WHERE s.user_id=%s AND s.active AND s.company_id=ANY(%s)'''
        parameters = [user.id, user.company_ids.ids]
        if before_id is not None:
            query += ' AND s.id<%s'
            parameters.append(before_id)
        query += ' ORDER BY s.id DESC LIMIT 31'
        self.env.cr.execute(query, parameters)
        candidates = self.env.cr.fetchall()
        for room_id in sorted({row[3] for row in candidates}):
            self.env['baseer.bchat.room']._lock_for_read(room_id)
        self.env.cr.execute(query, parameters)
        candidates = self.env.cr.fetchall()
        page, more = candidates[:30], len(candidates) > 30
        messages = self.env['baseer.bchat.message'].sudo().browse([row[1] for row in page])
        members = self.env['baseer.bchat.membership'].sudo().browse(list({row[2] for row in page}))
        by_room = {member.room_id.id: member for member in members}
        reply_ids = messages.mapped('reply_to_message_id').ids
        parents = self.env['baseer.bchat.message'].sudo().browse(reply_ids).filtered(
            lambda message: message.room_id.id in by_room
            and message.company_id == by_room[message.room_id.id].company_id
            and message.id > by_room[message.room_id.id].joined_after_message_id)
        names = self._v2_author_names(list(messages) + list(parents))
        canonical = self._v2_history_payload(list(messages), False, names,
            {parent.id: parent for parent in parents})['messages']
        social = self._social_projection_rows(messages, by_room)
        by_message = {message['id']: message for message in canonical}
        by_social = {row['message_id']: row for row in social}
        while True:
            result = {'api_version': 2, 'social_contract_version': 1, 'message_edit_policy': 'immutable',
                'saved': [{'id': row[0], 'saved_at': fields.Datetime.to_string(row[4]) if row[4] else None,
                           'room_id': row[3], 'membership_id': row[2], 'message': by_message[row[1]],
                           'social': by_social[row[1]]} for row in page],
                'next_before_id': page[-1][0] if page and more else None}
            if len(json.dumps(result, ensure_ascii=False).encode('utf-8')) <= 131072:
                return result
            if len(page) <= 1:
                raise ProtocolError('page_too_large', 'Saved messages exceed their supported byte bound.', 413)
            page.pop()
            more = True
