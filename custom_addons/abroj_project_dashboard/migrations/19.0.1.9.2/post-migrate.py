from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['abroj.contracting.voucher'].abroj_backfill_advance_budget_lines()
