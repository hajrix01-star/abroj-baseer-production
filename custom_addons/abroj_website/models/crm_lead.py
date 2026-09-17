from odoo import models


class CrmLead(models.Model):
    _inherit = "crm.lead"

    def website_form_input_filter(self, request, values):
        """Keep public website submissions from choosing an internal owner."""
        values.pop("team_id", None)
        values.pop("user_id", None)
        return super().website_form_input_filter(request, values)
