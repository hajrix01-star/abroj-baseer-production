from odoo import api, models, tools


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    @api.model
    @tools.ormcache('frozenset(self.env.user._get_group_ids())', 'debug')
    def _baseer_native_visible_menu_ids(self, debug=False):
        """Return native Odoo menu eligibility before Baseer's app curation.

        BASSER uses this only to prove that a configured shortcut still has the
        target menu's original Odoo eligibility.  It deliberately calls
        ``super`` in the current user environment: no sudo, no context supplied
        by the browser, and no call back into the curated method below.
        """
        return super()._visible_menu_ids(debug=debug)

    @api.model
    @tools.ormcache('frozenset(self.env.user._get_group_ids())', 'debug')
    def _visible_menu_ids(self, debug=False):
        visible = self._baseer_native_visible_menu_ids(debug=debug)
        user = self.env.user
        if user.has_group('baseer_access_roles.group_owner'):
            return visible
        if user.has_group('baseer_access_roles.group_pos_cashier'):
            role_roots = ['point_of_sale.menu_point_root']
        elif user.has_group('baseer_access_roles.group_cashier'):
            role_roots = [
                'point_of_sale.menu_point_root',
                'baseer_procurement_requests.menu_procurement_root',
            ]
        elif user.has_group('baseer_access_roles.group_accountant'):
            role_roots = ['account.menu_finance', 'purchase.menu_purchase_root',
                          'sale.sale_menu_root', 'point_of_sale.menu_point_root']
        else:
            return visible

        # The workspace addon depends on this addon, never the reverse.  Once it
        # is installed, its one root becomes the curated operational surface for
        # cashier/accountant roles.  Before installation, retain the previous
        # native navigation so upgrading access roles alone cannot strand users.
        workspace_root = self.env.ref(
            'baseer_basser_workspace.menu_basser_root', raise_if_not_found=False,
        )
        if workspace_root:
            role_roots = ['baseer_basser_workspace.menu_basser_root']

        root_ids = [menu.id for xmlid in role_roots
                    if (menu := self.env.ref(xmlid, raise_if_not_found=False))]
        allowed = self.sudo().search([('id', 'child_of', root_ids)]).ids
        return frozenset(visible.intersection(allowed))
