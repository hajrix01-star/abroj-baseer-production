"""Apply homepage SEO metadata during upgrades from the rolled-back release."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["website.page"]._set_abroj_homepage_seo()
