"""Stored, independently revocable BChat procurement permissions."""

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


ORDER_FIELDS = frozenset({'bchat_order_view', 'bchat_order_create', 'bchat_order_receive'})
ORDER_ROLES = ('owner', 'cashier', 'pos_cashier')
ORDER_EFFECTIVE_INPUTS = ORDER_FIELDS | {'baseer_access_role', 'company_ids',
                                         'group_ids', 'active'}


class ResUsers(models.Model):
    _inherit = 'res.users'

    bchat_order_view = fields.Boolean(
        string='View purchase requests', groups='base.group_system', copy=False,
        default=False,
    )
    bchat_order_create = fields.Boolean(
        string='Create and send purchase requests', groups='base.group_system',
        copy=False, default=False,
    )
    bchat_order_receive = fields.Boolean(
        string='Confirm purchase receipt', groups='base.group_system',
        copy=False, default=False,
    )
    # One-release compatibility field. The legacy group is no longer authority.
    bchat_can_order = fields.Boolean(
        string='BChat: Legacy order operator', compute='_compute_bchat_order_legacy',
        groups='base.group_system',
    )
    bchat_order_operator_eligible = fields.Boolean(
        compute='_compute_bchat_order_legacy', groups='base.group_system',
    )

    @api.depends('bchat_order_view', 'bchat_order_create', 'bchat_order_receive')
    def _compute_bchat_order_legacy(self):
        for user in self:
            eligible = ('baseer_access_role' in user._fields
                        and user.baseer_access_role in ORDER_ROLES)
            user.bchat_order_operator_eligible = eligible
            user.bchat_can_order = bool(eligible and user.bchat_order_view
                                        and user.bchat_order_create
                                        and user.bchat_order_receive)

    @api.constrains('bchat_order_view', 'bchat_order_create', 'bchat_order_receive')
    def _check_bchat_order_dependencies(self):
        for user in self:
            if not user.bchat_order_view and (user.bchat_order_create or user.bchat_order_receive):
                raise ValidationError(self.env._(
                    'Enable BChat order viewing before granting creation or receipt confirmation.'
                ))

    @api.onchange('bchat_order_view')
    def _onchange_bchat_order_view(self):
        if not self.bchat_order_view:
            self.bchat_order_create = False
            self.bchat_order_receive = False

    @api.model
    def _bchat_require_order_permissions_admin(self):
        if not self.env.su and not self.env.user.has_group('base.group_system'):
            raise AccessError(self.env._('Only an administrator can change BChat permissions.'))

    def _bchat_order_effective_signature(self):
        self.ensure_one()
        user = self.sudo()
        view = bool(user.active and user._is_internal() and user.bchat_order_view)
        eligible = ('baseer_access_role' in user._fields
                    and user.baseer_access_role in ORDER_ROLES)
        return (
            view,
            bool(view and eligible and user.bchat_order_create),
            bool(view and eligible and user.bchat_order_receive),
            tuple(sorted(user.company_ids.ids)) if view else (),
        )

    @api.model_create_multi
    def create(self, vals_list):
        if any(ORDER_FIELDS.intersection(vals) for vals in vals_list):
            self._bchat_require_order_permissions_admin()
        return super().create(vals_list)

    def write(self, vals):
        changed_fields = ORDER_FIELDS.intersection(vals)
        if not (ORDER_EFFECTIVE_INPUTS.intersection(vals)):
            return super().write(vals)
        if changed_fields:
            self._bchat_require_order_permissions_admin()
        before = {user.id: user._bchat_order_effective_signature() for user in self}
        result = super().write(vals)
        self.invalidate_recordset(list(ORDER_EFFECTIVE_INPUTS & set(self._fields)))
        changed_ids = [user.id for user in self if
                       before[user.id] != user._bchat_order_effective_signature()]
        if changed_ids:
            self.env.cr.execute('''
                UPDATE res_users
                SET bchat_permission_revision = COALESCE(bchat_permission_revision, 1) + 1
                WHERE id = ANY(%s)
            ''', [changed_ids])
            self.invalidate_recordset(['bchat_permission_revision'])
            self.env['baseer.bchat.service']._change_publish(changed_ids, 'permissions')
        return result
