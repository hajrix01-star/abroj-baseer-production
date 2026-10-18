"""Narrow application administration; never a grant to conversation contents."""
from odoo import api, fields, models
from odoo.exceptions import AccessError


_POLICY_TOKEN = object()
_PERMISSIONS = {
    'bchat_chat_view', 'bchat_chat_send', 'bchat_media', 'bchat_group_create',
    'bchat_group_manage', 'bchat_task_view', 'bchat_task_manage',
    'bchat_manage_rooms', 'bchat_permission_revision', 'bchat_mobile_admin',
}


class ResUsers(models.Model):
    _inherit = 'res.users'

    bchat_mobile_admin = fields.Boolean(
        string='Manage mobile application policy', default=False,
        groups='base.group_system',
        help='Manage direct conversation policy in allowed companies. Does not grant access to messages.',
    )

    def _bchat_effective_permissions(self):
        result = super()._bchat_effective_permissions()
        user = self.sudo()
        system_group = self.env.ref('base.group_system')
        result['mobile_admin'] = bool(user.active and user._is_internal()
                                      and (user.bchat_mobile_admin
                                           or system_group in user.group_ids))
        return result

    @api.model_create_multi
    def create(self, vals_list):
        # Validate before inherited create: field group metadata alone does not
        # protect inherited code paths which create records using elevated envs.
        if ((any(_PERMISSIONS.intersection(vals) for vals in vals_list)
             or any('default_' + key in self.env.context for key in _PERMISSIONS))
                and not self.env.su and not self.env.user.has_group('base.group_system')):
            raise AccessError(self.env._('Only a system administrator can assign BChat permissions.'))
        return super().create(vals_list)

    def write(self, vals):
        if 'bchat_mobile_admin' not in vals:
            return super().write(vals)
        if not self.env.su and not self.env.user.has_group('base.group_system'):
            raise AccessError(self.env._('Only a system administrator can assign mobile administration.'))
        before = {user.id: user.sudo().bchat_mobile_admin for user in self}
        result = super().write(vals)
        changed = [user.id for user in self if before[user.id] != user.sudo().bchat_mobile_admin]
        if changed:
            self.env.cr.execute('''
                UPDATE res_users SET bchat_permission_revision =
                    COALESCE(bchat_permission_revision, 1) + 1 WHERE id = ANY(%s)
            ''', [changed])
            self.invalidate_recordset(['bchat_permission_revision'])
            self.env['baseer.bchat.service']._change_publish(changed, 'permissions')
        return result


class ResCompany(models.Model):
    _inherit = 'res.company'

    bchat_mobile_direct_enabled = fields.Boolean(
        string='Enable mobile direct conversations', default=False,
        groups='base.group_system',
        help='Disabling preserves existing history but prevents new direct conversations and messages.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        if ((any('bchat_mobile_direct_enabled' in vals for vals in vals_list)
             or 'default_bchat_mobile_direct_enabled' in self.env.context)
                and not self.env.su and not self.env.user.has_group('base.group_system')):
            raise AccessError(self.env._('Only a system administrator can initialize mobile company policy.'))
        return super().create(vals_list)

    def _mobile_lock_policy(self, *, exclusive=False):
        self.ensure_one()
        # Lock order is company -> room -> membership/media. A toggle's UPDATE
        # conflicts with in-flight SHARE readers; a stale RR snapshot retries.
        mode = 'UPDATE' if exclusive else 'SHARE'
        self.env.cr.execute('SELECT id FROM res_company WHERE id = %s FOR ' + mode, [self.id])
        if not self.env.cr.fetchone():
            raise AccessError(self.env._('This company is unavailable.'))
        self.invalidate_recordset(['bchat_mobile_direct_enabled'])

    def _mobile_set_direct_enabled(self, enabled):
        self.ensure_one()
        service = self.env['baseer.bchat.service']
        service._mobile_company(self.id, manage=True)
        if type(enabled) is not bool:
            raise AccessError(self.env._('A boolean company policy is required.'))
        return self.with_context(_mobile_policy_token=_POLICY_TOKEN).sudo().write({
            'bchat_mobile_direct_enabled': enabled,
        })

    def write(self, vals):
        if 'bchat_mobile_direct_enabled' not in vals:
            return super().write(vals)
        trusted = self.env.context.get('_mobile_policy_token') is _POLICY_TOKEN
        if not trusted and not self.env.su and not self.env.user.has_group('base.group_system'):
            raise AccessError(self.env._('Change mobile policy through the authorized application service.'))
        if not self.env.su and any(company not in self.env.user.company_ids for company in self):
            raise AccessError(self.env._('This company is outside your allowed companies.'))
        for company in self.sorted('id'):
            company._mobile_lock_policy(exclusive=True)
        return super().write(vals)
