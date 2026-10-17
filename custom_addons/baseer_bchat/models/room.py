"""BChat-only room administration; no mail.thread or Discuss inheritance."""
import unicodedata

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


_GROUP_TOKEN = object()


def _valid_room_name(value):
    if not isinstance(value, str) or not value.strip():
        return False
    if any(unicodedata.category(char).startswith('C') for char in value):
        return False
    try:
        return len(value.encode('utf-8')) <= 256
    except UnicodeEncodeError:
        return False


class BChatRoom(models.Model):
    _name = 'baseer.bchat.room'
    _description = 'BChat private room'
    _order = 'id desc'
    _check_company_auto = True

    name = fields.Char(required=True, size=256)
    company_id = fields.Many2one('res.company', required=True, ondelete='restrict', index=True)
    membership_ids = fields.One2many('baseer.bchat.membership', 'room_id')
    revision = fields.Integer(required=True, readonly=True, default=0)
    invoice_policy = fields.Selection([
        ('off', 'Not an invoice room'),
        ('select_on_upload', 'Choose when attaching'),
        ('invoice_default', 'Invoice by default'),
    ], required=True, default='off')
    invoice_policy_version = fields.Integer(required=True, readonly=True, default=1)
    is_group = fields.Boolean(readonly=True, default=False)
    group_creator_user_id = fields.Many2one('res.users', readonly=True, ondelete='restrict')
    group_create_uuid = fields.Char(readonly=True, size=36)
    group_create_digest = fields.Char(readonly=True, size=64)
    group_description = fields.Text(readonly=True, default='')
    # Kept in this private model, not ir.attachment or public /web/content.
    avatar_png = fields.Binary(readonly=True, attachment=False)
    avatar_version = fields.Integer(required=True, readonly=True, default=0)
    admin_recovery_required = fields.Boolean(compute='_compute_admin_recovery_required')

    @api.depends('is_group', 'membership_ids.active', 'membership_ids.is_group_admin',
                 'membership_ids.user_id.active', 'membership_ids.user_id.group_ids',
                 'membership_ids.user_id.company_ids', 'membership_ids.user_id.bchat_chat_view',
                 'membership_ids.user_id.bchat_group_manage')
    def _compute_admin_recovery_required(self):
        members = self.env['baseer.bchat.membership']
        for room in self:
            room.admin_recovery_required = bool(
                room.is_group and not members._effective_group_admins(room))

    def action_open_admin_recovery(self):
        self.ensure_one()
        manager = self._require_manager()
        self.check_access('read')
        if not self.is_group or self.company_id not in manager.company_ids:
            raise AccessError(self.env._('This group is unavailable.'))
        if self.env['baseer.bchat.membership']._effective_group_admins(self):
            raise ValidationError(self.env._('This group already has an effective administrator.'))
        return {
            'type': 'ir.actions.act_window', 'name': self.env._('Recover group administration'),
            'res_model': 'baseer.bchat.group.admin.recovery', 'view_mode': 'form',
            'target': 'new', 'context': {'default_room_id': self.id},
        }

    _group_create_unique = models.Constraint(
        'UNIQUE(group_creator_user_id, group_create_uuid)',
        'A BChat group creation UUID belongs to one operation.',
    )

    @api.model
    def _create_group_verified(self, values, token):
        required = {
                'name', 'company_id', 'is_group', 'group_creator_user_id',
                'group_create_uuid', 'group_create_digest'}
        if (token is not _GROUP_TOKEN or not required <= set(values)
                or set(values) - required - {'group_description'}
                or values['is_group'] is not True):
            raise AccessError(self.env._('A verified BChat group operation is required.'))
        return super(BChatRoom, self.sudo()).create(values)

    def _write_group_verified(self, values, token):
        if token is not _GROUP_TOKEN or set(values) not in (
                {'name'}, {'group_description'}, {'avatar_png', 'avatar_version'}):
            raise AccessError(self.env._('A verified BChat group operation is required.'))
        return super(BChatRoom, self.sudo()).write(values)

    @api.model
    def _lock_for_mutation(self, room_id):
        # Room identities never change. NO KEY UPDATE still excludes other
        # mutators and the FOR SHARE read guard, but permits the KEY SHARE
        # foreign-key check of a concurrent content-free eligibility hint.
        # FOR UPDATE would invert room -> cursor versus cursor -> room-FK.
        # Bumping revision retains Odoo's REPEATABLE READ retry boundary.
        self.env.cr.execute('SELECT id FROM baseer_bchat_room WHERE id = %s FOR NO KEY UPDATE', [room_id])
        if not self.env.cr.fetchone():
            raise AccessError(self.env._('This room is unavailable.'))
        self.env.cr.execute('UPDATE baseer_bchat_room SET revision = revision + 1 WHERE id = %s', [room_id])
        self.browse(room_id).invalidate_recordset(['revision'])

    @api.model
    def _lock_for_read(self, room_id):
        # A reader sees a concurrent writer's revision or raises 40001 for
        # Odoo's full-request retry; no writer-like update for GET traffic.
        self.env.cr.execute('SELECT id FROM baseer_bchat_room WHERE id = %s FOR SHARE', [room_id])
        if not self.env.cr.fetchone():
            raise AccessError(self.env._('This room is unavailable.'))

    @api.model
    def _require_manager(self):
        return self.env['baseer.bchat.service']._require_room_manager()

    def _publish_room_change(self):
        plans = []
        recipient_union = set()
        for room in self:
            members = self.env['baseer.bchat.membership'].sudo().search([
                ('room_id', '=', room.id), ('active', '=', True),
            ], limit=2049)
            if len(members) > 2048:
                raise AccessError(self.env._('This BChat room exceeds its member limit.'))
            plans.append((room, members))
            recipient_union.update(members.mapped('user_id').ids)
        service = self.env['baseer.bchat.service']
        service._change_lock_recipients(recipient_union)
        for room, members in plans:
            service._change_publish(
                members.mapped('user_id').ids, 'room',
                room_id=room.id, company_id=room.company_id.id,
                memberships={row.user_id.id: row.id for row in members},
            )

    @api.model_create_multi
    def create(self, vals_list):
        user = self._require_manager()
        for vals in vals_list:
            if (set(vals) not in ({'name', 'company_id'},
                                  {'name', 'company_id', 'invoice_policy'})
                    or vals.get('invoice_policy', 'off') != 'off'):
                raise AccessError(self.env._('Only a room name, company, and disabled invoice policy may be supplied.'))
            if type(vals['company_id']) is not int or vals['company_id'] not in user.company_ids.ids:
                raise AccessError(self.env._('The room company is not authorized.'))
            if vals['company_id'] != self.env.company.id:
                raise AccessError(self.env._('Select the room company as your active company.'))
            if not _valid_room_name(vals['name']):
                raise ValidationError(self.env._('A room name of at most 256 UTF-8 bytes is required.'))
        clean = self.with_context({'allowed_company_ids': self.env.company.ids, 'lang': self.env.lang})
        return super(BChatRoom, clean).create(vals_list)

    def write(self, vals):
        user = self._require_manager()
        if not set(vals) or set(vals) - {'name', 'invoice_policy'}:
            raise AccessError(self.env._('Only a room name or invoice policy may be changed.'))
        if 'name' in vals and not _valid_room_name(vals['name']):
            raise AccessError(self.env._('Only a nonempty room name may be changed.'))
        if 'invoice_policy' in vals:
            if vals['invoice_policy'] not in ('off', 'select_on_upload', 'invoice_default'):
                raise AccessError(self.env._('An invoice policy is required.'))
            if (vals['invoice_policy'] != 'off'
                    and not self.env['baseer.bchat.service']._v2_documents_enabled()):
                raise AccessError(self.env._('Invoice storage is not available.'))
        for room in self:
            room.check_access('read')
            if room.company_id not in user.company_ids or room.company_id != self.env.company:
                raise AccessError(self.env._('The room company is not authorized.'))
        old_names = {room.id: room.name for room in self}
        if 'invoice_policy' not in vals:
            result = super().write(vals)
            for room in self:
                if 'name' in vals and room.name != old_names[room.id]:
                    self.env['baseer.bchat.service']._group_record_event(
                        room, 'rename', metadata={'source': 'admin', 'name': room.name})
            self._publish_room_change()
            return result
        for room in self.sorted('id'):
            self._lock_for_mutation(room.id)
            room.invalidate_recordset(['invoice_policy', 'invoice_policy_version'])
            if room.invoice_policy != vals['invoice_policy']:
                previous_policy = room.invoice_policy
                super(BChatRoom, room).write({
                    **({'name': vals['name']} if 'name' in vals else {}),
                    'invoice_policy': vals['invoice_policy'],
                    'invoice_policy_version': room.invoice_policy_version + 1,
                })
                self.env['baseer.bchat.service']._group_record_event(room, 'invoice_policy', metadata={
                    'before': previous_policy, 'after': room.invoice_policy, 'source': 'admin'})
            elif 'name' in vals:
                super(BChatRoom, room).write({'name': vals['name']})
            if 'name' in vals and room.name != old_names[room.id]:
                self.env['baseer.bchat.service']._group_record_event(
                    room, 'rename', metadata={'source': 'admin', 'name': room.name})
        self._publish_room_change()
        return True

    def unlink(self):
        raise AccessError(self.env._('BChat rooms cannot be deleted.'))

    def copy_data(self, default=None):
        raise AccessError(self.env._('BChat rooms cannot be copied.'))
