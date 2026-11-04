from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged

from .test_representative_petty_cash import RepresentativePettyCashCase


@tagged('post_install', '-at_install')
class ReceiptCustodyCase(TransactionCase):
    """All financial writes use rollback-only isolated test fixtures."""
    def setUp(self):
        super().setUp()
        self.env.user.group_ids |= self.env.ref('baseer_procurement_requests.group_procurement_accountant')
        self.env.user.group_ids |= self.env.ref('baseer_procurement_requests.group_procurement_manager')
        self.env.user.group_ids |= self.env.ref('base.group_erp_manager')
        self.env.user.group_ids |= self.env.ref('baseer_procurement_requests.group_procurement_cashier')
        self.company = self.env.company
        self.company.currency_id.active = True
        self.warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.company.id)], limit=1)
        category = self.env['product.category'].create({'name': 'Representative petty cash test category'})
        product = self.env['product.product'].create({
            'name': 'Representative petty cash test product', 'categ_id': category.id,
            'company_id': self.company.id,
        })
        self.option = self.env['baseer.procurement.purchase.option'].create({
            'name': 'Unit', 'company_id': self.company.id, 'product_id': product.id,
            'uom_id': product.uom_id.id,
        })
        self.representative = self.env['res.partner'].create({
            'name': 'Representative petty cash buyer', 'company_id': self.company.id,
        })
        self.representative.with_company(self.company).write({'is_purchase_representative': True})
        Account = self.env['account.account']
        self.petty_cash_account = Account.create({
            'name': 'Representative petty cash receivable', 'code': 'RPA701',
            'account_type': 'asset_receivable', 'reconcile': True,
            'company_ids': [Command.set(self.company.ids)],
        })
        cash_account = Account.create({
            'name': 'Representative petty cash bank', 'code': 'RPA702',
            'account_type': 'asset_cash', 'company_ids': [Command.set(self.company.ids)],
        })
        self.general_journal = self.env['account.journal'].create({
            'name': 'Representative petty cash entries', 'code': 'RPAG', 'type': 'general',
            'company_id': self.company.id,
        })
        self.bank_journal = self.env['account.journal'].create({
            'name': 'Representative petty cash bank', 'code': 'RPAB', 'type': 'bank',
            'company_id': self.company.id, 'default_account_id': cash_account.id,
        })
        self.company.write({
            'baseer_procurement_representative_petty_cash_account_id': self.petty_cash_account.id,
            'baseer_procurement_representative_petty_cash_journal_id': self.general_journal.id,
            'baseer_procurement_representative_petty_cash_payment_journal_ids': [Command.set([self.bank_journal.id])],
        })

    _request = RepresentativePettyCashCase._request
    _sent_request = RepresentativePettyCashCase._sent_request

    def _cashier(self):
        return self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Receipt custody branch manager', 'login': 'receipt-custody-%s' % uuid4(),
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([self.env.ref('baseer_procurement_requests.group_procurement_cashier').id])],
        })

    def _rows(self, request):
        return [{'line_id': request.line_ids.id, 'actual_qty': '3.00', 'actual_price': '4.00'}]

    def _payload(self, request, **changes):
        context = request.prepare_receipt_custody(request.id)
        return {**{'snapshot': context['snapshot'], 'amount': '27.50',
                   'payment_journal_id': self.bank_journal.id,
                   'movement_date': fields.Date.to_string(fields.Date.context_today(self))}, **changes}

    def test_receipt_custody_atomic_post_and_branch_review(self):
        request = self._sent_request().with_user(self._cashier())
        before = request.read(['write_date', 'state', 'client_payload_hash'])[0]
        counts = {m: self.env[m].sudo().search_count([]) for m in (
            'account.move', 'baseer.procurement.representative.advance', 'stock.picking', 'mail.message')}
        payload = self._payload(request)
        self.assertEqual(before, request.read(['write_date', 'state', 'client_payload_hash'])[0])
        for model, count in counts.items():
            self.assertEqual(self.env[model].sudo().search_count([]), count)
        self.assertFalse(request.env.su)
        request.confirm_actual_from_catalog(request.id, self._rows(request), payload)
        request.invalidate_recordset()
        self.assertEqual(request.state, 'purchased')
        self.assertTrue(request.receipt_custody_confirmed)
        funding = request.sudo()._receipt_custody_fundings()
        self.assertEqual(len(funding), 1)
        self.assertEqual(funding.amount, 27.5)  # deliberately differs from merchandise 12
        self.assertEqual(funding.created_by_id, request.env.user)
        self.assertEqual(funding.move_id.state, 'posted')
        debit = funding.move_id.line_ids.filtered(lambda l: l.account_id == self.petty_cash_account)
        self.assertEqual(debit.debit, 27.5)
        self.assertEqual(sum(funding.move_id.line_ids.mapped('credit')), 27.5)
        self.assertEqual(funding.move_id.line_ids.partner_id, self.representative)
        self.assertEqual(debit.baseer_representative_petty_cash_id, funding)
        dashboard = self.env['baseer.procurement.representative.advance'].with_user(request.env.user).dashboard_data()
        self.assertFalse(dashboard['can_record'])
        self.assertEqual(next(m['request_id'] for m in dashboard['movements'] if m['id'] == funding.id), request.id)
        self.assertEqual(request.action_open_receipt_custody()['params']['representative_id'], self.representative.id)
        request.action_confirm_actual_purchase()  # retry never posts a second movement
        self.assertEqual(len(request.sudo()._receipt_custody_fundings()), 1)
        with self.assertRaises(AccessError):
            self.env['baseer.procurement.representative.advance'].with_user(request.env.user).submit_return(
                funding.id, self.bank_journal.id, 1, str(uuid4()))

    def test_receipt_custody_existing_manual_reuse_and_later_manual_guard(self):
        request = self._sent_request()
        model = self.env['baseer.procurement.representative.advance']
        token = str(uuid4())
        funding_id = model.submit_funding(request.id, self.bank_journal.id, self.representative.id,
                                         31, token, fields.Date.context_today(self))
        context = request.prepare_receipt_custody(request.id)
        self.assertTrue(context['existing_funded'])
        self.assertEqual(context['funding_records'][0]['movement_date'], str(fields.Date.context_today(self)))
        request.confirm_actual_from_catalog(request.id, self._rows(request), {'snapshot': context['snapshot']})
        self.assertEqual(request._receipt_custody_fundings().ids, [funding_id])
        self.assertEqual(model.submit_funding(request.id, self.bank_journal.id, self.representative.id,
                                            31, token, fields.Date.context_today(self)), funding_id)
        with self.assertRaises(UserError):
            model.submit_funding(request.id, self.bank_journal.id, self.representative.id,
                                 1, str(uuid4()), fields.Date.context_today(self))

    def test_receipt_custody_validation_stale_bypass_and_legacy(self):
        request = self._sent_request()
        payload = self._payload(request)
        for amount in ('0', '-1', 'NaN', 'Infinity', '1.001', '1e1000'):
            with self.subTest(amount=amount), self.assertRaises(ValidationError):
                request.confirm_actual_from_catalog(request.id, self._rows(request), {**payload, 'amount': amount})
        with self.assertRaises(UserError):
            request.action_confirm_actual_purchase()
        with self.assertRaises(ValidationError):
            request.confirm_actual_from_catalog(request.id, self._rows(request))
        lock_date_before = self.company.fiscalyear_lock_date
        funding_count = self.env['baseer.procurement.representative.advance'].search_count([])
        move_count = self.env['account.move'].search_count([])
        self.company.write({'fiscalyear_lock_date': fields.Date.context_today(self)})
        try:
            with self.assertRaisesRegex(ValidationError, 'locked accounting period'):
                request.confirm_actual_from_catalog(request.id, self._rows(request), payload)
            self.assertEqual(self.env['baseer.procurement.representative.advance'].search_count([]), funding_count)
            self.assertEqual(self.env['account.move'].search_count([]), move_count)
            self.assertEqual(request.state, 'sent')
            self.assertFalse(request.receipt_custody_confirmed)
        finally:
            self.company.write({'fiscalyear_lock_date': lock_date_before})
        for proof in (True, 'proof', {}):
            with self.assertRaises(AccessError):
                request.sudo().with_context(_baseer_receipt_custody_proof=proof).write({'receipt_custody_confirmed': True})
        with self.assertRaises(AccessError):
            self.env['baseer.procurement.request'].create({'receipt_custody_confirmed': False})
        with self.assertRaises(AccessError):
            self.env['baseer.procurement.request'].with_context(default_receipt_custody_confirmed=True).create({})
        self.env['baseer.procurement.representative.advance'].submit_funding(
            request.id, self.bank_journal.id, self.representative.id, 9, str(uuid4()), fields.Date.context_today(self))
        with self.assertRaisesRegex(UserError, 'changed'):
            request.confirm_actual_from_catalog(request.id, self._rows(request), payload)
        legacy = self._request()
        employee = self.env['hr.employee'].create({'name': 'Legacy buyer', 'company_id': self.company.id})
        legacy.write({'representative_partner_id': False, 'purchaser_id': employee.id})
        legacy.action_mark_sent()
        with self.assertRaisesRegex(UserError, 'active purchase representative contact'):
            legacy.prepare_receipt_custody(legacy.id)

    def test_receipt_custody_later_native_failure_rolls_back_funding(self):
        request = self._sent_request()
        payload = self._payload(request)
        counts = {m: self.env[m].search_count([]) for m in ('account.move', 'baseer.procurement.representative.advance')}
        original = type(request).action_confirm_actual_purchase
        def fail_after_native(record):
            original(record)
            raise UserError('Injected later native failure')
        with patch.object(type(request), 'action_confirm_actual_purchase', fail_after_native):
            with self.assertRaisesRegex(UserError, 'Injected'):
                request.confirm_actual_from_catalog(request.id, self._rows(request), payload)
        request.invalidate_recordset()
        self.assertEqual(request.state, 'sent')
        self.assertFalse(request.receipt_custody_confirmed)
        for model, count in counts.items():
            self.assertEqual(self.env[model].search_count([]), count)

    def test_receipt_custody_company_role_currency_and_cancel_guards(self):
        request = self._sent_request()
        outsider = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'POS only', 'login': 'receipt-pos-%s' % uuid4(),
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([self.env.ref('point_of_sale.group_pos_user').id])],
        })
        with self.assertRaises(AccessError):
            request.with_user(outsider).prepare_receipt_custody(request.id)
        with self.assertRaises(AccessError):
            self.env['baseer.procurement.representative.advance'].with_user(outsider).dashboard_data()
        other = self.env['res.company'].create({'name': 'Receipt other company'})
        with self.assertRaises(AccessError):
            request.with_context(allowed_company_ids=[other.id, self.company.id]).prepare_receipt_custody(request.id)
        foreign = self.env['res.currency'].search([('id', '!=', self.company.currency_id.id)], limit=1)
        foreign.active = True
        self.bank_journal.currency_id = foreign
        with self.assertRaisesRegex(UserError, 'company-currency'):
            request.prepare_receipt_custody(request.id)
        self.bank_journal.currency_id = False
        for record in (self.petty_cash_account, self.general_journal):
            record.currency_id = foreign
            with self.assertRaisesRegex(UserError, 'company-currency'):
                request.prepare_receipt_custody(request.id)
            record.currency_id = False
        request.write({'cancellation_reason': 'Fixture cancellation'})
        request.action_cancel()
        with self.assertRaises(UserError):
            request.prepare_receipt_custody(request.id)


    def test_receipt_custody_historical_purchased_replay_does_not_backfill(self):
        request = self._sent_request()
        request.confirm_actual_from_catalog(request.id, self._rows(request), self._payload(request))
        # Reproduce a pre-feature purchased row, solely within this rollback fixture.
        self.env.cr.execute('UPDATE baseer_procurement_request SET receipt_custody_confirmed = FALSE WHERE id = %s', [request.id])
        request.invalidate_recordset()
        before = request.read(['write_date', 'receipt_custody_confirmed', 'state'])[0]
        request.action_confirm_actual_purchase()
        self.assertEqual(request.read(['write_date', 'receipt_custody_confirmed', 'state'])[0], before)
        self.assertFalse(request.receipt_custody_confirmed)

    def test_receipt_custody_real_repeatable_read_manual_receipt_races(self):
        """Real competing financial RPCs, exclusively in the disposable CI database."""
        import logging
        import os
        import threading
        import time
        from psycopg2.errors import SerializationFailure
        from odoo import SUPERUSER_ID, api, sql_db
        logger = logging.getLogger(__name__)
        if os.environ.get('BASEER_RECEIPT_CUSTODY_CONCURRENCY') != '1':
            logger.info('Receipt custody financial race not requested outside disposable CI')
            return
        self.assertEqual(self.env.cr.dbname, 'baseer_procurement_route_ci',
                         'Committed concurrency fixtures are permitted only in the disposable CI database')
        db = sql_db.db_connect(self.env.cr.dbname)
        owned = uuid4().hex[:10]
        # Independent cursor: never commit the TransactionCase transaction.
        with db.cursor() as setup_cr:
            setup = api.Environment(setup_cr, SUPERUSER_ID, {})
            company = setup['res.company'].create({'name': 'Receipt race %s' % owned})
            groups = [setup.ref(name).id for name in (
                'baseer_procurement_requests.group_procurement_manager',
                'baseer_procurement_requests.group_procurement_cashier',
                'baseer_procurement_requests.group_procurement_accountant',
                'account.group_account_manager')]
            actor = setup['res.users'].with_context(no_reset_password=True).create({
                'name': 'Receipt race %s' % owned, 'login': 'receipt-race-%s' % owned,
                'company_id': company.id, 'company_ids': [Command.set(company.ids)],
                'group_ids': [Command.set(groups)],
            })
            env = api.Environment(setup_cr, actor.id, {'allowed_company_ids': company.ids})
            warehouse = env['stock.warehouse'].search([('company_id', '=', company.id)], limit=1)
            if not warehouse:
                warehouse = env['stock.warehouse'].sudo().create({
                    'name': 'Receipt race warehouse', 'code': 'R%s' % str(company.id)[-3:], 'company_id': company.id})
            representative = env['res.partner'].create({
                'name': 'Receipt race contact %s' % owned, 'company_id': company.id,
                'is_purchase_representative': True})
            account = env['account.account'].create({
                'name': 'Receipt race custody', 'code': 'RRC1', 'account_type': 'asset_receivable',
                'reconcile': True, 'company_ids': [Command.set(company.ids)]})
            source = env['account.account'].create({
                'name': 'Receipt race cash', 'code': 'RRC2', 'account_type': 'asset_cash',
                'company_ids': [Command.set(company.ids)]})
            journal = env['account.journal'].create({
                'name': 'Receipt race general', 'code': 'RRG', 'type': 'general', 'company_id': company.id})
            bank = env['account.journal'].create({
                'name': 'Receipt race bank', 'code': 'RRB', 'type': 'bank', 'company_id': company.id,
                'default_account_id': source.id})
            company.sudo().write({
                'baseer_procurement_representative_petty_cash_account_id': account.id,
                'baseer_procurement_representative_petty_cash_journal_id': journal.id,
                'baseer_procurement_representative_petty_cash_payment_journal_ids': [Command.set(bank.ids)]})
            product = env['product.product'].create({'name': 'Receipt race material', 'company_id': company.id})
            option = env['baseer.procurement.purchase.option'].create({
                'name': 'Unit', 'company_id': company.id, 'product_id': product.id, 'uom_id': product.uom_id.id})
            requests = env['baseer.procurement.request']
            for order in ('manual_first', 'receipt_first'):
                request = requests.create({
                    'company_id': company.id, 'warehouse_id': warehouse.id,
                    'representative_partner_id': representative.id,
                    'line_ids': [Command.create({'option_id': option.id, 'requested_qty': 5, 'requested_price': 4})]})
                request.action_mark_sent()
                requests |= request
            ids = requests.ids
            company_id, actor_id, representative_id, bank_id = company.id, actor.id, representative.id, bank.id
            setup_cr.commit()
        ctx = {'allowed_company_ids': [company_id]}
        for request_id, order in zip(ids, ('manual_first', 'receipt_first')):
            with self.subTest(order=order), db.cursor() as winner_cr, db.cursor() as waiter_cr:
                winner = api.Environment(winner_cr, actor_id, ctx)
                waiter = api.Environment(waiter_cr, actor_id, ctx)
                winning_request = winner['baseer.procurement.request'].browse(request_id)
                waiting_request = waiter['baseer.procurement.request'].browse(request_id)
                waiting_context = waiting_request.prepare_receipt_custody(request_id)  # establishes old RR snapshot
                rows = [{'line_id': waiting_request.line_ids.id, 'actual_qty': '3', 'actual_price': '4'}]
                payload = {'snapshot': waiting_context['snapshot'], 'amount': '27.50',
                           'payment_journal_id': bank_id, 'movement_date': str(fields.Date.context_today(waiting_request))}
                token = 'manual-%s-%s' % (owned, order)
                if order == 'manual_first':
                    winner['baseer.procurement.representative.advance'].submit_funding(
                        request_id, bank_id, representative_id, 27.5, token, payload['movement_date'])
                else:
                    winning_request.confirm_actual_from_catalog(request_id, rows, payload)
                waiter_cr.execute('SELECT pg_backend_pid()')
                pid = waiter_cr.fetchone()[0]
                errors = []
                def compete():
                    try:
                        if order == 'manual_first':
                            waiting_request.confirm_actual_from_catalog(request_id, rows, payload)
                        else:
                            waiter['baseer.procurement.representative.advance'].submit_funding(
                                request_id, bank_id, representative_id, 27.5, token, payload['movement_date'])
                    except Exception as error:
                        errors.append(error)
                thread = threading.Thread(target=compete, daemon=True)
                thread.start()
                deadline = time.monotonic() + 10
                blocked = False
                # Observe an actual database lock wait; no scheduling assumptions.
                with db.cursor() as observer:
                    while time.monotonic() < deadline and thread.is_alive():
                        observer.execute('SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s', [pid])
                        row = observer.fetchone()
                        observer.rollback()  # fresh stats snapshot on the next observation
                        if row and row[0] == 'Lock':
                            blocked = True
                            break
                        time.sleep(0.02)
                try:
                    self.assertTrue(blocked, 'The competing financial RPC must wait on the shared database mutex')
                finally:
                    winner_cr.commit()
                    thread.join(15)
                self.assertFalse(thread.is_alive(), 'Competing RPC did not finish after mutex release')
                self.assertEqual(len(errors), 1)
                self.assertIsInstance(errors[0], SerializationFailure)
                waiter_cr.rollback()
            with db.cursor() as retry_cr:
                retry = api.Environment(retry_cr, actor_id, ctx)
                request = retry['baseer.procurement.request'].browse(request_id)
                if order == 'manual_first':
                    fresh = request.prepare_receipt_custody(request_id)
                    self.assertTrue(fresh['existing_funded'])
                    request.confirm_actual_from_catalog(request_id, rows, {'snapshot': fresh['snapshot']})
                else:
                    with self.assertRaises(UserError):
                        retry['baseer.procurement.representative.advance'].submit_funding(
                            request_id, bank_id, representative_id, 27.5, token, payload['movement_date'])
                self.assertEqual(len(request._receipt_custody_fundings()), 1)
                self.assertTrue(request.receipt_custody_confirmed)
                self.assertEqual(request.state, 'purchased')
                retry_cr.commit()
            logger.info('RECEIPT_CUSTODY_REAL_RR_RACE_OK %s request=%s fixture=%s', order, request_id, owned)
