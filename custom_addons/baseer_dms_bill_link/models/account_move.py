from odoo import models
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = "account.move"

    def write(self, vals):
        if set(vals) & {"company_id", "move_type"}:
            for move in self:
                changing = ("company_id" in vals and vals["company_id"] != move.company_id.id) or (
                    "move_type" in vals and vals["move_type"] != move.move_type
                )
                if changing and self.env["dms.file"].sudo().search_count([
                    ("bill_move_id", "=", move.id)
                ], limit=1):
                    raise UserError(self.env._("Remove document references before changing the bill company or type."))
        return super().write(vals)
