from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class BaseerFinancialRegisterDefaultViewsCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        company = cls.env.company
        cls.accountant = cls.env['res.users'].create({
            'name': 'Register test accountant',
            'login': 'register_test_accountant',
            'company_id': company.id,
            'company_ids': [Command.set(company.ids)],
            'group_ids': [Command.set([
                cls.env.ref('base.group_user').id,
                cls.env.ref('account.group_account_manager').id,
            ])],
        })

    def test_default_views_for_invoice_actions(self):
        moves = self.env['account.move'].with_user(self.accountant)
        register_kanbans = {
            self.env.ref('baseer_financial_register.view_register_kanban').id,
            self.env.ref('baseer_financial_register.view_cash_register_kanban').id,
        }
        for xmlid in ('account.action_move_in_invoice_type', 'account.action_move_in_invoice',
                      'account.action_move_out_invoice_type'):
            action = self.env.ref(xmlid)
            views = [(view_id, view_type) for view_id, view_type in action.views
                     if view_type == 'list']
            views += [(False, 'kanban'), (False, 'search')]
            result = moves.get_views(views, options={'action_id': action.id})
            kanban_id = result['views']['kanban']['id']
            self.assertNotIn(kanban_id, register_kanbans, xmlid)
            self.assertEqual(kanban_id, self.env.ref('account.view_account_move_kanban').id, xmlid)

        result = moves.get_views([(False, 'list'), (False, 'search')])
        for view_type in ('list', 'search'):
            register_ids = {
                self.env.ref(f'baseer_financial_register.view_register_{view_type}').id,
                self.env.ref(f'baseer_financial_register.view_cash_register_{view_type}').id,
            }
            self.assertNotIn(result['views'][view_type]['id'], register_ids)

    def test_register_actions_keep_explicit_views(self):
        moves = self.env['account.move'].with_user(self.accountant)
        for method, prefix in ((moves.action_open_financial_register, 'view_register'),
                               (moves.action_open_register_cash, 'view_cash_register')):
            action = method()
            for view_type in ('list', 'kanban'):
                view_id = self.env.ref(f'baseer_financial_register.{prefix}_{view_type}').id
                self.assertIn((view_id, view_type), action['views'])
            self.assertEqual(action['search_view_id'][0],
                             self.env.ref(f'baseer_financial_register.{prefix}_search').id)
