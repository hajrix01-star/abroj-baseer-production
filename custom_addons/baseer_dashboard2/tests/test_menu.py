import importlib.util
import os

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDashboard2Menu(TransactionCase):
    def test_dashboard_menu_is_first_root_menu(self):
        menu = self.env.ref('baseer_dashboard2.menu_dashboard')
        self.assertFalse(menu.parent_id)
        others = self.env['ir.ui.menu'].with_context(active_test=False, **{'ir.ui.menu.full_list': True}).search([('parent_id', '=', False), ('id', '!=', menu.id)])
        self.assertTrue(all(menu.sequence < other.sequence for other in others))
        roots = self.env['ir.ui.menu'].with_context(**{'ir.ui.menu.full_list': True}).search([('parent_id', '=', False)])
        self.assertEqual(roots[:1], menu)

    def test_migration_moves_menu_before_lowest_root_menu(self):
        menu = self.env.ref('baseer_dashboard2.menu_dashboard')
        other = self.env['ir.ui.menu'].create({'name': 'Earlier root', 'sequence': -500})
        menu.sequence = 20
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'migrations', '19.0.1.6.0', 'post-migration.py')
        spec = importlib.util.spec_from_file_location('bd2_mig_1_6_0', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.migrate(self.env.cr, '19.0.1.5.0')
        self.env.invalidate_all()
        self.assertEqual(menu.sequence, -501)
        self.assertLess(menu.sequence, other.sequence)
