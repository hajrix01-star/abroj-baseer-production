from odoo import SUPERUSER_ID, api
from odoo.addons.abroj_contracting.backfill import install_backfill_enabled, run_analytic_backfill


def migrate(cr, version):
    """Bill->project linking and draft analytics touch protected accounting
    tables; run only when explicitly enabled, otherwise via the post-deploy
    ops/production/abroj-analytic-backfill step."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    if install_backfill_enabled(env):
        run_analytic_backfill(env)
