"""The BWork switch enables navigation, never native financial read rights."""
from odoo import api, fields, models
from odoo.exceptions import AccessError


class ResUsers(models.Model):
    _inherit = 'res.users'

    bwork_dashboard_view = fields.Boolean(
        string='View BWork leadership dashboard', default=False,
        groups='base.group_system',
        help='Requires the ordinary Sales, heat calendar and supplier-bill report access.',
    )

    def _bwork_effective_permissions(self):
        result = super()._bwork_effective_permissions()
        self.ensure_one()
        # Same narrowly scoped protected-switch read as BWork. No report read
        # ever uses this elevated recordset.
        user = self.sudo()
        result['dashboard_view'] = bool(
            user.active and user._is_internal() and user.bwork_dashboard_view)
        return result

    @api.model_create_multi
    def create(self, vals_list):
        if any('bwork_dashboard_view' in values for values in vals_list):
            self._bwork_check_switch_admin()
        return super().create(vals_list)

    def _bwork_check_switch_admin(self):
        if not self.env.su and not self.env.user.has_group('base.group_system'):
            raise AccessError(self.env._('Only an administrator can change BWork dashboard access.'))

    def write(self, values):
        if 'bwork_dashboard_view' not in values:
            return super().write(values)
        self._bwork_check_switch_admin()
        before = {user.id: user.bwork_dashboard_view for user in self}
        result = super().write(values)
        changed = [user.id for user in self if before[user.id] != user.bwork_dashboard_view]
        if changed:
            self.env.cr.execute('''
                UPDATE res_users
                   SET bwork_permission_revision = COALESCE(bwork_permission_revision, 1) + 1
                 WHERE id = ANY(%s)
            ''', [changed])
            self.invalidate_recordset(['bwork_permission_revision'])
            self.env['baseer.bwork.service']._change_publish(changed, 'permissions')
        return result
