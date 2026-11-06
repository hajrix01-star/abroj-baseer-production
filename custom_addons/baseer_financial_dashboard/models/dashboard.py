from odoo import fields, models


class FinancialDashboard(models.Model):
    _inherit = 'spreadsheet.dashboard'

    baseer_dashboard_kind = fields.Selection(
        selection_add=[('financial_dashboard', 'Financial performance')],
        ondelete={'financial_dashboard': 'cascade'},
    )
