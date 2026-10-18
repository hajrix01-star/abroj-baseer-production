"""HTTP contract for the minimal BChat WebView landing page."""

from uuid import uuid4
from urllib.parse import parse_qs, urlsplit

from odoo import Command
from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install', 'baseer_bchat')
class BChatBridgeHttpCase(HttpCase):
    def test_guest_is_redirected_to_login_without_private_bridge_content(self):
        response = self.url_open('/bchat/app/bridge', allow_redirects=False)
        # The original main route is auth=user: Odoo redirects an anonymous
        # request before invoking the controller. It never promised a 404.
        self.assertEqual(response.status_code, 303)
        target = urlsplit(response.headers['Location'])
        self.assertEqual(target.path, '/web/login')
        redirect = parse_qs(target.query)['redirect']
        self.assertEqual(len(redirect), 1)
        self.assertEqual(urlsplit(redirect[0]).path, '/bchat/app/bridge')
        self.assertNotIn('BChat', response.text)
        self.assertNotIn('<title>BChat</title>', response.text)

    def test_internal_session_gets_only_small_static_bridge(self):
        password = 'test-only-%s' % uuid4().hex
        login = 'bchat-bridge-%s' % uuid4().hex
        self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BChat bridge test account',
            'login': login,
            'password': password,
            'company_id': self.env.company.id,
            'company_ids': [Command.set(self.env.company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        })
        self.authenticate(login, password)
        response = self.url_open('/bchat/app/bridge', allow_redirects=False)
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/html', response.headers['Content-Type'])
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
        self.assertLess(len(response.content), 256)
        self.assertEqual(response.text.count('BChat'), 1)
        self.assertNotIn('<script', response.text.lower())
        self.assertNotIn('<link', response.text.lower())
        self.assertNotIn('http:', response.text.lower())
        self.assertNotIn('https:', response.text.lower())
