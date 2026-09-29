from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    cashier_purchase_batch_approval_enabled = fields.Boolean(
        related='company_id.cashier_purchase_batch_approval_enabled', readonly=False,
    )
