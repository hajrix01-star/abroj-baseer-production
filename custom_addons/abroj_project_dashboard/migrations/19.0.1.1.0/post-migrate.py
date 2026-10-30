from odoo.addons.abroj_project_dashboard.hooks import backfill_duration


def migrate(cr, version):
    backfill_duration(cr)
