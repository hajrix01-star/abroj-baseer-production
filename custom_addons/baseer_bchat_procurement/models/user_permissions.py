"""Editable BChat capabilities backed by the existing security groups."""

from odoo import api, fields, models, Command
from odoo.exceptions import AccessError, ValidationError


ORDER_GROUP = 'baseer_bchat_procurement.group_bchat_procurement_operator'
ROOM_GROUP = 'baseer_bchat.group_bchat_manager'


class ResUsers(models.Model):
    _inherit = 'res.users'

    bchat_can_order = fields.Boolean(
        string='BChat: Send and receive purchase requests (manager/cashier)',
        compute='_compute_bchat_capabilities', inverse='_inverse_bchat_can_order',
        groups='base.group_system',
    )
    bchat_order_operator_eligible = fields.Boolean(
        compute='_compute_bchat_capabilities', groups='base.group_system',
    )
    bchat_manage_rooms = fields.Boolean(
        string='BChat: Manage rooms and members',
        compute='_compute_bchat_capabilities', inverse='_inverse_bchat_manage_rooms',
        groups='base.group_system',
    )
    bchat_room_admin_eligible = fields.Boolean(
        compute='_compute_bchat_capabilities', groups='base.group_system',
    )

    @api.depends('group_ids')
    def _compute_bchat_capabilities(self):
        order_group = self.env.ref(ORDER_GROUP)
        room_group = self.env.ref(ROOM_GROUP)
        admin = self.env.ref('base.user_admin')
        for user in self:
            eligible = ('baseer_access_role' in user._fields
                        and user.baseer_access_role in ('cashier', 'pos_cashier'))
            user.bchat_order_operator_eligible = eligible
            user.bchat_can_order = eligible and order_group in user.group_ids
            user.bchat_manage_rooms = room_group in user.group_ids and user.id == admin.id
            user.bchat_room_admin_eligible = user.id == admin.id

    def _bchat_require_permissions_admin(self):
        if self.env.su or not self.env.user.has_group('base.group_system'):
            raise AccessError(self.env._('Only an administrator can change BChat permissions.'))

    def _inverse_bchat_can_order(self):
        self._bchat_require_permissions_admin()
        group = self.env.ref(ORDER_GROUP)
        for user in self:
            if user.bchat_can_order:
                if ('baseer_access_role' not in user._fields
                        or user.baseer_access_role not in ('cashier', 'pos_cashier')):
                    raise ValidationError(self.env._('Only a branch manager or cashier can operate BChat purchasing.'))
                if group not in user.group_ids:
                    user.write({'group_ids': [Command.link(group.id)]})
            elif group in user.group_ids:
                user.write({'group_ids': [Command.unlink(group.id)]})

    def _inverse_bchat_manage_rooms(self):
        self._bchat_require_permissions_admin()
        group = self.env.ref(ROOM_GROUP)
        admin = self.env.ref('base.user_admin')
        for user in self:
            if user.bchat_manage_rooms:
                if user.id != admin.id:
                    raise AccessError(self.env._('Only the admin account may manage BChat rooms.'))
                if group not in user.group_ids:
                    user.write({'group_ids': [Command.link(group.id)]})
            elif group in user.group_ids:
                user.write({'group_ids': [Command.unlink(group.id)]})
