"""Dashboard-only conservative proof of split vendor payment settlements.

The billing report model is deliberately not extended in place.  A candidate
is accepted only after the original collector has accounted for it as one of
the two known exclusions and every additional accounting edge is proved.
"""
from collections import Counter
from decimal import Decimal
from hashlib import sha256
import json

from odoo import _, api, fields, models
from odoo.exceptions import AccessError
from odoo.addons.baseer_operations_report.models.operations import (
    EXPENSE_KEYS, NATIVE_PAYMENT_CENSUS_BATCH_SIZE, SECTION_KEYS,
)


class FinancialDashboardOperations(models.AbstractModel):
    _name = 'baseer.financial.dashboard.operations'
    _inherit = 'baseer.operations.report'
    _description = 'Financial dashboard isolated operations reader'

    @api.model
    def _scope(self, filters):
        dashboard = self.env.ref(
            'baseer_financial_dashboard.dashboard_financial_performance',
            raise_if_not_found=False,
        )
        if not dashboard:
            raise AccessError(_('The financial dashboard is not available.'))
        dashboard.check_access('read')
        dashboard.check_access_rule('read')
        if (dashboard.baseer_dashboard_kind != 'financial_dashboard'
                or not dashboard.is_published
                or (dashboard.group_ids
                    and not dashboard.group_ids & self.env.user.all_group_ids)):
            raise AccessError(_('The financial dashboard is not available.'))
        result = super()._scope(filters)
        company = result[0]
        if dashboard.company_ids and (
                company not in dashboard.company_ids
                or self.env.company not in dashboard.company_ids):
            raise AccessError(_('The financial dashboard is not available for this company.'))
        return result

    @api.model
    def _native_payment_outflows(self, company, start, end, journal_ids,
                                 sections, excluded, claimed_payment_ids=frozenset(),
                                 read_facts=None, prefetch_bills=True):
        # Preserve the original collector and every original rejection.  The
        # second pass can remove an exclusion only after proving that same
        # payment would have failed *exactly* one of the two narrow guards.
        super()._native_payment_outflows(
            company, start, end, journal_ids, sections, excluded,
            claimed_payment_ids=claimed_payment_ids, read_facts=read_facts,
            prefetch_bills=prefetch_bills,
        )
        if not (excluded.get('unsupported_native_payment')
                or excluded.get('unassigned_native_payment')):
            return
        domain = [
            ('company_id', '=', company.id), ('payment_type', '=', 'outbound'),
            ('partner_type', '=', 'supplier'), ('move_id.state', '=', 'posted'),
            ('move_id.date', '>=', start), ('move_id.date', '<=', end),
        ]
        # Never add an unbounded second scan to the existing report.  When
        # the period exceeds the proof budget, retain the original incomplete
        # result instead of accepting a partial census as complete.
        payments = self.env['account.payment'].search(
            domain, order='id', limit=NATIVE_PAYMENT_CENSUS_BATCH_SIZE + 1,
        )
        if len(payments) > NATIVE_PAYMENT_CENSUS_BATCH_SIZE:
            return
        self._owner_check_read(payments, read_facts)
        if not payments:
            return
        # The original collector has already proved the payment census. Prove
        # batch ownership again in one bounded identity query before reuse.
        self.env['baseer.purchase.batch.line'].flush_model(['company_id', 'payment_id'])
        self.env.cr.execute(
            'SELECT id FROM baseer_purchase_batch_line WHERE company_id=%s AND payment_id = ANY(%s)',
            [company.id, payments.ids],
        )
        batch_ids = {row[0] for row in self.env.cr.fetchall()}
        batch_payment_ids = set()
        if batch_ids:
            self._require_read(('baseer.purchase.batch.line',))
            batch = self.env['baseer.purchase.batch.line'].search([
                ('company_id', '=', company.id), ('payment_id', 'in', payments.ids),
            ])
            if set(batch.ids) != batch_ids:
                self._deny_incomplete_source()
            self._owner_check_read(batch, read_facts)
            batch_payment_ids = set(batch.mapped('payment_id').ids)
        used = set(claimed_payment_ids) | batch_payment_ids
        for section in sections.values():
            for entry in section.values():
                used.update(event['source_id'] for event in entry['events']
                            if event.get('source_model') == 'account.payment')
        candidates = payments.filtered(lambda payment: payment.id not in used)
        cache = self._native_payment_identity_census(candidates)

        def visible(table, field, parent_id, records):
            if not self._native_payment_cached_visible(
                    cache, table, field, parent_id, records, read_facts):
                self._assert_visible(table, '%s=%%s' % field, [parent_id],
                                     records, read_facts=read_facts)

        for payment in candidates:
            proved = self._dashboard_prove_split_payment(
                payment, company, journal_ids, visible, read_facts,
            )
            if not proved:
                continue
            exclusion, events = proved
            if excluded.get(exclusion, 0) <= 0:
                # An accepted proof must correspond to an actual rejection
                # made by the unchanged original collector in this request.
                self._deny_incomplete_source()
            self._record_many(sections, events, read_facts=read_facts)
            excluded[exclusion] -= 1
            excluded['unconfirmed_payment_link'] += 1

    def _dashboard_prove_split_payment(self, payment, company, journal_ids,
                                       visible, read_facts):
        """Return one narrow, entirely visible proof or leave it excluded."""
        move, journal = payment.move_id, payment.journal_id
        partner, method, currency = payment.partner_id, payment.payment_method_line_id, company.currency_id
        account = journal.default_account_id
        for records in (payment, move, journal, partner, method, account, currency):
            self._owner_check_read(records, read_facts)
        lines = move.line_ids
        visible('account_move_line', 'move_id', move.id, lines)
        visible('account_move', 'reversed_entry_id', move.id, move.reversal_move_ids)
        self._owner_check_read(lines.mapped('account_id'), read_facts)
        self._owner_check_read(lines.mapped('partner_id'), read_facts)
        if (payment.company_id != company or move.company_id != company
                or payment.move_id != move or move.origin_payment_id != payment
                or payment.payment_type != 'outbound' or payment.partner_type != 'supplier'
                or payment.state not in ('in_process', 'paid') or payment.currency_id != currency
                or journal.company_id != company or journal.type not in ('bank', 'cash')
                or (journal.currency_id and journal.currency_id != currency)
                or (journal_ids and journal.id not in journal_ids)
                or move.journal_id != journal or move.state != 'posted'
                or move.statement_line_id or move.reversed_entry_id or move.reversal_move_ids
                or not partner or not method or method.journal_id != journal
                or method.payment_account_id != account or payment.outstanding_account_id != account
                or account.account_type != 'asset_cash'
                or any(line.company_id != company or line.journal_id != journal
                       or line.currency_id != currency for line in lines)):
            return None
        liquidity = lines.filtered(lambda line: line.account_id == account)
        payable = lines.filtered(lambda line: line.account_id.account_type == 'liability_payable')
        amount = self._decimal(payment.amount)
        if (len(liquidity) != 1 or len(payable) != 1 or amount <= 0
                or self._decimal(liquidity.balance) != -amount
                or payable.partner_id != partner):
            return None
        others = lines - liquidity - payable
        payable_amount = self._decimal(payable.balance)
        if len(lines) == 3 and len(others) == 1:
            fee = others
            fee_amount = -self._decimal(fee.balance)
            if (fee.account_id.account_type != 'expense' or fee.partner_id != partner
                    or fee_amount <= 0
                    or payable_amount != amount + fee_amount
                    or sum((self._decimal(line.balance) for line in lines), Decimal(0)) != 0):
                return None
            exclusion = 'unsupported_native_payment'
        elif len(lines) == 2 and not others and payable_amount == amount:
            fee = self.env['account.move.line']
            exclusion = 'unassigned_native_payment'
        else:
            return None
        partials = payable.matched_credit_ids
        visible('account_partial_reconcile', 'debit_move_id', payable.id, partials)
        self._owner_check_read(partials.mapped('credit_move_id'), read_facts)
        if any(partial.debit_move_id != payable or partial.company_id != company
               for partial in partials):
            return None
        bill_partials = partials.filtered(lambda part: part.credit_move_id.move_id.move_type == 'in_invoice')
        adjustment_partials = partials - bill_partials
        if (len(bill_partials) != 1 or len(partials) != (1 if fee else 2)
                or len(adjustment_partials) != (0 if fee else 1)
                or sum((self._decimal(part.amount) for part in partials), Decimal(0)) != payable_amount):
            return None
        bill_partial = bill_partials
        bill_line = bill_partial.credit_move_id
        bill = bill_line.move_id
        self._owner_check_read(bill, read_facts)
        self._owner_check_read(bill.partner_id, read_facts)
        self._owner_check_read(bill_line.partner_id, read_facts)
        bill_lines = bill.line_ids
        visible('account_move_line', 'move_id', bill.id, bill_lines)
        visible('account_move', 'reversed_entry_id', bill.id, bill.reversal_move_ids)
        visible('account_partial_reconcile', 'credit_move_id', bill_line.id, bill_line.matched_debit_ids)
        self._owner_check_read(bill_lines.mapped('account_id'), read_facts)
        origin_bills, reconciled_bills = payment.invoice_ids, payment.reconciled_bill_ids
        self._owner_check_read(origin_bills, read_facts)
        self._owner_check_read(reconciled_bills, read_facts)
        if (bill.state != 'posted' or bill.company_id != company or bill.currency_id != currency
                or bill.partner_id != partner or not bill.invoice_date or bill.invoice_date > move.date
                or bill.reversed_entry_id or bill.reversal_move_ids
                or bill_line.company_id != company
                or bill_line.account_id != payable.account_id or bill_line.partner_id != partner
                or bill_line.currency_id != currency or bill_partial not in bill_line.matched_debit_ids
                or reconciled_bills != bill or (origin_bills and origin_bills != bill)
                or any(line.company_id != company or line.currency_id != currency for line in bill_lines)
                or len(bill_lines.filtered(lambda line: line.account_id.account_type == 'liability_payable')) != 1):
            return None
        for tax_line in bill_lines.filtered('tax_line_id'):
            tax, repartition = tax_line.tax_line_id, tax_line.tax_repartition_line_id
            self._owner_check_read(tax, read_facts)
            self._owner_check_read(repartition, read_facts)
            if not repartition or repartition.tax_id != tax or repartition not in tax.invoice_repartition_line_ids:
                self._deny_incomplete_source()
        bill_sections = {key: {} for key in SECTION_KEYS}
        bill_excluded, line_entries = Counter(), []
        self._invoice_amounts(bill, company, bill_sections, bill_excluded,
                              line_entries, read_facts=read_facts)
        if (len(line_entries) != 1 or line_entries[0][1] not in EXPENSE_KEYS
                or line_entries[0][3] != self._decimal(bill.amount_total)
                or any(bill_excluded.values())):
            return None
        invoice_id, section, bill_account, gross = line_entries[0]
        bill_paid = self._decimal(bill_partial.amount)
        if bill_paid <= 0 or bill_paid > gross or (fee and bill_paid != payable_amount):
            return None
        sources = [(invoice_id, section, bill_account, amount if fee else bill_paid)]
        adjustment = self.env['account.move']
        if not fee:
            partial = adjustment_partials
            counterpart = partial.credit_move_id
            adjustment = counterpart.move_id
            self._owner_check_read(adjustment, read_facts)
            self._owner_check_read(counterpart.partner_id, read_facts)
            adj_lines = adjustment.line_ids
            visible('account_move_line', 'move_id', adjustment.id, adj_lines)
            visible('account_move', 'reversed_entry_id', adjustment.id, adjustment.reversal_move_ids)
            visible('account_partial_reconcile', 'credit_move_id', counterpart.id,
                    counterpart.matched_debit_ids)
            self._owner_check_read(adj_lines.mapped('account_id'), read_facts)
            self._owner_check_read(adj_lines.mapped('partner_id'), read_facts)
            adj_expense = adj_lines.filtered(lambda line: line.account_id.account_type == 'expense')
            adj_payable = adj_lines.filtered(lambda line: line.account_id.account_type == 'liability_payable')
            delta = self._decimal(partial.amount)
            if (adjustment.move_type != 'entry' or adjustment.state != 'posted'
                    or adjustment.company_id != company or adjustment.date != move.date
                    or adjustment.journal_id.company_id != company
                    or adjustment.currency_id != currency or adjustment.reversed_entry_id
                    or adjustment.reversal_move_ids or adjustment.statement_line_id
                    or adjustment.origin_payment_id or len(adj_lines) != 2
                    or len(adj_expense) != 1 or len(adj_payable) != 1 or adj_payable != counterpart
                    or counterpart.account_id != payable.account_id or counterpart.partner_id != partner
                    or adj_expense.partner_id != partner
                    or len(counterpart.matched_debit_ids) != 1
                    or partial not in counterpart.matched_debit_ids or delta <= 0
                    or self._decimal(counterpart.balance) != -delta
                    or self._decimal(adj_expense.balance) != delta
                    or any(line.company_id != company or line.currency_id != currency
                           or line.journal_id != adjustment.journal_id for line in adj_lines)
                    or bill_paid + delta != amount):
                return None
            sources.append((adj_expense.id, 'expense', adj_expense.account_id, delta))
        proof = {
            'payment': payment.id, 'payment_move': move.id, 'journal': journal.id,
            'company': company.id, 'currency': currency.id, 'partner': partner.id,
            'amount': str(amount), 'payment_state': payment.state,
            'payment_type': payment.payment_type, 'partner_type': payment.partner_type,
            'method': method.id, 'method_account': method.payment_account_id.id,
            'outstanding_account': payment.outstanding_account_id.id,
            'bill': bill.id, 'bill_invoice_date': fields.Date.to_string(bill.invoice_date),
            'bill_total': str(self._decimal(bill.amount_total)),
            'origin_bills': sorted(origin_bills.ids),
            'reconciled_bills': sorted(reconciled_bills.ids),
            'adjustment': adjustment.id or 0,
            'moves': [(m.id, m.state, fields.Date.to_string(m.date), m.reversed_entry_id.id,
                       sorted(m.reversal_move_ids.ids)) for m in (move | bill | adjustment).sorted('id')],
            'lines': [(line.id, line.move_id.id, line.account_id.id, line.partner_id.id,
                       line.currency_id.id, str(self._decimal(line.balance)),
                       line.tax_line_id.id, sorted(line.tax_ids.ids))
                      for line in (lines | bill_lines | adjustment.line_ids).sorted('id')],
            'partials': [(part.id, part.debit_move_id.id, part.credit_move_id.id,
                          str(self._decimal(part.amount))) for part in partials.sorted('id')],
        }
        event_base = {
            'source_model': 'account.payment', 'source_id': payment.id,
            'line_model': 'account.move.line', 'payment_move_id': move.id,
            'payment_line_id': liquidity.id, 'date': fields.Date.to_string(move.date),
            'link_status': 'unconfirmed', 'dashboard_payment_proof': proof,
        }
        events = [(source_section, source_account, value, 'native_vendor_payment_unconfirmed',
                   {**event_base, 'line_id': line_id})
                  for line_id, source_section, source_account, value in sources]
        return exclusion, events

    def _owner_period_revision(self, company, start, end, journal_ids, sales, cash, display):
        original = super()._owner_period_revision(company, start, end, journal_ids, sales, cash, display)
        proofs = [event['dashboard_payment_proof'] for event in cash['events']
                  if event.get('dashboard_payment_proof')]
        canonical = sorted((json.dumps(proof, sort_keys=True, separators=(',', ':'))
                            for proof in proofs))
        return sha256(json.dumps([original, canonical], separators=(',', ':')).encode()).hexdigest()
