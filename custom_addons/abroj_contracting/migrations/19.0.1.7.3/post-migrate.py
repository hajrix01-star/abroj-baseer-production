from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Refresh derived summaries only; preserve vouchers and journal entries."""
    env = api.Environment(cr, SUPERUSER_ID, {'active_test': False})
    projects = env['project.project'].search([])
    for batch in projects.grouped('company_id').values():
        batch._compute_totals()
