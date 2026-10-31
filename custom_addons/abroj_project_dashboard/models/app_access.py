"""Who may use the Abroj projects app, and in which company.

The projects app/switcher is for any user with access to Projects, and
only while the current company is the Abroj company.  The Abroj company is
the one set in the system parameter ``abroj_project_dashboard.company_id``;
without it, a company named أبرج / Abroj; a single-company database is
treated as Abroj.
"""
from odoo import api, models

COMPANY_PARAM = 'abroj_project_dashboard.company_id'


class ResUsers(models.Model):
    _inherit = 'res.users'

    @api.model
    def _abroj_company(self):
        companies = self.env['res.company'].sudo().search([])
        param = self.env['ir.config_parameter'].sudo().get_param(COMPANY_PARAM)
        if param and param.isdigit() and int(param) in companies.ids:
            return companies.browse(int(param))
        named = companies.filtered(lambda c: any(
            key in (n or '').lower() for key in ('أبرج', 'abroj')
            for n in (c.name, getattr(c, 'contracting_name_ar', ''), getattr(c, 'contracting_name_en', ''))))
        if named:
            return named[:1]
        return companies if len(companies) == 1 else companies.browse()

    def _abroj_can_use_projects_app(self, company=None):
        user = self or self.env.user
        user.ensure_one()
        # Anyone with (at least read) access to the Projects app.
        if user.share or not (user.has_group('project.group_project_user')
                              or user.has_group('base.group_system')):
            return False
        abroj = self._abroj_company()
        company = company or self.env.company
        return bool(abroj) and company == abroj


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    def session_info(self):
        info = super().session_info()
        if self.env.user and not self.env.user._is_public():
            info['abroj_can_switch'] = self.env.user._abroj_can_use_projects_app()
        return info
