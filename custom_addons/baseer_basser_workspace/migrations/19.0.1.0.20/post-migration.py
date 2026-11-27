from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Retire the two seeded legacy PCUST Petty Cash shortcuts.

    Their menus are already hidden and legacy Petty Cash is read-only. Only the
    two seeded items are deactivated; no section, menu, or custody record changes.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    for xmlid in (
        'baseer_basser_workspace.workspace_item_accountant_procurement_custody',
        'baseer_basser_workspace.workspace_item_accountant_monthly_custody_reconciliation',
    ):
        item = env.ref(xmlid, raise_if_not_found=False)
        if item and item.active:
            item.write({'active': False})
