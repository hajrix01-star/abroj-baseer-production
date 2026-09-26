import json
import math

from odoo import _, models
from odoo.exceptions import AccessError


class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _baseer_has_native_preparation_obligation(self):
        self.ensure_one()
        try:
            baseline = json.loads(self.last_order_preparation_change or '{}')
            lines = baseline.get('lines', {})
            if not isinstance(lines, dict):
                return True
            for line in lines.values():
                quantity = float(line.get('quantity', 0))
                if not math.isfinite(quantity) or quantity != 0:
                    return True
            return False
        except (ValueError, TypeError, AttributeError):
            return True

    def _baseer_release_empty_table(self):
        """End an empty restaurant draft, never erase an order or its audit trail.

        The row lock/re-read is essential: another cashier may have populated
        the table since this device last displayed it as empty.
        """
        self.ensure_one()
        self.check_access('write')
        if (not self.env.user.has_group('point_of_sale.group_pos_user')
                or self.company_id not in self.env.companies):
            raise AccessError(_('This table does not belong to an allowed point of sale.'))
        self.env['baseer.print.preparation.state']._lock_order_state(self)
        self.invalidate_recordset()
        if not self.config_id.module_pos_restaurant or not self.table_id:
            return False
        if self.lines or self.payment_ids or self.account_move or self.is_refund:
            return False
        if self._baseer_has_native_preparation_obligation():
            return False
        if any(not self.currency_id.is_zero(value) for value in (
                self.amount_total, self.amount_paid, self.amount_return)):
            return False
        if self.env['baseer.print.preparation.state'].sudo().search_count([
                ('order_id', '=', self.id), ('quantity', '!=', 0)], limit=1):
            return False
        if self.state == 'cancel':
            return True
        if self.state != 'draft' or self.session_id.state not in ('opened', 'closing_control'):
            return False
        # No kitchen obligation exists. Native cancellation is safe and retains
        # every prior event; do not unlink an audited draft to make a table green.
        self._baseer_native_action_pos_order_cancel()
        return True

    def baseer_release_empty_table(self):
        self.ensure_one()
        released = self._baseer_release_empty_table()
        return {'released': released, 'state': self.state,
                'data': self.read_pos_data([], self.config_id)}
