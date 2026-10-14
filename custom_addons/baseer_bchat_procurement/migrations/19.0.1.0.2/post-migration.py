"""Seed independent order rights from the previously effective role/group grant.

The marker matters because a second invocation must never restore a right an
administrator deliberately revoked after the first successful migration.
"""

from odoo import api, SUPERUSER_ID


MARKER = 'baseer_bchat_procurement.order_permissions_seed_19_0_1_0_2'
ELIGIBLE_ROLES = ('owner', 'cashier', 'pos_cashier')


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    settings = env['ir.config_parameter'].sudo()
    if settings.get_param(MARKER) == 'done':
        return
    Users = env['res.users'].sudo().with_context(active_test=False)
    if 'baseer_access_role' not in Users._fields:
        raise RuntimeError('Baseer access roles must be installed before migrating BChat order permissions.')
    operator = env.ref('baseer_bchat_procurement.group_bchat_procurement_operator')
    for user in Users.search([('share', '=', False)]):
        role = user.baseer_access_role
        if role not in ELIGIBLE_ROLES:
            continue
        values = {'bchat_order_view': True}
        # The legacy owner was a viewer even when this technical group was
        # present; do not silently promote that account during migration.
        if role != 'owner' and operator in user.group_ids:
            values.update({'bchat_order_create': True, 'bchat_order_receive': True})
        user.write(values)
    settings.set_param(MARKER, 'done')
