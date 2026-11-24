from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestNativeDiscountFields(TransactionCase):
    def test_native_fields_and_per_company_product(self):
        config = self.env['pos.config'].create({'name': 'Native fixed fields'})
        legacy = self.env['product.product'].create({
            'name': 'Legacy discount', 'type': 'service', 'available_in_pos': True,
            'company_id': config.company_id.id,
        })
        config.baseer_global_discount_product_id = legacy
        config.action_baseer_setup_native_discount()
        product = config.discount_product_id
        self.assertNotEqual(product, legacy)
        self.assertEqual(product.default_code, 'BASEER-NATIVE-DISC')
        other = self.env['pos.config'].create({'name': 'Native fixed reuse'})
        other.action_baseer_setup_native_discount()
        self.assertEqual(other.discount_product_id, product)
        config.write({'baseer_fixed_discount_enabled': True, 'baseer_fixed_discount_max_amount': 10,
                      'baseer_fixed_discount_allowed': 'all'})
        self.assertEqual(config.baseer_fixed_discount_allowed, 'all')
        self.assertTrue(set(('baseer_fixed_discount_enabled', 'baseer_fixed_discount_max_amount',
                             'baseer_fixed_discount_allowed')).issubset(config._load_pos_data_fields(config)))
        fields = self.env['pos.order.line']._load_pos_data_fields(config)
        self.assertTrue(set(('baseer_discount_kind', 'baseer_discount_input',
                             'baseer_discount_approved_by_user_id', 'baseer_discount_approved_by_employee',
                             'baseer_discount_approved_by_employee_name')).issubset(fields))
