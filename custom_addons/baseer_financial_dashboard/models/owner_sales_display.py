"""Dashboard-only handling of non-financial invoice display lines."""

from odoo import models


class FinancialDashboardSalesDisplay(models.AbstractModel):
    _inherit = 'baseer.financial.dashboard.operations'

    def _owner_sales_pairs(self, parents, field_name, child_model, inverse):
        # The inherited implementation first checks read access and compares
        # the complete ORM set with the SQL census for every parent. Never
        # filter before this proof: hidden notes are still hidden source data.
        children = super()._owner_sales_pairs(parents, field_name, child_model, inverse)
        if (parents._name, field_name, child_model, inverse) != (
                'account.move', 'line_ids', 'account.move.line', 'move_id'):
            return children

        # Only an accountless, completely zero display line may be omitted.
        # Keep every other line for the original invoice validation, which
        # fails closed on accountless financial lines. Checking company,
        # journal and currency here preserves the parent's checks for the
        # small number of rows it no longer receives.
        candidates = children.filtered(lambda line: line.display_type == 'line_note' and not line.account_id)
        if not candidates:
            return children
        # A rule-hidden reconciliation must not make a line look unrelated.
        # Query identities only, then use normal ORM access for every match.
        self._require_read(('account.partial.reconcile',))
        partial_model = self.env['account.partial.reconcile']
        partial_model.flush_model(['debit_move_id', 'credit_move_id'])
        partials = partial_model.search(['|', ('debit_move_id', 'in', candidates.ids),
                                         ('credit_move_id', 'in', candidates.ids)])
        self._assert_visible('account_partial_reconcile',
                             '(debit_move_id = ANY(%s) OR credit_move_id = ANY(%s))',
                             [candidates.ids, candidates.ids], partials)
        reconciled_ids = set(partials.debit_move_id.ids + partials.credit_move_id.ids)
        ignored = self.env['account.move.line']
        for line in candidates:
            move, company = line.move_id, line.move_id.company_id
            if (line.company_id != company or line.journal_id != move.journal_id
                    or line.currency_id != company.currency_id
                    or line.tax_line_id or line.tax_ids
                    or line.id in reconciled_ids):
                continue
            if all(self._owner_sales_money(value, company.currency_id) == 0 for value in (
                    line.debit, line.credit, line.balance, line.amount_currency)):
                ignored |= line
        return children - ignored
