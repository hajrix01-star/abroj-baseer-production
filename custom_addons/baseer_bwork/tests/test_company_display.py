"""Native company metadata is opt-in presentation, never company revocation."""
from unittest.mock import patch
from uuid import uuid4

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class BWorkCompanyDisplayCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.owner = cls.env.ref('base.user_admin')
        cls.company = cls.owner.company_id
        cls.other = cls.env['res.company'].create({'name': 'شركة مطعم أرز لتقديم الوجبات | ARZ'})
        cls.foreign = cls.env['res.company'].create({'name': 'Foreign display company'})
        cls.owner.write({
            'company_ids': [Command.link(cls.other.id)],
            'group_ids': [Command.link(cls.env.ref('baseer_bwork.group_bwork_manager').id)],
            'bwork_chat_view': True, 'bwork_chat_send': True,
        })
        cls.ordinary = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Company display colleague', 'login': 'display-' + uuid4().hex,
            'company_id': cls.company.id,
            'company_ids': [Command.set((cls.company | cls.other).ids)],
            'group_ids': [Command.set([cls.env.ref('base.group_user').id])],
            'bwork_chat_view': True,
        })

    def companies(self):
        return (self.company | self.other).with_user(self.owner).with_context(
            allowed_company_ids=(self.company | self.other).ids)

    def service(self, user=None):
        return self.env['baseer.bwork.service'].with_user(user or self.owner).with_context(
            allowed_company_ids=(self.company | self.other).ids)

    def test_defaults_aliases_and_hide_preserve_legal_names_and_authority(self):
        self.assertFalse(self.other.bwork_hidden)
        self.assertFalse(self.other.bwork_short_name_ar)
        rights = self.ordinary.read(['company_ids', 'group_ids', 'bwork_chat_view', 'bwork_permission_revision'])
        legal = self.other.name
        companies = self.companies()
        other = companies.filtered(lambda company: company.id == self.other.id)
        other.write({'bwork_short_name_ar': '  أرز  ', 'bwork_short_name_en': ' ARZ ', 'bwork_hidden': True})
        data = self.service(self.ordinary)._v2_bootstrap()
        self.assertEqual(data['company_ids'], sorted((self.company | self.other).ids))
        preference = next(row for row in data['company_preferences'] if row['id'] == self.other.id)
        self.assertEqual(preference, {'id': self.other.id, 'name': legal,
            'short_name_ar': 'أرز', 'short_name_en': 'ARZ', 'hidden': True})
        self.assertEqual(self.service(self.ordinary)._bwork_visible_companies().ids, self.company.ids)
        self.assertEqual(self.other.name, legal)
        self.assertEqual(self.ordinary.read(['company_ids', 'group_ids', 'bwork_chat_view', 'bwork_permission_revision']), rights)
        other.write({'bwork_hidden': False})
        self.assertEqual(self.service(self.ordinary)._bwork_visible_companies().ids, sorted((self.company | self.other).ids))

    def test_metadata_is_independent_of_optional_profile_and_foreign_company(self):
        self.companies().filtered(lambda company: company.id == self.other.id).write({'bwork_hidden': True})
        service = self.service()
        with patch.object(type(service), '_v2_profile', side_effect=ValueError('optional HR unavailable')):
            result = service._v2_bootstrap()
        self.assertIsNone(result['profile'])
        self.assertEqual(result['profile_error'], 'profile_unavailable')
        rows = {row['id']: row for row in result['company_preferences']}
        self.assertNotIn(self.foreign.id, rows)
        self.assertTrue(rows[self.other.id]['hidden'])
        self.assertEqual(rows[self.other.id]['short_name_ar'], 'أرز')
        with self.assertRaises(AccessError):
            service._bwork_company_label(self.foreign)

    def test_metadata_write_requires_real_owner_active_company_and_not_sudo(self):
        for company in (
                self.other.with_user(self.ordinary).with_context(allowed_company_ids=self.other.ids),
                self.companies().filtered(lambda row: row.id == self.other.id).sudo(),
                self.other.with_user(self.owner).with_context(allowed_company_ids=self.company.ids),
                self.foreign.with_user(self.owner).with_context(allowed_company_ids=self.company.ids)):
            with self.assertRaises(AccessError), self.cr.savepoint():
                company.write({'bwork_hidden': True})
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.env['res.company'].create({'name': 'Must configure after creation', 'bwork_hidden': True})
        for field in ('bwork_hidden', 'bwork_short_name_ar', 'bwork_short_name_en'):
            with self.assertRaises(AccessError), self.cr.savepoint():
                self.env['res.company'].with_context(**{'default_' + field: True}).create({'name': 'No injected display defaults'})
        self.assertFalse(self.other.bwork_hidden)

    def test_alias_and_checkbox_validation_before_any_write(self):
        other = self.companies().filtered(lambda row: row.id == self.other.id)
        for value in ('x' * 65, 'Name\nHidden', 'Name\u200f', 12, True):
            with self.assertRaises(ValidationError), self.cr.savepoint():
                other.write({'bwork_short_name_ar': value})
        for value in (1, 'false', None):
            with self.assertRaises(ValidationError), self.cr.savepoint():
                other.write({'bwork_hidden': value})
        other.write({'bwork_short_name_ar': ' '})
        self.assertFalse(other.bwork_short_name_ar)
        self.assertEqual(self.service()._bwork_company_label(other, 'ar'), 'أرز')

    def test_all_hidden_does_not_change_full_bootstrap_company_ids(self):
        self.companies().write({'bwork_hidden': True})
        service = self.service(self.ordinary)
        self.assertFalse(service._bwork_visible_companies())
        result = service._v2_bootstrap()
        self.assertEqual(result['company_ids'], sorted((self.company | self.other).ids))
        self.assertTrue(all(row['hidden'] for row in result['company_preferences']))
