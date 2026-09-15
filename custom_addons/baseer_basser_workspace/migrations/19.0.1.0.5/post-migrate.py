from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Make the existing cashier batch shortcut discoverable on narrow screens.

    This only adjusts the module's seeded item.  It neither changes a native
    menu nor grants any new access to purchase batches.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    record = env.ref(
        'baseer_basser_workspace.workspace_item_cashier_purchase_batches',
        raise_if_not_found=False,
    )
    if record and record.sequence != 15:
        record.write({'sequence': 15})
