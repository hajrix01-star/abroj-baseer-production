from uuid import uuid4
import os
import threading
import time

from odoo import Command, fields, SUPERUSER_ID, api, sql_db
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged
from psycopg2.errors import SerializationFailure

from .test_representative_petty_cash import RepresentativePettyCashCase


class RepresentativeFundingReversalCase(RepresentativePettyCashCase):
    def _funding(self, amount='100.00'):
        model = self.env['baseer.procurement.representative.advance']
        return model.browse(model.submit_funding(
            False, self.bank_journal.id, self.representative.id, amount, str(uuid4()), '2025-01-15',
        ))

    def test_reversal_keeps_history_and_monthly_balances(self):
        model = self.env['baseer.procurement.representative.advance']
        funding = self._funding()
        token = str(uuid4())
        reversal_id = model.submit_funding_reversal(funding.id, 'Wrong funding', '2025-02-10', token)
        self.assertEqual(reversal_id, model.submit_funding_reversal(funding.id, 'Wrong funding', '2025-02-10', token))
        reversal = model.browse(reversal_id)
        self.assertEqual(reversal.origin_id, funding)
        self.assertEqual(reversal.move_id.reversed_entry_id, funding.move_id)
        self.assertEqual(reversal.reversal_reason, 'Wrong funding')
        self.assertEqual(reversal.move_id.state, 'posted')
        self.assertEqual(sum(reversal.move_id.line_ids.mapped('debit')), 100)
        self.assertEqual(sum(reversal.move_id.line_ids.mapped('credit')), 100)
        self.assertTrue(funding.move_id.line_ids.filtered('baseer_representative_petty_cash_id').reconciled)
        self.assertEqual(funding.returned_amount, 0)
        self.assertEqual(funding.remaining_amount, 0)
        self.assertEqual(model._baseer_representative_available_amount(self.company, self.representative), 0)
        january = model.dashboard_data(self.representative.id, '2025-01-01')['summary']
        february = model.dashboard_data(self.representative.id, '2025-02-01')['summary']
        self.assertEqual((january['funded'], january['closing']), (100, 100))
        self.assertEqual((february['opening'], february['returned'], february['reversed'], february['closing']), (100, 0, 100, 0))
        rows = model.dashboard_daily_movements(self.representative.id, '2025-02-01', '', 'reversal')['daily_movements']
        self.assertEqual([(row['type'], row['amount']) for row in rows], [('reversal', 100)])
        with self.assertRaises(ValidationError):
            model.submit_funding_reversal(funding.id, 'Again', '2025-02-11', str(uuid4()))
        with self.assertRaises(UserError):
            reversal.move_id.button_draft()

    def test_reversal_rejects_reconciled_funding_and_bad_inputs(self):
        model = self.env['baseer.procurement.representative.advance']
        funding = self._funding()
        for reason, day in [('', '2025-02-10'), ('wrong', '2025-01-01')]:
            with self.assertRaises(ValidationError):
                model.submit_funding_reversal(funding.id, reason, day, str(uuid4()))
        model.submit_aggregate_return(self.representative.id, self.bank_journal.id, '10.00', str(uuid4()), '2025-01-20')
        with self.assertRaises(ValidationError):
            model.submit_funding_reversal(funding.id, 'wrong', '2025-02-10', str(uuid4()))
        self.assertEqual(model._baseer_representative_available_amount(self.company, self.representative), 90)

    def test_reversal_requires_accountant_and_active_company(self):
        model = self.env['baseer.procurement.representative.advance']
        funding = self._funding()
        other = self.env['res.company'].create({'name': 'Reversal isolation', 'currency_id': self.company.currency_id.id})
        self.env.user.company_ids |= other
        with self.assertRaises(ValidationError):
            model.with_company(other).submit_funding_reversal(funding.id, 'wrong', '2025-02-10', str(uuid4()))
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Reversal viewer', 'login': 'reversal-viewer-' + str(uuid4()),
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        })
        with self.assertRaises(AccessError):
            model.with_user(user).submit_funding_reversal(funding.id, 'wrong', '2025-02-10', str(uuid4()))

    def test_reversal_respects_locked_period(self):
        model = self.env['baseer.procurement.representative.advance']
        funding = self._funding()
        day = fields.Date.context_today(self.env.user)
        self.company.write({'fiscalyear_lock_date': day})
        with self.assertRaises(ValidationError):
            model.with_context(ignore_exceptions=True).submit_funding_reversal(funding.id, 'wrong', day, str(uuid4()))
        self.assertFalse(model.search([('movement_type', '=', 'reversal'), ('origin_id', '=', funding.id)]))

    def test_reversal_rejects_foreign_currency_configuration(self):
        model = self.env['baseer.procurement.representative.advance']
        funding = self._funding()
        currency = self.env['res.currency'].with_context(active_test=False).search([
            ('id', '!=', self.company.currency_id.id), ('name', '=', 'EUR'),
        ], limit=1)
        self.assertTrue(currency)
        currency.active = True
        line = funding.move_id.line_ids.filtered('baseer_representative_petty_cash_id')
        self.env.cr.execute('UPDATE account_move_line SET currency_id = %s WHERE id = %s', (currency.id, line.id))
        line.invalidate_recordset(['currency_id'])
        with self.assertRaisesRegex(ValidationError, 'Foreign-currency'):
            model.submit_funding_reversal(funding.id, 'wrong', '2025-02-10', str(uuid4()))
        self.assertFalse(model.search([('movement_type', '=', 'reversal'), ('origin_id', '=', funding.id)]))


@tagged('post_install', '-at_install')
class RepresentativeFundingReversalRaceCase(TransactionCase):
    def test_return_and_reversal_are_serialized(self):
        if os.environ.get('BASEER_REVERSAL_CONCURRENCY') != '1':
            self.skipTest('Requires explicitly enabled disposable reversal test database')
        self.assertTrue(self.env.cr.dbname.startswith('custody_reversal_test_'))
        db = sql_db.db_connect(self.env.cr.dbname)
        suffix = uuid4().hex[:10]
        with db.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            company = env['res.company'].create({'name': 'Reversal race ' + suffix, 'currency_id': env.ref('base.SAR').id})
            ctx = {'allowed_company_ids': company.ids}
            env = api.Environment(cr, SUPERUSER_ID, ctx)
            actor = env['res.users'].with_context(no_reset_password=True).create({
                'name': 'Reversal race ' + suffix, 'login': 'reversal-race-' + suffix,
                'company_id': company.id, 'company_ids': [Command.set(company.ids)],
                'group_ids': [Command.set([env.ref('baseer_procurement_requests.group_procurement_accountant').id,
                                           env.ref('account.group_account_manager').id])],
            })
            account = env['account.account'].create({'name': 'Reversal receivable', 'code': 'RR101',
                'account_type': 'asset_receivable', 'reconcile': True, 'company_ids': [Command.set(company.ids)]})
            cash = env['account.account'].create({'name': 'Reversal cash', 'code': 'RR102',
                'account_type': 'asset_cash', 'company_ids': [Command.set(company.ids)]})
            general = env['account.journal'].create({'name': 'Reversal general', 'code': 'RRG',
                'type': 'general', 'company_id': company.id})
            bank = env['account.journal'].create({'name': 'Reversal bank', 'code': 'RRB',
                'type': 'bank', 'company_id': company.id, 'default_account_id': cash.id})
            company.write({'baseer_procurement_representative_petty_cash_account_id': account.id,
                           'baseer_procurement_representative_petty_cash_journal_id': general.id,
                           'baseer_procurement_representative_petty_cash_payment_journal_ids': [Command.set(bank.ids)]})
            actor_env = api.Environment(cr, actor.id, ctx)
            today = fields.Date.context_today(actor_env.user)
            pairs = []
            for order in ('reversal_first', 'return_first'):
                representative = env['res.partner'].create({'name': 'Reversal rep ' + suffix + order,
                    'company_id': company.id, 'is_purchase_representative': True})
                funding_id = actor_env['baseer.procurement.representative.advance'].submit_funding(
                    False, bank.id, representative.id, '25.00', str(uuid4()), today)
                pairs.append((order, representative.id, funding_id))
            company_id, actor_id, bank_id = company.id, actor.id, bank.id
            cr.commit()
        ctx = {'allowed_company_ids': [company_id]}
        for order, representative_id, funding_id in pairs:
            with self.subTest(order=order), db.cursor() as winner_cr, db.cursor() as waiter_cr:
                for cr in (winner_cr, waiter_cr):
                    cr.execute("SET LOCAL lock_timeout = '10s'")
                    cr.execute("SET LOCAL statement_timeout = '45s'")
                winner = api.Environment(winner_cr, actor_id, ctx)
                waiter = api.Environment(waiter_cr, actor_id, ctx)
                self.assertEqual(waiter['baseer.procurement.representative.advance']._baseer_representative_available_amount(
                    waiter['res.company'].browse(company_id), waiter['res.partner'].browse(representative_id)), 25)
                def reverse(env):
                    return env['baseer.procurement.representative.advance'].submit_funding_reversal(
                        funding_id, 'Correction', today, 'reverse-' + suffix + order)
                def return_cash(env):
                    return env['baseer.procurement.representative.advance'].submit_aggregate_return(
                        representative_id, bank_id, '10.00', 'return-' + suffix + order, today)
                first, second = (reverse, return_cash) if order == 'reversal_first' else (return_cash, reverse)
                first(winner)
                waiter_cr.execute('SELECT pg_backend_pid()')
                pid = waiter_cr.fetchone()[0]
                errors = []
                def compete():
                    try:
                        second(waiter)
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
                    self.assertTrue(blocked, 'Competing financial actions must wait on the balance lock')
                finally:
                    winner_cr.commit()
                    thread.join(15)
                self.assertFalse(thread.is_alive())
                self.assertEqual(len(errors), 1)
                self.assertIsInstance(errors[0], SerializationFailure)
                waiter_cr.rollback()
            with db.cursor() as retry_cr:
                retry = api.Environment(retry_cr, actor_id, ctx)
                with self.assertRaises(ValidationError):
                    second(retry)
                retry_cr.rollback()
            with db.cursor() as check_cr:
                check = api.Environment(check_cr, actor_id, ctx)
                balance = check['baseer.procurement.representative.advance']._baseer_representative_available_amount(
                    check['res.company'].browse(company_id), check['res.partner'].browse(representative_id))
                self.assertEqual(balance, 0 if order == 'reversal_first' else 15)

    def test_invoice_and_duplicate_reversal_are_serialized(self):
        if os.environ.get('BASEER_REVERSAL_CONCURRENCY') != '1':
            self.skipTest('Requires explicitly enabled disposable reversal test database')
        self.assertTrue(self.env.cr.dbname.startswith('custody_reversal_test_'))
        db = sql_db.db_connect(self.env.cr.dbname)
        suffix = uuid4().hex[:10]
        with db.cursor() as cr:
            setup = api.Environment(cr, SUPERUSER_ID, {})
            company = setup['res.company'].create({'name': 'Reversal invoice race ' + suffix,
                                                    'currency_id': setup.ref('base.SAR').id})
            ctx = {'allowed_company_ids': company.ids}
            env = api.Environment(cr, SUPERUSER_ID, ctx)
            groups = [env.ref(name).id for name in (
                'baseer_procurement_requests.group_procurement_manager',
                'baseer_procurement_requests.group_procurement_cashier',
                'baseer_procurement_requests.group_procurement_accountant',
                'account.group_account_manager')]
            actor = env['res.users'].with_context(no_reset_password=True).create({
                'name': 'Reversal invoice race ' + suffix, 'login': 'reversal-invoice-' + suffix,
                'company_id': company.id, 'company_ids': [Command.set(company.ids)],
                'group_ids': [Command.set(groups)],
            })
            account = env['account.account'].create({'name': 'Reversal race receivable', 'code': 'RRI1',
                'account_type': 'asset_receivable', 'reconcile': True, 'company_ids': [Command.set(company.ids)]})
            cash = env['account.account'].create({'name': 'Reversal race cash', 'code': 'RRI2',
                'account_type': 'asset_cash', 'company_ids': [Command.set(company.ids)]})
            expense = env['account.account'].create({'name': 'Reversal race expense', 'code': 'RRI3',
                'account_type': 'expense', 'company_ids': [Command.set(company.ids)]})
            payable = env['account.account'].create({'name': 'Reversal race payable', 'code': 'RRI4',
                'account_type': 'liability_payable', 'reconcile': True, 'company_ids': [Command.set(company.ids)]})
            general = env['account.journal'].create({'name': 'Reversal race entries', 'code': 'RIG',
                'type': 'general', 'company_id': company.id})
            bank = env['account.journal'].create({'name': 'Reversal race bank', 'code': 'RIB',
                'type': 'bank', 'company_id': company.id, 'default_account_id': cash.id})
            env['account.journal'].create({'name': 'Reversal race purchases', 'code': 'RIP',
                'type': 'purchase', 'company_id': company.id, 'sequence': -100, 'default_account_id': expense.id})
            company.write({'baseer_procurement_representative_petty_cash_account_id': account.id,
                'baseer_procurement_representative_petty_cash_journal_id': general.id,
                'baseer_procurement_representative_petty_cash_payment_journal_ids': [Command.set(bank.ids)]})
            vendor = env['res.partner'].create({'name': 'Reversal race vendor ' + suffix, 'supplier_rank': 1})
            vendor.property_account_payable_id = payable
            plan = env.ref('baseer_native_spend.spend_plan', raise_if_not_found=False)
            if plan:
                analytic = env['account.analytic.account'].create({'name': 'Reversal race spend ' + suffix,
                    'plan_id': plan.id, 'company_id': company.id})
                env['account.analytic.distribution.model'].create({'partner_id': vendor.id, 'company_id': company.id,
                    'analytic_distribution': {str(analytic.id): 100}})
            actor_env = api.Environment(cr, actor.id, ctx)
            today = fields.Date.context_today(actor_env.user)
            scenarios = []
            for order in ('reversal_first', 'invoice_first', 'double_reversal'):
                representative = env['res.partner'].create({'name': 'Reversal invoice rep ' + suffix + order,
                    'company_id': company.id, 'is_purchase_representative': True})
                funding_id = actor_env['baseer.procurement.representative.advance'].submit_funding(
                    False, bank.id, representative.id, '25.00', str(uuid4()), today)
                batch = actor_env['baseer.purchase.batch'].create({'company_id': company.id,
                    'line_ids': [Command.create({'partner_id': vendor.id, 'supplier_ref': 'RRI-' + suffix + order,
                        'entry_type': 'purchase', 'gross_amount': 20, 'payment_source_type': 'representative_petty_cash',
                        'representative_petty_cash_representative_id': representative.id})]})
                scenarios.append((order, representative.id, funding_id, batch.id))
            company_id, actor_id = company.id, actor.id
            cr.commit()
        ctx = {'allowed_company_ids': [company_id]}
        for order, representative_id, funding_id, batch_id in scenarios:
            with self.subTest(order=order), db.cursor() as winner_cr, db.cursor() as waiter_cr:
                for cr in (winner_cr, waiter_cr):
                    cr.execute("SET LOCAL lock_timeout = '10s'")
                    cr.execute("SET LOCAL statement_timeout = '45s'")
                winner = api.Environment(winner_cr, actor_id, ctx)
                waiter = api.Environment(waiter_cr, actor_id, ctx)
                advance = waiter['baseer.procurement.representative.advance']
                self.assertEqual(advance._baseer_representative_available_amount(
                    waiter['res.company'].browse(company_id), waiter['res.partner'].browse(representative_id)), 25)
                def reverse(env, token):
                    return env['baseer.procurement.representative.advance'].submit_funding_reversal(
                        funding_id, 'Correction', today, token)
                def invoice(env):
                    return env['baseer.purchase.batch'].browse(batch_id).action_approve()
                first_token = 'reverse-first-' + suffix + order
                second_token = 'reverse-second-' + suffix + order
                if order == 'reversal_first':
                    first, second = lambda env: reverse(env, first_token), invoice
                elif order == 'invoice_first':
                    first, second = invoice, lambda env: reverse(env, second_token)
                else:
                    first, second = lambda env: reverse(env, first_token), lambda env: reverse(env, second_token)
                first(winner)
                waiter_cr.execute('SELECT pg_backend_pid()')
                pid = waiter_cr.fetchone()[0]
                errors = []
                def compete():
                    try:
                        second(waiter)
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
                    self.assertTrue(blocked, 'Competing actions must wait on the financial lock')
                finally:
                    winner_cr.commit()
                    thread.join(15)
                self.assertFalse(thread.is_alive())
                self.assertEqual(len(errors), 1)
                self.assertIsInstance(errors[0], SerializationFailure)
                waiter_cr.rollback()
            with db.cursor() as retry_cr:
                retry = api.Environment(retry_cr, actor_id, ctx)
                expected_error = UserError if order == 'reversal_first' else ValidationError
                with self.assertRaises(expected_error):
                    second(retry)
                retry_cr.rollback()
            with db.cursor() as check_cr:
                check = api.Environment(check_cr, actor_id, ctx)
                model = check['baseer.procurement.representative.advance']
                balance = model._baseer_representative_available_amount(
                    check['res.company'].browse(company_id), check['res.partner'].browse(representative_id))
                self.assertEqual(balance, 5 if order == 'invoice_first' else 0)
                reversals = model.search([('origin_id', '=', funding_id), ('movement_type', '=', 'reversal')])
                self.assertEqual(len(reversals), 0 if order == 'invoice_first' else 1)
                original = model.browse(funding_id)
                reverse_moves = check['account.move'].search([('reversed_entry_id', '=', original.move_id.id),
                                                                ('state', '=', 'posted')])
                self.assertEqual(len(reverse_moves), len(reversals))
                self.assertEqual(check['baseer.purchase.batch'].browse(batch_id).state,
                                 'approved' if order == 'invoice_first' else 'draft')
