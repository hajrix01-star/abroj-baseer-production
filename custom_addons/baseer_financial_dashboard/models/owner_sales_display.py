"""Dashboard-only handling of non-financial invoice notes.

Only the dashboard's invoice validator is overridden. Shared relation-census
helpers and the billing and HR collectors retain their original behavior.
"""

from decimal import Decimal

from odoo import _, models
from odoo.addons.baseer_operations_report.models.operations import INVOICE_TYPES


class FinancialDashboardSalesDisplay(models.AbstractModel):
    _inherit = 'baseer.financial.dashboard.operations'

    def _dashboard_sales_note_lines(self, children):
        """Return notes proved harmless, with complete tax/reconcile census."""
        candidates = children.filtered(lambda line: line.display_type == 'line_note' and not line.account_id)
        if not candidates:
            return self.env['account.move.line']
        self._require_read(('account.partial.reconcile', 'account.tax'))
        partial_model = self.env['account.partial.reconcile']
        partial_model.flush_model(['debit_move_id', 'credit_move_id'])
        partials = partial_model.search(['|', ('debit_move_id', 'in', candidates.ids),
                                         ('credit_move_id', 'in', candidates.ids)])
        self._assert_visible('account_partial_reconcile',
                             '(debit_move_id = ANY(%s) OR credit_move_id = ANY(%s))',
                             [candidates.ids, candidates.ids], partials)
        reconciled_ids = set(partials.debit_move_id.ids + partials.credit_move_id.ids)

        # tax_ids is an M2M: proving the parent/line census does not prove
        # membership visibility. SQL supplies only identities, never amounts.
        candidates.flush_recordset(['tax_ids'])
        self.env.cr.execute(
            'SELECT account_move_line_id, account_tax_id '
            'FROM account_move_line_account_tax_rel WHERE account_move_line_id = ANY(%s)',
            [candidates.ids],
        )
        tax_edges = set(self.env.cr.fetchall())
        visible_edges = {(line.id, tax.id) for line in candidates for tax in line.tax_ids}
        if tax_edges != visible_edges:
            self._deny_incomplete_source()
        candidates.tax_ids.check_access('read')
        taxed_ids = {line_id for line_id, _tax_id in tax_edges}

        ignored = self.env['account.move.line']
        for line in candidates:
            move, company = line.move_id, line.move_id.company_id
            if (line.company_id != company or line.journal_id != move.journal_id
                    or line.currency_id != company.currency_id or line.tax_line_id
                    or line.id in taxed_ids or line.id in reconciled_ids):
                continue
            if all(self._owner_sales_money(value, company.currency_id) == 0 for value in (
                    line.debit, line.credit, line.balance, line.amount_currency)):
                ignored |= line
        return ignored

    def _owner_sales_invoices(self, moves, company):
        # The original complete ORM/SQL parent-line census is always done
        # before considering any note. Keep the remaining accounting checks
        # identical to the base reader; no billing model is changed.
        moves.check_access('read')
        moves.journal_id.check_access('read')
        for move in moves:
            self._owner_sales_currency(move, company)
        lines = self._owner_sales_pairs(moves, 'line_ids', 'account.move.line', 'move_id')
        lines -= self._dashboard_sales_note_lines(lines)
        lines.account_id.check_access('read')
        by_move = {move.id: [] for move in moves}
        for line in lines:
            if (line.company_id != company or line.journal_id != line.move_id.journal_id
                    or line.currency_id != company.currency_id
                    or not line.account_id or company not in line.account_id.company_ids):
                self._deny_incomplete_source()
            balance = self._owner_sales_money(line.balance, company.currency_id)
            debit = self._owner_sales_money(line.debit, company.currency_id)
            credit = self._owner_sales_money(line.credit, company.currency_id)
            if (debit < 0 or credit < 0 or debit - credit != balance
                    or self._owner_sales_money(line.amount_currency, company.currency_id) != balance):
                self._deny_incomplete_source()
            by_move[line.move_id.id].append((line.account_id.account_type, balance))
        result = {}
        for move in moves:
            if (move.company_id != company or move.state != 'posted'
                    or move.move_type not in INVOICE_TYPES or not move.invoice_date
                    or not move.journal_id or move.journal_id.company_id != company):
                self._deny_incomplete_source()
            total = self._owner_sales_money(move.amount_total, company.currency_id)
            amount = -total if move.move_type == 'out_refund' else total
            rows = by_move[move.id]
            receivable = [value for kind, value in rows if kind == 'asset_receivable']
            if (not rows or not receivable or sum((value for _kind, value in rows), Decimal(0))
                    or sum(receivable, Decimal(0)) != amount):
                self._deny_incomplete_source()
            result[move.id] = {
                'company_id': company.id, 'direction': 'incoming',
                'source_model': 'account.move', 'source_id': move.id,
                'line_model': 'account.move', 'line_id': move.id,
                'amount': amount, 'date': move.invoice_date,
                'ledger_confirmed': False, 'sales_posted': True,
                'channels': [('unallocated', _('Unallocated'), amount)],
            }
        return result
