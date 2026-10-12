from odoo import fields, models
from odoo.fields import Domain


class PosPayment(models.Model):
    _inherit = 'pos.payment'

    baseer_payment_category_id = fields.Many2one(
        related='payment_method_id.baseer_category_id',
        string='Payment Category', readonly=True, store=True,
        compute_sudo=False, index=True,
        help='Current configured settlement category; not proof of bank collection.',
    )

    def _search(self, domain, *args, **kwargs):
        if self.env.context.get('baseer_payment_category_report'):
            domain = (
                Domain(domain)
                & Domain('company_id', '=', self.env.company.id)
                & Domain('pos_order_id.state', 'in', ['paid', 'done', 'invoiced'])
            )
        return super()._search(domain, *args, **kwargs)
