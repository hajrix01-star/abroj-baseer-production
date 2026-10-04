from pathlib import Path
from unittest import TestCase

from lxml import etree


class TestSiteRedesignTemplate(TestCase):
    """Guard the approved public messaging and quote form without submitting it."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        module_root = Path(__file__).resolve().parents[1]
        cls.template_path = module_root / "views" / "abroj_templates.xml"
        cls.source = cls.template_path.read_text(encoding="utf-8")
        cls.template = etree.parse(str(cls.template_path))

    def test_public_contact_details_are_consistent(self):
        self.assertIn('href="tel:+966552210049"', self.source)
        self.assertIn('href="https://wa.me/966552210049"', self.source)
        self.assertIn('href="mailto:info@abroj.sa"', self.source)
        self.assertNotIn("0550000000", self.source)

    def test_site_copy_does_not_claim_unverified_history_or_guarantees(self):
        self.assertNotIn("2018", self.source)
        self.assertIn("Al Khobar, Dammam and surrounding areas", self.source)
        self.assertIn("when requested and agreed", self.source)
        self.assertNotIn("ready to operate", self.source)

    def test_quote_form_collects_scope_without_attachment_uploads(self):
        forms = self.template.xpath("//form[@data-model_name='crm.lead']")
        self.assertEqual(len(forms), 1)
        form = forms[0]
        field_names = {field.get("name") for field in form.xpath(".//input | .//select | .//textarea")}
        self.assertTrue({"project_type", "project_location", "approximate_area", "design_status", "drawings_available"}.issubset(field_names))
        self.assertEqual(form.xpath(".//input[@type='file']"), [])

    def test_bilingual_primary_navigation_and_empty_gallery_remain_available(self):
        self.assertIn("تنفيذ وتجهيز واضحان", self.source)
        self.assertIn("Clear fit-out delivery", self.source)
        self.assertEqual(len(self.template.xpath("//*[@id='projects' and @data-abroj-project-gallery='empty']")), 1)
