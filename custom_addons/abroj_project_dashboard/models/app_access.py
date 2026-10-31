"""Who may use the Abroj projects app, and in which company.

The projects app/switcher is for any user with access to Projects, and
only while the current company is the Abroj company.  The Abroj company is
the one set in the system parameter ``abroj_project_dashboard.company_id``;
without it, a company named أبرج / Abroj; a single-company database is
treated as Abroj.
"""
from odoo import api, models
from odoo.http import request

COMPANY_PARAM = 'abroj_project_dashboard.company_id'
_ALEF = str.maketrans({'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ٱ': 'ا'})
_KEYS = ('ابرج', 'ابراج', 'abroj', 'abraj', 'abrog')


def _is_abroj(name):
    text = (name or '').translate(_ALEF).lower()
    return any(key in text for key in _KEYS)


class ResUsers(models.Model):
    _inherit = 'res.users'

    @api.model
    def _abroj_company(self):
        """Companies where the projects app applies (a recordset, may be several).

        1. system parameter abroj_project_dashboard.company_id (id or comma list);
        2. companies whose name matches Abroj in any spelling (أبرج/ابرج/أبراج/
           Abroj/Abraj/ABROJ ..., alef variants and case ignored);
        3. companies that own at least one project;
        4. a single-company database.
        """
        companies = self.env['res.company'].sudo().search([])
        param = (self.env['ir.config_parameter'].sudo().get_param(COMPANY_PARAM) or '').replace(' ', '')
        ids = [int(x) for x in param.split(',') if x.isdigit()]
        picked = companies.filtered(lambda c: c.id in ids)
        if picked:
            return picked
        named = companies.filtered(lambda c: any(_is_abroj(n) for n in (
            c.name, getattr(c, 'contracting_name_ar', ''), getattr(c, 'contracting_name_en', ''))))
        if named:
            return named
        if 'project.project' in self.env:
            groups = self.env['project.project'].sudo().with_context(active_test=False)._read_group(
                [('company_id', '!=', False)], ['company_id'])
            with_projects = companies.browse([g[0].id for g in groups]) & companies
            if with_projects:
                return with_projects
        return companies if len(companies) == 1 else companies.browse()

    def _abroj_active_company(self):
        """The company active in the web client: first id of the 'cids' cookie
        (plain http routes do not apply it to env.company), else env.company."""
        user = self or self.env.user
        try:
            cids = request and request.httprequest.cookies.get('cids') or ''
        except RuntimeError:
            cids = ''
        first = str(cids).split('-')[0].split(',')[0]
        if first.isdigit() and int(first) in user.company_ids.ids:
            return user.company_ids.browse(int(first))
        return self.env.company

    def _abroj_can_use_projects_app(self, company=None):
        user = self or self.env.user
        user.ensure_one()
        # Anyone with (at least read) access to the Projects app.
        if user.share or not (user.has_group('project.group_project_user')
                              or user.has_group('base.group_system')):
            return False
        abroj = self._abroj_company()
        company = company or user._abroj_active_company()
        return bool(abroj) and company in abroj


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    def session_info(self):
        info = super().session_info()
        if self.env.user and not self.env.user._is_public():
            user = self.env.user
            info['abroj_can_switch'] = user._abroj_can_use_projects_app()
            # Companies where the button applies; the web client checks the
            # *active* company itself (the cids cookie may differ from env.company).
            allowed = user._abroj_company() & user.company_ids
            info['abroj_switch_company_ids'] = allowed.ids if user._abroj_can_use_projects_app(allowed[:1] or None) else []
        return info
