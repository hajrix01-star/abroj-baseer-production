from pathlib import Path
from unittest import TestCase

from lxml import etree
from odoo.tests.common import TransactionCase


class TestHomepageSeoData(TestCase):
    def test_data_calls_page_seo_and_sets_arabic_default(self):
        module_root = Path(__file__).resolve().parents[1]
        document = etree.parse(str(module_root / "data" / "website_data.xml"))
        website_writes = document.xpath("//function[@model='website' and @name='write']/value")
        self.assertEqual(len(website_writes), 2)
        self.assertNotIn("website_meta_", website_writes[1].get("eval"))
        self.assertIn("default_lang_id", website_writes[1].get("eval"))
        self.assertEqual(len(document.xpath("//function[@model='website.page' and @name='_set_abroj_homepage_seo']")), 1)


class TestHomepageSeoRuntime(TransactionCase):
    def test_home_and_contact_metadata_are_localized_and_website_specific(self):
        website = self.env.ref("website.default_website")
        website.domain = "https://abroj.sa"
        arabic = self.env.ref("base.lang_ar")
        arabic.active = True
        generic_home = self.env.ref("website.homepage_page")
        original_title = generic_home.with_context(lang="en_US").website_meta_title
        self.env["website.page"]._set_abroj_homepage_seo()
        for url, english, arabic_title in [
            ("/", "Abroj | Commercial Fit-Out in Al Khobar", "أبرج | تنفيذ وتجهيز مشاريع تجارية في الخبر"),
            ("/contactus", "Contact Abroj | Request a Fit-Out Quote in Al Khobar", "تواصل مع أبرج | اطلب عرض سعر لتجهيز مشروعك في الخبر"),
        ]:
            page = self.env["website.page"].search([("url", "=", url), ("website_id", "=", website.id)], limit=1)
            self.assertTrue(page, url)
            for lang, expected in [("en_US", english), (arabic.code, arabic_title)]:
                localized = page.with_context(lang=lang)
                self.assertEqual(localized.website_meta_title, expected)
                self.assertIn("2018", localized.website_meta_description)
                self.assertEqual(localized.get_website_meta()["opengraph_meta"]["og:description"], localized.website_meta_description)
        generic_home.invalidate_recordset(["website_meta_title"])
        self.assertEqual(generic_home.with_context(lang="en_US").website_meta_title, original_title)
