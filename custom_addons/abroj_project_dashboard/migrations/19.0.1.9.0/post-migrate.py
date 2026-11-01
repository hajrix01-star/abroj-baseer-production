"""Rename the Odoo-side dashboard menu/action to 'أبرج داشبورد' in every language."""
from odoo import SUPERUSER_ID, api

NAME = {'ar': 'أبرج داشبورد', 'en': 'Abroj Dashboard'}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    langs = [code for code, _n in env['res.lang'].get_installed()]
    for xmlid in ('abroj_project_dashboard.menu_dashboard', 'abroj_project_dashboard.action_dashboard'):
        record = env.ref(xmlid, raise_if_not_found=False)
        if record:
            record.with_context(lang='en_US').name = NAME['ar']
            record.update_field_translations('name', {code: NAME['ar'] for code in langs})
