from odoo import api, models


class WebsitePage(models.Model):
    _inherit = "website.page"

    @api.model
    def _set_abroj_homepage_seo(self):
        """Set translated metadata on Abroj's own home and contact pages."""
        website = self.env.ref("website.default_website", raise_if_not_found=False)
        if not website or website.domain != "https://abroj.sa":
            return

        metadata = {
            "/": {
                "en_US": {
                    "website_meta_title": "Abroj | Commercial Fit-Out in Al Khobar",
                    "website_meta_description": "Abroj Integrated Construction — café, restaurant, retail and office fit-outs in Al Khobar & Dammam since 2018. Request a quote.",
                    "website_meta_keywords": "Abroj, commercial fit-out, cafe, restaurant, retail, office, Al Khobar, Dammam",
                },
                "ar": {
                    "website_meta_title": "أبرج | تنفيذ وتجهيز مشاريع تجارية في الخبر",
                    "website_meta_description": "مؤسسة أبرج للمقاولات — تنفيذ وتجهيز المقاهي والمطاعم والمحلات والمكاتب في الخبر والدمام منذ 2018. اطلب عرض سعر.",
                    "website_meta_keywords": "أبرج، مقاولات، تجهيز تجاري، مقاهي، مطاعم، محلات، مكاتب، الخبر، الدمام",
                },
            },
            "/contactus": {
                "en_US": {
                    "website_meta_title": "Contact Abroj | Request a Fit-Out Quote in Al Khobar",
                    "website_meta_description": "Contact Abroj for café, restaurant, retail and office fit-outs in Al Khobar and Dammam. Serving commercial projects since 2018.",
                    "website_meta_keywords": "contact Abroj, fit-out quote, Al Khobar, Dammam, commercial contracting",
                },
                "ar": {
                    "website_meta_title": "تواصل مع أبرج | اطلب عرض سعر لتجهيز مشروعك في الخبر",
                    "website_meta_description": "تواصل مع أبرج لتنفيذ وتجهيز المقاهي والمطاعم والمحلات والمكاتب في الخبر والدمام. نخدم المشاريع التجارية منذ 2018.",
                    "website_meta_keywords": "تواصل مع أبرج، عرض سعر، تجهيز تجاري، مقاولات، الخبر، الدمام",
                },
            },
        }
        for url, translations in metadata.items():
            pages = self.sudo()
            page = pages.search([("url", "=", url), ("website_id", "=", website.id)], limit=1)
            if not page:
                page = pages.search([("url", "=", url), ("website_id", "=", False)], limit=1)
            if not page:
                continue
            # The first write creates a website-specific copy when needed.
            page.with_context(website_id=website.id, lang="en_US").write(translations["en_US"])
            page = pages.search([("url", "=", url), ("website_id", "=", website.id)], limit=1) or page
            page.with_context(website_id=website.id, lang=self.env.ref("base.lang_ar").code).write(translations["ar"])
