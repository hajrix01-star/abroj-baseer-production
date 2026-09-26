from odoo.tests import TransactionCase, tagged
from ..hooks import uninstall_hook


@tagged('post_install', '-at_install')
class TestSuitePackaging(TransactionCase):
    def test_one_application_and_dependency_closure(self):
        names = ['baseer_pos_suite', 'baseer_pos_print_bridge',
                 'baseer_pos_receipt_layout', 'baseer_pos_product_substitution']
        modules = self.env['ir.module.module'].search([('name', 'in', names)])
        self.assertEqual(set(modules.mapped('name')), set(names))
        self.assertEqual(modules.filtered('application').mapped('name'), ['baseer_pos_suite'])
        self.assertTrue(all(m.state == 'installed' for m in modules))

    def test_root_and_native_configuration(self):
        root = self.env.ref('baseer_pos_suite.menu_baseer_pos_suite')
        bridge = self.env.ref('baseer_pos_print_bridge.menu_baseer_direct_print')
        self.assertFalse(root.parent_id)
        self.assertEqual(bridge.parent_id, root)
        self.assertEqual(self.env.ref('baseer_pos_suite.action_suite_config').res_model, 'pos.config')
        self.assertIn(self.env.ref('point_of_sale.group_pos_manager'), root.group_ids)
        agents = self.env.ref('baseer_pos_print_bridge.menu_baseer_print_agents')
        self.assertIn(self.env.ref('base.group_system'), agents.group_ids)

    def test_uninstall_restores_dependency_menu_without_data_loss(self):
        bridge = self.env.ref('baseer_pos_print_bridge.menu_baseer_direct_print')
        children = bridge.child_id
        config = self.env['pos.config'].search([], limit=1)
        before = config.read(['name', 'baseer_direct_print_enabled',
                              'baseer_substitution_enabled', 'baseer_receipt_layout_mode'])
        uninstall_hook(self.env)
        uninstall_hook(self.env)
        self.assertEqual(bridge.parent_id, self.env.ref('point_of_sale.menu_point_config_product'))
        self.assertEqual(bridge.with_context(lang='en_US').name, 'Direct printing')
        self.assertEqual(bridge.child_id, children)
        self.assertEqual(config.read(['name', 'baseer_direct_print_enabled',
                                     'baseer_substitution_enabled', 'baseer_receipt_layout_mode']), before)
        self.assertTrue(all(m.state == 'installed' for m in self.env['ir.module.module'].search([
            ('name', 'in', ['baseer_pos_print_bridge', 'baseer_pos_receipt_layout',
                           'baseer_pos_product_substitution'])])))
