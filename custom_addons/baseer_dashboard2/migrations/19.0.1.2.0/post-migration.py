from odoo import api, SUPERUSER_ID

from odoo.addons.baseer_dashboard2.models.configuration import APP_BALANCE_START_DATE


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    settings = env['baseer.dashboard2.settings'].search([
        ('company_id', 'in', [1, 2, 3]),
        '|', ('app_balance_start_date', '=', False), ('app_balance_start_date', '=', '2026-10-01'),
    ])
    settings.write({'app_balance_start_date': APP_BALANCE_START_DATE})
