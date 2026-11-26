"""Narrow liquidity rules for financial-correction payment journals."""
from odoo import models


class CorrectionLiquidityJournal(models.Model):
    _inherit = 'account.journal'

    def _baseer_is_custody_liquidity_journal(self):
        """Official representative-custody cash/bank journals only.

        A journal qualifies when all of the following hold:
        - its type is cash or bank
        - its default account is ``asset_current`` (petty cash / عهدة, not a
          generic receivable, expense, or other current asset)
        - it is explicitly flagged with ``baseer_custody_representative_id``
          (set by ``baseer_procurement_requests`` on journals such as
          «عهدة أسامة», whose default account is 108990
          «عهدة مندوبي المشتريات»)

        Ordinary ``asset_current`` accounts are never accepted, even when the
        journal type is cash or bank. This module does not treat an account
        code list as the rule; the representative flag is the narrow official
        marker already used in production.
        """
        self.ensure_one()
        account = self.default_account_id
        if self.type not in ('cash', 'bank') or not account or account.account_type != 'asset_current':
            return False
        return bool(
            'baseer_custody_representative_id' in self._fields
            and self.baseer_custody_representative_id
        )

    def _baseer_is_correction_liquidity_journal(self):
        """Journals whose default account may host a correctable payment.

        Accepted:
        - cash/bank journals whose default account is ``asset_cash``
        - official custody journals as defined by
          :meth:`_baseer_is_custody_liquidity_journal`

        Every other account type, including unflagged ``asset_current``, is
        rejected.
        """
        self.ensure_one()
        account = self.default_account_id
        if self.type not in ('cash', 'bank') or not account:
            return False
        if account.account_type == 'asset_cash':
            return True
        return self._baseer_is_custody_liquidity_journal()
