"""Committed concurrency proof: run only against the disposable CI database."""
import os
import threading
import time
from uuid import uuid4

from psycopg2.errors import SerializationFailure
from odoo import SUPERUSER_ID, Command, api, fields, sql_db
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class RepresentativeBalanceRaceCase(TransactionCase):
    def test_return_and_invoice_compete_for_independent_funding(self):
        if os.environ.get('BASEER_REPRESENTATIVE_BALANCE_CONCURRENCY') != '1':
            return
        self.assertEqual(self.env.cr.dbname, 'custody_focused',
                         'Committed concurrency fixtures are restricted to the disposable CI database')
        db = sql_db.db_connect(self.env.cr.dbname)
        suffix = uuid4().hex[:10]
        # All fixtures commit through a separate cursor, never TransactionCase.
        with db.cursor() as cr:
            cr.execute("SET LOCAL lock_timeout = '10s'")
            cr.execute("SET LOCAL statement_timeout = '45s'")
            setup = api.Environment(cr, SUPERUSER_ID, {})
            company = setup['res.company'].create({
                'name': 'Representative balance race ' + suffix,
                'currency_id': setup.ref('base.SAR').id,
            })
            group_ids = [setup.ref(xmlid).id for xmlid in (
                'baseer_procurement_requests.group_procurement_manager',
                'baseer_procurement_requests.group_procurement_cashier',
                'baseer_procurement_requests.group_procurement_accountant',
                'account.group_account_manager')]
            actor = setup['res.users'].with_context(no_reset_password=True).create({
                'name': 'Representative balance race ' + suffix,
                'login': 'representative-balance-race-' + suffix,
                'company_id': company.id, 'company_ids': [Command.set(company.ids)],
                'group_ids': [Command.set(group_ids)],
            })
            env = api.Environment(cr, SUPERUSER_ID, {'allowed_company_ids': company.ids})
            account = env['account.account'].create({
                'name': 'Representative balance race receivable', 'code': 'RBR101',
                'account_type': 'asset_receivable', 'reconcile': True,
                'company_ids': [Command.set(company.ids)],
            })
            cash = env['account.account'].create({
                'name': 'Representative balance race cash', 'code': 'RBR102',
                'account_type': 'asset_cash', 'company_ids': [Command.set(company.ids)],
            })
            expense = env['account.account'].create({
                'name': 'Representative balance race expense', 'code': 'RBR103',
                'account_type': 'expense', 'company_ids': [Command.set(company.ids)],
            })
            payable = env['account.account'].create({
                'name': 'Representative balance race payable', 'code': 'RBR104',
                'account_type': 'liability_payable', 'reconcile': True,
                'company_ids': [Command.set(company.ids)],
            })
            general = env['account.journal'].create({
                'name': 'Representative balance race journal', 'code': 'RBG',
                'type': 'general', 'company_id': company.id,
            })
            bank = env['account.journal'].create({
                'name': 'Representative balance race bank', 'code': 'RBB',
                'type': 'bank', 'company_id': company.id, 'default_account_id': cash.id,
            })
            env['account.journal'].create({
                'name': 'Representative balance race purchases', 'code': 'RBP',
                'type': 'purchase', 'company_id': company.id, 'sequence': -100,
                'default_account_id': expense.id,
            })
            company.sudo().write({
                'baseer_procurement_representative_petty_cash_account_id': account.id,
                'baseer_procurement_representative_petty_cash_journal_id': general.id,
                'baseer_procurement_representative_petty_cash_payment_journal_ids': [Command.set(bank.ids)],
            })
            vendor = env['res.partner'].create({'name': 'Race supplier ' + suffix, 'supplier_rank': 1})
            vendor.property_account_payable_id = payable
            spend_plan = env.ref('baseer_native_spend.spend_plan', raise_if_not_found=False)
            if spend_plan:
                analytic = env['account.analytic.account'].create({
                    'name': 'Race spend ' + suffix, 'plan_id': spend_plan.id, 'company_id': company.id,
                })
                env['account.analytic.distribution.model'].create({
                    'partner_id': vendor.id, 'company_id': company.id,
                    'analytic_distribution': {str(analytic.id): 100},
                })
            pairs = []
            today = fields.Date.context_today(env.user)
            actor_env = api.Environment(cr, actor.id, {'allowed_company_ids': company.ids})
            for order in ('return_first', 'invoice_first'):
                rep = env['res.partner'].create({
                    'name': 'Race rep ' + suffix + order, 'company_id': company.id,
                    'is_purchase_representative': True,
                })
                advance = actor_env['baseer.procurement.representative.advance'].submit_funding(
                    False, bank.id, rep.id, '25.00', str(uuid4()), today,
                )
                batch = actor_env['baseer.purchase.batch'].create({
                    'company_id': company.id,
                    'line_ids': [Command.create({
                        'partner_id': vendor.id, 'supplier_ref': 'RBR-' + suffix + order,
                        'entry_type': 'purchase', 'gross_amount': 20,
                        'payment_source_type': 'representative_petty_cash',
                        'representative_petty_cash_representative_id': rep.id,
                    })],
                })
                pairs.append((order, rep.id, batch.id, advance))
            company_id, actor_id, bank_id = company.id, actor.id, bank.id
            cr.commit()
        ctx = {'allowed_company_ids': [company_id]}
        for order, rep_id, batch_id, advance_id in pairs:
            with self.subTest(order=order), db.cursor() as winner_cr, db.cursor() as waiter_cr:
                for cr in (winner_cr, waiter_cr):
                    cr.execute("SET LOCAL lock_timeout = '10s'")
                    cr.execute("SET LOCAL statement_timeout = '45s'")
                winner = api.Environment(winner_cr, actor_id, ctx)
                waiter = api.Environment(waiter_cr, actor_id, ctx)
                # Establish an old repeatable-read snapshot before the winner commits.
                self.assertEqual(waiter['baseer.procurement.representative.advance'].
                                 _baseer_representative_available_amount(
                                     waiter['res.company'].browse(company_id),
                                     waiter['res.partner'].browse(rep_id)), 25)
                token = 'return-race-' + suffix + order
                def return_cash(env):
                    return env['baseer.procurement.representative.advance'].submit_aggregate_return(
                        rep_id, bank_id, '10.00', token, today)
                def approve_invoice(env):
                    return env['baseer.purchase.batch'].browse(batch_id).action_approve()
                first, second = ((return_cash, approve_invoice) if order == 'return_first'
                                 else (approve_invoice, return_cash))
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
                    self.assertTrue(blocked, 'Competing operations must wait on the shared balance mutex')
                finally:
                    winner_cr.commit()
                    thread.join(15)
                self.assertFalse(thread.is_alive())
                self.assertEqual(len(errors), 1)
                self.assertIsInstance(errors[0], SerializationFailure)
                waiter_cr.rollback()
            with db.cursor() as retry_cr:
                retry = api.Environment(retry_cr, actor_id, ctx)
                expected_error = UserError if order == 'return_first' else ValidationError
                with self.assertRaises(expected_error):
                    second(retry)
                retry_cr.rollback()
            with db.cursor() as check_cr:
                check = api.Environment(check_cr, actor_id, ctx)
                advance = check['baseer.procurement.representative.advance'].browse(advance_id)
                self.assertFalse(advance.procurement_request_id)
                remaining = check['baseer.procurement.representative.advance']._baseer_representative_available_amount(
                    check['res.company'].browse(company_id), check['res.partner'].browse(rep_id))
                self.assertEqual(remaining, 15 if order == 'return_first' else 5)
                batch = check['baseer.purchase.batch'].browse(batch_id)
                self.assertEqual(batch.state, 'draft' if order == 'return_first' else 'approved')
                self.assertEqual(len(batch.line_ids.representative_petty_cash_invoice_settlement_id),
                                 0 if order == 'return_first' else 1)
