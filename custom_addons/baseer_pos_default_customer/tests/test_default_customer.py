from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPosDefaultCustomer(TransactionCase):
    def test_default_customer_is_loaded_with_the_pos_config(self):
        customer = self.env['res.partner'].create({
            'name': 'POS default customer test',
            'company_id': self.env.company.id,
        })
        config = self.env['pos.config'].create({
            'name': 'POS default customer test',
            'baseer_default_customer_id': customer.id,
        })

        fields_to_load = config._load_pos_data_fields(config)
        self.assertNotIn('baseer_default_customer_id', fields_to_load)

        payload = self.env['pos.config']._load_pos_data_read(config, config)
        self.assertEqual(payload[0]['baseer_default_customer_id'], customer.id)

        partner_ids = config.get_limited_partners_loading()
        self.assertIn((customer.id,), partner_ids)

    def test_empty_configuration_keeps_native_partner_loading(self):
        config = self.env['pos.config'].create({'name': 'POS no default customer test'})
        payload = self.env['pos.config']._load_pos_data_read(config, config)
        self.assertFalse(payload[0]['baseer_default_customer_id'])
