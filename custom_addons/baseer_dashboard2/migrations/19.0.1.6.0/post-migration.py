from odoo import SUPERUSER_ID, api

FIRST_MENU_SEQUENCE = -100


def migrate(cr, version):
    """Make «Dashboard 2» the first main menu (the menu record is noupdate)."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    menu = env.ref('baseer_dashboard2.menu_dashboard', raise_if_not_found=False)
    if not menu:
        return
    others = env['ir.ui.menu'].with_context(active_test=False, **{'ir.ui.menu.full_list': True}).search([('parent_id', '=', False), ('id', '!=', menu.id)], order='sequence', limit=1)
    sequence = min(FIRST_MENU_SEQUENCE, others.sequence - 1) if others else FIRST_MENU_SEQUENCE
    if menu.sequence != sequence:
        menu.sequence = sequence
