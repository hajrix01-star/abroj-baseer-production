from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['abroj.contract.clause.template'].migrate_defaults()
    # Existing contracts previously read shared defaults at print time. Freeze
    # those defaults once on upgrade; never refresh snapshots on later updates.
    for model in ('project.project', 'abroj.contracting.subcontractor'):
        records = env[model].with_context(active_test=False).search([('clause_line_ids', '=', False)])
        records.action_reload_default_clauses()
