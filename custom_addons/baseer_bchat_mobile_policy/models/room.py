"""Explicit direct-room identity; legacy non-group rooms stay untouched."""
from odoo import api, fields, models
from odoo.exceptions import AccessError
from odoo.addons.baseer_bchat.models.room import BChatRoom as LegacyRoom
from odoo.addons.baseer_bchat.models.membership import BChatMembership as LegacyMembership


_DIRECT_TOKEN = object()


class BChatRoom(models.Model):
    _inherit = 'baseer.bchat.room'

    mobile_direct = fields.Boolean(default=False, readonly=True, index=True)
    mobile_direct_low_user_id = fields.Many2one('res.users', readonly=True, ondelete='restrict')
    mobile_direct_high_user_id = fields.Many2one('res.users', readonly=True, ondelete='restrict')

    _mobile_direct_pair_unique = models.Constraint(
        'UNIQUE(company_id, mobile_direct_low_user_id, mobile_direct_high_user_id)',
        'One direct conversation exists per company and user pair.',
    )
    _mobile_direct_shape = models.Constraint(
        '''CHECK((NOT mobile_direct AND mobile_direct_low_user_id IS NULL
                  AND mobile_direct_high_user_id IS NULL)
                 OR (mobile_direct AND NOT is_group
                     AND mobile_direct_low_user_id IS NOT NULL
                     AND mobile_direct_high_user_id IS NOT NULL
                     AND mobile_direct_low_user_id < mobile_direct_high_user_id))''',
        'Direct conversations require exactly two ordered users and cannot be groups.',
    )

    @api.model
    def _create_mobile_direct_verified(self, values, token):
        if token is not _DIRECT_TOKEN or set(values) != {
                'name', 'company_id', 'mobile_direct',
                'mobile_direct_low_user_id', 'mobile_direct_high_user_id'} or values['mobile_direct'] is not True:
            raise AccessError(self.env._('A verified direct-conversation operation is required.'))
        # The service validates identity, company, both users and policy first.
        # Bypass only the legacy room-manager create path, as its group-token
        # helper does; the private Python token cannot be supplied over RPC.
        return super(LegacyRoom, self.sudo()).create(values)

    def write(self, vals):
        if self.sudo().filtered('mobile_direct'):
            raise AccessError(self.env._('Direct conversation metadata is immutable.'))
        return super().write(vals)

    def _write_group_verified(self, values, token):
        if self.sudo().filtered('mobile_direct'):
            raise AccessError(self.env._('A direct conversation cannot be edited as a group.'))
        return super()._write_group_verified(values, token)


class BChatMembership(models.Model):
    _inherit = 'baseer.bchat.membership'

    @api.model
    def _create_mobile_direct_verified(self, room, token):
        if token is not _DIRECT_TOKEN or not room.mobile_direct:
            raise AccessError(self.env._('A verified direct-conversation operation is required.'))
        return super(LegacyMembership, self.sudo()).create([{
            'room_id': room.id, 'company_id': room.company_id.id, 'user_id': user_id,
            'joined_after_message_id': 0, 'active': True, 'is_group_admin': False,
        } for user_id in [room.mobile_direct_low_user_id.id, room.mobile_direct_high_user_id.id]])

    @api.model_create_multi
    def create(self, vals_list):
        rooms = self.env['baseer.bchat.room'].sudo().browse([
            vals.get('room_id') for vals in vals_list if type(vals.get('room_id')) is int])
        if rooms.filtered('mobile_direct'):
            raise AccessError(self.env._('Direct conversation members are fixed.'))
        return super().create(vals_list)

    @api.model
    def _create_group_verified(self, values, token):
        rows = values if type(values) is list else [values]
        rooms = self.env['baseer.bchat.room'].sudo().browse([
            row.get('room_id') for row in rows if type(row) is dict and type(row.get('room_id')) is int])
        if rooms.filtered('mobile_direct'):
            raise AccessError(self.env._('Direct conversation members are fixed.'))
        return super()._create_group_verified(values, token)

    def _write_group_verified(self, values, token):
        if self.sudo().mapped('room_id').filtered('mobile_direct'):
            raise AccessError(self.env._('Direct conversation members are fixed.'))
        return super()._write_group_verified(values, token)

    def action_revoke(self):
        if self.sudo().mapped('room_id').filtered('mobile_direct'):
            raise AccessError(self.env._('Direct conversation members are fixed.'))
        return super().action_revoke()
