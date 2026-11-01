"""Who may use the Abroj projects app, and in which company.

The Abroj company is ONLY the id in the system parameter
``abroj_project_dashboard.company_id``; if it is empty or invalid, company
id 56 is used (resolved by res.company._abroj_company in abroj_contracting).

The projects app / switch button is for users with access to Projects whose
allowed companies include that company, while it is the active company.
"""
from odoo import api, models
from odoo.http import request

COMPANY_PARAM = 'abroj_project_dashboard.company_id'
DEFAULT_COMPANY_ID = 56


class ResUsers(models.Model):
    _inherit = 'res.users'

    @api.model
    def _abroj_company_id(self):
        return self.env['res.company']._abroj_company().id

    @api.model
    def _abroj_company(self):
        return self.env['res.company'].sudo().browse(self._abroj_company_id()).exists()

    def _abroj_has_projects_access(self):
        user = self or self.env.user
        user.ensure_one()
        return not user.share and (user.has_group('project.group_project_user')
                                   or user.has_group('base.group_system'))

    def _abroj_active_company(self):
        """Company active in the web client: first id of the 'cids' cookie
        (plain http routes do not apply it to env.company), else env.company."""
        user = self or self.env.user
        try:
            cids = (request and request.httprequest.cookies.get('cids')) or ''
        except RuntimeError:
            cids = ''
        first = str(cids).split('-')[0].split(',')[0]
        if first.isdigit() and int(first) in user.company_ids.ids:
            return user.company_ids.browse(int(first))
        return self.env.company

    def _abroj_can_use_projects_app(self, company=None):
        """Projects access + Abroj in the user's companies + Abroj active
        (``company`` overrides the active company, e.g. at login)."""
        user = self or self.env.user
        user.ensure_one()
        abroj_id = self._abroj_company_id()
        if not user._abroj_has_projects_access() or abroj_id not in user.company_ids.ids:
            return False
        company = company or user._abroj_active_company()
        return company.id == abroj_id


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    def session_info(self):
        info = super().session_info()
        user = self.env.user
        if user and not user._is_public():
            abroj_id = user._abroj_company_id()
            allowed = user._abroj_has_projects_access() and abroj_id in user.company_ids.ids
            info['abroj_switch_company_id'] = abroj_id if allowed else False
            info['abroj_can_switch'] = bool(allowed) and user._abroj_can_use_projects_app()
        return info
