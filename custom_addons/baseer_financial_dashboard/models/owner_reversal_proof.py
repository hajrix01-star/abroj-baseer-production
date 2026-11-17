"""Read-only proof for a narrow, complete vendor-payment reversal pair.

This helper is not wired to the dashboard collector yet. It supplies evidence,
not accounting events, so callers must also prove source census and ownership.
"""

from collections import Counter

from odoo import models


class FinancialDashboardReversalProof(models.AbstractModel):
    _inherit = 'baseer.financial.dashboard.operations'

    def _dashboard_reversal_pair(self, payment, company, read_facts=None):
        """Return payment/reversal witnesses only for an exact two-line pair.

        Every referenced row is read under the caller's normal permissions.
        A mismatch remains unproved; no company, amount or name is inferred.
        """
        payment.ensure_one()
        company.ensure_one()
        # Rebind caller-provided identities to this request's environment;
        # otherwise a sudo or foreign-context recordset could bypass checks.
        payment = self.env['account.payment'].browse(payment.id).exists()
        company = self.env['res.company'].browse(company.id).exists()
        if (not payment or not company or company != self.env.company
                or company not in self.env.companies
                or company not in self.env.user.company_ids):
            self._deny_incomplete_source()
        self._owner_check_read(payment, read_facts)
        move = payment.move_id
        self._owner_check_read(move, read_facts)
        if not move:
            return None
        self.env['account.move'].flush_model(['reversed_entry_id'])
        self.env['account.move.line'].flush_model(['move_id'])
        reversals = move.reversal_move_ids
        self._assert_visible('account_move', 'reversed_entry_id=%s', [move.id],
                             reversals, read_facts=read_facts)
        self._owner_check_read(reversals, read_facts)
        if len(reversals) != 1:
            return None
        reversal = reversals
        descendants = reversal.reversal_move_ids
        self._assert_visible('account_move', 'reversed_entry_id=%s', [reversal.id],
                             descendants, read_facts=read_facts)
        self._owner_check_read(descendants, read_facts)
        journal, reverse_journal = move.journal_id, reversal.journal_id
        partner, currency = payment.partner_id, company.currency_id
        method, outstanding = payment.payment_method_line_id, payment.outstanding_account_id
        lines, reverse_lines = move.line_ids, reversal.line_ids
        for record in (company, currency, journal, reverse_journal, partner, method, outstanding,
                       lines, reverse_lines, lines.account_id, reverse_lines.account_id,
                       lines.partner_id, reverse_lines.partner_id):
            self._owner_check_read(record, read_facts)
        for entry, entry_lines in ((move, lines), (reversal, reverse_lines)):
            self._assert_visible('account_move_line', 'move_id=%s', [entry.id],
                                 entry_lines, read_facts=read_facts)
        if (payment.company_id != company or move.company_id != company
                or reversal.company_id != company or payment.move_id != move
                or move.origin_payment_id != payment or reversal.reversed_entry_id != move
                or move.reversed_entry_id or descendants or reversal.origin_payment_id
                or move.state != 'posted' or reversal.state != 'posted'
                or move.move_type != 'entry' or reversal.move_type != 'entry'
                or move.statement_line_id or reversal.statement_line_id
                or payment.payment_type != 'outbound' or payment.partner_type != 'supplier'
                or payment.state not in ('in_process', 'paid')
                or payment.journal_id != journal or not method or method.journal_id != journal
                or not partner or payment.currency_id != currency
                or move.currency_id != currency or reversal.currency_id != currency
                or journal.company_id != company or reverse_journal.company_id != company
                or journal.type not in ('bank', 'cash')
                or reverse_journal.type not in ('bank', 'cash')
                or len(lines) != 2 or len(reverse_lines) != 2
                or reversal.date < move.date
                or any(line.company_id != company or line.currency_id != currency
                       or line.journal_id != line.move_id.journal_id
                       or line.tax_line_id or line.tax_ids
                       or self._decimal(line.amount_currency) != self._decimal(line.balance)
                       for line in (lines | reverse_lines))):
            return None
        cash = lines.filtered(lambda line: line.account_id.account_type == 'asset_cash')
        payable = lines.filtered(lambda line: line.account_id.account_type == 'liability_payable')
        reverse_cash = reverse_lines.filtered(lambda line: line.account_id.account_type == 'asset_cash')
        reverse_payable = reverse_lines.filtered(lambda line: line.account_id.account_type == 'liability_payable')
        if any(len(group) != 1 for group in (cash, payable, reverse_cash, reverse_payable)):
            return None
        amount = self._decimal(payment.amount)
        if (amount <= 0 or payable.partner_id != partner
                or reverse_payable.partner_id != partner
                or cash.account_id != journal.default_account_id
                or outstanding != cash.account_id or method.payment_account_id != cash.account_id
                or reverse_cash.account_id != reverse_journal.default_account_id
                or cash.account_id != reverse_cash.account_id
                or payable.account_id != reverse_payable.account_id
                or self._decimal(cash.balance) != -amount
                or self._decimal(payable.balance) != amount
                or self._decimal(reverse_cash.balance) != amount
                or self._decimal(reverse_payable.balance) != -amount):
            return None
        # Compare the scoped account, partner, currency and balance attributes.
        def signature(rows, sign):
            return Counter((row.account_id.id, row.partner_id.id, row.currency_id.id,
                            sign * self._decimal(row.balance)) for row in rows)
        if signature(lines, 1) != signature(reverse_lines, -1):
            return None
        return {'payment': payment, 'move': move, 'reversal': reversal,
                'outflow': cash, 'refund': reverse_cash,
                'payable': payable, 'reverse_payable': reverse_payable,
                'amount': amount}
