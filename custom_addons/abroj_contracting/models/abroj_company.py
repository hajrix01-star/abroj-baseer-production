"""Single resolver for the Abroj company.

Abroj contracting records must always live on the Abroj company, whatever the
user's default/active company is (the admin default is the restaurant).
Order: system parameter ``abroj_project_dashboard.company_id`` -> company 56
(production) -> a company whose name contains 'ABROJ'/'ابرج'.  Only if none of
those exist (e.g. a fresh test database) the current company is used.
"""
from odoo import api, models

COMPANY_PARAM = 'abroj_project_dashboard.company_id'
DEFAULT_COMPANY_ID = 56


class ResCompany(models.Model):
    _inherit = 'res.company'

    @api.model
    def _abroj_company(self):
        Company = self.env['res.company'].sudo()
        value = (self.env['ir.config_parameter'].sudo().get_param(COMPANY_PARAM) or '').strip()
        for cid in ([int(value)] if value.isdigit() and int(value) > 0 else []) + [DEFAULT_COMPANY_ID]:
            company = Company.browse(cid).exists()
            if company:
                return company
        company = Company.search(['|', ('name', 'ilike', 'ABROJ'), ('name', 'ilike', 'ابرج')], order='id', limit=1)
        return company or self.env.company

    @api.model
    def _abroj_force_company(self, vals_list):
        """Set company_id to the Abroj company on every vals dict."""
        cid = self._abroj_company().id
        for vals in vals_list:
            vals['company_id'] = cid
        return vals_list
