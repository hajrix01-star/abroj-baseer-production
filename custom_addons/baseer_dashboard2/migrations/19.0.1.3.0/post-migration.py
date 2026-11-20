from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['baseer.dashboard2.settings']._seed_food_purchase_accounts()
