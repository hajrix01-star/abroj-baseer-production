from pathlib import Path
from unittest import TestCase

from lxml import etree
from odoo.tests.common import TransactionCase


class TestHomepageSeoData(TestCase):
    """Keep SEO metadata on Odoo 19's page/view model."""

    def test_data_file_does_not_write_page_seo_fields_to_website(self):
        module_root = Path(__file__).resolve().parents[1]
        document = etree.parse(str(module_root / "data" / "website_data.xml"))
        website_writes = document.xpath("//function[@model='website' and @name='write']/value")
        self.assertEqual(len(website_writes), 2)
        self.assertNotIn("website_meta_", website_writes[1].get("eval"))
        self.assertEqual(
            len(document.xpath("//function[@model='website.page' and @name='_set_abroj_homepage_seo']")),
            1,
        )


class TestHomepageSeoRuntime(TransactionCase):
    def test_abroj_homepage_seo_is_written_to_a_website_specific_page(self):
        website = self.env.ref("website.default_website")
        original_domain = website.domain
        generic_homepage = self.env.ref("website.homepage_page")
        original_title = generic_homepage.website_meta_title
        try:
            website.domain = "https://abroj.sa"
            self.env["website.page"]._set_abroj_homepage_seo()
            homepage = self.env["website.page"].search([
                ("url", "=", "/"),
                ("website_id", "=", website.id),
            ], limit=1)
            self.assertTrue(homepage)
            self.assertEqual(
                homepage.website_meta_title,
                "أبرج | تنفيذ مشاريع تجارية في المنطقة الشرقية",
            )
            generic_homepage.invalidate_recordset(["website_meta_title"])
            self.assertEqual(generic_homepage.website_meta_title, original_title)
        finally:
            website.domain = original_domain
