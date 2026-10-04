"""Move existing website installations to the approved core vector logo."""
import base64

from odoo import SUPERUSER_ID, api
from odoo.tools import file_open


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    website = env.ref('website.default_website')
    with file_open('abroj_website/static/src/img/abroj-logo-core-primary-20261004.svg', 'rb') as image:
        website.with_context(image_no_postprocess=True).write({
            'logo': base64.b64encode(image.read()),
        })
