from odoo import api, models


class WebsitePage(models.Model):
    _inherit = "website.page"

    @api.model
    def _set_abroj_homepage_seo(self):
        """Set Abroj's homepage metadata on its page/view, not ``website``.

        Odoo 19 stores website SEO fields on ``ir.ui.view``. ``website.page``
        delegates to that view and a website-context write creates an
        Abroj-specific homepage through Odoo's copy-on-write mechanism.
        """
        website = self.env["website"].sudo().search([
            ("domain", "=", "https://abroj.sa"),
        ], limit=1)
        if not website:
            return

        homepage = self.sudo().search([
            ("url", "=", "/"),
            ("website_id", "=", website.id),
        ], limit=1)
        if not homepage:
            homepage = self.sudo().search([
                ("url", "=", "/"),
                ("website_id", "=", False),
            ], limit=1)
        if not homepage:
            return

        homepage.with_context(website_id=website.id).write({
            "website_meta_title": "أبرج | تنفيذ مشاريع تجارية في المنطقة الشرقية",
            "website_meta_description": (
                "أبرج للإنشاءات المتكاملة لتنفيذ وتجهيز المشاريع التجارية "
                "في الخبر والدمام والمناطق المحيطة. راجع نطاق مشروعك "
                "واطلب عرض سعر."
            ),
            "website_meta_keywords": (
                "أبرج للإنشاءات، تنفيذ مشاريع، تشطيب تجاري، تشطيب مقاهي، "
                "تشطيب مطاعم، تشطيب مكاتب، تشطيب محلات، الخبر، الدمام"
            ),
        })
