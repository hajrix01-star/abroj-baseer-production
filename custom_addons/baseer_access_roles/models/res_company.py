from odoo import _, fields, models
from odoo.exceptions import AccessError


class ResCompany(models.Model):
    _inherit = 'res.company'

    cashier_purchase_batch_approval_enabled = fields.Boolean(
        string='Allow cashiers to approve their own purchase batches',
        default=False,
        help=(
            'When enabled for this company, a cashier may approve only a draft '
            'purchase batch that they created in the active company. The approval '
            'still uses the protected native accounting workflow.'
        ),
    )

    def write(self, vals):
        if ('cashier_purchase_batch_approval_enabled' in vals
                and not self.env.su
                and not self.env.user.has_group('baseer_access_roles.group_owner')):
            raise AccessError(_(
                'Only the Baseer owner can change cashier purchase-batch approval policy.'
            ))
        return super().write(vals)
