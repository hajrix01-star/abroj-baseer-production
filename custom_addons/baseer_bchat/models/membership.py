"""Each join is a new, non-revivable visibility epoch."""
from psycopg2.errors import UniqueViolation

from odoo import api, fields, models
from odoo.exceptions import AccessError

from .room import _GROUP_TOKEN
from ..contracts import ProtocolError


class BChatMembership(models.Model):
    _name = 'baseer.bchat.membership'
    _description = 'BChat private room membership epoch'
    _order = 'id desc'
    _check_company_auto = True

    room_id = fields.Many2one('baseer.bchat.room', required=True, readonly=True, ondelete='restrict', index=True)
    company_id = fields.Many2one('res.company', required=True, readonly=True, ondelete='restrict', index=True)
    user_id = fields.Many2one('res.users', required=True, readonly=True, ondelete='restrict', index=True)
    joined_after_message_id = fields.Integer(required=True, readonly=True, default=0)
    joined_after_group_event_id = fields.Integer(required=True, readonly=True, default=0)
    active = fields.Boolean(required=True, readonly=True, default=True)
    left_at = fields.Datetime(readonly=True)
    is_group_admin = fields.Boolean(readonly=True, default=False)
    _group_event_boundary_nonnegative = models.Constraint(
        'CHECK(joined_after_group_event_id >= 0)', 'A group audit epoch boundary cannot be negative.',
    )

    def _is_effective_group_admin(self):
        self.ensure_one()
        user = self.user_id
        rights = user._bchat_effective_permissions()
        return bool(self.active and self.is_group_admin and user.active
                    and user._is_internal() and self.room_id.company_id in user.company_ids
                    and rights['chat_view'] and rights['group_manage'])

    @api.model
    def _effective_group_admins(self, room, exclude_ids=()):
        members = self.sudo().search([
            ('room_id', '=', room.id), ('active', '=', True),
            ('is_group_admin', '=', True), ('id', 'not in', list(exclude_ids)),
        ], order='id', limit=51)
        if len(members) > 50:
            raise ProtocolError('too_many_members', 'This group exceeds its supported member limit.', 409)
        return members.filtered(lambda row: row._is_effective_group_admin())

    @api.model
    def _assert_room_capacity_for_users(self, user_ids):
        """Serialize all BChat joins for these users without changing res.users.

        A separate cursor sees commits made while waiting for the advisory
        locks, even when the caller's Odoo REPEATABLE READ snapshot is older.
        Union with the caller's view retains its own uncommitted joins.
        """
        ids = sorted(set(user_ids))
        if not ids or any(type(user_id) is not int or user_id <= 0 for user_id in ids):
            raise AccessError(self.env._('Invalid BChat member.'))
        for user_id in ids:
            self.env.cr.execute('SELECT pg_advisory_xact_lock(%s, %s)', [915731, user_id])
        query = '''
            SELECT membership.id, membership.user_id
            FROM unnest(%s::integer[]) AS users(user_id)
            CROSS JOIN LATERAL (
                SELECT id, user_id FROM baseer_bchat_membership
                WHERE user_id = users.user_id AND active
                ORDER BY id DESC LIMIT 101
            ) AS membership
        '''
        self.env.cr.execute(query, [ids])
        membership_ids = {user_id: set() for user_id in ids}
        for membership_id, user_id in self.env.cr.fetchall():
            membership_ids[user_id].add(membership_id)
        with self.env.registry.cursor() as fresh_cr:
            fresh_cr.execute(query, [ids])
            for membership_id, user_id in fresh_cr.fetchall():
                membership_ids[user_id].add(membership_id)
        if any(len(found) >= 100 for found in membership_ids.values()):
            raise ProtocolError('too_many_rooms', 'This user has reached the room limit.', 409)

    @api.model
    def _create_group_verified(self, values, token):
        rows = values if type(values) is list else [values]
        if (token is not _GROUP_TOKEN or not rows or any(
                type(row) is not dict or set(row) - {'joined_after_group_event_id'} != {
                    'room_id', 'company_id', 'user_id', 'joined_after_message_id',
                    'active', 'is_group_admin'} or row['active'] is not True
                or ('joined_after_group_event_id' in row and (
                    type(row['joined_after_group_event_id']) is not int or row['joined_after_group_event_id'] < 0))
                for row in rows)):
            raise AccessError(self.env._('A verified BChat group operation is required.'))
        return super(BChatMembership, self.sudo()).create(values)

    def _write_group_verified(self, values, token):
        if token is not _GROUP_TOKEN or set(values) not in (
                {'is_group_admin'}, {'active', 'left_at'}):
            raise AccessError(self.env._('A verified BChat group operation is required.'))
        return super(BChatMembership, self.sudo()).write(values)

    def init(self):
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS baseer_bchat_membership_active_uniq
            ON baseer_bchat_membership (room_id, user_id) WHERE active
        """)

    @api.model_create_multi
    def create(self, vals_list):
        manager = self.env['baseer.bchat.room']._require_manager()
        records = self.browse()
        with self.env.cr.savepoint():
            # A batch must not hold cursor B before it discovers recipient A
            # in a later row. Validate/lock every room first, then publish once
            # the full batch recipient union is known.
            rooms = self.env['baseer.bchat.room']
            user_ids = set()
            for vals in vals_list:
                if set(vals) != {'room_id', 'user_id'} or type(vals['room_id']) is not int or type(vals['user_id']) is not int:
                    raise AccessError(self.env._('Only a room and authorized user may be selected.'))
                room = rooms.browse(vals['room_id'])
                room.check_access('read')
                if not room.exists() or room.company_id != self.env.company or room.company_id not in manager.company_ids:
                    raise AccessError(self.env._('The room company is not authorized.'))
                rooms |= room
                user_ids.add(vals['user_id'])
            for room in rooms.sorted('id'):
                rooms._lock_for_mutation(room.id)
            if user_ids:
                self._assert_room_capacity_for_users(user_ids)
            plans = []
            for vals in vals_list:
                if set(vals) != {'room_id', 'user_id'} or type(vals['room_id']) is not int or type(vals['user_id']) is not int:
                    raise AccessError(self.env._('Only a room and authorized user may be selected.'))
                room = self.env['baseer.bchat.room'].browse(vals['room_id'])
                room.check_access('read')
                if not room.exists() or room.company_id != self.env.company or room.company_id not in manager.company_ids:
                    raise AccessError(self.env._('The room company is not authorized.'))
                user = self.env['res.users'].browse(vals['user_id'])
                user.check_access('read')
                if (not user.exists() or not user.active or not user._is_internal()
                        or room.company_id not in user.company_ids):
                    raise AccessError(self.env._('The member must be an active internal account in this company.'))
                pair = room.sudo().direct_pair_id
                if pair and user.id not in (pair.low_user_id.id, pair.high_user_id.id):
                    raise AccessError(self.env._('A direct conversation may only contain its two authorized participants.'))
                if self.sudo().search_count([('room_id', '=', room.id), ('user_id', '=', user.id), ('active', '=', True)]):
                    raise AccessError(self.env._('This user is already an active room member.'))
                if room.is_group and self.sudo().search_count([
                        ('room_id', '=', room.id), ('active', '=', True)]) >= 50:
                    raise ProtocolError('too_many_members', 'This group is full.', 409)
                self._assert_room_capacity_for_users([user.id])
                last = self.env['baseer.bchat.message'].sudo().search([('room_id', '=', room.id)], order='id desc', limit=1)
                clean = self.with_context({'allowed_company_ids': room.company_id.ids, 'lang': self.env.lang})
                try:
                    with self.env.cr.savepoint():
                        created = super(BChatMembership, clean).create({
                            'room_id': room.id, 'company_id': room.company_id.id,
                            'user_id': user.id, 'joined_after_message_id': last.id or 0,
                            'joined_after_group_event_id': self.env['baseer.bchat.service']._group_last_event_id(room),
                            'active': True,
                        })
                except UniqueViolation as error:
                    if error.diag.constraint_name != 'baseer_bchat_membership_active_uniq':
                        raise
                    raise AccessError(self.env._('This user is already an active room member.')) from None
                plans.append((room, user.id, created.id))
                records |= created
            service = self.env['baseer.bchat.service']
            for room, user_id, _member_id in plans:
                service._group_record_event(room, 'add_member', user_id, metadata={'source': 'admin'})
            service._change_lock_recipients({user_id for _room, user_id, _member_id in plans})
            for room, user_id, member_id in plans:
                service._change_publish([user_id], 'room',
                    room_id=room.id, company_id=room.company_id.id,
                    memberships={user_id: member_id})
        return records

    def action_revoke(self):
        manager = self.env['baseer.bchat.room']._require_manager()
        with self.env.cr.savepoint():
            rooms = self.env['baseer.bchat.room']
            for record in self:
                record.check_access('read')
                room = record.room_id
                if room.company_id != self.env.company or room.company_id not in manager.company_ids:
                    raise AccessError(self.env._('The room company is not authorized.'))
                rooms |= room
            for room in rooms.sorted('id'):
                rooms._lock_for_mutation(room.id)
            revoked = []
            for record in self:
                record.check_access('read')
                room = record.room_id
                if room.company_id != self.env.company or room.company_id not in manager.company_ids:
                    raise AccessError(self.env._('The room company is not authorized.'))
                record.invalidate_recordset(['active'])
                if record.active:
                    if room.is_group and record._is_effective_group_admin():
                        remaining_admins = self._effective_group_admins(room, [record.id])
                        if not remaining_admins:
                            raise AccessError(self.env._('Assign another group admin first.'))
                    super(BChatMembership, record.sudo()).write({
                        'active': False, 'left_at': fields.Datetime.now(),
                    })
                    revoked.append((room, record.user_id.id))
            service = self.env['baseer.bchat.service']
            for room, user_id in revoked:
                service._group_record_event(room, 'remove_member', user_id, metadata={'source': 'admin'})
            recipient_union = {user_id for _room, user_id in revoked}
            plans = []
            for room in rooms.filtered(lambda row: row.id in {item.id for item, _user in revoked}):
                remaining = self.sudo().search([
                    ('room_id', '=', room.id), ('active', '=', True),
                ], limit=2049)
                if len(remaining) > 2048:
                    raise AccessError(self.env._('This BChat room exceeds its member limit.'))
                recipient_union.update(remaining.mapped('user_id').ids)
                plans.append((room, remaining))
            service._change_lock_recipients(recipient_union)
            for room, user_id in revoked:
                service._change_publish([user_id], 'revoked',
                    room_id=room.id, company_id=room.company_id.id)
            for room, remaining in plans:
                service._change_publish(remaining.mapped('user_id').ids, 'room',
                    room_id=room.id, company_id=room.company_id.id,
                    memberships={row.user_id.id: row.id for row in remaining})
        return True

    def write(self, vals):
        raise AccessError(self.env._('Membership epochs cannot be edited.'))

    def unlink(self):
        raise AccessError(self.env._('Membership epochs cannot be deleted.'))

    def copy_data(self, default=None):
        raise AccessError(self.env._('Membership epochs cannot be copied.'))
