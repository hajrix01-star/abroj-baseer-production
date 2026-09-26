def uninstall_hook(env):
    """Restore the dependency-owned menu before Odoo removes our root."""
    menu = env.ref('baseer_pos_print_bridge.menu_baseer_direct_print',
                   raise_if_not_found=False)
    parent = env.ref('point_of_sale.menu_point_config_product',
                     raise_if_not_found=False)
    if menu:
        menu.with_context(lang='en_US').write({
            'parent_id': parent.id if parent else False,
            'name': 'Direct printing',
        })
        # The suite supplied an Arabic label; do not leave it behind on uninstall.
        if env['res.lang'].search_count([('code', '=', 'ar_001'), ('active', '=', True)]):
            menu.with_context(lang='ar_001').write({'name': 'الطباعة المباشرة'})
