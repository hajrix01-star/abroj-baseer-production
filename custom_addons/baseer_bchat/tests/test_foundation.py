"""Odoo integration tests; require an isolated Odoo 19 database, never production."""
from uuid import uuid4

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import HttpCase, TransactionCase, tagged

from .. import contracts


@tagged('post_install', '-at_install', 'baseer_bchat')
class BChatFoundationCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.other_company = cls.env['res.company'].create({'name': 'BChat isolated test company'})
        cls.user = cls._make_user('user', 'baseer_bchat.group_bchat_user')
        cls.manager = cls._make_user('manager', 'baseer_bchat.group_bchat_manager')
        cls.other_member = cls._make_user('other', 'baseer_bchat.group_bchat_user', cls.other_company)
        cls.other_manager = cls._make_user('other-manager', 'baseer_bchat.group_bchat_manager', cls.other_company)
        cls.plain = cls._make_user('plain', 'base.group_user')
        cls.portal = cls._make_user('portal', 'base.group_portal')
        cls.inactive = cls._make_user('inactive', 'base.group_user')
        cls.inactive.active = False
        cls.binding = cls._make_binding('primary', cls.manager, cls.user)
        cls.other_binding = cls._make_binding('other', cls.other_manager, cls.other_member)

    @classmethod
    def _make_user(cls, label, group, company=None):
        company = company or cls.company
        return cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BChat test %s' % label,
            'login': 'bchat-%s-%s' % (label, uuid4().hex),
            'company_id': company.id,
            'company_ids': [Command.set(company.ids)],
            'group_ids': [Command.set([cls.env.ref(group).id])],
        })

    @classmethod
    def _make_binding(cls, label, manager, member):
        channel = cls.env['discuss.channel'].with_user(manager).create({
            'name': 'BChat test %s group' % label,
            'channel_type': 'group',
            'channel_partner_ids': [Command.link(member.partner_id.id)],
        })
        return cls.env['baseer.bchat.binding'].with_user(manager).with_company(manager.company_id).create({
            'name': 'BChat test %s binding' % label,
            'company_id': manager.company_id.id,
            'channel_id': channel.id,
            'purpose': 'chat',
            'policy_reference': 'isolated-test',
            'history_policy': 'since_join',
            'history_policy_reference': 'isolated-test',
        })

    def _service(self, user=None):
        return self.env['baseer.bchat.service'].with_user(user or self.user)

    def _message(self):
        return {'api_version': 1, 'company_id': self.company.id, 'channel_id': 1,
                'client_uuid': str(uuid4()), 'text': 'Offline foundation test',
                'attachment_ids': [], 'reply_to_id': None}

    def _conversation(self, members=None, company=None):
        return {'api_version': 1, 'company_id': (company or self.company).id,
                'client_uuid': str(uuid4()), 'name': 'Test conversation',
                'member_user_ids': members or [self.manager.id, self.user.id]}

    def test_authorized_bootstrap_is_disabled_and_self_scoped(self):
        result = self._service()._bootstrap()
        self.assertEqual(result['user_id'], self.user.id)
        self.assertEqual(result['database'], self.env.cr.dbname)
        self.assertEqual(result['company_ids'], self.company.ids)
        self.assertFalse(result['integration_enabled'])
        self.assertFalse(any(result['capabilities'].values()))
        self.assertNotIn('channels', result)
        self.assertNotIn('tasks', result)
        automatic = self._service(self.plain)._bootstrap()
        self.assertEqual(automatic['user_id'], self.plain.id)
        self.assertEqual(automatic['company_ids'], self.company.ids)
        self.assertFalse(automatic['integration_enabled'])

    def test_no_automatic_user_role_grants(self):
        self.assertFalse(self.plain.has_group('baseer_bchat.group_bchat_user'))
        self.assertFalse(self.plain.has_group('baseer_bchat.group_bchat_manager'))
        self.assertFalse(self.user.has_group('baseer_bchat.group_bchat_manager'))
        self.assertFalse(self.user.has_group('project.group_project_manager'))

    def test_direct_read_acl_and_global_member_company_rules(self):
        for user in [self.user, self.plain]:
            binding = self.env['baseer.bchat.binding'].with_user(user)
            receipt = self.env['baseer.bchat.receipt'].with_user(user)
            self.assertTrue(binding.has_access('read'))
            self.assertTrue(receipt.has_access('read'))
            self.assertFalse(binding.has_access('create'))
            self.assertFalse(binding.has_access('write'))
            self.assertFalse(binding.has_access('unlink'))
            for operation in ['create', 'write', 'unlink']:
                self.assertFalse(receipt.has_access(operation))
        self.assertEqual(self.env['baseer.bchat.binding'].with_user(self.user).search([
            ('id', '=', self.binding.id),
        ]).ids, self.binding.ids)
        self.assertTrue(self.binding.with_user(self.user).has_access('read'))
        self.assertFalse(self.binding.with_user(self.plain).has_access('read'))
        self.assertFalse(self.env['baseer.bchat.binding'].with_user(self.plain).search([
            ('id', '=', self.binding.id),
        ]))
        self.assertFalse(self.other_binding.with_user(self.user).with_context(
            allowed_company_ids=[self.company.id],
        ).has_access('read'))
        self.assertFalse(self.env['baseer.bchat.binding'].with_user(self.user).with_context(
            allowed_company_ids=[self.company.id],
        ).search([
            ('id', '=', self.other_binding.id),
        ]))
        self.assertEqual(self.env['baseer.bchat.binding'].with_user(self.other_member).search([
            ('id', '=', self.other_binding.id),
        ]).ids, self.other_binding.ids)

    def test_portal_inactive_and_superuser_rejected(self):
        for user in [self.portal, self.inactive]:
            with self.subTest(user=user.login), self.assertRaises(AccessError):
                self._service(user)._bootstrap()
        with self.assertRaises(AccessError):
            self._service().sudo()._bootstrap()

    def test_company_scope_rejects_foreign_company(self):
        with self.assertRaises(AccessError):
            self._service()._company_scope(self.other_company.id)
        with self.assertRaises(AccessError):
            self._service().with_context(
                allowed_company_ids=[self.other_company.id],
            )._company_scope(self.other_company.id)

    def test_company_scope_discards_untrusted_context(self):
        scoped = self._service().with_context(
            allowed_company_ids=[self.other_company.id],
            mail_create_nosubscribe=True, default_user_id=self.manager.id,
            skip_bchat_checks=True,
        )._company_scope(self.company.id)
        self.assertEqual(scoped.env.context['allowed_company_ids'], self.company.ids)
        self.assertEqual(scoped.env.uid, self.user.id)
        self.assertFalse(scoped.env.su)
        self.assertEqual(scoped.env.company.id, self.company.id)
        self.assertNotIn('skip_bchat_checks', scoped.env.context)
        self.assertNotIn('default_user_id', scoped.env.context)
        self.assertNotIn('mail_create_nosubscribe', scoped.env.context)

    def test_manager_member_preflight_validates_company(self):
        service = self._service(self.manager)
        normalized = service._prepare_conversation(self._conversation())
        self.assertEqual(normalized['member_user_ids'], sorted([self.manager.id, self.user.id]))
        automatic = service._prepare_conversation(self._conversation([self.manager.id, self.plain.id]))
        self.assertEqual(automatic['member_user_ids'], sorted([self.manager.id, self.plain.id]))
        with self.assertRaises(AccessError):
            service._prepare_conversation(self._conversation([self.manager.id, self.other_member.id]))
        with self.assertRaises(AccessError):
            service._prepare_conversation(self._conversation([self.manager.id, self.portal.id]))
        with self.assertRaises(AccessError):
            service._prepare_conversation(self._conversation([self.user.id]))

    def test_manager_creation_and_messages_stay_disabled(self):
        with self.assertRaises(AccessError):
            self._service()._create_conversation(self._conversation())
        with self.assertRaises(contracts.ProtocolError) as blocked:
            self._service(self.manager)._create_conversation(self._conversation())
        self.assertEqual(blocked.exception.code, 'integration_disabled')
        with self.assertRaises(contracts.ProtocolError) as blocked:
            self._service()._submit_message(self._message())
        self.assertEqual(blocked.exception.code, 'integration_disabled')

    def test_history_configuration_never_activates(self):
        self.assertEqual(self.company.bchat_history_policy, 'since_join')
        self.company.bchat_history_policy = 'all_history'
        self.assertFalse(self._service(self.manager)._bootstrap()['integration_enabled'])
        with self.assertRaises(AccessError):
            self.company.with_user(self.user).write({'bchat_history_policy': 'all_history'})

    def test_receipt_rpc_and_orm_mutations_denied_even_for_admin(self):
        for model in [self.env['baseer.bchat.receipt'],
                      self.env['baseer.bchat.receipt'].with_user(self.user)]:
            with self.assertRaises(AccessError):
                model.create({})
            with self.assertRaises(AccessError):
                model.write({'client_uuid': str(uuid4())})
            with self.assertRaises(AccessError):
                model.unlink()


@tagged('post_install', '-at_install', 'baseer_bchat')
class BChatAccountHttpCase(HttpCase):
    def test_existing_internal_account_bootstraps_without_bchat_group(self):
        login = 'bchat-http-%s' % uuid4().hex
        password = 'test-only-%s' % uuid4().hex
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BChat HTTP test account',
            'login': login,
            'password': password,
            'company_id': self.env.company.id,
            'company_ids': [Command.set(self.env.company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        })
        self.assertFalse(user.has_group('baseer_bchat.group_bchat_user'))
        self.authenticate(login, password)
        response = self.url_open('/bchat/api/v1/bootstrap')
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result['user_id'], user.id)
        self.assertEqual(result['database'], self.env.cr.dbname)
        self.assertEqual(result['company_ids'], self.env.company.ids)
        self.assertFalse(result['integration_enabled'])
        self.assertFalse(any(result['capabilities'].values()))

        portal_login = 'bchat-http-portal-%s' % uuid4().hex
        self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BChat HTTP portal test account',
            'login': portal_login,
            'password': password,
            'company_id': self.env.company.id,
            'company_ids': [Command.set(self.env.company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_portal').id])],
        })
        self.authenticate(portal_login, password)
        self.assertEqual(self.url_open('/bchat/api/v1/bootstrap').status_code, 403)
