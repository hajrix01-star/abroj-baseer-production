from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['baseer.dashboard2.settings'].search([('display_name_override', '=', 'دوحة المساكن')]).write({'display_name_override': 'دوحة المستهلك'})
    category = env.ref('baseer_dashboard2.category_utilities', raise_if_not_found=False)
    if category:
        category.with_context(lang='en_US').name = 'الكهرباء والماء'
        for lang in env['res.lang'].search([('code', 'in', ['ar', 'ar_001'])]).mapped('code'):
            category.with_context(lang=lang).name = 'الكهرباء والماء'
