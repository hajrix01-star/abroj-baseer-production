"""Narrow session-bound BChat group management; never grant room ORM ACLs."""
import base64
import io

from PIL import Image, ImageOps, UnidentifiedImageError
from psycopg2.errors import UniqueViolation

from odoo import api, fields, models
from odoo.exceptions import AccessError

from .. import group_contracts
from ..contracts import ProtocolError, positive_id
from .room import _GROUP_TOKEN


class BChatGroupService(models.AbstractModel):
    _inherit = 'baseer.bchat.service'

    @api.model
    def _v2_group_member(self, room):
        return self.env['baseer.bchat.membership'].sudo().search([
            ('room_id', '=', room.id), ('user_id', '=', self.env.uid),
            ('active', '=', True),
        ], limit=1)

    @api.model
    def _v2_group_can_manage(self, room, member):
        return bool(member and member.is_group_admin) or bool(
            self.env.uid == self.env.ref('base.user_admin').id
            and self.env.user.has_group('baseer_bchat.group_bchat_manager')
        )

    @api.model
    def _v2_group_room(self, room_id, *, mutate=False, manager=False):
        room = self._v2_lock_room(room_id, mutate=mutate)
        if not room.is_group:
            raise ProtocolError('not_a_group', 'This room is not a managed group.', 409)
        member = self._v2_group_member(room)
        if manager:
            if not self._v2_group_can_manage(room, member):
                raise AccessError(self.env._('Only group admins may manage this group.'))
        elif not member:
            raise AccessError(self.env._('This group is unavailable.'))
        return room, member

    @api.model
    def _v2_group_create(self, payload):
        data = group_contracts.normalize_create(payload)
        user = self._require_user()
        company_id = data['company_id']
        if company_id not in user.company_ids.ids:
            raise AccessError(self.env._('The group company is not authorized.'))
        if not data['member_user_ids'] or user.id in data['member_user_ids']:
            raise ProtocolError('invalid_payload', 'Choose other group members.')
        digest = group_contracts.create_digest(data)
        rooms = self.env['baseer.bchat.room'].sudo()
        existing = rooms.search([
            ('group_creator_user_id', '=', user.id),
            ('group_create_uuid', '=', data['client_uuid']),
        ], limit=1)
        if existing:
            return self._v2_group_replay(existing, digest)
        selected = self.env['res.users'].sudo().browse(data['member_user_ids']).exists()
        if len(selected) != len(data['member_user_ids']) or any(
                not target.active or not target._is_internal()
                or company_id not in target.company_ids.ids for target in selected):
            raise AccessError(self.env._('Each group member must be an active colleague in this company.'))
        with self.env.cr.savepoint():
            try:
                self.env['baseer.bchat.membership']._assert_room_capacity_for_users(
                    [user.id] + data['member_user_ids'])
            except ProtocolError as error:
                if error.code != 'too_many_rooms':
                    raise
                # Another request with this UUID can finish while this one
                # waits on the per-user capacity lock. The caller's Odoo
                # REPEATABLE READ snapshot is then stale; a fresh replay must
                # win over the now-full quota, but only for the same digest.
                replay = self._v2_group_fresh_replay_if_exists(
                    user.id, company_id, data['client_uuid'], digest)
                if replay is not None:
                    return replay
                raise
            try:
                with self.env.cr.savepoint():
                    values = {
                        'name': data['name'], 'company_id': company_id,
                        'is_group': True, 'group_creator_user_id': user.id,
                        'group_create_uuid': data['client_uuid'],
                        'group_create_digest': digest,
                    }
                    if 'description' in data:
                        values['group_description'] = data['description']
                    room = rooms.with_context(allowed_company_ids=[company_id])._create_group_verified(
                        values, _GROUP_TOKEN)
            except UniqueViolation as error:
                if error.diag.constraint_name != 'baseer_bchat_room_group_create_unique':
                    raise
                replay = self._v2_group_fresh_replay_if_exists(
                    user.id, company_id, data['client_uuid'], digest)
                if replay is None:
                    raise ProtocolError('idempotency_conflict', 'Retry group creation.', 409)
                return replay
            member_model = self.env['baseer.bchat.membership'].sudo().with_context(
                allowed_company_ids=[company_id])
            members = member_model._create_group_verified([{
                'room_id': room.id, 'company_id': company_id, 'user_id': member_id,
                'joined_after_message_id': 0, 'active': True,
                'is_group_admin': member_id == user.id,
            } for member_id in [user.id] + data['member_user_ids']], _GROUP_TOKEN)
            self._change_publish(members.mapped('user_id').ids, 'room',
                                 room_id=room.id, company_id=company_id,
                                 memberships={row.user_id.id: row.id for row in members})
            own = members.filtered(lambda row: row.user_id.id == user.id)
            return {'api_version': 2, 'room_id': room.id,
                    'membership_id': own.id, 'replayed': False}

    @api.model
    def _v2_group_replay(self, room, digest):
        if not room.is_group or room.group_create_digest != digest:
            raise ProtocolError('idempotency_conflict', 'This UUID belongs to another operation.', 409)
        member = self.env['baseer.bchat.membership'].sudo().search([
            ('room_id', '=', room.id), ('user_id', '=', self.env.uid),
            ('active', '=', True),
        ], limit=1)
        if not member or room.company_id.id not in self.env.user.company_ids.ids:
            raise AccessError(self.env._('This group is unavailable.'))
        return {'api_version': 2, 'room_id': room.id,
                'membership_id': member.id, 'replayed': True}

    @api.model
    def _v2_group_fresh_replay_if_exists(self, user_id, company_id, client_uuid, digest):
        with self.env.registry.cursor() as fresh_cr:
            fresh = api.Environment(fresh_cr, user_id, {'allowed_company_ids': [company_id]})
            room = fresh['baseer.bchat.room'].sudo().search([
                ('group_creator_user_id', '=', user_id), ('group_create_uuid', '=', client_uuid),
            ], limit=1)
            if not room:
                return None
            return fresh['baseer.bchat.service']._v2_group_replay(room, digest)

    @api.model
    def _v2_group_detail(self, room_id):
        # Legacy rooms predate managed groups. Members may inspect them, but
        # the group mutation route must remain restricted to managed groups.
        room = self._v2_lock_room(room_id)
        member = self._v2_current_member(room)
        members = self.env['baseer.bchat.membership'].sudo().search([
            ('room_id', '=', room.id), ('active', '=', True),
        ], order='id', limit=51)
        if len(members) > 50:
            raise ProtocolError('too_many_members', 'This group exceeds its supported member limit.', 409)
        return {'api_version': 2,
                'room': {'id': room.id, 'company_id': room.company_id.id,
                         'name': room.name, 'description': room.group_description or '',
                         'avatar_version': room.avatar_version,
                         'is_group': bool(room.is_group)},
                'members': [{'user_id': item.user_id.id,
                             'name': item.user_id.name or '',
                             'is_admin': bool(item.is_group_admin)} for item in members],
                'can_manage': bool(room.is_group and self._v2_group_can_manage(room, member))}

    @api.model
    def _v2_group_member_candidates(self, company_id, query):
        user = self._require_user()
        company_id = positive_id(company_id, 'company_id')
        if company_id not in user.company_ids.ids:
            raise AccessError(self.env._('The company is unavailable.'))
        if type(query) is not str or len(query) > 80 or any(ord(char) < 32 for char in query):
            raise ProtocolError('invalid_payload', 'Invalid member search.')
        domain = [('active', '=', True), ('share', '=', False),
                  ('company_ids', 'in', [company_id]), ('id', '!=', user.id)]
        if query.strip():
            domain.append(('name', 'ilike', query.strip()))
        found = self.env['res.users'].sudo().search(domain, order='name,id', limit=40)
        return {'api_version': 2, 'users': [
            {'user_id': candidate.id, 'name': candidate.name or ''}
            for candidate in found if candidate._is_internal()
        ]}

    @api.model
    def _v2_group_change(self, room_id, payload):
        data = group_contracts.normalize_change(payload)
        with self.env.cr.savepoint():
            room, caller = self._v2_group_room(room_id, mutate=True,
                                                manager=data['action'] != 'leave')
            if data['action'] == 'leave' and not caller:
                raise AccessError(self.env._('This group is unavailable.'))
            if data['action'] == 'rename':
                room._write_group_verified({'name': data['name']}, _GROUP_TOKEN)
            elif data['action'] == 'set_description':
                room._write_group_verified({
                    'group_description': data['description'],
                }, _GROUP_TOKEN)
            else:
                target_id = self.env.uid if data['action'] == 'leave' else data['user_id']
                target = self.env['baseer.bchat.membership'].sudo().search([
                    ('room_id', '=', room.id), ('user_id', '=', target_id),
                    ('active', '=', True),
                ], limit=1)
                if data['action'] == 'add_member':
                    if target:
                        raise ProtocolError('already_member', 'This user is already a group member.', 409)
                    target_user = self.env['res.users'].sudo().browse(target_id).exists()
                    if (not target_user or not target_user.active or not target_user._is_internal()
                            or room.company_id not in target_user.company_ids):
                        raise AccessError(self.env._('The user is unavailable in this company.'))
                    count = self.env['baseer.bchat.membership'].sudo().search_count([
                        ('room_id', '=', room.id), ('active', '=', True),
                    ])
                    if count >= group_contracts.MAX_GROUP_MEMBERS:
                        raise ProtocolError('too_many_members', 'This group is full.', 409)
                    self.env['baseer.bchat.membership']._assert_room_capacity_for_users([target_id])
                    last = self.env['baseer.bchat.message'].sudo().search([
                        ('room_id', '=', room.id)], order='id desc', limit=1)
                    target = self.env['baseer.bchat.membership'].sudo()._create_group_verified({
                        'room_id': room.id, 'company_id': room.company_id.id,
                        'user_id': target_id, 'joined_after_message_id': last.id or 0,
                        'active': True, 'is_group_admin': False,
                    }, _GROUP_TOKEN)
                else:
                    if not target:
                        raise ProtocolError('not_a_member', 'This user is not a current group member.', 409)
                    if data['action'] in ('remove_member', 'leave', 'demote_admin') and target.is_group_admin:
                        other_admins = self.env['baseer.bchat.membership'].sudo().search_count([
                            ('room_id', '=', room.id), ('active', '=', True),
                            ('is_group_admin', '=', True), ('id', '!=', target.id),
                        ])
                        if not other_admins:
                            raise ProtocolError('last_admin', 'Assign another group admin first.', 409)
                    if data['action'] in ('remove_member', 'leave'):
                        target._write_group_verified({
                            'active': False, 'left_at': fields.Datetime.now(),
                        }, _GROUP_TOKEN)
                        self._change_publish([target_id], 'revoked',
                                             room_id=room.id, company_id=room.company_id.id)
                    elif data['action'] == 'promote_admin':
                        target._write_group_verified({'is_group_admin': True}, _GROUP_TOKEN)
                    elif data['action'] == 'demote_admin':
                        target._write_group_verified({'is_group_admin': False}, _GROUP_TOKEN)
            room._publish_room_change()
            return {'api_version': 2, 'room_id': room.id, 'action': data['action']}

    @api.model
    def _v2_group_avatar(self, room_id):
        room, _member = self._v2_group_room(room_id)
        if not room.avatar_png:
            raise ProtocolError('avatar_missing', 'This group has no image.', 404)
        return base64.b64decode(room.avatar_png), room.avatar_version

    @api.model
    def _v2_group_set_avatar(self, room_id, raw):
        if not isinstance(raw, bytes) or not raw or len(raw) > 2 * 1024 * 1024:
            raise ProtocolError('invalid_avatar', 'Group image must be at most 2 MiB.', 413)
        try:
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in ('JPEG', 'PNG', 'WEBP') or source.width * source.height > 4_000_000:
                    raise ProtocolError('invalid_avatar', 'Unsupported group image.', 415)
                source.verify()
            with Image.open(io.BytesIO(raw)) as source:
                image = ImageOps.exif_transpose(source)
                image.thumbnail((256, 256), Image.Resampling.LANCZOS)
                output = io.BytesIO()
                image.convert('RGBA').save(output, format='PNG', optimize=True)
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
            raise ProtocolError('invalid_avatar', 'Unsupported group image.', 415) from None
        encoded = output.getvalue()
        if len(encoded) > 256 * 1024:
            raise ProtocolError('invalid_avatar', 'Group image is too large.', 413)
        with self.env.cr.savepoint():
            room, _member = self._v2_group_room(room_id, mutate=True, manager=True)
            room._write_group_verified({
                'avatar_png': base64.b64encode(encoded),
                'avatar_version': room.avatar_version + 1,
            }, _GROUP_TOKEN)
            room._publish_room_change()
            return {'api_version': 2, 'room_id': room.id,
                    'avatar_version': room.avatar_version}
