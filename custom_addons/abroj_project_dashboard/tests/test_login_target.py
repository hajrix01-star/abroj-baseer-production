import re

from odoo import Command
from odoo.tests import HttpCase, tagged

RADIO_CHECKED = re.compile(r'<input[^>]*name="abroj_target"[^>]*checked', re.S)


@tagged('-at_install', 'post_install')
class AbrojLoginTargetCase(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['res.users'].create({'name': 'Login target', 'login': 'login_target_user', 'password': 'login_target_user',
                                     'group_ids': [Command.set([cls.env.ref('base.group_user').id])]})

    def _csrf(self, html):
        return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    def test_no_radio_preselected(self):
        for url in ('/web/login', '/app/login', '/abroj/app/login', '/web/login?redirect=/odoo/action-1',
                    '/web/login?redirect=/abroj/app', '/web/login?abroj_target=app'):
            response = self.url_open(url)
            self.assertEqual(response.status_code, 200, url)
            self.assertIn('name="abroj_target" value="app"', response.text, url)
            self.assertIn('name="abroj_target" value="odoo"', response.text, url)
            self.assertFalse(RADIO_CHECKED.search(response.text), url)

    def test_submit_without_target_blocked(self):
        page = self.url_open('/web/login?lang=ar')
        response = self.url_open('/web/login', data={'csrf_token': self._csrf(page.text), 'login': 'login_target_user',
                                                      'password': 'login_target_user', 'lang': 'ar'}, allow_redirects=False)
        self.assertEqual(response.status_code, 200)
        self.assertIn('اختر وجهة الدخول', response.text)
        self.assertFalse(RADIO_CHECKED.search(response.text))
        self.assertIn('/web/login', self.url_open('/odoo', allow_redirects=False).headers.get('Location', ''))

    def test_submit_with_target_redirects(self):
        page = self.url_open('/web/login')
        response = self.url_open('/web/login', data={'csrf_token': self._csrf(page.text), 'login': 'login_target_user',
                                                      'password': 'login_target_user', 'abroj_target': 'odoo'}, allow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIn('/odoo', response.headers['Location'])


@tagged('-at_install', 'post_install')
class AbrojDashboardNameCase(HttpCase):
    def test_manifest_and_shell_name(self):
        manifest = self.url_open('/abroj/app/manifest.webmanifest?lang=ar').json()
        self.assertIn(manifest['name'], ('أبرج داشبورد', 'Abroj Dashboard'))
        self.assertEqual(manifest['short_name'], manifest['name'])
        from pathlib import Path
        html = (Path(__file__).parents[1] / 'static/pwa/index.html').read_text()
        self.assertIn('<title>أبرج داشبورد</title>', html)
        self.assertIn('name="apple-mobile-web-app-title" content="أبرج داشبورد"', html)
        self.assertEqual(self.env.ref('abroj_project_dashboard.menu_dashboard').with_context(lang='en_US').name, 'أبرج داشبورد')
