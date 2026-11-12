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
        ignored = self.env['account.move.line']
        for line in children:
            if line.display_type != 'line_note' or line.account_id:
                continue
            move, company = line.move_id, line.move_id.company_id
            if (line.company_id != company or line.journal_id != move.journal_id
                    or line.currency_id != company.currency_id
                    or line.tax_line_id or line.tax_ids
                    or line.matched_debit_ids or line.matched_credit_ids):
                continue
            if all(self._owner_sales_money(value, company.currency_id) == 0 for value in (
                    line.debit, line.credit, line.balance, line.amount_currency)):
                ignored |= line
        return children - ignored
