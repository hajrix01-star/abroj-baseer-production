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
