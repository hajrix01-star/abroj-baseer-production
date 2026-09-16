from odoo import _
from odoo.exceptions import AccessError
from odoo import models


class ProcurementCustody(models.Model):
    """Keep Petty Cash lifecycle control with the Baseer owner role."""

    _inherit = 'baseer.procurement.custody'

    def action_close(self):
        if not self.env.user.has_group('baseer_access_roles.group_owner'):
            raise AccessError(_('Only the owner can close Petty Cash.'))
        return super().action_close()
