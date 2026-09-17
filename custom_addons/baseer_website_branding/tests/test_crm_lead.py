from types import SimpleNamespace

from odoo.tests.common import TransactionCase


class BaseerWebsiteBrandingLeadCase(TransactionCase):
    def test_public_form_cannot_assign_team_or_user(self):
        website = self.env.ref("website.default_website")
        values = {"team_id": 999999, "user_id": 999998}

        filtered = self.env["crm.lead"].website_form_input_filter(
            SimpleNamespace(website=website), values,
        )

        self.assertNotEqual(filtered.get("team_id"), 999999)
        self.assertNotEqual(filtered.get("user_id"), 999998)

    def test_sync_replaces_a_website_specific_contact_copy(self):
        website = self.env.ref("website.default_website")
        original_domain = website.domain
        generic_page = self.env["website.page"].search([
            ("url", "=", "/contactus"),
            ("website_id", "=", False),
        ], limit=1)
        copied_page = self.env["website.page"].search([
            ("url", "=", "/contactus"),
            ("website_id", "=", website.id),
        ], limit=1)
        if not copied_page:
            copied_view = generic_page.view_id.copy({
                "website_id": website.id,
                "key": f"{generic_page.view_id.key}.test_copy",
            })
            copied_page = self.env["website.page"].create({
                "url": "/contactus",
                "website_id": website.id,
                "view_id": copied_view.id,
                "is_published": True,
            })
        try:
            website.domain = "https://abroj.sa"
            self.env["website.page"]._sync_abroj_contact_page()
            copied_page.invalidate_recordset(["view_id"])
            self.assertIn("abroj-contact-name", copied_page.view_id.arch_db)
            # The public interaction only binds to forms inside this wrapper.
            self.assertIn('class="s_website_form"', copied_page.view_id.arch_db)
        finally:
            website.domain = original_domain
