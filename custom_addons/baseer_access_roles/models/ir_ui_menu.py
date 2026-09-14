from odoo import api, models, tools


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    @api.model
    @tools.ormcache('frozenset(self.env.user._get_group_ids())', 'debug')
    def _visible_menu_ids(self, debug=False):
        visible = super()._visible_menu_ids(debug=debug)
        user = self.env.user
        if user.has_group('baseer_access_roles.group_owner'):
            return visible
        if user.has_group('baseer_access_roles.group_cashier'):
            roots = [
                'point_of_sale.menu_point_root',
                'baseer_procurement_requests.menu_procurement_root',
            ]
            # The procurement menu is intentionally nested under Inventory.  Keep
            # that parent visible without admitting the rest of the Inventory tree.
            inventory_parent = self.env.ref('stock.menu_stock_root', raise_if_not_found=False)
        elif user.has_group('baseer_access_roles.group_accountant'):
            roots = ['account.menu_finance', 'purchase.menu_purchase_root',
                     'sale.sale_menu_root', 'point_of_sale.menu_point_root']
            inventory_parent = False
        else:
            return visible
        root_ids = [menu.id for xmlid in roots
                    if (menu := self.env.ref(xmlid, raise_if_not_found=False))]
        allowed = self.sudo().search([('id', 'child_of', root_ids)]).ids
        parent_ids = set()
        if inventory_parent:
            allowed.append(inventory_parent.id)
            # The Inventory parent carries the native stock-user menu group, which
            # a procurement cashier deliberately does not inherit.  It is only a
            # navigation container here; do not grant stock model permissions.
            parent_ids.add(inventory_parent.id)
        return frozenset(visible.intersection(allowed).union(parent_ids))
