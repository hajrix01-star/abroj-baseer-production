from odoo import api, models


class WebsitePage(models.Model):
    _inherit = "website.page"

    @api.model
    def _sync_abroj_contact_page(self):
        """Replace only Abroj's website-specific legacy contact page.

        Website editor copies a page view per site; an inheritance on the
        generic contact template cannot affect that copied view.
        """
        website = self.env["website"].sudo().search([
            ("domain", "=", "https://abroj.sa"),
        ], limit=1)
        if not website:
            return
        page = self.sudo().search([
            ("website_id", "=", website.id),
            ("url", "=", "/contactus"),
        ], limit=1)
        if not page:
            return
        template = self.env.ref(
            "baseer_website_branding.abroj_contactus_page",
            raise_if_not_found=False,
        )
        if not template:
            return
        key = f"{page.view_id.key}.abroj_contact"
        view = self.env["ir.ui.view"].sudo().search([
            ("key", "=", key),
            ("website_id", "=", website.id),
        ], limit=1)
        if not view:
            view = template.copy({
                "website_id": website.id,
                "key": key,
                "name": "Abroj contact page",
            })
        arch = template.with_context(lang=None).arch_db.replace(template.key, key)
        view.with_context(lang=None).write({"arch_db": arch})
        page.write({"view_id": view.id})
