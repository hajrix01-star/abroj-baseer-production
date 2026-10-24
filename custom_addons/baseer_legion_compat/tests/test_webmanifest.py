import io

from lxml import html
from PIL import Image

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestBaseerWebManifest(HttpCase):
    def test_install_manifest_and_icons(self):
        response = self.url_open("/web/manifest.webmanifest")
        self.assertEqual(response.status_code, 200)
        manifest = response.json()
        self.assertEqual(manifest["scope"], "/odoo")
        self.assertEqual(manifest["start_url"], "/odoo")
        self.assertEqual(manifest["display"], "standalone")
        self.assertIn("shortcuts", manifest)
        self.assertIn(manifest["name"], ("Baseer", "بصير"))
        self.assertEqual(manifest["theme_color"], "#5B04A0")
        for icon in manifest["icons"]:
            self.assertTrue(icon["src"].startswith("/baseer_legion_compat/static/"))
            image_response = self.url_open(icon["src"])
            self.assertEqual(image_response.status_code, 200)
            image = Image.open(io.BytesIO(image_response.content))
            self.assertEqual(image.size, tuple(map(int, icon["sizes"].split("x"))))
            self.assertEqual(image.format, "PNG")

    def test_webclient_identity_and_asset_compilation(self):
        self.authenticate("admin", "admin")
        response = self.url_open("/odoo")
        self.assertEqual(response.status_code, 200)
        document = html.fromstring(response.content)
        self.assertEqual(document.xpath('//meta[@name="theme-color"]/@content'), ["#5B04A0"])
        icons = document.xpath('//link[@rel="apple-touch-icon"]/@href')
        self.assertIn("/baseer_legion_compat/static/src/img/baseer-icon-b-180.png", icons)
        self.assertEqual(self.url_open(icons[0]).status_code, 200)
        paths = document.xpath('//link[@rel="stylesheet"]/@href')
        backend_sheets = [path for path in paths if "web.assets_web" in path]
        self.assertTrue(backend_sheets, "Native backend asset bundle must be present")
        css = "\n".join(self.url_open(path).text for path in backend_sheets)
        self.assertNotIn("Could not get content for", css)
        self.assertNotIn("Error: Undefined variable", css)
        self.assertIn("--baseer-purple", css)
        self.assertIn("#5b04a0", css.lower())
