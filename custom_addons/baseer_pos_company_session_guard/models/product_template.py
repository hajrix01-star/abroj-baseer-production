from odoo import _, api, models
from odoo.exceptions import UserError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    def _baseer_has_relevant_open_pos_session(self):
        """Return whether an open POS session protects any template in ``self``.

        Company-owned products are protected by their own company's sessions.
        Shared products intentionally retain Odoo's global protection.
        """
        if not self:
            return False

        domain = [('state', '!=', 'closed')]
        if not self.filtered(lambda product: not product.company_id):
            domain.append(('config_id.company_id', 'in', self.company_id.ids))
        return bool(self.env['pos.session'].sudo().search_count(domain))

    @api.ondelete(at_uninstall=False)
    def _unlink_except_open_session(self):
        """Keep Odoo's POS delete guard, scoped to the product company."""
        pos_products = self.with_context(active_test=False).search([
            ('id', 'in', self.ids),
            ('available_in_pos', '=', True),
        ])
        if pos_products._baseer_has_relevant_open_pos_session():
            raise UserError(_(
                'To delete a product, make sure that it is not used in any open sessions.'
            ))

    def _ensure_unused_in_pos(self):
        """Keep Odoo's POS archive guard, scoped to the product company."""
        pos_products = self.filtered('available_in_pos')
        if pos_products._baseer_has_relevant_open_pos_session():
            raise UserError(_(
                'To archive a product, make sure that it is not used in any open sessions.'
            ))
