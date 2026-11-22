from uuid import uuid4

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError

from .test_representative_petty_cash import RepresentativePettyCashCase


class DirectBillCustodyCase(RepresentativePettyCashCase):
    """A direct supplier bill consumes representative custody only after settlement."""

    def setUp(self):
        super().setUp()
        self._use_isolated_sar_company()
        self.Advance = self.env['baseer.procurement.representative.advance']
        self.Settlement = self.env['baseer.procurement.direct.bill.custody.settlement']
        self.day = fields.Date.from_string('2025-03-15')
        self.payable = self.env['account.account'].create({
            'name': 'Direct vendor payable', 'code': 'DB1001', 'account_type': 'liability_payable',
            'reconcile': True, 'company_ids': [Command.set(self.company.ids)],
        })
        self.expense = self.env['account.account'].create({
            'name': 'Direct vendor expense', 'code': 'DB1002', 'account_type': 'expense',
            'company_ids': [Command.set(self.company.ids)],
        })
        self.vendor = self.env['res.partner'].create({
            'name': 'Direct bill synthetic supplier', 'company_id': self.company.id, 'supplier_rank': 1,
        })
        self.vendor.with_company(self.company).property_account_payable_id = self.payable
        self.purchase_journal = self.env['account.journal'].create({
            'name': 'Direct supplier bill journal', 'code': 'DBIL', 'type': 'purchase',
            'company_id': self.company.id, 'default_account_id': self.expense.id,
        })

    def _fund(self, amount=100):
        return self.Advance.submit_funding(False, self.bank_journal.id, self.representative.id,
                                          str(amount), str(uuid4()), self.day)

    def _bill(self, amount=60, post=True):
        bill = self.env['account.move'].with_company(self.company).create({
            'move_type': 'in_invoice', 'company_id': self.company.id, 'journal_id': self.purchase_journal.id,
            'partner_id': self.vendor.id, 'invoice_date': self.day, 'date': self.day,
            'ref': 'QA-SUPPLIER-DIRECT',
            'invoice_line_ids': [Command.create({'name': 'Synthetic purchase', 'account_id': self.expense.id,
                                                 'quantity': 1, 'price_unit': amount,
                                                 'tax_ids': [Command.clear()]})],
        })
        if post:
            bill.action_post()
        return bill

    def _settle(self, bill, amount, token=None, date=None, rep=None):
        return self.Settlement.submit_direct_bill_settlement(
            bill.id, (rep or self.representative).id, str(amount), date or self.day, token or str(uuid4()),
        )

    def test_direct_partial_full_idempotency_ledger_and_carryover(self):
        self._fund()
        bill = self._bill()
        token = str(uuid4())
        record_id = self._settle(bill, 20, token)
        self.assertEqual(self._settle(bill, 20, token), record_id)
        settlement = self.Settlement.browse(record_id)
        self.assertEqual(settlement.bill_id, bill)
        self.assertEqual(settlement.move_id.state, 'posted')
        custody_credit = settlement.move_id.line_ids.filtered(lambda line: line.account_id == self.petty_cash_account)
        self.assertEqual(len(custody_credit), 1)
        self.assertEqual(custody_credit.amount_residual, 0)
        self.assertTrue(custody_credit.matched_debit_ids or custody_credit.matched_credit_ids)
        self.assertEqual(bill.amount_residual, 40)
        data = self.Advance.dashboard_data(self.representative.id, '2025-03-01')
        self.assertEqual((data['summary']['funded'], data['summary']['settled'], data['summary']['closing']),
                         (100, 20, 80))
        self.assertTrue(any(row['type'] == 'purchase' and row['amount'] == 20
                            and 'QA-SUPPLIER-DIRECT' in row['reference'] for row in data['daily_movements']))
        self.assertEqual(self.Advance.dashboard_data(self.representative.id, '2025-04-01')['summary']['opening'], 80)
        self._settle(bill, 40)
        bill.invalidate_recordset(['amount_residual', 'payment_state'])
        self.assertEqual(bill.amount_residual, 0)
        self.assertEqual(self.Advance.dashboard_data(self.representative.id, '2025-03-01')['summary']['closing'], 40)
        self.assertEqual(self.Settlement.search_count([('bill_id', '=', bill.id)]), 2)
        with self.assertRaises(ValidationError):
            self._settle(bill, 1)
        with self.assertRaises(ValidationError):
            self._settle(bill, 21, token)

    def test_amount_residual_balance_and_draft_validation(self):
        self._fund(30)
        bill = self._bill(40)
        draft = self._bill(10, post=False)
        with self.assertRaises(ValidationError):
            self._settle(draft, 10)
        with self.assertRaises(ValidationError):
            self._settle(bill, 31)
        with self.assertRaises(ValidationError):
            self._settle(bill, '0.001')
        self._settle(bill, 30)
        with self.assertRaises(ValidationError):
            self._settle(bill, 1)
        self.assertEqual(bill.amount_residual, 10)

    def test_protect_bill_settlement_and_reconciliation(self):
        self._fund()
        bill = self._bill()
        record = self.Settlement.browse(self._settle(bill, 20))
        payable = bill.line_ids.filtered(lambda line: line.account_id == self.payable)
        partial = payable.matched_debit_ids | payable.matched_credit_ids
        self.assertTrue(partial)
        for operation in (lambda: bill.button_draft(), lambda: bill.button_cancel(),
                          lambda: record.move_id.button_draft(), lambda: partial.unlink()):
            with self.assertRaises(UserError):
                with self.env.cr.savepoint():
                    operation()
        self.assertEqual(bill.amount_residual, 40)
        self.assertEqual(self.Advance.dashboard_data(self.representative.id, '2025-03-01')['summary']['closing'], 80)

    def test_company_access_and_locked_period(self):
        self._fund()
        bill = self._bill()
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'No direct custody rights', 'login': 'no-direct-custody-test',
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        })
        with self.assertRaises(AccessError):
            self.Settlement.with_user(user).with_company(self.company).submit_direct_bill_settlement(
                bill.id, self.representative.id, '10', self.day, str(uuid4()),
            )
        other = self.env['res.company'].create({'name': 'Other direct test company', 'currency_id': self.company.currency_id.id})
        self.env.user.company_ids |= other
        with self.assertRaises(ValidationError):
            self.Settlement.with_company(other).submit_direct_bill_settlement(
                bill.id, self.representative.id, '10', self.day, str(uuid4()),
            )
        self.company.fiscalyear_lock_date = self.day
        with self.assertRaises(ValidationError):
            self._settle(bill, 10)

    def test_backdated_settlement_cannot_make_intervening_balance_negative(self):
        self.Advance.submit_funding(False, self.bank_journal.id, self.representative.id,
                                    '100', str(uuid4()), '2025-03-15')
        self.Advance.submit_aggregate_return(self.representative.id, self.bank_journal.id,
                                             '100', str(uuid4()), '2025-03-20')
        self.Advance.submit_funding(False, self.bank_journal.id, self.representative.id,
                                    '100', str(uuid4()), '2025-03-30')
        bill = self._bill(50)
        with self.assertRaises(ValidationError):
            self._settle(bill, 50, date='2025-03-16')
        self.assertEqual(bill.amount_residual, 50)
        self.assertEqual(self.Advance.dashboard_data(self.representative.id, '2025-03-01')['summary']['closing'], 100)



    def test_foreign_currency_bill_is_rejected(self):
        self._fund()
        bill = self._bill(20, post=False)
        currency = self.env.ref('base.USD')
        currency.active = True
        bill.currency_id = currency
        bill.action_post()
        with self.assertRaises(ValidationError):
            self._settle(bill, 10)
        self.assertEqual(self.Settlement.search_count([('bill_id', '=', bill.id)]), 0)

    def test_unpaid_deferred_supplier_bill_is_eligible(self):
        self._fund()
        bill = self._bill(60, post=False)
        payment_term = self.env['account.payment.term'].create({
            'name': 'Direct bill deferred 30 days',
            'line_ids': [Command.create({'value': 'percent', 'value_amount': 100,
                                         'nb_days': 30, 'delay_type': 'days_after'})],
        })
        bill.invoice_payment_term_id = payment_term
        bill.action_post()
        self.assertGreater(bill.invoice_date_due, bill.invoice_date)
        self._settle(bill, 20)
        bill.invalidate_recordset(['amount_residual'])
        self.assertEqual(bill.amount_residual, 40)

    def test_read_only_bill_cannot_be_settled(self):
        self._fund()
        bill = self._bill()
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Read only direct bill accountant', 'login': 'direct-read-only-accountant',
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([self.env.ref('baseer_procurement_requests.group_procurement_accountant').id,
                                       self.env.ref('account.group_account_invoice').id])],
        })
        self.env['ir.rule'].create({
            'name': 'Synthetic deny write direct bill', 'model_id': self.env.ref('account.model_account_move').id,
            'domain_force': "[('id', '!=', %d)]" % bill.id,
            'perm_read': False, 'perm_write': True, 'perm_create': False, 'perm_unlink': False,
        })
        bill.with_user(user).check_access('read')
        with self.assertRaises(AccessError):
            self.Settlement.with_user(user).with_company(self.company).submit_direct_bill_settlement(
                bill.id, self.representative.id, '10', self.day, str(uuid4()))
        self.assertEqual(self.Settlement.search_count([('bill_id', '=', bill.id)]), 0)
        self.assertEqual(bill.amount_residual, 60)

    def test_native_payment_after_partial_settlement_can_be_unreconciled(self):
        self._fund()
        bill = self._bill()
        self._settle(bill, 20)
        self.bank_journal.outbound_payment_method_line_ids.payment_account_id = self.bank_journal.default_account_id
        wizard = self.env['account.payment.register'].with_company(self.company).with_context(
            active_model='account.move', active_ids=bill.ids).create({
                'journal_id': self.bank_journal.id, 'payment_date': self.day,
            })
        wizard.action_create_payments()
        bill.invalidate_recordset(['amount_residual'])
        self.assertEqual(bill.amount_residual, 0)
        payable = bill.line_ids.filtered(lambda line: line.account_id == self.payable)
        partials = payable.matched_debit_ids | payable.matched_credit_ids
        custody_move = self.Settlement.search([('bill_id', '=', bill.id)]).move_id
        native = partials.filtered(lambda partial: custody_move not in (partial.debit_move_id.move_id | partial.credit_move_id.move_id))
        self.assertEqual(len(native), 1)
        protected = partials - native
        self.assertEqual(len(protected), 1)
        with self.assertRaises(UserError):
            protected.unlink()
        full = payable.full_reconcile_id
        self.assertTrue(full)
        with self.assertRaises(UserError):
            full.unlink()
        native.unlink()
        self.assertTrue(protected.exists())
        bill.invalidate_recordset(['amount_residual'])
        self.assertEqual(bill.amount_residual, 40)
        self.assertEqual(self.Advance.dashboard_data(self.representative.id, '2025-03-01')['summary']['closing'], 80)




    def test_custody_settlement_reversal_restores_bill_and_open_funding(self):
        self._fund()
        bill = self._bill()
        record = self.Settlement.browse(self._settle(bill, 20))
        reversal_id = self.Settlement.reverse_direct_bill_settlement(record.id, 'Correction', '2025-03-16')
        reversal = self.env['baseer.procurement.direct.bill.custody.reversal'].browse(reversal_id)
        self.assertEqual(reversal.settlement_id, record)
        self.assertEqual(reversal.move_id.state, 'posted')
        self.assertAlmostEqual(sum(reversal.move_id.line_ids.mapped('balance')), 0)
        bill.invalidate_recordset(['amount_residual'])
        self.assertEqual(bill.amount_residual, 60)
        self.assertEqual(self.Advance.dashboard_data(self.representative.id, '2025-03-01')['summary']['closing'], 100)
        balance_on_original = self.Advance._baseer_representative_available_amount_on(
            self.company, self.representative, fields.Date.from_string('2025-03-15'))
        self.assertEqual(balance_on_original, 80)
        with self.assertRaises(ValidationError):
            self.Settlement.reverse_direct_bill_settlement(record.id, 'Again', '2025-03-16')

    def test_reversal_rejects_mixed_native_payment_without_changes(self):
        self._fund()
        bill = self._bill()
        record = self.Settlement.browse(self._settle(bill, 20))
        self.bank_journal.outbound_payment_method_line_ids.payment_account_id = self.bank_journal.default_account_id
        wizard = self.env['account.payment.register'].with_company(self.company).with_context(
            active_model='account.move', active_ids=bill.ids).create({'journal_id': self.bank_journal.id, 'payment_date': self.day})
        wizard.action_create_payments()
        with self.assertRaises(ValidationError):
            self.Settlement.reverse_direct_bill_settlement(record.id, 'Mixed', '2025-03-16')
        bill.invalidate_recordset(['amount_residual'])
        self.assertEqual(bill.amount_residual, 0)
        self.assertEqual(self.Advance.dashboard_data(self.representative.id, '2025-03-01')['summary']['closing'], 80)
        self.assertFalse(self.env['baseer.procurement.direct.bill.custody.reversal'].search([('settlement_id', '=', record.id)]))

    def test_company_scoped_accountant_can_open_and_reverse_settlement(self):
        self._fund()
        bill = self._bill()
        settlement_id = self._settle(bill, 20)
        other = self.env['res.company'].create({'name': 'Other accountant company', 'currency_id': self.company.currency_id.id})
        groups = [self.env.ref('baseer_procurement_requests.group_procurement_accountant').id,
                  self.env.ref('account.group_account_manager').id]
        def accountant(company, login):
            return self.env['res.users'].with_context(no_reset_password=True).create({
                'name': login, 'login': login, 'company_id': company.id,
                'company_ids': [Command.set(company.ids)], 'group_ids': [Command.set(groups)],
            })
        right_user = accountant(self.company, 'custody-scope-right')
        wrong_user = accountant(other, 'custody-scope-other')
        right_adv = self.Advance.with_user(right_user).with_company(self.company)
        settlement = self.Settlement.with_user(right_user).with_company(self.company).browse(settlement_id)
        values = settlement.read(['amount', 'display_name'])[0]
        self.assertEqual(values['amount'], 20)
        self.assertIn('QA-SUPPLIER-DIRECT', values['display_name'])
        self.assertIn(self.representative.name, values['display_name'])
        self.assertIn('20.00', values['display_name'])
        self.assertIn(self.company.currency_id.name, values['display_name'])
        action = right_adv.action_open_direct_bill_custody_reversal(settlement_id)
        self.assertEqual(action['res_model'], 'baseer.procurement.direct.bill.custody.reversal.wizard')
        self.assertEqual(action['context']['default_settlement_id'], settlement_id)
        wrong = self.Settlement.with_user(wrong_user).with_company(other).browse(settlement_id)
        with self.assertRaises(AccessError):
            wrong.read(['amount'])
        with self.assertRaises(ValidationError):
            self.Advance.with_user(wrong_user).with_context(allowed_company_ids=other.ids).with_company(other).action_open_direct_bill_custody_reversal(settlement_id)
        wizard = self.env['baseer.procurement.direct.bill.custody.reversal.wizard'].with_user(right_user).with_company(self.company).create({
            'settlement_id': settlement_id, 'reason': 'Correction', 'reversal_date': '2025-03-16',
        })
        self.assertEqual(wizard.settlement_id.display_name, values['display_name'])
        self.assertEqual(wizard.action_reverse()['type'], 'ir.actions.act_window_close')
        bill.invalidate_recordset(['amount_residual'])
        self.assertEqual(bill.amount_residual, 60)

    def test_fully_reversed_bill_can_be_corrected_but_journal_entries_stay_protected(self):
        self._fund()
        bill = self._bill()
        settlement = self.Settlement.browse(self._settle(bill, 20))
        reversal = self.env['baseer.procurement.direct.bill.custody.reversal'].browse(
            self.Settlement.reverse_direct_bill_settlement(settlement.id, 'Correction', '2025-03-16'))
        for entry in (settlement.move_id, reversal.move_id):
            with self.assertRaises(UserError):
                entry.button_draft()
        bill.button_draft()
        self.assertEqual(bill.state, 'draft')
        bill.invoice_line_ids.write({'name': 'Corrected purchase description'})
        self.assertEqual(bill.invoice_line_ids[0].name, 'Corrected purchase description')
        with self.assertRaises(UserError):
            bill.unlink()

    def test_bill_stays_protected_when_another_settlement_is_active(self):
        self._fund()
        bill = self._bill()
        first = self.Settlement.browse(self._settle(bill, 20))
        self.Settlement.reverse_direct_bill_settlement(first.id, 'Correction', '2025-03-16')
        self._settle(bill, 20, date='2025-03-16')
        with self.assertRaises(UserError):
            bill.button_draft()
        with self.assertRaises(UserError):
            bill.invoice_line_ids.write({'price_unit': 999})

    def test_corrected_bill_preserves_historical_settlement_identity(self):
        self._fund()
        bill = self._bill()
        first = self.Settlement.browse(self._settle(bill, 20))
        self.Settlement.reverse_direct_bill_settlement(first.id, 'Correction', '2025-03-16')
        bill.button_draft()
        new_vendor = self.env['res.partner'].create({
            'name': 'Corrected synthetic supplier', 'company_id': self.company.id, 'supplier_rank': 1,
        })
        new_vendor.with_company(self.company).property_account_payable_id = self.payable
        bill.write({'partner_id': new_vendor.id, 'ref': 'CORRECTED-DIRECT-REF',
                    'invoice_date': '2025-03-17', 'date': '2025-03-17'})
        bill.action_post()
        second = self.Settlement.browse(self._settle(bill, 30, date='2025-03-17'))
        self.assertEqual(first.bill_reference_snapshot, 'QA-SUPPLIER-DIRECT')
        self.assertEqual(first.bill_supplier_snapshot, 'Direct bill synthetic supplier')
        self.assertEqual(first.bill_invoice_date_snapshot, fields.Date.from_string('2025-03-15'))
        self.assertEqual(first.bill_accounting_date_snapshot, fields.Date.from_string('2025-03-15'))
        self.assertEqual(second.bill_reference_snapshot, 'CORRECTED-DIRECT-REF')
        self.assertEqual(second.bill_supplier_snapshot, 'Corrected synthetic supplier')
        self.assertEqual(second.bill_invoice_date_snapshot, fields.Date.from_string('2025-03-17'))
        data = self.Advance.dashboard_data(self.representative.id, '2025-03-01')
        rows = {row['key']: row for row in data['daily_movements']}
        self.assertEqual(rows['direct_invoice:%s' % first.id]['reference'], 'QA-SUPPLIER-DIRECT')
        self.assertEqual(rows['direct_invoice:%s' % second.id]['reference'], 'CORRECTED-DIRECT-REF')
        reversal_rows = [row for row in rows.values() if row['type'] == 'purchase_reversal']
        self.assertEqual(len(reversal_rows), 1)
        self.assertEqual(reversal_rows[0]['reference'], 'QA-SUPPLIER-DIRECT')
        self.assertEqual(data['summary']['closing'], 70)
        bill.invalidate_recordset(['amount_residual'])
        self.assertEqual(bill.amount_residual, 30)

from odoo import SUPERUSER_ID, api, sql_db
from odoo.tests import tagged, TransactionCase
from psycopg2.errors import SerializationFailure
import os
import threading
import time


@tagged('post_install', '-at_install')
class DirectBillSettlementRaceCase(TransactionCase):
    def test_two_settlements_compete_for_the_same_bill_and_custody(self):
        self._run_competition(False)

    def test_settlement_and_cash_return_compete_for_custody(self):
        self._run_competition(True)

    def _run_competition(self, compete_with_return):
        if os.environ.get('BASEER_DIRECT_CUSTODY_CONCURRENCY') != '1':
            self.skipTest('Requires explicitly enabled disposable direct-custody test database')
        self.assertTrue(self.env.cr.dbname.startswith('direct_bill_custody_test_'))
        db = sql_db.db_connect(self.env.cr.dbname)
        suffix = uuid4().hex[:8]
        with db.cursor() as cr:
            initial = api.Environment(cr, SUPERUSER_ID, {})
            company = initial['res.company'].create({'name': 'Direct race ' + suffix, 'currency_id': initial.ref('base.SAR').id})
            ctx = {'allowed_company_ids': company.ids}
            env = api.Environment(cr, SUPERUSER_ID, ctx)
            groups = [env.ref(name).id for name in ('baseer_procurement_requests.group_procurement_accountant', 'account.group_account_manager')]
            actor = env['res.users'].with_context(no_reset_password=True).create({
                'name': 'Direct race ' + suffix, 'login': 'direct-race-' + suffix,
                'company_id': company.id, 'company_ids': [Command.set(company.ids)], 'group_ids': [Command.set(groups)]})
            account = env['account.account']
            def make_account(name, code, kind, reconcile=False):
                return account.create({'name': name, 'code': code, 'account_type': kind, 'reconcile': reconcile,
                                       'company_ids': [Command.set(company.ids)]})
            custody = make_account('Race custody', 'DR101', 'asset_receivable', True)
            cash = make_account('Race cash', 'DR102', 'asset_cash')
            payable = make_account('Race payable', 'DR103', 'liability_payable', True)
            expense = make_account('Race expense', 'DR104', 'expense')
            general = env['account.journal'].create({'name': 'Race entries', 'code': 'DRG', 'type': 'general', 'company_id': company.id})
            bank = env['account.journal'].create({'name': 'Race bank', 'code': 'DRB', 'type': 'bank', 'company_id': company.id, 'default_account_id': cash.id})
            journal = env['account.journal'].create({'name': 'Race bills', 'code': 'DRP', 'type': 'purchase', 'company_id': company.id, 'default_account_id': expense.id})
            company.write({'baseer_procurement_representative_petty_cash_account_id': custody.id,
                           'baseer_procurement_representative_petty_cash_journal_id': general.id,
                           'baseer_procurement_representative_petty_cash_payment_journal_ids': [Command.set(bank.ids)]})
            rep = env['res.partner'].create({'name': 'Race representative', 'company_id': company.id, 'is_purchase_representative': True})
            vendor = env['res.partner'].create({'name': 'Race supplier', 'supplier_rank': 1, 'company_id': company.id})
            vendor.with_company(company).property_account_payable_id = payable
            day = fields.Date.context_today(env.user)
            bill = env['account.move'].with_company(company).create({'move_type': 'in_invoice', 'company_id': company.id,
                'journal_id': journal.id, 'partner_id': vendor.id, 'invoice_date': day, 'date': day, 'ref': 'RACE-' + suffix,
                'invoice_line_ids': [Command.create({'name': 'Race invoice', 'account_id': expense.id, 'quantity': 1,
                                                     'price_unit': 60, 'tax_ids': [Command.clear()]})]})
            bill.action_post()
            actor_env = api.Environment(cr, actor.id, ctx)
            actor_env['baseer.procurement.representative.advance'].submit_funding(False, bank.id, rep.id, '60', str(uuid4()), day)
            company_id, actor_id, rep_id, bill_id, bank_id = company.id, actor.id, rep.id, bill.id, bank.id
            cr.commit()
        ctx = {'allowed_company_ids': [company_id]}
        with db.cursor() as winner_cr, db.cursor() as waiter_cr:
            for cr in (winner_cr, waiter_cr):
                cr.execute("SET LOCAL lock_timeout = '10s'")
                cr.execute("SET LOCAL statement_timeout = '45s'")
            winner = api.Environment(winner_cr, actor_id, ctx)
            waiter = api.Environment(waiter_cr, actor_id, ctx)
            waiter['baseer.procurement.representative.advance']._baseer_representative_available_amount(
                waiter['res.company'].browse(company_id), waiter['res.partner'].browse(rep_id))
            def settle(env, token):
                return env['baseer.procurement.direct.bill.custody.settlement'].submit_direct_bill_settlement(
                    bill_id, rep_id, '40', day, token)
            def competing(env):
                if compete_with_return:
                    return env['baseer.procurement.representative.advance'].submit_aggregate_return(
                        rep_id, bank_id, '40', 'race-return-' + suffix, day)
                return settle(env, 'race-waiter-' + suffix)
            settle(winner, 'race-winner-' + suffix)
            waiter_cr.execute('SELECT pg_backend_pid()')
            pid = waiter_cr.fetchone()[0]
            errors = []
            def compete():
                try:
                    competing(waiter)
                except Exception as error:
                    errors.append(error)
            thread = threading.Thread(target=compete, daemon=True)
            thread.start()
            blocked = False
            deadline = time.monotonic() + 10
            with db.cursor() as observer:
                while time.monotonic() < deadline and thread.is_alive():
                    observer.execute('SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s', [pid])
                    row = observer.fetchone()
                    observer.rollback()
                    if row and row[0] == 'Lock':
                        blocked = True
                        break
                    time.sleep(.02)
            try:
                self.assertTrue(blocked, 'Competing settlements must wait on the financial lock')
            finally:
                winner_cr.commit()
                thread.join(15)
            self.assertFalse(thread.is_alive())
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], SerializationFailure)
            waiter_cr.rollback()
        with db.cursor() as cr:
            retry = api.Environment(cr, actor_id, ctx)
            with self.assertRaises(ValidationError):
                competing(retry)
            cr.rollback()
        with db.cursor() as cr:
            check = api.Environment(cr, SUPERUSER_ID, ctx)
            self.assertEqual(check['account.move'].browse(bill_id).amount_residual, 20)
            self.assertEqual(check['baseer.procurement.representative.advance']._baseer_representative_available_amount(
                check['res.company'].browse(company_id), check['res.partner'].browse(rep_id)), 20)
            self.assertEqual(check['baseer.procurement.direct.bill.custody.settlement'].search_count([('bill_id', '=', bill_id)]), 1)
