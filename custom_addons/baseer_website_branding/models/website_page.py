from odoo import api, models


class WebsitePage(models.Model):
    _inherit = "website.page"

    _ABROJ_LEGACY_LOGO = "/abroj_website/static/src/img/abroj-logo.png"
    _ABROJ_CORE_LOGO = "/abroj_website/static/src/img/abroj-logo-core-primary-20261004.svg"

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
        arch = arch.replace(self._ABROJ_LEGACY_LOGO, self._ABROJ_CORE_LOGO)
        view.with_context(lang=None).write({"arch_db": arch})
        page.write({"view_id": view.id})

    @api.model
    def _replace_abroj_legacy_logo_sources(self):
        """Upgrade every existing Abroj contact-page view to the core logo.

        Contact pages may have been copied by Website editor before this module
        upgrade. Update the source, copied contact page, and confirmation page
        by their unique legacy asset reference without touching other brands.
        """
        views = self.env["ir.ui.view"].sudo().with_context(active_test=False).search([
            ("arch_db", "like", self._ABROJ_LEGACY_LOGO),
        ])
        for view in views:
            view.with_context(no_cow=True, lang=None).write({
                "arch_db": view.arch_db.replace(
                    self._ABROJ_LEGACY_LOGO,
                    self._ABROJ_CORE_LOGO,
                ),
            })
