from uuid import uuid4

from odoo import Command
from odoo.tests.common import HttpCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestLeadershipHttp(HttpCase):
    def setUp(self):
        super().setUp()
        self.password = 'isolated-leadership-test'
        sar = self.env.ref('base.SAR')
        sar.active = True
        self.company = self.env['res.company'].create({
            'name': 'BWork HTTP isolated SAR company', 'currency_id': sar.id,
        })
        self.reader = new_test_user(self.env, login='bwork_http_' + uuid4().hex,
            password=self.password,
            groups='base.group_user,point_of_sale.group_pos_user,sales_team.group_sale_salesman_all_leads,account.group_account_invoice',
            company_id=self.company.id, company_ids=[Command.set(self.company.ids)],
            bwork_dashboard_view=True)

    def test_unauthenticated_and_token_fallback_are_rejected(self):
        for path in ('/bchat/api/v2/leadership/options',
                     '/bchat/api/v2/leadership?month=2026-10&period=month&auth_token=anything'):
            response = self.url_open(path, allow_redirects=False)
            self.assertIn(response.status_code, (302, 303, 401, 403))
            self.assertNotIn('"source": "sales_summary"', response.text)

    def test_options_nostore_and_strict_query_body_methods(self):
        self.authenticate(self.reader.login, self.password)
        response = self.url_open('/bchat/api/v2/leadership/options')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertTrue(response.json()['can_view'])
        for path in ('/bchat/api/v2/leadership/options?extra=1',
                     '/bchat/api/v2/leadership?month=2026-10&period=month&period=today',
                     '/bchat/api/v2/leadership?month=2026-10&period=month&company_id=0',
                     '/bchat/api/v2/leadership?month=2026-10&period=month&sudo=1'):
            self.assertEqual(self.url_open(path).status_code, 400)
        response = self.opener.request('GET', self.base_url() + '/bchat/api/v2/leadership/options',
                                      data=b'{}', timeout=30)
        self.assertEqual(response.status_code, 400)
        self.assertIn(self.url_open('/bchat/api/v2/leadership/options', data={'x': '1'}).status_code, (400, 403, 405))
