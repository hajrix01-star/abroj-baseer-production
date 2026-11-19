"""Keep native posting, with an explicit and verifiable discount account."""
from odoo import _, models
from odoo.exceptions import ValidationError


class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _gd_check_discount_accounts(self):
        self.ensure_one()
        account = self.config_id._gd_check_account_setup()
        effective = self.fiscal_position_id.map_account(account) if self.fiscal_position_id else account
        if (not effective.active or effective.account_type not in ('income', 'income_other')
                or self.company_id not in effective.company_ids):
            raise ValidationError(_('The fiscal position must map the invoice discount to an active income account in this company.'))

    def _gd_source_lines(self):
        self._gd_check_discount_accounts()
        return super()._gd_source_lines()

    def _gd_snapshot(self):
        snapshot = super()._gd_snapshot()
        # Existing paid snapshots did not record accounts. Preserve them as
        # legacy evidence rather than silently inventing their account history.
        recorded = self.baseer_global_discount_snapshot or {}
        if self.baseer_global_discount_locked and not any(
                '_gd_accounts' in entry for entry in recorded.get('tax_configuration', [])):
            return snapshot
        snapshot['tax_configuration'].append({'_gd_accounts': {
            'configured': self.config_id.baseer_global_discount_account_id.id,
            'product': self.config_id.baseer_global_discount_product_id.with_company(
                self.company_id).property_account_income_id.id,
            'lines': [[line.id, line._prepare_base_line_for_taxes_computation()['account_id'].id]
                      for line in self.lines.sorted('id')],
        }})
        return snapshot

    def _gd_assert_snapshot(self, ignore_tax=False):
        # Removal stays a recovery path if the account/tax setup has drifted.
        if not ignore_tax:
            for order in self.filtered('baseer_global_discount_locked'):
                order._gd_check_discount_accounts()
        return super()._gd_assert_snapshot(ignore_tax=ignore_tax)

    def _gd_refund_ready(self):
        for order in self.filtered('baseer_global_discount_locked'):
            order._gd_check_discount_accounts()
        return super()._gd_refund_ready()
