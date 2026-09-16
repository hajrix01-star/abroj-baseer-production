from odoo import _
from odoo.exceptions import AccessError
from odoo import models


class ProcurementCustody(models.Model):
    """Keep Petty Cash lifecycle control with the Baseer owner role."""

    _inherit = 'baseer.procurement.custody'

    def _require_owner(self):
        if not self.env.user.has_group('baseer_access_roles.group_owner'):
            raise AccessError(_('Only the owner can change or delete Petty Cash.'))

    def write(self, vals):
        # Odoo requires write access to expose Save/Discard in a new form.
        # The accountant has that UI access only; every persisted-record
        # change remains owner-only at the model boundary.
        self._require_owner()
        return super().write(vals)

    def unlink(self):
        self._require_owner()
        return super().unlink()

    def action_close(self):
        self._require_owner()
        return super().action_close()
