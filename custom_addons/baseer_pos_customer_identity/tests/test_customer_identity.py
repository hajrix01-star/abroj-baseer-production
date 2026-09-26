from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.baseer_pos_customer_identity.models.res_partner import _saudi_mobile_key


@tagged('post_install', '-at_install')
class TestPosCustomerIdentity(TransactionCase):
    def _cashier_customer_capability(self, cashier, partner=False):
        PosConfig = self.env['pos.config']
        domain = [('baseer_summary_only', '=', False)] if 'baseer_summary_only' in PosConfig._fields else []
        config = PosConfig.search(domain, limit=1)
        self.assertTrue(config)
        session = self.env['pos.session'].sudo().search([
            ('config_id', '=', config.id), ('state', '=', 'opened'),
        ], limit=1)
        if session:
            session.write({'user_id': cashier.id})
        else:
            self.env['pos.session'].sudo().create({
                'config_id': config.id,
                'user_id': cashier.id,
                'state': 'opened',
            })
        return config.with_user(cashier).baseer_prepare_customer_form(partner.id if partner else False)

    def test_cashier_can_create_only_from_the_pos_customer_form(self):
        cashier = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'POS customer cashier',
            'login': 'pos-customer-cashier',
            'baseer_access_role': 'cashier',
        })
        Partner = self.env['res.partner'].with_user(cashier)
        with self.assertRaises(AccessError):
            Partner.create({'name': 'Backend contact is denied'})
        with self.assertRaises(AccessError):
            Partner.with_context(baseer_pos_customer_form=True).create({
                'name': 'Forged POS context is denied', 'phone': '0511111111',
            })
        capability = self._cashier_customer_capability(cashier)
        customer = Partner.with_context(baseer_pos_customer_capability=capability).create({
            'name': 'POS customer is allowed', 'phone': '0511111111',
        })
        self.assertEqual(customer.create_uid, cashier)

    def test_cashier_can_edit_only_from_the_pos_customer_form(self):
        cashier = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'POS customer editor',
            'login': 'pos-customer-editor',
            'baseer_access_role': 'cashier',
        })
        customer = self.env['res.partner'].create({
            'name': 'Original POS customer', 'phone': '0511111111',
        })
        Partner = customer.with_user(cashier)
        with self.assertRaises(AccessError):
            Partner.write({'name': 'Backend edit is denied'})
        capability = self._cashier_customer_capability(cashier, customer)
        Partner.with_context(baseer_pos_customer_capability=capability).write({
            'name': 'POS edit is allowed', 'phone': '+966 511 111 111',
        })
        self.assertEqual(customer.name, 'POS edit is allowed')
        self.assertEqual(customer.baseer_pos_phone_key, '966511111111')

    def test_pos_customer_capability_rejects_protected_fields_and_companies(self):
        cashier = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'POS customer protection cashier',
            'login': 'pos-customer-protection-cashier',
            'baseer_access_role': 'cashier',
        })
        customer = self.env['res.partner'].create({
            'name': 'Protected customer', 'phone': '0512222222',
        })
        capability = self._cashier_customer_capability(cashier, customer)
        with self.assertRaises(AccessError):
            customer.with_user(cashier).with_context(
                baseer_pos_customer_capability=capability
            ).write({'active': False})
        company = self.env['res.partner'].create({'name': 'Not a POS editable company', 'is_company': True})
        with self.assertRaises(AccessError):
            self._cashier_customer_capability(cashier, company)
        other_customer = self.env['res.partner'].create({
            'name': 'Different customer', 'phone': '0513333333',
        })
        with self.assertRaises(AccessError):
            other_customer.with_user(cashier).with_context(
                baseer_pos_customer_capability=capability
            ).write({'name': 'Wrong target'})
        create_capability = self._cashier_customer_capability(cashier)
        with self.assertRaises(AccessError):
            self.env['res.partner'].with_user(cashier).with_context(
                baseer_pos_customer_capability=create_capability
            ).create({'name': 'Protected create', 'phone': '0514444444', 'active': False})

    def test_pos_customer_capability_expires_when_its_session_changes(self):
        cashier = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'POS session-bound capability cashier',
            'login': 'pos-session-bound-capability-cashier',
            'baseer_access_role': 'cashier',
        })
        customer = self.env['res.partner'].create({
            'name': 'Session-bound customer', 'phone': '0515555555',
        })
        capability = self._cashier_customer_capability(cashier, customer)
        config = self.env['pos.config'].search(
            [('baseer_summary_only', '=', False)] if 'baseer_summary_only' in self.env['pos.config']._fields else [],
            limit=1,
        )
        session = self.env['pos.session'].sudo().search([
            ('config_id', '=', config.id), ('user_id', '=', cashier.id), ('state', '=', 'opened'),
        ], limit=1)
        session.write({'state': 'closed'})
        self.env['pos.session'].sudo().create({
            'config_id': config.id,
            'user_id': cashier.id,
            'state': 'opened',
        })
        with self.assertRaises(AccessError):
            customer.with_user(cashier).with_context(
                baseer_pos_customer_capability=capability
            ).write({'name': 'Expired after session change'})

    def test_pos_customer_creation_allows_a_non_saudi_or_empty_mobile(self):
        cashier = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'POS non Saudi customer cashier',
            'login': 'pos-non-saudi-customer-cashier',
            'baseer_access_role': 'cashier',
        })
        capability = self._cashier_customer_capability(cashier)
        customer = self.env['res.partner'].with_user(cashier).with_context(
            baseer_pos_customer_capability=capability
        ).create({'name': 'Customer without Saudi mobile', 'phone': '+971 50 123 4567'})
        self.assertEqual(customer.phone, '+971 50 123 4567')

    def test_pos_customer_edit_rejects_an_existing_saudi_mobile(self):
        Partner = self.env['res.partner']
        original = Partner.create({'name': 'Original', 'phone': '0511111111'})
        Partner.create({'name': 'Existing', 'phone': '+966 512 222 222'})
        cashier = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'POS duplicate editor',
            'login': 'pos-duplicate-editor',
            'baseer_access_role': 'cashier',
        })
        capability = self._cashier_customer_capability(cashier, original)
        with self.assertRaises(ValidationError):
            original.with_user(cashier).with_context(baseer_pos_customer_capability=capability).write({
                'phone': '0512222222',
            })

    def test_saudi_phone_variants_share_one_identity(self):
        expected = '966512345678'
        for value in ('0512345678', '512345678', '966512345678', '+966 512 345 678', '٠٥١٢٣٤٥٦٧٨'):
            self.assertEqual(_saudi_mobile_key(value), expected)
        self.assertFalse(_saudi_mobile_key('+971 50 123 4567'))
        self.assertFalse(_saudi_mobile_key('051234567'))

    def test_pos_customer_creation_rejects_same_saudi_mobile_in_another_format(self):
        Partner = self.env['res.partner']
        existing = Partner.create({'name': 'POS customer identity existing', 'phone': '+966 512 345 678'})
        self.assertEqual(existing.baseer_pos_phone_key, '966512345678')
        cashier = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'POS duplicate creator',
            'login': 'pos-duplicate-creator',
            'baseer_access_role': 'cashier',
        })
        capability = self._cashier_customer_capability(cashier)
        with self.assertRaises(ValidationError):
            Partner.with_user(cashier).with_context(baseer_pos_customer_capability=capability).create({
                'name': 'POS customer identity duplicate', 'phone': '0512345678',
            })

    def test_non_pos_creation_keeps_native_partner_behavior(self):
        Partner = self.env['res.partner']
        Partner.create({'name': 'Native contact A', 'phone': '0500000001'})
        duplicate = Partner.create({'name': 'Native contact B', 'phone': '+966500000001'})
        self.assertEqual(duplicate.baseer_pos_phone_key, '966500000001')

    def test_customer_import_rejects_a_saudi_phone_variant(self):
        Partner = self.env['res.partner']
        Partner.create({'name': 'Imported customer source', 'phone': '0555555555'})
        with self.assertRaises(ValidationError):
            Partner.with_context(import_file=True).create({
                'name': 'Imported customer duplicate', 'phone': '+966 555 555 555',
            })

    def test_pos_and_import_reject_invalid_saudi_mobile_lengths(self):
        Partner = self.env['res.partner']
        cashier = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'POS invalid mobile cashier',
            'login': 'pos-invalid-mobile-cashier',
            'baseer_access_role': 'cashier',
        })
        capability = self._cashier_customer_capability(cashier)
        with self.assertRaises(ValidationError):
            Partner.with_user(cashier).with_context(baseer_pos_customer_capability=capability).create({
                'name': 'Invalid POS Saudi mobile', 'phone': '051234567',
            })
        with self.assertRaises(ValidationError):
            Partner.with_context(import_file=True).create({
                'name': 'Invalid imported Saudi mobile', 'phone': '+966 512 345 6789',
            })

    def test_pos_search_finds_a_phone_variant_outside_the_initial_batch(self):
        config = self.env['pos.config'].search([], limit=1)
        self.assertTrue(config)
        partner = self.env['res.partner'].create({
            'name': 'POS phone search customer',
            'phone': '0512345678',
            'company_id': config.company_id.id,
        })
        payload = self.env['res.partner'].get_new_partner(
            config.id, [('phone_mobile_search', 'ilike', '+966 512 345 678')], 0
        )
        self.assertIn(partner.id, {row['id'] for row in payload['res.partner']})
