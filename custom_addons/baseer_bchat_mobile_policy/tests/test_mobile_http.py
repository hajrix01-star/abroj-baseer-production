"""Session/CSRF boundary tests for a disposable Odoo HTTP test database."""
import json
from uuid import uuid4

from odoo import Command
from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install', 'baseer_bchat_mobile_policy')
class MobilePolicyHttpCase(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({'name': 'Synthetic HTTP company'})
        cls.login = 'mobile-policy-http-' + uuid4().hex
        cls.member = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Synthetic HTTP member', 'login': cls.login,
            'password': 'synthetic-http-password', 'company_id': cls.company.id,
            'company_ids': [Command.set(cls.company.ids)],
            'group_ids': [Command.set([cls.env.ref('base.group_user').id])],
        })

    def test_policy_requires_session_and_csrf_and_cannot_escalate_manager(self):
        path = '/bchat/api/v2/mobile/policy?company_id=%s' % self.company.id
        self.authenticate(self.login, 'synthetic-http-password')
        response = self.url_open(path)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['can_manage'])
        self.assertFalse(response.json()['direct_enabled'])
        bootstrap = self.url_open('/bchat/api/v2/bootstrap').json()
        payload = json.dumps({'api_version': 2, 'company_id': self.company.id, 'direct_enabled': True})
        missing_csrf = self.url_open('/bchat/api/v2/mobile/policy', data={'payload': payload})
        self.assertEqual(missing_csrf.status_code, 400)
        forbidden = self.url_open('/bchat/api/v2/mobile/policy', data={
            'csrf_token': bootstrap['csrf_token'], 'payload': payload,
        })
        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(forbidden.json()['error']['code'], 'forbidden')

    def test_repeated_and_foreign_company_query_are_rejected(self):
        self.authenticate(self.login, 'synthetic-http-password')
        bad = self.url_open('/bchat/api/v2/mobile/policy?company_id=1&company_id=2')
        self.assertEqual(bad.status_code, 400)
        foreign = self.url_open('/bchat/api/v2/mobile/policy?company_id=%s' % self.env.company.id)
        self.assertEqual(foreign.status_code, 403)
        candidates = self.url_open('/bchat/api/v2/mobile/candidates?company_id=%s&q=Synthetic' % self.company.id)
        self.assertEqual(candidates.status_code, 200)
        self.assertEqual(set(candidates.json()), {'api_version', 'users'})
        repeated = self.url_open('/bchat/api/v2/mobile/candidates?company_id=1&q=a&q=b')
        self.assertEqual(repeated.status_code, 400)
        foreign_candidates = self.url_open('/bchat/api/v2/mobile/candidates?company_id=%s' % self.env.company.id)
        self.assertEqual(foreign_candidates.status_code, 403)
