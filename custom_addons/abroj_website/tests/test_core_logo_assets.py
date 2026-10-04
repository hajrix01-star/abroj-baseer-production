from hashlib import sha256
from pathlib import Path
from unittest import TestCase

from lxml import etree


class TestCoreLogoAssets(TestCase):
    """Keep the approved core mark intact and separate from optional services copy."""

    EXPECTED_HASHES = {
        "abroj-logo-core-primary-20261004.svg": "780306e4e31910015e8d351f709a80913f1b2d6bf2c9270ae76771f5204bf2cb",
        "abroj-logo-core-white-20261004.svg": "f1aaa772895c9423a337f77306e7ada9085d4a1bfae0fe2a3e7c36ce14d8a7af",
    }

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.module_root = Path(__file__).resolve().parents[1]
        cls.template_source = (cls.module_root / "views" / "abroj_templates.xml").read_text(encoding="utf-8")

    def test_assets_match_the_approved_masters(self):
        assets = self.module_root / "static" / "src" / "img"
        for filename, expected_hash in self.EXPECTED_HASHES.items():
            self.assertEqual(sha256((assets / filename).read_bytes()).hexdigest(), expected_hash)

    def test_core_assets_keep_one_orange_a_accent_without_services(self):
        assets = self.module_root / "static" / "src" / "img"
        for filename in self.EXPECTED_HASHES:
            document = etree.parse(str(assets / filename))
            self.assertEqual(document.xpath("count(//*[local-name()='g' and @id='services'])"), 0)
            accent = document.xpath("//*[local-name()='path' and @id='approved-orange-a-accent']")
            self.assertEqual(len(accent), 1)
            self.assertEqual(accent[0].get("fill"), "#E97027")

    def test_view_inheritance_switches_to_the_core_assets(self):
        self.assertIn("abroj-logo-core-primary-20261004.svg", self.template_source)
        self.assertIn("abroj-logo-core-white-20261004.svg", self.template_source)
        self.assertIn('id="contactus_core_logo"', self.template_source)

    def test_public_identity_reuses_the_approved_orange(self):
        stylesheet = (self.module_root / "static" / "src" / "scss" / "abroj-v2.scss").read_text(encoding="utf-8")
        self.assertIn("--abroj-orange: #E97027", stylesheet)
