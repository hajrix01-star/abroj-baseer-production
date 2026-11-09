"""Reapply Abroj settings and remove the obsolete editor-added login link."""
import base64

from lxml import etree
from odoo import SUPERUSER_ID, api
from odoo.tools import file_open


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    website = env.ref("website.default_website")
    arabic = env.ref("base.lang_ar")
    english = env.ref("base.lang_en")
    arabic.active = True
    with file_open("abroj_website/static/src/img/abroj-favicon.png", "rb") as image:
        website.with_context(image_no_postprocess=True).write({
            "favicon": base64.b64encode(image.read()),
            "language_ids": [(6, 0, [arabic.id, english.id])],
            "default_lang_id": arabic.id,
        })
    pages = env["website.page"].sudo()
    if hasattr(pages, "_sync_abroj_contact_page"):
        pages._sync_abroj_contact_page()
    pages._set_abroj_homepage_seo()

    # Website editor can persist a link inside the site's own homepage copy.
    # Only remove matching links from this website's homepage, preserving the
    # rest of the editor content and leaving Baseer's website untouched.
    home = pages.search([("url", "=", "/"), ("website_id", "=", website.id)], limit=1)
    if home:
        view = home.view_id.with_context(lang=None, no_cow=True)
        arch = view.arch_db.replace("966552210049", "966533507223").replace("0552210049", "0533507223")
        root = etree.fromstring(arch.encode())
        links = root.xpath("//a[contains(@href, 'baseer.abroj.sa/web/login')]")
        for link in links:
            link.getparent().remove(link)
        if links or arch != view.arch_db:
            view.write({"arch_db": etree.tostring(root, encoding="unicode")})
