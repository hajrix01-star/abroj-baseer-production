"""User-owned BChat switches; effective rights still intersect native boundaries."""

import logging

from odoo import api, fields, models, Command
from odoo.exceptions import AccessError


_CORE_SWITCHES = (
    'bchat_chat_view', 'bchat_chat_send', 'bchat_media',
    'bchat_media_view', 'bchat_media_download',
    'bchat_group_create', 'bchat_group_manage',
    'bchat_task_view', 'bchat_task_manage',
)
_INVERSE_TOKEN = object()
_LOGGER = logging.getLogger(__name__)


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
    bchat_media_view = fields.Boolean(string='View media previews',
                                      default=True, groups='base.group_system')
    bchat_media_download = fields.Boolean(string='Download original media',
                                          default=True, groups='base.group_system')
    bchat_media_rights_migrated = fields.Boolean(default=False, readonly=True, copy=False,
                                                groups='base.group_system')
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
        media_view = bool(chat_view and user.bchat_media_view)
        media_upload = bool(media_view and user.bchat_media)
        media_download = bool(media_view and user.bchat_media_download)
        admin = self.env.ref('base.user_admin', raise_if_not_found=False)
        room_group = self.env.ref('baseer_bchat.group_bchat_manager', raise_if_not_found=False)
        return {
            'version': 1,
            'revision': user.bchat_permission_revision or 1,
            'chat_view': chat_view,
            'chat_send': bool(chat_view and user.bchat_chat_send),
            # v87 has one switch. Never advertise a broader combined ability
            # to it when the new independent controls have been restricted.
            'media': bool(media_view and media_upload and media_download),
            'media_view': media_view,
            'media_upload': media_upload,
            'media_download': media_download,
            'group_create': bool(chat_view and user.bchat_group_create and user.bchat_group_manage),
            'group_manage': bool(chat_view and user.bchat_group_manage),
            'task_view': task_view,
            'task_manage': bool(task_view and user.bchat_task_manage),
            'room_admin': bool(internal and admin and room_group
                               and user.id == admin.id and room_group in user.group_ids
                               and user.bchat_manage_rooms),
        }

    @api.model_create_multi
    def create(self, vals_list):
        prepared = []
        for vals in vals_list:
            if 'bchat_media_rights_migrated' in vals:
                raise AccessError(self.env._('BChat media migration markers are maintained by the service.'))
            values = dict(vals)
            if 'bchat_media' in values:
                # An explicitly supplied legacy switch already passes the
                # native field-group ACL. Ordinary user creation need not
                # inject additional administrator-only fields into vals.
                values.setdefault('bchat_media_view', values['bchat_media'])
                values.setdefault('bchat_media_download', values['bchat_media'])
            prepared.append(values)
        users = super().create(prepared)
        # This internal upgrade marker conveys no business permission and
        # must not require broader user-create privileges from the caller.
        self.env.cr.execute('''
            UPDATE res_users SET bchat_media_rights_migrated = TRUE WHERE id = ANY(%s)
        ''', [users.ids])
        users.invalidate_recordset(['bchat_media_rights_migrated'])
        # A newly created portal account must not display enabled BChat flags.
        # An administrator must explicitly enable switches after making it an
        # internal user; the service still rejects all external sessions.
        external = users.filtered(lambda user: not user._is_internal())
        if external:
            super(ResUsers, external).write({field: False for field in _CORE_SWITCHES})
        return users

    def write(self, vals):
        if {'bchat_permission_revision', 'bchat_media_rights_migrated'} & set(vals):
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
                    'chat_view', 'chat_send', 'media', 'media_view',
                    'media_upload', 'media_download', 'group_create',
                    'group_manage', 'task_view', 'task_manage', 'room_admin'))):
                changed_ids.append(user.id)
        if changed_ids:
            self.env.cr.execute('''
                UPDATE res_users
                SET bchat_permission_revision = COALESCE(bchat_permission_revision, 1) + 1
                WHERE id = ANY(%s)
            ''', [changed_ids])
            self.invalidate_recordset(['bchat_permission_revision'])
            # Reserve every peer cursor before the first permissions hint.
            # Otherwise B's own hint followed by room [A,B] in one request
            # can deadlock with A's request doing the inverse.
            plans = self._bchat_eligibility_change_plans(changed_ids)
            recipient_union = set(changed_ids)
            for plan in plans:
                recipient_union.update(plan['user_ids'])
            service = self.env['baseer.bchat.service']
            service._change_lock_recipients(recipient_union)
            service._change_publish(changed_ids, 'permissions')
            for plan in plans:
                service._change_publish(plan['user_ids'], 'room',
                                        room_id=plan['room_id'], company_id=plan['company_id'],
                                        memberships=plan['memberships'])
        return result

    def _bchat_eligibility_change_plans(self, user_ids):
        """Collect peer refreshes without taking cursor locks or publishing hints.

        Normal accounts have at most 100 active rooms. Keep this notification
        path bounded even for a legacy import, and never prevent HR offboarding
        merely because an imported account exceeds that product limit.
        """
        memberships = self.env['baseer.bchat.membership'].sudo()
        room_ids = set()
        for user_id in sorted(set(user_ids)):
            rows = memberships.search([('user_id', '=', user_id), ('active', '=', True)],
                                      order='room_id', limit=101)
            if len(rows) > 100:
                _LOGGER.warning('BChat eligibility hints exceed room limit for user %s', user_id)
            room_ids.update(rows[:100].mapped('room_id').ids)
        plans = []
        for room_id in sorted(room_ids):
            members = memberships.search([('room_id', '=', room_id), ('active', '=', True)],
                                         order='user_id', limit=2049)
            if len(members) > 2048:
                _LOGGER.warning('BChat eligibility hints exceed member limit for room %s', room_id)
            members = members[:2048]
            room = members[:1].room_id
            if room:
                plans.append({'user_ids': members.mapped('user_id').ids,
                              'room_id': room.id, 'company_id': room.company_id.id,
                              'memberships': {row.user_id.id: row.id for row in members}})
        return plans
