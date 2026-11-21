from datetime import date
import importlib.util
from pathlib import Path

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestTaxBasis(TransactionCase):
    def test_posted_bills_refund_and_tax_exclusions(self):
        company = self.env.company
        ids = [company.id]
        account = self.env['account.account'].with_company(company)
        def make_account(code, kind):
            return account.create({'code': code, 'name': code, 'account_type': kind, 'company_ids': [(6, 0, ids)]})
        food = make_account('400001', 'expense_direct_cost')
        vat = make_account('104041', 'asset_current')
        payable = make_account('D2TAXPAY', 'liability_payable')
        partner = self.env['res.partner'].create({'name': 'Tax supplier', 'property_account_payable_id': payable.id})
        journal = self.env['account.journal'].create({'name': 'Tax bills', 'code': 'TAXB', 'type': 'purchase', 'company_id': company.id})
        country = company.account_fiscal_country_id or company.country_id or self.env.ref('base.us')
        group = self.env['account.tax.group'].create({'name': 'Test VAT', 'company_id': company.id, 'country_id': country.id})
        def tax(name, amount, kind='percent'):
            record = self.env['account.tax'].with_company(company).create({'name': name, 'type_tax_use': 'purchase', 'amount_type': kind,
                       'amount': amount, 'company_id': company.id, 'country_id': country.id, 'tax_group_id': group.id})
            (record.invoice_repartition_line_ids | record.refund_repartition_line_ids).filtered(lambda r: r.repartition_type == 'tax').write({'account_id': vat.id})
            return record
        normal, reverse, withholding = tax('VAT normal', 15), tax('15% R C', 15), tax('WH 5', -5, 'division')
        def bill(name, tax_record=None, kind='in_invoice', expense=None):
            move = self.env['account.move'].create({'move_type': kind, 'journal_id': journal.id, 'partner_id': partner.id,
                'invoice_date': '2026-10-05', 'date': '2026-10-05', 'ref': name,
                'invoice_line_ids': [(0, 0, {'name': name, 'account_id': (expense or food).id, 'quantity': 1, 'price_unit': 100,
                                              'tax_ids': [(6, 0, tax_record.ids if tax_record else [])]})]})
            move.action_post()
            return move
        taxed = bill('taxed', normal)
        service = self.env['baseer.dashboard2.service']
        first, last = date(2026, 10, 1), date(2026, 10, 31)
        before = service._accounting(ids, first, last)
        gross = service._accounting_gross(ids, first, last)
        self.assertAlmostEqual(gross['categories']['food_cost'] - before['categories']['food_cost'], 15)
        bill('untaxed')
        untaxed = service._accounting_gross(ids, first, last)
        self.assertAlmostEqual(untaxed['categories']['food_cost'] - gross['categories']['food_cost'], 100)
        bill('refund', normal, 'in_refund')
        bill('reverse charge', reverse)
        bill('withholding', withholding)
        self.assertTrue(taxed.line_ids.filtered(lambda l: l.tax_line_id), taxed.line_ids.read(['date', 'account_id', 'tax_line_id', 'tax_ids', 'balance']))
        observed = service._tax_window(ids, first, last)
        self.assertTrue(observed, taxed.line_ids.read(['date', 'account_id', 'tax_line_id', 'tax_ids', 'balance', 'parent_state']))
        basis = service._tax_basis(ids, first, last)
        self.assertAlmostEqual(basis['input_vat'], 0)
        self.assertAlmostEqual(basis['accounts'][(company.id, food.id)], 0)
        # Removing the tax association makes that move's own tax line unallocated.
        base = taxed.invoice_line_ids.filtered(lambda l: l.account_id == food)
        self.env.cr.execute('DELETE FROM account_move_line_account_tax_rel WHERE account_move_line_id = %s', [base.id])
        base.invalidate_recordset(['tax_ids'])
        basis = service._tax_basis(ids, first, last)
        self.assertAlmostEqual(basis['unallocated_input_vat'], 15)
        self.assertAlmostEqual(basis['input_vat'], -15)
        commission = make_account('400011', 'expense')
        bill('app commission', normal, expense=commission)
        self.assertAlmostEqual(service._recorded_app_commissions(ids, first, last), 115)
        self.assertIn('unallocated_input_vat', service._accounting_gross(ids, first, last)['warnings'])

    def test_migration_idempotent_guard(self):
        config = self.env['ir.config_parameter'].sudo()
        config.set_param('baseer_dashboard2.target_basis', 'inclusive')
        targets = self.env['baseer.dashboard2.target'].sudo().search([])
        before = targets.mapped('value')
        path = Path(__file__).resolve().parents[1] / 'migrations/19.0.2.0.0/post-migration.py'
        spec = importlib.util.spec_from_file_location('bd2_tax_migration_test', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.migrate(self.env.cr, '19.0.1.7.0')
        self.assertEqual(targets.mapped('value'), before)
