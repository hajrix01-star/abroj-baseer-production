from pathlib import Path
from unittest import TestCase

from lxml import etree


class TestProjectsGalleryTemplate(TestCase):
    """Keep the public projects gallery deliberately empty until real work is supplied."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        module_root = Path(__file__).resolve().parents[1]
        cls.template_path = module_root / "views" / "abroj_templates.xml"
        cls.template = etree.parse(str(cls.template_path))

    def test_projects_link_is_available_in_desktop_and_mobile_navigation(self):
        links = self.template.xpath("//a[@href='#projects']")
        self.assertGreaterEqual(len(links), 4)

    def test_projects_gallery_has_an_explicit_empty_state(self):
        gallery = self.template.xpath("//*[@id='projects' and @data-abroj-project-gallery='empty']")
        self.assertEqual(len(gallery), 1)
        self.assertIn("نعمل على تجهيز معرض مشاريعنا", self.template_path.read_text(encoding="utf-8"))

    def test_no_project_images_are_declared(self):
        projects = self.template.xpath("//*[@id='projects']")[0]
        self.assertEqual(projects.xpath(".//img | .//*[contains(@style, 'background-image')]"), [])
