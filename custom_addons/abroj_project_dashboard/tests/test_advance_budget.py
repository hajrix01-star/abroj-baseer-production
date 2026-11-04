from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.addons.abroj_contracting.models.contracting import FrozenDocument
from .test_contract_budget import AbrojContractBudgetCase


@tagged('post_install', '-at_install', 'abroj_advance_budget')
class AdvanceBudgetCase(AbrojContractBudgetCase):
    def test_advance_link_and_contract_change_preserve_posted_move(self):
        contract, journal, payable, _expense = self._progress_setup()
        voucher = self._voucher(kind='payment', payment_purpose='advance', subcontractor_id=contract.id)
        self.assertEqual(voucher.abroj_budget_line_id, self.budget)
        with self.assertRaises(AccessError):
            voucher.write({'abroj_budget_line_id': False})
        voucher.action_issue()
        self.assertEqual(voucher.abroj_budget_line_id, self.budget)
        payment = self._progress_payment(contract, journal, payable, 30, fields.Date.today())
        linked = self.env['abroj.contracting.voucher'].search([('payment_id', '=', payment.id)], limit=1)
        before = (payment.move_id.write_date, payment.write_date,
                  [(line.id, line.write_date, line.debit, line.credit) for line in payment.move_id.line_ids])
        new_line = self.env['abroj.project.budget.line'].create({
            'project_id': self.project.id, 'name': 'Other works', 'budget': 500})
        contract.budget_line_id = new_line
        self.assertEqual(voucher.abroj_budget_line_id, new_line)
        self.assertEqual(linked.abroj_budget_line_id, new_line)
        self.assertEqual(before, (payment.move_id.write_date, payment.write_date,
                                  [(line.id, line.write_date, line.debit, line.credit) for line in payment.move_id.line_ids]))

    def test_backfill_and_invalid_project(self):
        contract, _journal, _payable, _expense = self._progress_setup()
        advance = self._voucher(kind='payment', payment_purpose='advance', subcontractor_id=contract.id)
        advance.action_issue()
        super(FrozenDocument, advance).write({'abroj_budget_line_id': False})
        updated = self.env['abroj.contracting.voucher'].abroj_backfill_advance_budget_lines()
        self.assertIn({'id': advance.id, 'name': advance.name, 'budget_line_id': self.budget.id}, updated)
        self.assertFalse(self.env['abroj.contracting.voucher'].abroj_backfill_advance_budget_lines())
        other_project = self.env['project.project'].create({'name': 'Other project'})
        other_line = self.env['abroj.project.budget.line'].create({'project_id': other_project.id, 'name': 'Other'})
        contract.budget_line_id = other_line
        super(FrozenDocument, advance).write({'abroj_budget_line_id': False})
        self.assertFalse(self.env['abroj.contracting.voucher'].abroj_backfill_advance_budget_lines())
        self.assertFalse(advance.abroj_budget_line_id)

    def test_purpose_change_and_non_advance(self):
        contract, _journal, _payable, _expense = self._progress_setup()
        voucher = self._voucher(kind='payment', payment_purpose='direct', subcontractor_id=contract.id)
        super(FrozenDocument, voucher).write({'abroj_budget_line_id': False})
        contract.budget_line_id = self.budget
        self.assertFalse(voucher.abroj_budget_line_id)
        voucher.write({'payment_purpose': 'advance'})
        self.assertEqual(voucher.abroj_budget_line_id, self.budget)
