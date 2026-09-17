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
        arch = template.with_context(lang=None).arch_db.replace(
            template.key, page.view_id.key,
        )
        page.view_id.with_context(lang=None).write({"arch_db": arch})
