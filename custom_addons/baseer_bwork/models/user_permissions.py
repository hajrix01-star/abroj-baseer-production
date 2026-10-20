"""User-owned BWork switches; effective rights still intersect native boundaries."""

from odoo import api, fields, models, Command
from odoo.exceptions import AccessError


_CORE_SWITCHES = (
    'bwork_chat_view', 'bwork_chat_send', 'bwork_media',
    'bwork_group_create', 'bwork_group_manage',
    'bwork_task_view', 'bwork_task_manage',
)
_INVERSE_TOKEN = object()


class ResUsers(models.Model):
    _inherit = 'res.users'

    # Existing internal accounts had these BWork abilities before this version.
    # External users are never authorized by a default: _is_internal is always
    # checked at the service boundary and effective-permission computation.
    bwork_chat_view = fields.Boolean(string='View conversations',
                                     default=True, groups='base.group_system')
    bwork_chat_send = fields.Boolean(string='Send messages',
                                     default=True, groups='base.group_system')
    bwork_media = fields.Boolean(string='Send media and files',
                                 default=True, groups='base.group_system')
    bwork_group_create = fields.Boolean(string='Create groups',
                                        default=True, groups='base.group_system')
    bwork_group_manage = fields.Boolean(string='Manage assigned groups',
                                        default=True, groups='base.group_system')
    bwork_task_view = fields.Boolean(string='View tasks',
                                    default=True, groups='base.group_system')
    bwork_task_manage = fields.Boolean(string='Create and update tasks',
                                      default=True, groups='base.group_system')
    bwork_manage_rooms = fields.Boolean(
        string='Manage rooms and members',
        compute='_compute_bwork_manage_rooms', inverse='_inverse_bwork_manage_rooms',
        store=True, groups='base.group_system',
    )
    bwork_room_admin_eligible = fields.Boolean(
        compute='_compute_bwork_room_admin_eligible', groups='base.group_system',
    )
    bwork_permission_revision = fields.Integer(default=1, readonly=True,
                                               groups='base.group_system')

    @api.depends('group_ids')
    def _compute_bwork_manage_rooms(self):
        group = self.env.ref('baseer_bwork.group_bwork_manager', raise_if_not_found=False)
        admin = self.env.ref('base.user_admin', raise_if_not_found=False)
        for user in self:
            user.bwork_manage_rooms = bool(group and admin and user.id == admin.id
                                           and group in user.group_ids)

    def _compute_bwork_room_admin_eligible(self):
        admin = self.env.ref('base.user_admin', raise_if_not_found=False)
        for user in self:
            user.bwork_room_admin_eligible = bool(admin and user.id == admin.id)

    def _inverse_bwork_manage_rooms(self):
        if not self.env.su and not self.env.user.has_group('base.group_system'):
            raise AccessError(self.env._('Only an administrator can change BWork permissions.'))
        admin = self.env.ref('base.user_admin')
        group = self.env.ref('baseer_bwork.group_bwork_manager')
        for user in self:
            if user.bwork_manage_rooms and user.id != admin.id:
                raise AccessError(self.env._('Only the admin account may manage BWork rooms.'))
            if user.bwork_manage_rooms and group not in user.group_ids:
                user.with_context(_bwork_permission_internal_inverse=_INVERSE_TOKEN).write({
                    'group_ids': [Command.link(group.id)],
                })
            elif not user.bwork_manage_rooms and group in user.group_ids:
                user.with_context(_bwork_permission_internal_inverse=_INVERSE_TOKEN).write({
                    'group_ids': [Command.unlink(group.id)],
                })

    def _bwork_effective_permissions(self):
        """Read only after session identity validation; never trust client flags."""
        self.ensure_one()
        user = self.sudo()
        internal = bool(user.active and user._is_internal())
        chat_view = bool(internal and user.bwork_chat_view)
        task_view = bool(internal and user.bwork_task_view)
        admin = self.env.ref('base.user_admin', raise_if_not_found=False)
        room_group = self.env.ref('baseer_bwork.group_bwork_manager', raise_if_not_found=False)
        return {
            'version': 1,
            'revision': user.bwork_permission_revision or 1,
            'chat_view': chat_view,
            'chat_send': bool(chat_view and user.bwork_chat_send),
            'media': bool(chat_view and user.bwork_media),
            'group_create': bool(chat_view and user.bwork_group_create),
            'group_manage': bool(chat_view and user.bwork_group_manage),
            'task_view': task_view,
            'task_manage': bool(task_view and user.bwork_task_manage),
            'room_admin': bool(internal and admin and room_group
                               and user.id == admin.id and room_group in user.group_ids
                               and user.bwork_manage_rooms),
        }

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        # A newly created portal account must not display enabled BWork flags.
        # An administrator must explicitly enable switches after making it an
        # internal user; the service still rejects all external sessions.
        external = users.filtered(lambda user: not user._is_internal())
        if external:
            super(ResUsers, external).write({field: False for field in _CORE_SWITCHES})
        return users

    def write(self, vals):
        if 'bwork_permission_revision' in vals:
            raise AccessError(self.env._('BWork permission revisions are maintained by the service.'))
        if self.env.context.get('_bwork_permission_internal_inverse') is _INVERSE_TOKEN:
            return super().write(vals)
        watched = set(_CORE_SWITCHES) | {
            'bwork_manage_rooms', 'group_ids', 'company_ids', 'active',
        }
        if not (watched & set(vals)):
            return super().write(vals)
        if set(_CORE_SWITCHES + ('bwork_manage_rooms',)) & set(vals):
            if not self.env.su and not self.env.user.has_group('base.group_system'):
                raise AccessError(self.env._('Only an administrator can change BWork permissions.'))
        before = {user.id: (user._bwork_effective_permissions(),
                            tuple(sorted(user.sudo().company_ids.ids))) for user in self}
        result = super().write(vals)
        self.invalidate_recordset(list(_CORE_SWITCHES) + ['bwork_manage_rooms',
                                                          'group_ids', 'company_ids', 'active'])
        changed_ids = []
        for user in self:
            after = user._bwork_effective_permissions()
            if (before[user.id][1] != tuple(sorted(user.sudo().company_ids.ids))
                    or any(before[user.id][0][key] != after[key] for key in (
                    'chat_view', 'chat_send', 'media', 'group_create',
                    'group_manage', 'task_view', 'task_manage', 'room_admin'))):
                changed_ids.append(user.id)
        if changed_ids:
            self.env.cr.execute('''
                UPDATE res_users
                SET bwork_permission_revision = COALESCE(bwork_permission_revision, 1) + 1
                WHERE id = ANY(%s)
            ''', [changed_ids])
            self.invalidate_recordset(['bwork_permission_revision'])
            self.env['baseer.bwork.service']._change_publish(changed_ids, 'permissions')
        return result
