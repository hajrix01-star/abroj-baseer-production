from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestGlobalDiscountSettings(TransactionCase):
    def setUp(self):
        super().setUp()
        self.native_product = self.env.ref('pos_discount.product_product_consumable')
        self.account = self.env['account.account'].create({
            'name': 'GD settings revenue', 'code': 'GDSET001', 'account_type': 'income',
            'company_ids': [Command.set(self.env.company.ids)],
        })
        self.config = self.env['pos.config'].create({
            'name': 'GD unified settings', 'discount_product_id': self.native_product.id,
            'baseer_global_discount_account_id': self.account.id,
        })
        self.other_config = self.env['pos.config'].create({
            'name': 'GD untouched settings', 'baseer_global_discount_account_id': self.account.id,
        })

    def test_explicit_native_product_setup_is_company_owned_and_idempotent(self):
        self.config.action_baseer_setup_native_discount()
        product = self.config.discount_product_id
        self.assertNotEqual(product, self.native_product)
        self.assertEqual(product.default_code, "BASEER-NATIVE-DISC")
        self.assertNotEqual(product, self.config.baseer_global_discount_product_id)
        self.assertEqual(product.company_id, self.config.company_id)
        self.assertEqual(product.type, 'service')
        self.assertTrue(product.available_in_pos)
        self.assertFalse(product.taxes_id)
        self.assertEqual(product.property_account_income_id, self.account)
        self.config.action_baseer_setup_native_discount()
        self.assertEqual(self.config.discount_product_id, product)
        cashier = self.env['res.users'].create({
            'name': 'Native discount cashier', 'login': 'native-discount-cashier',
            'group_ids': [Command.set([self.env.ref('point_of_sale.group_pos_user').id])],
            'company_id': self.env.company.id, 'company_ids': [Command.set(self.env.company.ids)],
        })
        with self.assertRaises(AccessError):
            self.config.with_user(cashier).action_baseer_setup_native_discount()

    def test_native_settings_switch_limits_and_product_round_trip(self):
        settings = self.env['res.config.settings'].create({
            'company_id': self.env.company.id, 'pos_config_id': self.config.id,
            'pos_module_pos_discount': True,
            'pos_baseer_global_discount_max_percent': 25,
            'pos_baseer_global_discount_max_amount': 50,
        })
        self.assertTrue(self.config.module_pos_discount)
        self.assertTrue(self.config.baseer_global_discount_enabled)
        self.assertEqual(self.config.baseer_global_discount_max_percent, 25)
        self.assertEqual(self.config.baseer_global_discount_max_amount, 50)
        product = self.config.baseer_global_discount_product_id
        self.assertFalse(product)
        self.assertEqual(self.config.discount_product_id, self.native_product)
        settings.write({'pos_baseer_global_discount_max_percent': 12.5,
                        'pos_baseer_global_discount_max_amount': 35})
        self.assertEqual(self.config.baseer_global_discount_max_percent, 12.5)
        self.assertEqual(self.config.baseer_global_discount_max_amount, 35)
        settings.write({'pos_module_pos_discount': False, 'pos_discount_product_id': False})
        self.assertFalse(self.config.module_pos_discount)
        self.assertFalse(self.config.baseer_global_discount_enabled)
        self.assertEqual(self.config.baseer_global_discount_product_id, product)
        self.assertEqual(self.config.discount_product_id, self.native_product)
        settings.write({'pos_module_pos_discount': True})
        self.assertEqual(self.config.baseer_global_discount_product_id, product)
        self.env['res.config.settings'].create({
            'company_id': self.env.company.id, 'pos_config_id': self.config.id,
            'pos_module_pos_discount': False, 'pos_discount_product_id': False,
        })
        self.assertFalse(self.config.baseer_global_discount_enabled)
        self.assertEqual(self.config.discount_product_id, self.native_product)
        self.env['res.config.settings'].create({
            'company_id': self.env.company.id, 'pos_config_id': self.config.id,
            'pos_module_pos_discount': True, 'pos_discount_product_id': self.native_product.id,
        })
        self.assertTrue(self.config.baseer_global_discount_enabled)
        self.assertEqual(self.config.discount_product_id, self.native_product)
        self.assertEqual(self.config.baseer_global_discount_product_id, product)
        self.assertFalse(self.other_config.baseer_global_discount_enabled)
        self.env['res.config.settings'].create({'pos_config_id': self.other_config.id})
        self.assertFalse(self.other_config.baseer_global_discount_enabled)

    def test_settings_manager_and_company_permissions(self):
        groups = [self.env.ref('base.group_user').id, self.env.ref('point_of_sale.group_pos_user').id]
        cashier = self.env['res.users'].create({
            'name': 'GD settings cashier', 'login': 'gd-settings-cashier',
            'group_ids': [Command.set(groups)], 'company_id': self.env.company.id,
            'company_ids': [Command.set(self.env.company.ids)],
        })
        with self.assertRaises(AccessError):
            self.env['res.config.settings'].with_user(cashier).create({
                'pos_config_id': self.config.id, 'pos_module_pos_discount': True,
            })
        settings = self.env['res.config.settings'].create({'pos_config_id': self.config.id})
        with self.assertRaises(AccessError):
            settings.with_user(cashier).write({'pos_module_pos_discount': True})
        other_company = self.env['res.company'].create({'name': 'GD settings other company'})
        admin_groups = [self.env.ref('base.group_system').id, self.env.ref('point_of_sale.group_pos_manager').id]
        manager = self.env['res.users'].create({
            'name': 'GD settings manager', 'login': 'gd-settings-manager',
            'group_ids': [Command.set(admin_groups)], 'company_id': self.env.company.id,
            'company_ids': [Command.set(self.env.company.ids)],
        })
        managed = self.env['res.config.settings'].with_user(manager).create({
            'company_id': self.env.company.id, 'pos_config_id': self.other_config.id,
            'pos_module_pos_discount': True, 'pos_baseer_global_discount_max_percent': 30,
        })
        managed.write({'pos_baseer_global_discount_max_percent': 15})
        self.assertTrue(self.other_config.baseer_global_discount_enabled)
        self.assertEqual(self.other_config.baseer_global_discount_max_percent, 15)
        other_manager = self.env['res.users'].create({
            'name': 'GD other settings manager', 'login': 'gd-other-settings-manager',
            'group_ids': [Command.set(admin_groups)], 'company_id': other_company.id,
            'company_ids': [Command.set(other_company.ids)],
        })
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.env['res.config.settings'].with_user(other_manager).create({
                'company_id': other_company.id, 'pos_config_id': self.config.id,
                'pos_module_pos_discount': True,
            })
        self.assertFalse(self.config.baseer_global_discount_enabled)

    def test_one_native_settings_card_and_no_separate_config_group(self):
        view = self.env.ref('baseer_pos_global_discount.res_config_settings_global_discount')
        combined = view._get_combined_arch()
        cards = combined.xpath("//setting[@id='pos_global_discount']")
        self.assertEqual(len(cards), 1)
        card = cards[0]
        for name in ('pos_baseer_global_discount_max_percent', 'pos_baseer_global_discount_account_id'):
            self.assertEqual(len(card.xpath(f".//field[@name='{name}']")), 1)
        for name in ('pos_discount_product_id', 'pos_discount_pc'):
            self.assertNotEqual(card.xpath(f".//field[@name='{name}']/parent::div")[0].get('invisible'),
                                'pos_baseer_global_discount_enabled')
        old = self.env.ref('baseer_pos_global_discount.pos_config_global_discount')
        self.assertNotIn('<group', old.arch_db)
