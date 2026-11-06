"""Safe navigation policy for native sales dashboards.

The native spreadsheets remain their owning modules' records.  This module only
puts the three operational dashboards in a dedicated group, without touching
their sheet data, publication, access, company scope, or user favourites.
"""
from odoo import api, models


OPERATIONS_DASHBOARDS = (
    ('spreadsheet_dashboard_sale.spreadsheet_dashboard_sales',
     'Sales order performance', 'أداء أوامر البيع', 10),
    ('spreadsheet_dashboard_pos_hr.spreadsheet_dashboard_pos',
     'Direct point of sale performance', 'أداء نقاط البيع المباشر', 20),
    ('spreadsheet_dashboard_pos_restaurant.spreadsheet_dashboard_pos_restaurant',
     'Restaurant point of sale performance', 'أداء نقاط بيع المطاعم', 30),
)


class SpreadsheetDashboard(models.Model):
    _inherit = 'spreadsheet.dashboard'

    @api.model
    def _baseer_reorganize_dashboard_navigation(self):
        """Apply the navigation policy during module install/upgrade.

        Restaurant dashboards are optional in a generic Odoo database, so a
        missing native XML ID is deliberately skipped.  The method is
        idempotent and writes only navigation metadata on records that differ.
        """
        operations = self.env.ref(
            'baseer_sales_dashboard.dashboard_group_sales_operations',
            raise_if_not_found=False,
        )
        if not operations:
            return
        installed_arabic_languages = self.env['res.lang'].search([
            ('code', 'in', ('ar', 'ar_001')),
        ]).mapped('code')
        for xmlid, english_name, arabic_name, sequence in OPERATIONS_DASHBOARDS:
            dashboard = self.env.ref(xmlid, raise_if_not_found=False)
            if not dashboard:
                continue
            values = {}
            if dashboard.with_context(lang='en_US').name != english_name:
                values['name'] = english_name
            if dashboard.dashboard_group_id != operations:
                values['dashboard_group_id'] = operations.id
            if dashboard.sequence != sequence:
                values['sequence'] = sequence
            if values:
                dashboard.with_context(lang='en_US').write(values)
            for language in installed_arabic_languages:
                translated = dashboard.with_context(lang=language)
                if translated.name != arabic_name:
                    translated.write({'name': arabic_name})
