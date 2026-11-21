from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestZatcaPosScope(TransactionCase):
    def test_scope_flag_is_loaded_in_pos_session_data(self):
        config = self.env['pos.config'].search([], limit=1)
        self.assertTrue(config)
        self.assertIn('baseer_zatca_phase2_enabled', config._load_pos_data_fields(config))

        config.baseer_zatca_phase2_enabled = True
        payload = config._load_pos_data_read(config, config)
        self.assertTrue(payload[0]['baseer_zatca_phase2_enabled'])
