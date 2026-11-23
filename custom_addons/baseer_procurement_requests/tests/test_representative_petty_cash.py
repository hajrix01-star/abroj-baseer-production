from uuid import uuid4

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase


class RepresentativePettyCashCase(TransactionCase):
    """Focused accounting and workflow checks for PRA-BUILD-1 only."""

    def setUp(self):
        super().setUp()
        self.env.user.group_ids |= self.env.ref('baseer_procurement_requests.group_procurement_accountant')
        self.env.user.group_ids |= self.env.ref('baseer_procurement_requests.group_procurement_manager')
        self.env.user.group_ids |= self.env.ref('base.group_erp_manager')
        self.company = self.env.company
        self._configure_company_fixture()

    def _configure_company_fixture(self):
        self.company.currency_id.active = True
        self.warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.company.id)], limit=1)
        if not self.warehouse:
            self.warehouse = self.env['stock.warehouse'].create({
                'name': 'Petty cash fixture warehouse', 'code': 'RPCFX', 'company_id': self.company.id,
            })
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

    def _use_isolated_sar_company(self):
        sar = self.env['res.currency'].with_context(active_test=False).search([('name', '=', 'SAR')], limit=1)
        if not sar:
            sar = self.env['res.currency'].create({'name': 'SAR', 'symbol': 'SR', 'active': True})
        sar.active = True
        self.company = self.env['res.company'].create({'name': 'Petty cash fixture SAR company', 'currency_id': sar.id})
        self.env.user.company_ids |= self.company
        self.env = self.env['res.company'].with_company(self.company).env
        self._configure_company_fixture()

    def _request(self):
        request = self.env['baseer.procurement.request'].create({
            'company_id': self.company.id, 'warehouse_id': self.warehouse.id,
            'representative_partner_id': self.representative.id,
            'line_ids': [Command.create({
                'option_id': self.option.id, 'requested_qty': 5, 'requested_price': 4,
            })],
        })
        # The request-linked custody routes are supported for pre-separation data.
        request.flush_recordset(['list_only'])
        self.cr.execute('UPDATE baseer_procurement_request SET list_only = false WHERE id = %s', [request.id])
        request.invalidate_recordset(['list_only'])
        return request

    def _sent_request(self):
        request = self._request()
        request.action_mark_sent()
        return request

    def test_dashboard_ignores_vendor_payments(self):
        self._use_isolated_sar_company()
        self.env.user.group_ids |= self.env.ref('account.group_account_manager')
        Model = self.env['baseer.procurement.representative.advance']
        request = self._sent_request()
        today = fields.Date.context_today(self.env.user)
        advance = Model.browse(Model.submit_funding(
            request.id, self.bank_journal.id, self.representative.id, 20, str(uuid4()), today,
        ))
        def summary(partner=False):
            return Model.dashboard_data(partner.id if partner else False)['summary']

        self.assertEqual(summary(self.representative)['remaining'], 20)
        payable = self.env['account.account'].create({
            'name': 'Vendor payable', 'code': 'RPA703', 'account_type': 'liability_payable',
            'reconcile': True, 'company_ids': [Command.set(self.company.ids)],
        })
        vendor = self.env['res.partner'].create({'name': 'Vendor'})
        journal = self.env['account.journal'].create({
            'name': 'Custody payments', 'code': 'RPAC', 'type': 'cash',
            'company_id': self.company.id, 'default_account_id': self.petty_cash_account.id,
        })
        journal.outbound_payment_method_line_ids.payment_account_id = self.petty_cash_account
        self.bank_journal.outbound_payment_method_line_ids.payment_account_id = self.bank_journal.default_account_id

        def payment(point, amount):
            record = self.env['account.payment'].create({
                'company_id': self.company.id, 'payment_type': 'outbound', 'partner_type': 'supplier',
                'partner_id': vendor.id, 'amount': amount, 'date': today, 'journal_id': point.id,
                'payment_method_line_id': point.outbound_payment_method_line_ids[0].id,
                'destination_account_id': payable.id,
            })
            record._generate_journal_entry()
            liquidity = record.move_id.line_ids.filtered(
                lambda line: line.account_id == point.default_account_id and line.credit
            )
            self.assertEqual(liquidity.partner_id, vendor)
            record.action_post()
            return record

        payment(journal, 3)
        payment(journal, 4)
        payment(self.bank_journal, 5)
        self.assertEqual(summary(self.representative)['settled'], 0)
        self.assertEqual(summary(self.representative)['remaining'], 20)
        self.assertEqual(summary()['settled'], 0)
        self.assertEqual(advance.remaining_amount, 20)

        linked = payment(journal, 2)
        batch = self.env['baseer.purchase.batch'].create({'company_id': self.company.id})
        self.env['baseer.procurement.representative.advance.settlement'].sudo().with_context(
            baseer_representative_petty_cash_internal=True,
        ).create({
            'company_id': self.company.id, 'advance_id': advance.id, 'batch_id': batch.id,
            'move_id': linked.move_id.id, 'amount': 2,
        })
        self.assertEqual(summary(self.representative)['settled'], 2)
        self.assertEqual(summary(self.representative)['remaining'], 18)
        self.assertEqual(summary()['settled'], 2)
        journal.baseer_custody_representative_id = self.representative
        self.assertEqual(summary(self.representative)['settled'], 9)
        self.assertEqual(summary(self.representative)['remaining'], 11)

    def test_native_vendor_payments_follow_the_linked_journal(self):
        self._use_isolated_sar_company()
        self.env.user.group_ids |= self.env.ref('account.group_account_manager')
        company = self.company
        Model = self.env['baseer.procurement.representative.advance']
        Account = self.env['account.account']
        Journal = self.env['account.journal']
        self.petty_cash_account.account_type = 'asset_current'
        payable = Account.create({
            'name': 'Native custody test payable', 'code': 'RPC703',
            'account_type': 'liability_payable', 'reconcile': True,
            'company_ids': [Command.set(company.ids)],
        })
        expense = Account.create({
            'name': 'Native custody test expense', 'code': 'RPC704',
            'account_type': 'expense', 'company_ids': [Command.set(company.ids)],
        })
        purchase = Journal.create({
            'name': 'Native custody test purchases', 'code': 'RPCP', 'type': 'purchase',
            'company_id': company.id, 'default_account_id': expense.id,
        })
        custody = Journal.create({
            'name': 'Native custody test cash', 'code': 'RPCC', 'type': 'cash',
            'company_id': company.id, 'default_account_id': self.petty_cash_account.id,
        })
        custody.outbound_payment_method_line_ids.payment_account_id = self.petty_cash_account
        self.bank_journal.outbound_payment_method_line_ids.payment_account_id = self.bank_journal.default_account_id
        vendor = self.env['res.partner'].create({'name': 'Native custody test vendor'})
        vendor.with_company(company).property_account_payable_id = payable
        product = self.env['product.product'].create({
            'name': 'Native custody test service', 'type': 'service', 'company_id': company.id,
        })

        def make_bill(amount, ref):
            bill = self.env['account.move'].create({
                'move_type': 'in_invoice', 'company_id': company.id, 'journal_id': purchase.id,
                'partner_id': vendor.id, 'invoice_date': '2025-01-20', 'ref': ref,
                'invoice_line_ids': [Command.create({
                    'product_id': product.id, 'account_id': expense.id, 'quantity': 1,
                    'price_unit': amount, 'tax_ids': [Command.clear()],
                })],
            })
            bill.action_post()
            return bill

        def pay(bills, journal, date, amount=None):
            wizard = self.env['account.payment.register'].with_context(
                active_model='account.move', active_ids=bills.ids,
            ).create({
                'journal_id': journal.id, 'payment_date': date, 'group_payment': True,
                'payment_method_line_id': journal.outbound_payment_method_line_ids[0].id,
            })
            if amount is not None:
                wizard.amount = amount
            return wizard._create_payments().ensure_one()

        rep = self.representative
        successor = self.env['res.partner'].create({
            'name': rep.name, 'company_id': company.id,
        })
        Model.submit_funding(False, self.bank_journal.id, rep.id, '100.00', str(uuid4()), '2025-01-15')
        partial = make_bill(30, 'RPC partial')
        pay(partial, custody, '2025-01-21', amount=10)
        self.assertEqual(partial.amount_residual, 20)
        pay(make_bill(8, 'RPC normal bank'), self.bank_journal, '2025-01-22')
        self.assertEqual(Model.dashboard_data(rep.id, '2025-01-01')['summary']['settled'], 0)

        custody.baseer_custody_representative_id = rep
        self.assertEqual(rep.action_baseer_open_custody_journal()['res_id'], custody.id)
        grouped = make_bill(12, 'RPC group 1') | make_bill(13, 'RPC group 2')
        payment = pay(grouped, custody, '2025-02-03')
        self.assertEqual(grouped.mapped('amount_residual'), [0, 0])
        self.assertEqual(payment.amount, 25)
        move_count = self.env['account.move'].search_count([('company_id', '=', company.id)])

        jan = Model.dashboard_data(rep.id, '2025-01-01')
        feb = Model.dashboard_data(rep.id, '2025-02-01')
        self.assertEqual((jan['summary']['settled'], jan['summary']['closing']), (10, 90))
        self.assertEqual((feb['summary']['opening'], feb['summary']['settled'], feb['summary']['closing']), (90, 25, 65))
        purchase_rows = [row for row in feb['daily_movements'] if row['type'] == 'purchase']
        self.assertEqual([(row['key'], row['amount']) for row in purchase_rows], [
            (f'native_payment:{payment.move_id.id}', 25),
        ])
        self.assertEqual(Model._baseer_representative_available_amount(company, rep), 65)
        self.assertEqual(Model.dashboard_data(successor.id, '2025-02-01')['summary']['closing'], 0)
        self.assertEqual(self.env['account.move'].search_count([('company_id', '=', company.id)]), move_count)

        with self.assertRaises(ValidationError):
            custody.baseer_custody_representative_id = successor
        rep.is_purchase_representative = False
        history = Model.dashboard_data(rep.id, '2025-02-01')
        self.assertEqual(history['summary']['closing'], 65)
        self.assertIn(rep.id, [row['id'] for row in history['history_representatives']])
        self.assertNotIn(rep.id, [row['id'] for row in history['representatives']])

        reversal = payment.move_id._reverse_moves([{'date': '2025-03-04'}], cancel=True)
        march = Model.dashboard_data(rep.id, '2025-03-01')
        self.assertEqual((march['summary']['opening'], march['summary']['settled'], march['summary']['closing']), (65, -25, 90))
        self.assertEqual([(row['key'], row['amount']) for row in march['daily_movements']], [
            (f'native_payment:{reversal.id}', -25),
        ])

        journal_domain = [('company_id', '=', company.id), ('baseer_custody_representative_id', '=', successor.id)]
        self.assertFalse(Journal.search(journal_domain))
        move_count = self.env['account.move'].search_count([('company_id', '=', company.id)])
        successor.is_purchase_representative = True
        new_custody = Journal.search(journal_domain).ensure_one()
        self.assertEqual(successor.action_baseer_open_custody_journal()['res_id'], new_custody.id)
        successor.is_purchase_representative = False
        successor.is_purchase_representative = True
        self.assertEqual(Journal.search(journal_domain), new_custody)
        self.assertEqual(self.env['account.move'].search_count([('company_id', '=', company.id)]), move_count)
        self.assertEqual(new_custody.default_account_id, self.petty_cash_account)
        methods = new_custody.inbound_payment_method_line_ids | new_custody.outbound_payment_method_line_ids
        self.assertEqual(methods.mapped('payment_account_id'), self.petty_cash_account)
        Model.submit_funding(False, self.bank_journal.id, successor.id, '15.00', str(uuid4()), '2025-03-05')
        pay(make_bill(5, 'RPC successor'), new_custody, '2025-03-05')
        self.assertEqual(Model.dashboard_data(successor.id, '2025-03-01')['summary']['closing'], 10)
        self.assertEqual(Model.dashboard_data(rep.id, '2025-03-01')['summary']['closing'], 90)

    def test_legacy_custody_transfers_are_included_in_representative_balance(self):
        self._use_isolated_sar_company()
        self.company.write({
            'baseer_procurement_custody_account_id': self.petty_cash_account.id,
            'baseer_procurement_custody_journal_id': self.general_journal.id,
            'baseer_procurement_representative_petty_cash_account_id': False,
        })
        employee = self.env['hr.employee'].create({
            'name': 'Legacy custody employee', 'company_id': self.company.id,
            'work_contact_id': self.representative.id,
        })
        custody = self.env['baseer.procurement.custody'].create({
            'company_id': self.company.id, 'employee_id': employee.id,
        })
        Event = self.env['baseer.procurement.custody.event']
        first = Event.create({
            'custody_id': custody.id, 'event_type': 'funding', 'event_date': '2025-01-04',
            'amount': 100, 'cash_journal_id': self.bank_journal.id,
        })
        first.action_post()
        returned = Event.create({
            'custody_id': custody.id, 'event_type': 'return', 'event_date': '2025-02-04',
            'amount': 20, 'cash_journal_id': self.bank_journal.id,
        })
        returned.action_post()
        self.company.baseer_procurement_representative_petty_cash_account_id = self.petty_cash_account
        self.assertFalse(first.representative_partner_id)
        Model = self.env['baseer.procurement.representative.advance']
        Model.submit_funding(False, self.bank_journal.id, self.representative.id, 50, str(uuid4()), '2025-02-10')
        jan = Model.dashboard_data(self.representative.id, '2025-01-01')
        feb = Model.dashboard_data(self.representative.id, '2025-02-01')
        self.assertEqual((jan['summary']['funded'], jan['summary']['closing']), (100, 100))
        self.assertEqual((feb['summary']['opening'], feb['summary']['funded'], feb['summary']['returned'], feb['summary']['closing']), (100, 50, 20, 130))
        self.assertEqual(Model._baseer_representative_available_amount(self.company, self.representative), 130)
        self.assertEqual([(row['type'], row['amount']) for row in feb['daily_movements']], [('funding', 50), ('return', 20)])
        self.assertIn(100, [row['amount'] for row in feb['carryovers']])
        with self.assertRaises(UserError):
            Event.create({
                'custody_id': custody.id, 'event_type': 'funding', 'event_date': '2025-02-12',
                'amount': 1, 'cash_journal_id': self.bank_journal.id,
            }).action_post()
        Model.submit_aggregate_return(self.representative.id, self.bank_journal.id, 60, str(uuid4()), '2025-02-15')
        self.assertEqual(Model._baseer_representative_available_amount(self.company, self.representative), 70)
        legacy_line = first.move_id.line_ids.filtered(lambda line: line.account_id == self.petty_cash_account)
        self.assertLess(legacy_line.amount_residual, 80)

    def test_funding_posts_once_and_is_immutable(self):
        request = self._sent_request()
        token = str(uuid4())
        Model = self.env['baseer.procurement.representative.advance']
        movement_date = fields.Date.context_today(self.env.user)
        record_id = Model.submit_funding(request.id, self.bank_journal.id, self.representative.id, 20, token, movement_date)
        self.assertEqual(record_id, Model.submit_funding(request.id, self.bank_journal.id, self.representative.id, 20, token, movement_date))
        record = Model.browse(record_id)
        self.assertEqual(record.move_id.state, 'posted')
        self.assertEqual(record.amount, 20)
        self.assertEqual(record.movement_date, movement_date)
        dashboard_movement = next(row for row in Model.dashboard_data()['movements'] if row['id'] == record.id)
        self.assertNotIn('external_reference', dashboard_movement)
        self.assertNotIn('proof_url', dashboard_movement)
        self.assertEqual(dashboard_movement['from_name'], self.bank_journal.display_name)
        self.assertEqual(dashboard_movement['to_name'], self.representative.display_name)
        daily = Model.dashboard_data(False, record.movement_date.replace(day=1))['daily_movements']
        historical_funding = next(row for row in daily if row['key'] == 'movement:%s' % record.id)
        self.assertEqual(historical_funding['request_id'], request.id)
        self.assertEqual(historical_funding['request_name'], request.name)
        line = record.move_id.line_ids.filtered(lambda row: row.account_id == self.petty_cash_account)
        self.assertEqual(line.baseer_representative_petty_cash_id, record)
        self.assertEqual(line.partner_id, self.representative)
        returned_id = Model.submit_return(record.id, self.bank_journal.id, 5, str(uuid4()))
        returned = Model.browse(returned_id)
        dashboard_return = next(row for row in Model.dashboard_data()['movements'] if row['id'] == returned.id)
        self.assertEqual(dashboard_return['from_name'], self.representative.display_name)
        self.assertEqual(dashboard_return['to_name'], self.bank_journal.display_name)
        self.assertEqual(record.remaining_amount, 15)
        returned_line = returned.move_id.line_ids.filtered(lambda row: row.account_id == self.petty_cash_account)
        self.assertEqual(returned_line.baseer_representative_petty_cash_id, record)
        self.assertTrue(returned_line.matched_debit_ids)
        with self.assertRaises(ValidationError):
            Model.submit_return(record.id, self.bank_journal.id, 16, str(uuid4()))
        with self.assertRaises(UserError):
            record.write({'amount': 10})
        with self.assertRaises(UserError):
            record.move_id.button_draft()

    def test_independent_funding_carries_balance_and_return_between_months(self):
        Model = self.env['baseer.procurement.representative.advance']
        token = str(uuid4())
        values = (False, self.bank_journal.id, self.representative.id, '100.00', token, '2025-01-15')
        advance = Model.browse(Model.submit_funding(*values))
        self.assertEqual(Model.submit_funding(*values), advance.id)
        self.assertFalse(advance.procurement_request_id)
        self.assertEqual(advance.move_id.state, 'posted')
        debit = advance.move_id.line_ids.filtered(lambda line: line.account_id == self.petty_cash_account)
        self.assertEqual((debit.partner_id, debit.debit, debit.credit), (self.representative, 100, 0))
        Model.submit_aggregate_return(self.representative.id, self.bank_journal.id, '15.00', str(uuid4()), '2025-02-10')
        Model.submit_funding(False, self.bank_journal.id, self.representative.id, '30.00', str(uuid4()), '2025-03-01')
        jan = Model.dashboard_data(self.representative.id, '2025-01-01')['summary']
        feb_data = Model.dashboard_data(self.representative.id, '2025-02-01')
        feb = feb_data['summary']
        self.assertEqual((jan['opening'], jan['funded'], jan['returned'], jan['closing']), (0, 100, 0, 100))
        self.assertEqual((feb['opening'], feb['funded'], feb['returned'], feb['closing']), (100, 0, 15, 85))
        self.assertEqual(feb['remaining'], 85)
        self.assertEqual(feb['available'], 115)
        self.assertEqual([(row['type'], row['amount']) for row in feb_data['daily_movements']], [('return', 15)])
        self.assertIn(self.representative.id, [row['id'] for row in Model.dashboard_data()['representatives']])

        other = self.env['res.partner'].create({'name': 'Other petty cash representative', 'company_id': self.company.id})
        other.with_company(self.company).is_purchase_representative = True
        Model.submit_funding(False, self.bank_journal.id, other.id, '17.00', str(uuid4()), '2025-01-20')
        moves_before = self.env['account.move'].search_count([('company_id', '=', self.company.id)])
        advances_before = Model.search_count([('company_id', '=', self.company.id)])
        carryovers = Model.dashboard_data(self.representative.id, '2025-03-01')['carryovers']
        self.assertEqual([(row['source_month'], row['destination_month'], row['amount']) for row in carryovers], [
            ('2025-02-01', '2025-03-01', 85), ('2025-01-01', '2025-02-01', 100),
        ])
        self.assertTrue(all(row['representative_id'] == self.representative.id for row in carryovers))
        all_carryovers = Model.dashboard_data(False, '2025-03-01')['carryovers']
        self.assertIn(other.id, [row['representative_id'] for row in all_carryovers])
        self.assertEqual(self.env['account.move'].search_count([('company_id', '=', self.company.id)]), moves_before)
        self.assertEqual(Model.search_count([('company_id', '=', self.company.id)]), advances_before)

    def test_monthly_total_is_not_limited_to_displayed_movements(self):
        # Synthetic rows isolate aggregation coverage; the posting workflow is
        # verified separately by the independent-funding test above.
        Model = self.env['baseer.procurement.representative.advance']
        values = [{
            'company_id': self.company.id, 'movement_type': 'funding',
            'representative_partner_id': self.representative.id,
            'payment_journal_id': self.bank_journal.id, 'movement_date': '2025-03-01',
            'amount': 1, 'client_token': str(uuid4()), 'created_by_id': self.env.user.id,
        } for _ in range(101)]
        values[0]['amount'] = 777
        Model.sudo().with_context(baseer_representative_petty_cash_internal=True).create(values)
        data = Model.dashboard_data(self.representative.id, '2025-03-01')
        self.assertEqual(len(data['movements']), 100)
        self.assertEqual(data['summary']['funded'], 877)
        self.assertEqual(data['summary']['closing'], 877)
        self.assertEqual(len(data['daily_movements']), 100)
        self.assertTrue(data['daily_movements_truncated'])
        self.assertEqual(len({row['key'] for row in data['daily_movements']}), 100)
        filtered = Model.dashboard_daily_movements(self.representative.id, '2025-03-01', '777', 'funding')
        self.assertEqual([row['amount'] for row in filtered['daily_movements']], [777])
        self.assertFalse(filtered['daily_movements_truncated'])
        self.assertFalse(Model.dashboard_daily_movements(self.representative.id, '2025-03-01', '777', 'return')['daily_movements'])
        second = Model.dashboard_daily_movements(self.representative.id, '2025-03-01', '', '', 100)
        self.assertEqual([row['amount'] for row in second['daily_movements']], [777])
        self.assertEqual(Model.dashboard_data(self.representative.id, '2025-03-01')['summary'], data['summary'])
        with self.assertRaises(ValidationError):
            Model.dashboard_daily_movements(self.representative.id, '2025-03-01', '', 'invalid')

    def test_independent_funding_rejects_foreign_currency_sources(self):
        Model = self.env['baseer.procurement.representative.advance']
        foreign = (self.env.ref('base.USD') if self.company.currency_id != self.env.ref('base.USD')
                   else self.env.ref('base.EUR'))
        foreign.active = True
        records = (self.petty_cash_account, self.general_journal,
                   self.bank_journal, self.bank_journal.default_account_id)
        for record in records:
            with self.subTest(model=record._name, id=record.id):
                original = record.currency_id
                record.currency_id = foreign
                before = Model.search_count([('company_id', '=', self.company.id)])
                with self.assertRaisesRegex(ValidationError, 'company-currency'):
                    Model.submit_funding(False, self.bank_journal.id, self.representative.id,
                                         '10.00', str(uuid4()), '2025-01-15')
                self.assertEqual(Model.search_count([('company_id', '=', self.company.id)]), before)
                record.currency_id = original

    def test_both_return_routes_reject_foreign_currency_point(self):
        Model = self.env['baseer.procurement.representative.advance']
        advance = Model.browse(Model.submit_funding(False, self.bank_journal.id, self.representative.id,
                                                    '20.00', str(uuid4()), '2025-01-15'))
        foreign = (self.env.ref('base.USD') if self.company.currency_id != self.env.ref('base.USD')
                   else self.env.ref('base.EUR'))
        foreign.active = True
        foreign_account = self.env['account.account'].create({
            'name': 'Foreign currency petty cash', 'code': 'RPA799', 'account_type': 'asset_cash',
            'currency_id': foreign.id, 'company_ids': [Command.set(self.company.ids)],
        })
        foreign_bank = self.env['account.journal'].create({
            'name': 'Foreign bank', 'code': 'RPAF', 'type': 'bank', 'company_id': self.company.id,
            'default_account_id': foreign_account.id, 'currency_id': foreign.id,
        })
        self.company.baseer_procurement_representative_petty_cash_payment_journal_ids = [Command.link(foreign_bank.id)]
        before = Model.search_count([('company_id', '=', self.company.id)])
        with self.assertRaisesRegex(ValidationError, 'company-currency'):
            Model.submit_return(advance.id, foreign_bank.id, 1, str(uuid4()), '2025-01-16')
        with self.assertRaisesRegex(ValidationError, 'company-currency'):
            Model.submit_aggregate_return(self.representative.id, foreign_bank.id, 1, str(uuid4()), '2025-01-16')
        self.assertEqual(Model.search_count([('company_id', '=', self.company.id)]), before)

    def test_monthly_balances_include_both_settlement_generations(self):
        # The settlement links are synthetic; real invoice approval is covered
        # by the procurement-flow tests. This isolates the two reporting sources.
        self._use_isolated_sar_company()
        Model = self.env['baseer.procurement.representative.advance']
        jan = Model.browse(Model.submit_funding(False, self.bank_journal.id, self.representative.id,
                                                '100.00', str(uuid4()), '2025-01-15'))
        feb = Model.browse(Model.submit_funding(False, self.bank_journal.id, self.representative.id,
                                                '30.00', str(uuid4()), '2025-02-15'))
        Batch = self.env['baseer.purchase.batch']
        historic_batch = Batch.create({'company_id': self.company.id})
        self.env['baseer.procurement.representative.advance.settlement'].sudo().with_context(
            baseer_representative_petty_cash_internal=True,
        ).create({
            'company_id': self.company.id, 'advance_id': jan.id, 'batch_id': historic_batch.id,
            'move_id': jan.move_id.id, 'amount': 20,
        })
        supplier = self.env['res.partner'].create({'name': 'Monthly test supplier'})
        invoice_batch = Batch.create({
            'company_id': self.company.id,
            'line_ids': [Command.create({
                'partner_id': supplier.id, 'supplier_ref': 'MONTHLY-TEST',
                'gross_amount': 15, 'is_credit': True,
            })],
        })
        self.env['baseer.procurement.representative.petty.cash.invoice.settlement'].sudo().with_context(
            baseer_representative_petty_cash_internal=True,
        ).create({
            'company_id': self.company.id, 'representative_partner_id': self.representative.id,
            'batch_line_id': invoice_batch.line_ids.id, 'move_id': feb.move_id.id, 'amount': 15,
        })
        jan_summary = Model.dashboard_data(self.representative.id, '2025-01-01')['summary']
        feb_data = Model.dashboard_data(self.representative.id, '2025-02-01')
        feb_summary = feb_data['summary']
        self.assertEqual((jan_summary['settled'], jan_summary['closing']), (20, 80))
        self.assertEqual((feb_summary['opening'], feb_summary['funded'], feb_summary['settled'], feb_summary['closing']),
                         (80, 30, 15, 95))
        carryovers = Model.dashboard_data(self.representative.id, '2025-03-01')['carryovers']
        self.assertEqual([(row['source_month'], row['amount']) for row in carryovers],
                         [('2025-02-01', 95), ('2025-01-01', 80)])
        jan_rows = Model.dashboard_data(self.representative.id, '2025-01-01')['daily_movements']
        feb_rows = feb_data['daily_movements']
        self.assertEqual([(row['type'], row['amount']) for row in jan_rows if row['type'] == 'purchase'], [('purchase', 20)])
        self.assertEqual([(row['type'], row['amount'], row['reference']) for row in feb_rows if row['type'] == 'purchase'],
                         [('purchase', 15, 'MONTHLY-TEST')])
        cashier = self.env['res.users'].create({
            'name': 'Daily custody cashier', 'login': 'daily-custody-cashier',
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([self.env.ref('baseer_procurement_requests.group_procurement_cashier').id])],
        })
        cashier_model = Model.with_user(cashier).with_context(allowed_company_ids=[self.company.id])
        cashier_jan = cashier_model.dashboard_data(self.representative.id, '2025-01-01')['daily_movements']
        cashier_feb = cashier_model.dashboard_data(self.representative.id, '2025-02-01')['daily_movements']
        self.assertEqual([row['reference'] for row in cashier_jan if row['type'] == 'purchase'], [''])
        self.assertEqual([row['reference'] for row in cashier_feb if row['type'] == 'purchase'], [''])
        self.assertEqual([row['amount'] for row in cashier_feb if row['type'] == 'purchase'], [15])
        self.assertEqual(len(Model.dashboard_daily_movements(self.representative.id, '2025-02-01', 'MONTHLY-TEST')['daily_movements']), 1)
        self.assertFalse(cashier_model.dashboard_daily_movements(self.representative.id, '2025-02-01', 'MONTHLY-TEST')['daily_movements'])
        self.assertEqual([row['amount'] for row in cashier_model.dashboard_daily_movements(
            self.representative.id, '2025-02-01', '', 'purchase')['daily_movements']], [15])

    def test_carryover_history_stays_within_the_active_company(self):
        Model = self.env['baseer.procurement.representative.advance']
        other_company = self.env['res.company'].create({
            'name': 'Carryover isolation company', 'currency_id': self.company.currency_id.id,
        })
        other_partner = self.env['res.partner'].create({'name': 'Other company representative', 'company_id': other_company.id})
        other_partner.with_company(other_company).is_purchase_representative = True
        other_account = self.env['account.account'].create({
            'name': 'Other cash', 'code': 'RPA801', 'account_type': 'asset_cash',
            'company_ids': [Command.set(other_company.ids)],
        })
        other_journal = self.env['account.journal'].create({
            'name': 'Other bank', 'code': 'RPAY', 'type': 'bank', 'company_id': other_company.id,
            'default_account_id': other_account.id,
        })
        other_company.baseer_procurement_representative_petty_cash_payment_journal_ids = [Command.set(other_journal.ids)]
        Model.sudo().with_company(other_company).with_context(baseer_representative_petty_cash_internal=True).create({
            'company_id': other_company.id, 'movement_type': 'funding',
            'representative_partner_id': other_partner.id, 'payment_journal_id': other_journal.id,
            'movement_date': '2025-01-15', 'amount': 50, 'client_token': str(uuid4()),
            'created_by_id': self.env.user.id,
        })
        Model.submit_funding(False, self.bank_journal.id, self.representative.id, '20.00', str(uuid4()), '2025-01-15')
        local = Model.dashboard_data(False, '2025-02-01')['carryovers']
        other = Model.sudo().with_company(other_company).dashboard_data(False, '2025-02-01')['carryovers']
        self.assertIn(self.representative.id, [row['representative_id'] for row in local])
        self.assertNotIn(other_partner.id, [row['representative_id'] for row in local])
        self.assertIn(other_partner.id, [row['representative_id'] for row in other])
        self.assertNotIn(self.representative.id, [row['representative_id'] for row in other])
        local_daily = Model.dashboard_data(False, '2025-01-01')['daily_movements']
        other_daily = Model.sudo().with_company(other_company).dashboard_data(False, '2025-01-01')['daily_movements']
        self.assertEqual({row['representative_id'] for row in local_daily}, {self.representative.id})
        self.assertEqual({row['representative_id'] for row in other_daily}, {other_partner.id})
        self.assertFalse(Model.dashboard_daily_movements(False, '2025-01-01', other_partner.name)['daily_movements'])
        self.assertEqual({row['representative_id'] for row in Model.sudo().with_company(other_company)
                         .dashboard_daily_movements(False, '2025-01-01', other_partner.name)['daily_movements']}, {other_partner.id})

    def test_funding_rejects_draft_request_and_wrong_destination(self):
        request = self._request()
        Model = self.env['baseer.procurement.representative.advance']
        with self.assertRaises(ValidationError):
            Model.submit_funding(request.id, self.bank_journal.id, self.representative.id, 20, str(uuid4()), '2026-09-17')
        request.action_mark_sent()
        other = self.env['res.partner'].create({'name': 'Other representative', 'company_id': self.company.id})
        other.with_company(self.company).write({'is_purchase_representative': True})
        with self.assertRaises(ValidationError):
            Model.submit_funding(request.id, self.bank_journal.id, other.id, 20, str(uuid4()), '2026-09-17')

    def test_cashier_cannot_record_a_movement(self):
        request = self._sent_request()
        cashier = self.env['res.users'].create({
            'name': 'Representative petty cash cashier', 'login': 'representative-petty-cash-cashier',
            'group_ids': [Command.set([self.env.ref('baseer_procurement_requests.group_procurement_cashier').id])],
        })
        with self.assertRaises(AccessError):
            self.env['baseer.procurement.representative.advance'].with_user(cashier).submit_funding(
                request.id, self.bank_journal.id, self.representative.id, 20, str(uuid4()), '2026-09-17',
            )

    def test_manager_dashboard_is_read_only_without_payment_point_access(self):
        manager = self.env['res.users'].create({
            'name': 'Representative petty cash manager', 'login': 'representative-petty-cash-manager',
            'group_ids': [Command.set([self.env.ref('baseer_procurement_requests.group_procurement_manager').id])],
        })
        dashboard = self.env['baseer.procurement.representative.advance'].with_user(manager).dashboard_data()
        self.assertFalse(dashboard['can_record'])
        self.assertEqual(dashboard['payment_points'], [])

    def test_accountant_dashboard_lists_only_valid_company_payment_points(self):
        dashboard = self.env['baseer.procurement.representative.advance'].dashboard_data()
        self.assertIn(self.bank_journal.id, [point['id'] for point in dashboard['payment_points']])
        self.assertFalse(dashboard['setup_issue'])

    def test_dashboard_exposes_the_eligible_request_timestamp_without_changing_amount(self):
        request = self._sent_request()
        dashboard = self.env['baseer.procurement.representative.advance'].dashboard_data()
        row = next(item for item in dashboard['requests'] if item['id'] == request.id)
        self.assertEqual(row['request_date'], fields.Datetime.to_string(request.request_date))
        self.assertEqual(row['amount'], request.requested_total)
        self.assertEqual(row['representative_id'], self.representative.id)

    def test_dashboard_reports_missing_company_accounting_setup_before_save(self):
        self.company.baseer_procurement_representative_petty_cash_account_id = False
        dashboard = self.env['baseer.procurement.representative.advance'].dashboard_data()
        self.assertEqual(
            dashboard['setup_issue'],
            'Configure an active reconcilable Representative Petty Cash account first.',
        )

    def test_manager_initializes_one_shared_company_setup_without_payment_points(self):
        company = self.env['res.company'].create({
            'name': 'New representative petty cash company',
            'currency_id': self.company.currency_id.id,
        })
        payment_point_ids_before = company.baseer_procurement_representative_petty_cash_payment_journal_ids.ids

        # This is the real native completion event for a new company, not a
        # write simulation: the chart loader runs and our inherited hook then
        # creates the one shared account and general journal.
        self.env['account.chart.template']._load(
            self.company.chart_template, company, install_demo=False,
        )
        account = company.baseer_procurement_representative_petty_cash_account_id
        journal = company.baseer_procurement_representative_petty_cash_journal_id
        self.assertTrue(account.active)
        self.assertTrue(account.reconcile)
        self.assertEqual(account.account_type, 'asset_current')
        self.assertIn(company, account.company_ids)
        self.assertTrue(journal.active)
        self.assertEqual(journal.type, 'general')
        self.assertEqual(company.baseer_procurement_representative_petty_cash_payment_journal_ids.ids, payment_point_ids_before)

        company.action_baseer_initialize_representative_petty_cash()
        self.assertEqual(company.baseer_procurement_representative_petty_cash_account_id, account)
        self.assertEqual(company.baseer_procurement_representative_petty_cash_journal_id, journal)

        first = self.env['res.partner'].create({'name': 'First representative', 'company_id': company.id})
        second = self.env['res.partner'].create({'name': 'Second representative', 'company_id': company.id})
        first.with_company(company).is_purchase_representative = True
        second.with_company(company).is_purchase_representative = True
        self.assertEqual(company.baseer_procurement_representative_petty_cash_account_id, account)
        self.assertEqual(company.baseer_procurement_representative_petty_cash_journal_id, journal)

    def test_invalid_module_owned_seed_never_creates_the_other_setup_side(self):
        company = self.company
        company.write({
            'baseer_procurement_representative_petty_cash_account_id': False,
            'baseer_procurement_representative_petty_cash_journal_id': False,
        })
        company.action_baseer_initialize_representative_petty_cash()
        account = company.baseer_procurement_representative_petty_cash_account_id
        journal = company.baseer_procurement_representative_petty_cash_journal_id
        account.active = False
        company.write({
            'baseer_procurement_representative_petty_cash_account_id': False,
            'baseer_procurement_representative_petty_cash_journal_id': False,
        })
        with self.assertRaises(ValidationError):
            company.action_baseer_initialize_representative_petty_cash()
        self.assertFalse(company.baseer_procurement_representative_petty_cash_account_id)
        self.assertFalse(company.baseer_procurement_representative_petty_cash_journal_id)
        self.assertTrue(journal.exists())

    def test_manager_setup_does_not_complete_a_partial_manual_configuration(self):
        company = self.company
        account = self.env['account.account'].create({
            'name': 'Partial representative petty cash account', 'code': 'RPA80',
            'account_type': 'asset_current', 'reconcile': True,
            'company_ids': [Command.set(company.ids)],
        })
        company.write({
            'baseer_procurement_representative_petty_cash_account_id': account.id,
            'baseer_procurement_representative_petty_cash_journal_id': False,
        })
        with self.assertRaises(UserError):
            company.action_baseer_initialize_representative_petty_cash()
        self.assertEqual(company.baseer_procurement_representative_petty_cash_account_id, account)
        self.assertFalse(company.baseer_procurement_representative_petty_cash_journal_id)

    def test_only_erp_manager_can_initialize_company_setup(self):
        company = self.company
        accountant = self.env['res.users'].create({
            'name': 'Representative petty cash accountant setup',
            'login': 'representative-petty-cash-accountant-setup',
            'group_ids': [Command.set([
                self.env.ref('baseer_procurement_requests.group_procurement_accountant').id,
            ])],
        })
        with self.assertRaises(AccessError):
            company.with_user(accountant).action_baseer_initialize_representative_petty_cash()

    def test_only_configured_existing_payment_points_are_listed_and_accepted(self):
        other_cash_account = self.env['account.account'].create({
            'name': 'Other cash point', 'code': 'RPA703', 'account_type': 'asset_cash',
            'company_ids': [Command.set(self.company.ids)],
        })
        other_journal = self.env['account.journal'].create({
            'name': 'Unapproved cash point', 'code': 'RPAU', 'type': 'cash',
            'company_id': self.company.id, 'default_account_id': other_cash_account.id,
        })
        dashboard = self.env['baseer.procurement.representative.advance'].dashboard_data()
        self.assertEqual([point['id'] for point in dashboard['payment_points']], [self.bank_journal.id])
        request = self._sent_request()
        with self.assertRaises(ValidationError):
            self.env['baseer.procurement.representative.advance'].submit_funding(
                request.id, other_journal.id, self.representative.id, 20, str(uuid4()), '2026-09-17',
            )

    def test_system_administrator_can_review_dashboard(self):
        administrator = self.env.ref('base.user_admin')
        administrator.group_ids |= self.env.ref('base.group_system')
        dashboard = self.env['baseer.procurement.representative.advance'].with_user(administrator).dashboard_data()
        self.assertIn('summary', dashboard)

    def test_funding_requires_transfer_date(self):
        request = self._sent_request()
        Model = self.env['baseer.procurement.representative.advance']
        with self.assertRaises(ValidationError):
            Model.submit_funding(
                request.id, self.bank_journal.id, self.representative.id, 20, str(uuid4()), False,
            )
