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
