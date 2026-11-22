from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Hide only the two seeded workspace shortcuts; preserve all batch records."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    for xmlid in (
        'baseer_basser_workspace.workspace_item_cashier_purchase_batches',
        'baseer_basser_workspace.workspace_item_accountant_purchase_batches',
    ):
        item = env.ref(xmlid, raise_if_not_found=False)
        if item and item.active:
            item.write({'active': False})
