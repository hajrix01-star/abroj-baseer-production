from odoo import api, fields, models


class PosOrder(models.Model):
    _inherit = 'pos.order'

    @api.model
    def search_paid_order_ids(self, config_id, domain, limit, offset):
        """Do not expose paid ticket history to the dedicated cashier role.

        Odoo's ticket screen loads open orders locally, but calls this endpoint
        for its synchronised (paid) history.  Refusing that data at the server
        boundary, in addition to hiding the filter in the interface, prevents a
        cashier from restoring paid orders through a crafted browser request.
        Other POS roles keep Odoo's original, paginated history unchanged.
        """
        if (
            self.env.user.has_group('baseer_access_roles.group_pos_cashier')
            and self.env.user.baseer_restrict_pos_history
        ):
            return {'ordersInfo': [], 'totalCount': 0}
        return super().search_paid_order_ids(config_id, domain, limit, offset)


class PosConfig(models.Model):
    _inherit = 'pos.config'

    baseer_cashier_history_hidden = fields.Boolean(
        compute='_compute_baseer_cashier_history_hidden',
    )

    @api.depends_context('uid')
    def _compute_baseer_cashier_history_hidden(self):
        hidden = (
            self.env.user.has_group('baseer_access_roles.group_pos_cashier')
            and self.env.user.baseer_restrict_pos_history
        )
        for config in self:
            config.baseer_cashier_history_hidden = hidden
