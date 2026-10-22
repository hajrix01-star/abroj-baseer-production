"""Native POS accounting evidence; all amounts and links are synthetic."""

from collections import Counter
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from odoo import Command, fields
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.baseer_profit_loss_report.models.profit_loss import SECTION_KEYS

from . import test_operations


@tagged('post_install', '-at_install', 'operations_pos_evidence')
class TestOperationsPosEvidence(TransactionCase):
    # Reuse fixture builders without inheriting/discovering the existing tests.
    _account = test_operations.TestOperationsGrossCalculator._account
    _journal = test_operations.TestOperationsGrossCalculator._journal
    _tax = test_operations.TestOperationsGrossCalculator._tax
    _empty_native_pos_order = test_operations.TestOperationsGrossCalculator._empty_native_pos_order
    _native_global_rounding_order = test_operations.TestOperationsGrossCalculator._native_global_rounding_order
    _empty_order_payment = test_operations.TestOperationsGrossCalculator._empty_order_payment
    _empty_native_reader = test_operations.TestOperationsGrossCalculator._empty_native_reader

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.company.partner_id.tz = 'UTC'
        self.report = self.env['baseer.operations.report']
        self.receivable = self._account('957101', 'asset_receivable', True)
        self.payable = self._account('957102', 'liability_payable', True)
        self.income = self._account('957103', 'income')
        self.other_income = self._account('957104', 'income_other')
        self.expense = self._account('957105', 'expense')
        self.cash = self._account('957106', 'asset_cash')
        self.tax_account = self._account('957107', 'liability_current')
        self.partner = self.env['res.partner'].with_company(self.company).create({
            'name': 'POS evidence synthetic partner',
            'property_account_receivable_id': self.receivable.id,
            'property_account_payable_id': self.payable.id,
        })
        self.sale_journal = self._journal('sale', 'PES')
        self.tax = self._tax('sale', self.tax_account)
        self.tax.refund_repartition_line_ids.filtered(
            lambda line: line.repartition_type == 'tax',
        ).account_id = self.tax_account

    def _order(self, session=None, amount=100, taxed=False):
        order = self._empty_native_pos_order(session)
        product = self.env['product.product'].with_company(self.company).create({
            'name': 'POS evidence synthetic service', 'type': 'service',
            'available_in_pos': True, 'property_account_income_id': self.income.id,
            'taxes_id': [Command.set(self.tax.ids if taxed else [])],
        })
        tax = amount * .15 if taxed else 0
        total = amount + tax
        order.write({
            'date_order': fields.Datetime.now(),
            'amount_total': total, 'amount_tax': tax, 'amount_paid': total,
            'lines': [Command.create({
                'product_id': product.id, 'uuid': str(uuid4()), 'qty': 1,
                'price_unit': amount, 'price_subtotal': amount,
                'price_subtotal_incl': total,
                'full_product_name': product.display_name,
                'tax_ids': [Command.set(self.tax.ids if taxed else [])],
            })],
        })
        self._empty_order_payment(order).amount = total
        return order

    def _close(self, order):
        session = order.session_id
        session.action_pos_session_closing_control()
        self.assertEqual(session.state, 'closed')
        self.assertEqual(session.move_id.state, 'posted')
        return session

    def _pl(self, move):
        return move.line_ids.filtered(
            lambda line: line.account_id.account_type in ('income', 'income_other'),
        )

    def _proven(self, lines):
        return self.report._proven_pos_secondary_lines(self.company, lines)

    def _assert_not_proven(self, lines):
        try:
            result = self._proven(lines)
        except AccessError:
            return
        self.assertFalse(set(lines.ids) & result)

    def _today_sources(self, journal_ids=None, report=None):
        today = fields.Date.today()
        selected_report = report if report is not None else self.report
        return selected_report._period_sources(
            self.company, today, today, journal_ids or [],
        )

    def test_closed_native_global_rounding_vector_is_secondary_only(self):
        order = self._native_global_rounding_order()
        order.date_order = fields.Datetime.now()
        self._empty_order_payment(order).amount = .09
        session = self._close(order)
        income = self._pl(session.move_id)
        self.assertTrue(income)
        self.assertEqual(self._proven(income), set(income.ids))
        sections, excluded = self._today_sources()
        self.assertEqual(sections['income'][self.income.id]['raw'], Decimal('.09'))
        self.assertEqual(len(sections['income'][self.income.id]['events']), 4)
        self.assertEqual(excluded['direct_aml_unproven'], 0)

    def test_sale_and_genuine_refund_same_account_preserve_signed_vectors(self):
        sale = self._order(taxed=True)
        refund = sale._refund()
        refund.write({'date_order': sale.date_order})
        self._empty_order_payment(refund).amount = -115
        refund._compute_prices()
        refund.action_pos_order_paid()
        session = self._close(sale)
        income = self._pl(session.move_id)
        self.assertTrue(income.filtered(lambda line: line.balance > 0))
        self.assertTrue(income.filtered(lambda line: line.balance < 0))
        self.assertEqual(self._proven(income), set(income.ids))
        sections, excluded = self._today_sources()
        self.assertEqual(sections['income'][self.income.id]['raw'], Decimal('0'))
        self.assertEqual(len(sections['income'][self.income.id]['events']), 2)
        self.assertEqual(excluded['direct_aml_unproven'], 0)

    def test_invoiced_order_is_excluded_from_session_sales_vector(self):
        sale = self._order(taxed=True)
        invoiced = self._order(sale.session_id, amount=40, taxed=True)
        invoiced.with_context(generate_pdf=False).action_pos_order_invoice()
        self.assertEqual(invoiced.state, 'done')
        self.assertTrue(invoiced.is_invoiced)
        self.assertEqual(invoiced.account_move.state, 'posted')
        session = self._close(sale)
        income = self._pl(session.move_id)
        self.assertEqual(sum(income.mapped('balance')), -100)
        self.assertEqual(self._proven(income), set(income.ids))
        sections, excluded = self._today_sources()
        self.assertEqual(sections['income'][self.income.id]['raw'], Decimal('161'))
        self.assertEqual(len(sections['income'][self.income.id]['events']), 2)
        self.assertEqual(excluded['direct_aml_unproven'], 0)

    def test_matching_reference_and_amount_without_native_fk_is_unproven(self):
        session = self._close(self._order())
        unrelated = self.env['account.move'].create({
            'journal_id': session.move_id.journal_id.id,
            'date': session.move_id.date, 'ref': session.move_id.ref,
            'line_ids': [Command.create({
                'name': session.name, 'account_id': self.income.id, 'credit': 100,
            }), Command.create({
                'account_id': self.cash.id, 'debit': 100,
            })],
        })
        unrelated.action_post()
        self.assertFalse(self._proven(self._pl(unrelated)))
        _sections, excluded = self._today_sources()
        self.assertEqual(excluded['direct_aml_unproven'], 1)
        self.assertFalse(self.report._coverage_complete(excluded))

    def test_compensating_extra_profit_lines_cannot_net_to_native_sale(self):
        session = self._close(self._order())
        move = session.move_id
        move.button_draft()
        move.write({'line_ids': [Command.create({
            'account_id': self.income.id, 'debit': 1,
        }), Command.create({
            'account_id': self.income.id, 'credit': 1,
        })]})
        move.action_post()
        self._assert_not_proven(self._pl(move))

    def test_changed_tax_vector_cannot_prove_unchanged_sales_total(self):
        session = self._close(self._order(taxed=True))
        move = session.move_id
        tax_line = move.line_ids.filtered('tax_repartition_line_id')
        self.assertTrue(tax_line)
        move.button_draft()
        tax_line.account_id = self._account('957108', 'liability_current')
        move.action_post()
        self._assert_not_proven(self._pl(move))

    def test_changed_tax_tags_cannot_prove_matching_balances(self):
        session = self._close(self._order(taxed=True))
        move = session.move_id
        tag = self.env['account.account.tag'].create({
            'name': 'Synthetic unrelated POS tax tag', 'applicability': 'taxes',
            'country_id': self.company.country_id.id,
        })
        move.button_draft()
        self._pl(move).tax_tag_ids = [Command.set(tag.ids)]
        move.action_post()
        self._assert_not_proven(self._pl(move))

    def test_hidden_native_session_line_fails_closed(self):
        session = self._close(self._order(taxed=True))
        lines = self._pl(session.move_id)
        hidden = session.move_id.line_ids.filtered('tax_repartition_line_id')[:1]
        self.assertTrue(hidden)
        secured = self._empty_native_reader()
        rule = self.env['ir.rule'].create({
            'name': 'Hide synthetic POS session tax evidence',
            'model_id': self.env['ir.model']._get('account.move.line').id,
            'domain_force': f"[('id', '!=', {hidden.id})]",
        })
        try:
            secured.env.invalidate_all()
            self.assertFalse(secured.env['account.move.line'].search([
                ('id', '=', hidden.id),
            ]))
            with self.assertRaises(AccessError):
                secured._proven_pos_secondary_lines(
                    self.company, secured.env['account.move.line'].browse(lines.ids),
                )
        finally:
            rule.unlink()

    def test_hidden_zero_tax_group_child_fails_even_when_header_still_matches(self):
        order = self._order(taxed=True)
        child = self.tax.copy({
            'name': 'Synthetic POS zero-rate tax group child', 'amount': 0,
        })
        group = self.env['account.tax'].with_company(self.company).create({
            'name': 'Synthetic POS tax group with zero child',
            'amount_type': 'group', 'type_tax_use': 'sale',
            'company_id': self.company.id,
            'children_tax_ids': [Command.set((self.tax | child).ids)],
        })
        order.lines.tax_ids = [Command.set(group.ids)]
        self.assertEqual(order.amount_total, 115)
        self.assertEqual(order.amount_tax, 15)
        self.assertEqual(child.amount, 0)
        session = self._close(order)
        lines = self._pl(session.move_id)
        secured = self._empty_native_reader()
        candidates = secured.env['account.move.line'].browse(lines.ids)
        self.assertEqual(secured._proven_pos_secondary_lines(
            self.company, candidates,
        ), set(lines.ids))
        rule = self.env['ir.rule'].create({
            'name': 'Hide zero-value synthetic tax group child',
            'model_id': self.env['ir.model']._get('account.tax').id,
            'domain_force': f"[('id', '!=', {child.id})]",
        })
        try:
            secured.env.invalidate_all()
            self.assertFalse(secured.env['account.tax'].search([('id', '=', child.id)]))
            # Removing this zero child leaves the visible 15% amount and the
            # stored 115/15 header consistent. Membership itself must be read.
            with self.assertRaises(AccessError):
                secured._proven_pos_secondary_lines(self.company, candidates)
        finally:
            rule.unlink()

    def _administrative_correction(self):
        # Model the historical defect through ordinary ORM: a paid order had
        # no lines when its native session was closed.  The later correction
        # remains separate, dated when it was actually performed.
        order = self._empty_native_pos_order()
        order.write({
            'date_order': fields.Datetime.now(),
            'amount_total': 5, 'amount_paid': 5,
        })
        self._empty_order_payment(order).amount = 5
        session = order.session_id
        session.config_id.journal_id = self._journal('general', 'PEA')
        session.action_pos_session_closing_control(
            balancing_account=self.receivable, amount_to_balance=5,
        )
        self.assertEqual(session.state, 'closed')
        self.assertEqual(session.move_id.state, 'posted')
        original_counter = session.move_id.line_ids.filtered(
            lambda line: line.account_id == self.receivable and line.balance == -5,
        )
        self.assertEqual(len(original_counter), 1)
        product = self.env['product.product'].with_company(self.company).create({
            'name': 'Synthetic recovered administrative source', 'type': 'service',
            'available_in_pos': True, 'property_account_income_id': self.income.id,
            'taxes_id': [Command.clear()],
        })
        order.write({'lines': [Command.create({
            'product_id': product.id, 'uuid': str(uuid4()), 'qty': 1,
            'price_unit': 5, 'price_subtotal': 5, 'price_subtotal_incl': 5,
            'full_product_name': product.display_name, 'tax_ids': [Command.clear()],
        })]})
        correction = self.env['account.move'].create({
            'journal_id': session.move_id.journal_id.id,
            'date': fields.Date.today() + timedelta(days=1),
            'line_ids': [Command.create({
                'account_id': self.income.id, 'credit': 5,
            }), Command.create({
                'account_id': self.receivable.id, 'debit': 5,
            })],
        })
        correction.action_post()
        counter = correction.line_ids.filtered(
            lambda line: line.account_id == self.receivable,
        )
        (original_counter | counter).reconcile()
        self.assertTrue(counter.full_reconcile_id)
        return order, session, correction, counter

    def test_reconciled_administrative_correction_is_secondary_on_actual_date(self):
        order, session, correction, _counter = self._administrative_correction()
        self.assertNotEqual(correction.date, session.move_id.date)
        self.assertEqual(self._proven(self._pl(correction)), set(self._pl(correction).ids))
        today = fields.Date.today()
        for day in (today, today + timedelta(days=1)):
            sections, excluded = self.report._period_sources(
                self.company, day, day, [correction.journal_id.id],
            )
            self.assertEqual(excluded['direct_aml_unproven'], 0)
            if day == today:
                events = sections['income'][self.income.id]['events']
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0]['source_id'], order.id)
                self.assertEqual(events[0]['date'], fields.Date.to_string(today))
                self.assertEqual(events[0]['amount'], Decimal('5'))
            else:
                self.assertFalse(sections['income'])
        unrelated_journal = self._journal('general', 'PEF')
        sections, excluded = self._today_sources([unrelated_journal.id])
        self.assertTrue(all(not value for value in sections.values()))
        self.assertEqual(excluded['direct_aml_unproven'], 0)

    def test_hidden_administrative_partial_or_counter_fails_closed(self):
        _order, _session, correction, counter = self._administrative_correction()
        partial = counter.matched_credit_ids | counter.matched_debit_ids
        self.assertEqual(len(partial), 1)
        secured = self._empty_native_reader()
        self.assertEqual(secured._proven_pos_secondary_lines(
            self.company,
            secured.env['account.move.line'].browse(self._pl(correction).ids),
        ), set(self._pl(correction).ids))
        for model, hidden in (
                ('account.partial.reconcile', partial),
                ('account.move.line', counter)):
            with self.subTest(model=model):
                rule = self.env['ir.rule'].create({
                    'name': 'Hide synthetic administrative reconciliation',
                    'model_id': self.env['ir.model']._get(model).id,
                    'domain_force': f"[('id', '!=', {hidden.id})]",
                })
                try:
                    secured.env.invalidate_all()
                    self.assertFalse(secured.env[model].search([('id', '=', hidden.id)]))
                    with self.assertRaises(AccessError):
                        secured._proven_pos_secondary_lines(
                            self.company,
                            secured.env['account.move.line'].browse(self._pl(correction).ids),
                        )
                finally:
                    rule.unlink()

    def test_unreconciled_administrative_counter_cannot_prove_correction(self):
        _order, _session, correction, counter = self._administrative_correction()
        self.assertEqual(self._proven(self._pl(correction)), set(self._pl(correction).ids))
        counter.remove_move_reconcile()
        self.assertFalse(counter.full_reconcile_id)
        self.assertFalse(self._proven(self._pl(correction)))

    def test_hidden_administrative_reversal_cannot_make_correction_standalone(self):
        _order, _session, correction, _counter = self._administrative_correction()
        lines = self._pl(correction)
        secured = self._empty_native_reader()
        candidates = secured.env['account.move.line'].browse(lines.ids)
        self.assertEqual(secured._proven_pos_secondary_lines(
            self.company, candidates,
        ), set(lines.ids))
        reversal = self.env['account.move'].create({
            'journal_id': correction.journal_id.id, 'date': correction.date,
            'reversed_entry_id': correction.id,
            'line_ids': [Command.create({
                'account_id': self.income.id, 'debit': 5,
            }), Command.create({
                'account_id': self.receivable.id, 'credit': 5,
            })],
        })
        reversal.action_post()
        self.assertFalse(secured._proven_pos_secondary_lines(self.company, candidates))
        rule = self.env['ir.rule'].create({
            'name': 'Hide synthetic administrative reversal',
            'model_id': self.env['ir.model']._get('account.move').id,
            'domain_force': f"[('id', '!=', {reversal.id})]",
        })
        try:
            secured.env.invalidate_all()
            self.assertFalse(secured.env['account.move'].search([('id', '=', reversal.id)]))
            with self.assertRaises(AccessError):
                secured._proven_pos_secondary_lines(self.company, candidates)
        finally:
            rule.unlink()

    def _variance_session(self, kind, surplus=5, outstanding_account=None):
        self.cash.reconcile = True
        journal = self._journal(kind, 'PEC' if kind == 'cash' else 'PEB')
        journal.write({
            'default_account_id': self.cash.id,
            'profit_account_id': self.other_income.id,
            'loss_account_id': self.expense.id,
        })
        method = self.env['pos.payment.method'].with_company(self.company).create({
            'name': 'POS evidence synthetic ' + kind,
            'company_id': self.company.id, 'journal_id': journal.id,
            'receivable_account_id': self.receivable.id,
            'outstanding_account_id': (
                outstanding_account.id if outstanding_account is not None else self.cash.id
            ),
        })
        config = self.env['pos.config'].with_company(self.company).create({
            'name': 'POS evidence synthetic variance ' + kind,
            'company_id': self.company.id,
            'journal_id': self.sale_journal.id,
            'invoice_journal_id': self.sale_journal.id,
            'cash_control': kind == 'cash',
            'payment_method_ids': [Command.set(method.ids)],
        })
        session = self.env['pos.session'].create({'config_id': config.id})
        session.set_opening_control(0, 'Synthetic POS variance')
        order = self._order(session)
        if kind == 'cash':
            self.assertTrue(session.post_closing_cash_details(100 + surplus)['successful'])
            session.action_pos_session_closing_control()
        else:
            session.action_pos_session_closing_control(
                bank_payment_method_diffs={method.id: surplus},
            )
        self.assertEqual(session.state, 'closed')
        return order, session, journal, method

    def _variance_sources(self, journal_ids=None, report=None):
        today = fields.Date.today()
        sections = {key: {} for key in SECTION_KEYS}
        excluded = Counter()
        selected_report = report if report is not None else self.report
        recognized = selected_report._native_pos_variance_inflows(
            self.company, today, today, journal_ids or [], sections, excluded,
        )
        return recognized, sections, excluded

    def _assert_variance_event(self, sections, model, income_empty=True):
        if income_empty:
            self.assertFalse(sections['income'])
        entry = sections['income_other'][self.other_income.id]
        self.assertEqual(entry['raw'], Decimal('5'))
        self.assertEqual(entry['count'], 1)
        event, = entry['events']
        self.assertEqual(event['source_model'], model)
        self.assertTrue(event['liquidity_line_id'])
        self.assertFalse(event.get('payment_line_id'))
        self.assertEqual(event['date'], fields.Date.to_string(fields.Date.today()))

    def test_native_cash_surplus_is_other_income_once_without_extra_sale(self):
        order, session, _journal, _method = self._variance_session('cash')
        statements = session.statement_line_ids.filtered(
            lambda line: self._pl(line.move_id),
        )
        self.assertEqual(len(statements), 1)
        recognized, sections, _excluded = self._variance_sources()
        self.assertEqual(recognized, set(self._pl(statements.move_id).ids))
        self._assert_variance_event(sections, 'account.bank.statement.line')
        combined, excluded = self._today_sources()
        self.assertEqual(combined['income'][self.income.id]['raw'], Decimal('100'))
        self.assertEqual(combined['income'][self.income.id]['events'][0]['source_id'], order.id)
        self._assert_variance_event(combined, 'account.bank.statement.line', income_empty=False)
        self.assertEqual(excluded['direct_aml_unproven'], 0)

    def test_native_bank_surplus_does_not_recognize_entire_pos_payment(self):
        _order, session, journal, _method = self._variance_session('bank')
        payment, = session.bank_payment_ids
        self.assertEqual(payment.amount, 105)
        recognized, sections, _excluded = self._variance_sources([journal.id])
        self.assertEqual(recognized, set(self._pl(payment.move_id).ids))
        self._assert_variance_event(sections, 'account.payment')
        recognized, filtered, _excluded = self._variance_sources([self.sale_journal.id])
        self.assertFalse(recognized)
        self.assertTrue(all(not value for value in filtered.values()))
        combined, excluded = self._today_sources()
        self.assertEqual(combined['income'][self.income.id]['raw'], Decimal('100'))
        self.assertEqual(combined['income_other'][self.other_income.id]['raw'], Decimal('5'))
        self.assertEqual(excluded['direct_aml_unproven'], 0)

    def test_cash_surplus_without_session_fk_is_unproven(self):
        _order, session, _journal, _method = self._variance_session('cash')
        statements = session.statement_line_ids.filtered(lambda line: self._pl(line.move_id))
        statements.pos_session_id = False
        recognized, sections, _excluded = self._variance_sources()
        self.assertFalse(recognized)
        self.assertFalse(sections['income_other'])
        _sections, excluded = self._today_sources()
        self.assertEqual(excluded['direct_aml_unproven'], 1)

    def test_hidden_bank_surplus_source_payment_fails_closed(self):
        order, _session, _journal, _method = self._variance_session('bank')
        secured = self._empty_native_reader()
        recognized, sections, _excluded = self._variance_sources(report=secured)
        self.assertTrue(recognized)
        self._assert_variance_event(sections, 'account.payment')
        rule = self.env['ir.rule'].create({
            'name': 'Hide synthetic POS surplus source payment',
            'model_id': self.env['ir.model']._get('pos.payment').id,
            'domain_force': f"[('id', 'not in', {order.payment_ids.ids})]",
        })
        try:
            secured.env.invalidate_all()
            self.assertFalse(secured.env['pos.payment'].search([
                ('id', 'in', order.payment_ids.ids),
            ]))
            with self.assertRaises(AccessError):
                self._variance_sources(report=secured)
        finally:
            rule.unlink()

    def test_hidden_bank_original_reconciliation_witness_fails_closed(self):
        _order, session, _journal, _method = self._variance_session('bank')
        payment, = session.bank_payment_ids
        receivable = payment.move_id.line_ids.filtered(
            lambda line: line.account_id == self.receivable,
        )
        partial = receivable.matched_credit_ids | receivable.matched_debit_ids
        self.assertEqual(len(partial), 1)
        original = partial.debit_move_id
        self.assertEqual(original.move_id, session.move_id)
        full = receivable.full_reconcile_id
        self.assertTrue(full)
        secured = self._empty_native_reader()
        recognized, sections, _excluded = self._variance_sources(report=secured)
        self.assertEqual(recognized, set(self._pl(payment.move_id).ids))
        self._assert_variance_event(sections, 'account.payment')
        for model, hidden in (
                ('account.partial.reconcile', partial),
                ('account.full.reconcile', full),
                ('account.move.line', original)):
            with self.subTest(model=model):
                rule = self.env['ir.rule'].create({
                    'name': 'Hide original synthetic POS bank witness',
                    'model_id': self.env['ir.model']._get(model).id,
                    'domain_force': f"[('id', '!=', {hidden.id})]",
                })
                try:
                    secured.env.invalidate_all()
                    self.assertFalse(secured.env[model].search([('id', '=', hidden.id)]))
                    with self.assertRaises(AccessError):
                        self._variance_sources(report=secured)
                finally:
                    rule.unlink()

    def test_bank_surplus_on_current_asset_claim_is_not_liquidity_income(self):
        claim = self._account('957109', 'asset_current', True)
        _order, session, journal, method = self._variance_session(
            'bank', outstanding_account=claim,
        )
        payment, = session.bank_payment_ids
        self.assertEqual(journal.default_account_id.account_type, 'asset_cash')
        self.assertEqual(method.outstanding_account_id, claim)
        self.assertEqual(payment.outstanding_account_id, claim)
        self.assertEqual(payment.amount, 105)
        self.assertFalse(payment.move_id.line_ids.filtered(
            lambda line: line.account_id.account_type == 'asset_cash',
        ))
        secured = self._empty_native_reader()
        visible_move = secured.env['account.move'].browse(payment.move_id.id)
        # A fully readable, valid native posting still proves only an asset
        # claim. There is no cash/bank liquidity inflow to recognize here.
        self.assertEqual(set(secured._pos_evidence_lines(
            visible_move, self.company,
        ).ids), set(payment.move_id.line_ids.ids))
        recognized, sections, _excluded = self._variance_sources(report=secured)
        self.assertFalse(recognized)
        self.assertFalse(sections['income_other'])
        _sections, excluded = self._today_sources()
        self.assertEqual(excluded['direct_aml_unproven'], 1)

    def test_liquidity_source_id_changes_event_fingerprint(self):
        today = fields.Date.today()
        event = {
            'source_model': 'account.bank.statement.line', 'source_id': 1,
            'line_model': 'account.move.line', 'line_id': 2,
            'date': fields.Date.to_string(today), 'amount': Decimal('5'),
            'liquidity_line_id': 3,
        }
        first = self.report._event_fingerprint(
            self.company, today, today, [], 'other_income', self.other_income.id,
            [event],
        )
        second = self.report._event_fingerprint(
            self.company, today, today, [], 'other_income', self.other_income.id,
            [{**event, 'liquidity_line_id': 4}],
        )
        self.assertNotEqual(first, second)
