"""Replace the retired Abroj contact-page logo after module upgrades."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["website.page"]._replace_abroj_legacy_logo_sources()
