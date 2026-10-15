"""User-owned BChat switches; effective rights still intersect native boundaries."""

from odoo import api, fields, models, Command
from odoo.exceptions import AccessError


_CORE_SWITCHES = (
    'bchat_chat_view', 'bchat_chat_send', 'bchat_media',
    'bchat_group_create', 'bchat_group_manage',
    'bchat_task_view', 'bchat_task_manage',
)
_INVERSE_TOKEN = object()


class ResUsers(models.Model):
    _inherit = 'res.users'

    # Existing internal accounts had these BChat abilities before this version.
    # External users are never authorized by a default: _is_internal is always
    # checked at the service boundary and effective-permission computation.
    bchat_chat_view = fields.Boolean(string='View conversations',
                                     default=True, groups='base.group_system')
    bchat_chat_send = fields.Boolean(string='Send messages',
                                     default=True, groups='base.group_system')
    bchat_media = fields.Boolean(string='Send media and files',
                                 default=True, groups='base.group_system')
    bchat_group_create = fields.Boolean(string='Create groups',
                                        default=True, groups='base.group_system')
    bchat_group_manage = fields.Boolean(string='Manage assigned groups',
                                        default=True, groups='base.group_system')
    bchat_task_view = fields.Boolean(string='View tasks',
                                    default=True, groups='base.group_system')
    bchat_task_manage = fields.Boolean(string='Create and update tasks',
                                      default=True, groups='base.group_system')
    bchat_manage_rooms = fields.Boolean(
        string='Manage rooms and members',
        compute='_compute_bchat_manage_rooms', inverse='_inverse_bchat_manage_rooms',
        store=True, groups='base.group_system',
    )
    bchat_room_admin_eligible = fields.Boolean(
        compute='_compute_bchat_room_admin_eligible', groups='base.group_system',
    )
    bchat_permission_revision = fields.Integer(default=1, readonly=True,
                                               groups='base.group_system')

    @api.depends('group_ids')
    def _compute_bchat_manage_rooms(self):
        group = self.env.ref('baseer_bchat.group_bchat_manager', raise_if_not_found=False)
        admin = self.env.ref('base.user_admin', raise_if_not_found=False)
        for user in self:
            user.bchat_manage_rooms = bool(group and admin and user.id == admin.id
                                           and group in user.group_ids)

    def _compute_bchat_room_admin_eligible(self):
        admin = self.env.ref('base.user_admin', raise_if_not_found=False)
        for user in self:
            user.bchat_room_admin_eligible = bool(admin and user.id == admin.id)

    def _inverse_bchat_manage_rooms(self):
        if not self.env.su and not self.env.user.has_group('base.group_system'):
            raise AccessError(self.env._('Only an administrator can change BChat permissions.'))
        admin = self.env.ref('base.user_admin')
        group = self.env.ref('baseer_bchat.group_bchat_manager')
        for user in self:
            if user.bchat_manage_rooms and user.id != admin.id:
                raise AccessError(self.env._('Only the admin account may manage BChat rooms.'))
            if user.bchat_manage_rooms and group not in user.group_ids:
                user.with_context(_bchat_permission_internal_inverse=_INVERSE_TOKEN).write({
                    'group_ids': [Command.link(group.id)],
                })
            elif not user.bchat_manage_rooms and group in user.group_ids:
                user.with_context(_bchat_permission_internal_inverse=_INVERSE_TOKEN).write({
                    'group_ids': [Command.unlink(group.id)],
                })

    def _bchat_effective_permissions(self):
        """Read only after session identity validation; never trust client flags."""
        self.ensure_one()
        user = self.sudo()
        internal = bool(user.active and user._is_internal())
        chat_view = bool(internal and user.bchat_chat_view)
        task_view = bool(internal and user.bchat_task_view)
        admin = self.env.ref('base.user_admin', raise_if_not_found=False)
        room_group = self.env.ref('baseer_bchat.group_bchat_manager', raise_if_not_found=False)
        return {
            'version': 1,
            'revision': user.bchat_permission_revision or 1,
            'chat_view': chat_view,
            'chat_send': bool(chat_view and user.bchat_chat_send),
            'media': bool(chat_view and user.bchat_media),
            'group_create': bool(chat_view and user.bchat_group_create),
            'group_manage': bool(chat_view and user.bchat_group_manage),
            'task_view': task_view,
            'task_manage': bool(task_view and user.bchat_task_manage),
            'room_admin': bool(internal and admin and room_group
                               and user.id == admin.id and room_group in user.group_ids
                               and user.bchat_manage_rooms),
        }

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        # A newly created portal account must not display enabled BChat flags.
        # An administrator must explicitly enable switches after making it an
        # internal user; the service still rejects all external sessions.
        external = users.filtered(lambda user: not user._is_internal())
        if external:
            super(ResUsers, external).write({field: False for field in _CORE_SWITCHES})
        return users

    def write(self, vals):
        if 'bchat_permission_revision' in vals:
            raise AccessError(self.env._('BChat permission revisions are maintained by the service.'))
        if self.env.context.get('_bchat_permission_internal_inverse') is _INVERSE_TOKEN:
            return super().write(vals)
        watched = set(_CORE_SWITCHES) | {
            'bchat_manage_rooms', 'group_ids', 'company_ids', 'active',
        }
        if not (watched & set(vals)):
            return super().write(vals)
        if set(_CORE_SWITCHES + ('bchat_manage_rooms',)) & set(vals):
            if not self.env.su and not self.env.user.has_group('base.group_system'):
                raise AccessError(self.env._('Only an administrator can change BChat permissions.'))
        before = {user.id: (user._bchat_effective_permissions(),
                            tuple(sorted(user.sudo().company_ids.ids))) for user in self}
        result = super().write(vals)
        self.invalidate_recordset(list(_CORE_SWITCHES) + ['bchat_manage_rooms',
                                                          'group_ids', 'company_ids', 'active'])
        changed_ids = []
        for user in self:
            after = user._bchat_effective_permissions()
            if (before[user.id][1] != tuple(sorted(user.sudo().company_ids.ids))
                    or any(before[user.id][0][key] != after[key] for key in (
                    'chat_view', 'chat_send', 'media', 'group_create',
                    'group_manage', 'task_view', 'task_manage', 'room_admin'))):
                changed_ids.append(user.id)
        if changed_ids:
            self.env.cr.execute('''
                UPDATE res_users
                SET bchat_permission_revision = COALESCE(bchat_permission_revision, 1) + 1
                WHERE id = ANY(%s)
            ''', [changed_ids])
            self.invalidate_recordset(['bchat_permission_revision'])
            self.env['baseer.bchat.service']._change_publish(changed_ids, 'permissions')
        return result
