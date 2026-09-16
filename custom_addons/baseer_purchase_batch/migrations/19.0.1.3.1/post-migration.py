"""Retire batch category entry surfaces, retaining referenced business data."""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for xmlid in (
        'baseer_purchase_batch.view_partner_purchase_batch_defaults',
        'baseer_purchase_batch.menu_purchase_category_maps',
    ):
        record = env.ref(xmlid, raise_if_not_found=False)
        if record:
            record.unlink()
