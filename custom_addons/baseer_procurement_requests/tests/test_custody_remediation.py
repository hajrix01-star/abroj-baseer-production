from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


INTERNAL = 'baseer_procurement_custody_internal'


class CustodyRemediationCase(TransactionCase):
    """Focused regressions for PRC-REMEDIATION1's financial controls."""

    def setUp(self):
        super().setUp()
        self.env.user.group_ids |= self.env.ref(
            'baseer_procurement_requests.group_procurement_accountant'
        )
        self.env.user.group_ids |= self.env.ref(
            'baseer_procurement_requests.group_procurement_manager'
        )
        self.env.user.group_ids |= self.env.ref(
            'baseer_procurement_requests.group_procurement_cashier'
        )
        self.env.user.group_ids |= self.env.ref('account.group_account_invoice')
        sar = self.env['res.currency'].with_context(active_test=False).search(
            [('name', '=', 'SAR')], limit=1
        )
        self.assertTrue(sar, 'The remediation accounting tests require the standard SAR currency.')
        if not sar.active:
            sar.active = True
        self.company = self.env['res.company'].search([('currency_id', '=', sar.id)], limit=1)
        if not self.company:
            self.company = self.env['res.company'].create({
                'name': 'Remediation SAR company',
                'currency_id': sar.id,
            })
        self.env.user.company_ids |= self.company
        other_company_ids = (self.env.companies - self.company).ids
        self.env = self.env(
            context={
                **self.env.context,
                'allowed_company_ids': [self.company.id, *sorted(other_company_ids)],
            },
        )
        Account = self.env['account.account']
        self.custody_account = Account.create({
            'name': 'Remediation custody receivable',
            'code': 'RMD701',
            'account_type': 'asset_receivable',
            'reconcile': True,
            'company_ids': [Command.set(self.company.ids)],
        })
        self.cash_account = Account.create({
            'name': 'Remediation cash',
            'code': 'RMD702',
            'account_type': 'asset_cash',
            'company_ids': [Command.set(self.company.ids)],
        })
        self.expense_account = Account.create({
            'name': 'Remediation expense',
            'code': 'RMD703',
            'account_type': 'expense',
            'company_ids': [Command.set(self.company.ids)],
        })
        self.payable_account = Account.create({
            'name': 'Remediation payable',
            'code': 'RMD704',
            'account_type': 'liability_payable',
            'reconcile': True,
            'company_ids': [Command.set(self.company.ids)],
        })
        Journal = self.env['account.journal']
        self.purchase_journal = Journal.create({
            'name': 'Remediation purchases', 'code': 'RMDP', 'type': 'purchase',
            'company_id': self.company.id, 'sequence': -100,
            'default_account_id': self.expense_account.id,
        })
        self.general_journal = Journal.create({
            'name': 'Remediation custody entries',
            'code': 'RMDG',
            'type': 'general',
            'company_id': self.company.id,
        })
        self.cash_journal = Journal.create({
            'name': 'Remediation cash journal',
            'code': 'RMDC',
            'type': 'cash',
            'company_id': self.company.id,
            'default_account_id': self.cash_account.id,
        })
        self.company.write({
            'baseer_procurement_custody_account_id': self.custody_account.id,
            'baseer_procurement_custody_journal_id': self.general_journal.id,
        })
        self.employee = self.env['hr.employee'].create({
            'name': 'Remediation buyer',
            'company_id': self.company.id,
        })
        self.custody = self.env['baseer.procurement.custody'].create({
            'company_id': self.company.id,
            'employee_id': self.employee.id,
        })

    def test_new_petty_cash_totals_are_zero_before_save(self):
        """Opening a new Petty Cash form must not issue an empty SQL IN clause."""
        petty_cash = self.env['baseer.procurement.custody'].new({
            'company_id': self.company.id,
            'is_company_pool': True,
        })
        self.assertEqual(petty_cash.funded_amount, 0)
        self.assertEqual(petty_cash.returned_amount, 0)
        self.assertEqual(petty_cash.settled_amount, 0)
        self.assertEqual(petty_cash.balance, 0)

    def _post_funding(self, amount=100):
        event = self.env['baseer.procurement.custody.event'].create({
            'custody_id': self.custody.id,
            'event_type': 'funding',
            'event_date': fields.Date.context_today(self),
            'amount': amount,
            'cash_journal_id': self.cash_journal.id,
            'reference': 'PRC remediation funding',
        })
        event.action_post()
        return event

    def _draft_batch_line(self, supplier):
        category = self.env['product.category'].create({
            'name': 'Remediation expense category',
        })
        service = self.env['product.product'].create({
            'name': 'Remediation expense service',
            'type': 'service',
            'categ_id': category.id,
            'property_account_expense_id': self.expense_account.id,
        })
        mapping = self.env['baseer.purchase.category.map'].create({
            'company_id': self.company.id,
            'category_id': category.id,
            'product_id': service.id,
        })
        batch = self.env['baseer.purchase.batch'].create({
            'company_id': self.company.id,
            'line_ids': [Command.create({
                'partner_id': supplier.id,
                'supplier_ref': 'RMD-HISTORICAL-1',
                'entry_type': 'purchase',
                'gross_amount': 40,
                'is_credit': True,
                'procurement_custody_id': self.custody.id,
            })],
        })
        return batch.line_ids

    def test_custody_moves_reject_standard_lifecycle_but_normal_moves_do_not(self):
        funding = self._post_funding()
        protected_move = funding.move_id
        for action in ('button_draft', 'button_cancel'):
            with self.assertRaisesRegex(UserError, 'documented custody return'):
                getattr(protected_move, action)()
        with self.assertRaisesRegex(UserError, 'documented custody return'):
            protected_move._reverse_moves()
        with self.assertRaisesRegex(UserError, 'documented custody return'):
            protected_move.unlink()
        self.assertEqual(protected_move.state, 'posted')
        self.assertEqual(funding.state, 'posted')

        normal_move = self.env['account.move'].create({
            'move_type': 'entry',
            'company_id': self.company.id,
            'journal_id': self.general_journal.id,
            'date': fields.Date.context_today(self),
            'line_ids': [
                Command.create({
                    'name': 'normal debit',
                    'account_id': self.expense_account.id,
                    'debit': 1,
                }),
                Command.create({
                    'name': 'normal credit',
                    'account_id': self.cash_account.id,
                    'credit': 1,
                }),
            ],
        })
        normal_move.action_post()
        normal_reversal = normal_move._reverse_moves(cancel=False)
        self.assertTrue(normal_reversal)
        self.assertFalse(normal_reversal.line_ids.baseer_procurement_custody_id)
        normal_move.button_draft()
        self.assertEqual(normal_move.state, 'draft')

    def test_historical_settlement_reversal_uses_custody_representative(self):
        self._post_funding()
        supplier = self.env['res.partner'].create({
            'name': 'Remediation supplier',
            'supplier_rank': 1,
        })
        batch_line = self._draft_batch_line(supplier)
        representative = self.employee.work_contact_id.commercial_partner_id
        settlement_move = (
            self.env['account.move']
            .sudo()
            .with_company(self.company)
            .with_context(**{INTERNAL: True})
            .create({
                'move_type': 'entry',
                'company_id': self.company.id,
                'journal_id': self.general_journal.id,
                'date': fields.Date.context_today(self),
                'ref': 'Historical custody settlement',
                'line_ids': [
                    Command.create({
                        'name': 'historical payable',
                        'account_id': self.payable_account.id,
                        'partner_id': supplier.id,
                        'debit': 40,
                    }),
                    Command.create({
                        'name': 'historical custody',
                        'account_id': self.custody_account.id,
                        'partner_id': representative.id,
                        'credit': 40,
                        'baseer_procurement_custody_id': self.custody.id,
                    }),
                ],
            })
        )
        settlement_move.action_post()
        settlement = self.env['baseer.procurement.custody.settlement'].sudo().create({
            'company_id': self.company.id,
            'custody_id': self.custody.id,
            'batch_line_id': batch_line.id,
            'move_id': settlement_move.id,
            # Deliberately absent: historical records predate this field.
            'amount': 40,
        })
        self.assertFalse(settlement.representative_partner_id)
        settlement.write({'reversal_reason': 'Historical fallback regression'})
        settlement.action_reverse()

        reversal_custody_line = settlement.reversal_move_id.line_ids.filtered(
            lambda line: (
                line.account_id == self.custody_account
                and line.baseer_procurement_custody_id == self.custody
            )
        )
        self.assertEqual(len(reversal_custody_line), 1)
        self.assertEqual(reversal_custody_line.partner_id, representative)
        self.assertEqual(settlement.state, 'reversed')
