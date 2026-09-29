from odoo import models


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    def session_info(self):
        """Expose the per-company app flag to the backend menu without extra RPC calls."""
        result = super().session_info()
        companies = result.get("user_companies", {}).get("allowed_companies", {})
        for company in self.env.user.company_ids:
            if company.id in companies:
                companies[company.id]["abroj_project_costing_enabled"] = bool(
                    company.abroj_project_costing_enabled
                )
        return result
