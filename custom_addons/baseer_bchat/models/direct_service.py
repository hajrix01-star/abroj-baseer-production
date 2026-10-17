"""New company-scoped direct pairs, never inferred from or merged into legacy."""
from psycopg2.errors import UniqueViolation

from odoo import api, fields, models
from odoo.exceptions import AccessError

from ..contracts import ProtocolError, canonical_uuid, positive_id
from .membership import BChatMembership
from .push import _notification_text
from .room import BChatRoom, _valid_room_name


_DIRECT_TOKEN = object()


class BChatDirectPair(models.Model):
    _name = 'baseer.bchat.direct.pair'
    _description = 'BChat private canonical direct pair'
    _rec_name = 'room_id'

    company_id = fields.Many2one('res.company', required=True, readonly=True, ondelete='restrict', index=True)
    low_user_id = fields.Many2one('res.users', required=True, readonly=True, ondelete='restrict')
    high_user_id = fields.Many2one('res.users', required=True, readonly=True, ondelete='restrict')
    room_id = fields.Many2one('baseer.bchat.room', required=True, readonly=True, ondelete='restrict', index=True)

    _company_pair_unique = models.Constraint('UNIQUE(company_id,low_user_id,high_user_id)', 'One company direct pair has one room.')
    _room_unique = models.Constraint('UNIQUE(room_id)', 'A direct room belongs to one pair.')
    _canonical_order = models.Constraint('CHECK(low_user_id < high_user_id)', 'A direct pair has two different canonical users.')

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError(self.env._('Direct BChat pairs are service-owned.'))

    def write(self, vals):
        raise AccessError(self.env._('Direct BChat pairs are immutable.'))

    def unlink(self):
        raise AccessError(self.env._('Direct BChat pairs cannot be deleted.'))

    def copy_data(self, default=None):
        raise AccessError(self.env._('Direct BChat pairs cannot be copied.'))

    @api.model
    def _create_verified(self, values, token):
        if token is not _DIRECT_TOKEN or set(values) != {'company_id', 'low_user_id', 'high_user_id', 'room_id'}:
            raise AccessError(self.env._('A verified direct pair is required.'))
        room = self.env['baseer.bchat.room'].sudo().browse(values['room_id'])
        if room.is_group or room.company_id.id != values['company_id']:
            raise AccessError(self.env._('A direct pair must use its own company room.'))
        return super(BChatDirectPair, self.sudo()).create(values)


class BChatDirectRoom(models.Model):
    _inherit = 'baseer.bchat.room'

    direct_pair_id = fields.Many2one('baseer.bchat.direct.pair', readonly=True, ondelete='restrict')

    @api.model
    def _create_direct_verified(self, values, token):
        if (token is not _DIRECT_TOKEN or set(values) != {'name', 'company_id'}
                or not _valid_room_name(values['name'])):
            raise AccessError(self.env._('A verified direct room is required.'))
        return super(BChatRoom, self.sudo()).create({**values, 'is_group': False})

    def _link_direct_pair_verified(self, pair, token):
        self.ensure_one()
        if token is not _DIRECT_TOKEN or pair.room_id != self or self.direct_pair_id:
            raise AccessError(self.env._('A verified direct pair link is required.'))
        return super(BChatRoom, self.sudo()).write({'direct_pair_id': pair.id})


class BChatDirectMembership(models.Model):
    _inherit = 'baseer.bchat.membership'

    @api.model
    def _create_direct_verified(self, room, pair, token):
        if token is not _DIRECT_TOKEN or pair.room_id != room or room.direct_pair_id != pair or room.is_group:
            raise AccessError(self.env._('A verified direct membership is required.'))
        if self.sudo().search_count([('room_id', '=', room.id)]):
            raise AccessError(self.env._('Direct membership already exists.'))
        return super(BChatMembership, self.sudo()).create([{
            'room_id': room.id, 'company_id': pair.company_id.id, 'user_id': user_id,
            'joined_after_message_id': 0, 'active': True, 'is_group_admin': False,
        } for user_id in (pair.low_user_id.id, pair.high_user_id.id)])


class BChatDirectService(models.AbstractModel):
    _inherit = 'baseer.bchat.service'

    @api.model
    def _v2_social_rooms(self, archived=False, cursor=None):
        result = super()._v2_social_rooms(archived, cursor)
        pairs = self.env['baseer.bchat.direct.pair'].sudo().search([
            ('room_id', 'in', [row['id'] for row in result['rooms']]),
            '|', ('low_user_id', '=', self.env.uid), ('high_user_id', '=', self.env.uid),
        ], limit=30)
        by_room = {pair.room_id.id: pair for pair in pairs}
        for row in result['rooms']:
            pair = by_room.get(row['id'])
            row['is_direct'] = bool(pair)
            if pair:
                peer = pair.high_user_id if pair.low_user_id.id == self.env.uid else pair.low_user_id
                row['peer'] = {'user_id': peer.id, 'name': _notification_text(peer.name, 120) or 'User'}
                row['name'] = row['peer']['name']
        # Parent already bounded the page; add at most 30 bounded labels.
        # If those labels cross the ceiling, reject rather than silently
        # dropping a row whose cursor the parent has already advanced past.
        import json
        if len(json.dumps(result, ensure_ascii=False).encode('utf-8')) > 131072:
            raise ProtocolError('page_too_large', 'Room list exceeds its supported size.', 413)
        return result

    @api.model
    def _direct_scope(self, company_id, peer_id):
        user = self._require_bchat_permission('group_create')
        self._require_bchat_permission('chat_send')
        scoped = self._company_scope(company_id)
        peer_id = positive_id(peer_id, 'peer_user_id')
        if peer_id == user.id:
            raise ProtocolError('invalid_payload', 'Choose another authorized colleague.')
        peer = scoped.env['res.users'].sudo().browse(peer_id).exists()
        if (not peer or not peer.active or not peer._is_internal()
                or scoped.env.company not in peer.company_ids
                or not peer._bchat_effective_permissions()['chat_view']):
            raise AccessError(self.env._('This direct conversation is unavailable.'))
        return scoped, peer

    @api.model
    def _direct_pair(self, company_id, peer_id):
        low, high = sorted([self.env.uid, peer_id])
        return self.env['baseer.bchat.direct.pair'].sudo().search([
            ('company_id', '=', company_id), ('low_user_id', '=', low), ('high_user_id', '=', high),
        ], limit=1)

    @api.model
    def _direct_existing_data(self, pair, peer):
        room = self._v2_lock_room(pair.room_id.id)
        if room.is_group or room.direct_pair_id != pair:
            raise AccessError(self.env._('This direct conversation is unavailable.'))
        members = self.env['baseer.bchat.membership'].sudo().search([
            ('room_id', '=', room.id), ('active', '=', True),
        ], limit=3)
        if len(members) != 2 or set(members.mapped('user_id').ids) != {pair.low_user_id.id, pair.high_user_id.id}:
            raise ProtocolError('direct_unavailable', 'This direct conversation requires explicit membership recovery.', 409)
        member = members.filtered(lambda row: row.user_id.id == self.env.uid)
        if not member:
            raise AccessError(self.env._('This direct conversation is unavailable.'))
        return {'api_version': 2, 'room_id': room.id, 'membership_id': member.id, 'created': False,
                'peer': {'user_id': peer.id, 'name': _notification_text(peer.name, 120) or 'User'}}

    @api.model
    def _direct_fresh_pair(self, company_id, peer_id):
        with self.env.registry.cursor() as cursor:
            low, high = sorted([self.env.uid, peer_id])
            cursor.execute('''SELECT id FROM baseer_bchat_direct_pair
                              WHERE company_id = %s AND low_user_id = %s AND high_user_id = %s''',
                           [company_id, low, high])
            if not cursor.fetchone():
                # An uncommitted fixture user cannot own a committed pair.
                return None
            fresh = api.Environment(cursor, self.env.uid, {'allowed_company_ids': [company_id]})
            service, peer = fresh['baseer.bchat.service']._direct_scope(company_id, peer_id)
            pair = service._direct_pair(company_id, peer_id)
            return service._direct_existing_data(pair, peer) if pair else None

    @api.model
    def _social_replay_guard(self, action, intent):
        if action == 'direct_room':
            service, peer = self._direct_scope(intent['company_id'], intent['peer_user_id'])
            pair = service._direct_pair(intent['company_id'], peer.id)
            if not pair:
                raise AccessError(self.env._('This direct conversation is unavailable.'))
            service._direct_existing_data(pair, peer)
            return
        return super()._social_replay_guard(action, intent)

    @api.model
    def _v2_direct_room(self, payload):
        if (type(payload) is not dict or set(payload) != {'api_version', 'company_id', 'peer_user_id', 'client_uuid'}
                or type(payload['api_version']) is not int or payload['api_version'] != 2):
            raise ProtocolError('invalid_payload', 'Invalid direct conversation fields.')
        company_id = positive_id(payload['company_id'], 'company_id')
        token = canonical_uuid(payload['client_uuid'])
        scoped, peer = self._direct_scope(company_id, payload['peer_user_id'])
        low, high = sorted([self.env.uid, peer.id])
        with self.env.cr.savepoint():
            digest, replay = scoped._social_lock_operation('direct_room', token, payload)
            self.env.cr.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))',
                                ['bchat-direct:%s:%s:%s' % (company_id, low, high)])
            pair = scoped._direct_pair(company_id, peer.id)
            result = scoped._direct_existing_data(pair, peer) if pair else scoped._direct_fresh_pair(company_id, peer.id)
            if result is None:
                if replay is not None:
                    raise AccessError(self.env._('This direct conversation is unavailable.'))
                memberships = scoped.env['baseer.bchat.membership']
                memberships._assert_room_capacity_for_users([low, high])
                name = ' / '.join(_notification_text(user.name, 120) or 'User' for user in
                                  scoped.env['res.users'].sudo().browse([low, high]))
                name = name.encode('utf-8')[:256].decode('utf-8', 'ignore')
                try:
                    with self.env.cr.savepoint():
                        room = scoped.env['baseer.bchat.room']._create_direct_verified({
                            'name': name, 'company_id': company_id,
                        }, _DIRECT_TOKEN)
                        pair = scoped.env['baseer.bchat.direct.pair']._create_verified({
                            'company_id': company_id, 'low_user_id': low, 'high_user_id': high, 'room_id': room.id,
                        }, _DIRECT_TOKEN)
                        room._link_direct_pair_verified(pair, _DIRECT_TOKEN)
                        joined = memberships._create_direct_verified(room, pair, _DIRECT_TOKEN)
                        scoped._change_publish([low, high], 'room', room_id=room.id, company_id=company_id,
                                               memberships={row.user_id.id: row.id for row in joined})
                        member = joined.filtered(lambda row: row.user_id.id == self.env.uid)
                        result = {'api_version': 2, 'room_id': room.id, 'membership_id': member.id, 'created': True,
                                  'peer': {'user_id': peer.id, 'name': _notification_text(peer.name, 120) or 'User'}}
                except UniqueViolation as error:
                    if error.diag.constraint_name != 'baseer_bchat_direct_pair_company_pair_unique':
                        raise
                    result = scoped._direct_fresh_pair(company_id, peer.id)
                    if result is None:
                        raise ProtocolError('retry', 'Retry the same direct conversation intent.', 409) from None
            if replay is None:
                scoped._social_complete_operation('direct_room', token, digest,
                                                  {'room_id': result['room_id'], 'membership_id': result['membership_id']})
            return {**result, 'client_uuid': token, 'replayed': replay is not None}
