from odoo import api, models


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @api.model
    def _baseer_localize_company_session_names(self, session_info):
        """Only relabel companies already authorized by the native session."""
        company_info = session_info.get('user_companies', {})
        entries = [entry for key in ('allowed_companies', 'disallowed_ancestor_companies')
                   for entry in company_info.get(key, {}).values()]
        if not entries:
            return session_info
        lang = (session_info.get('bundle_params', {}).get('lang')
                or session_info.get('user_context', {}).get('lang') or self.env.lang)
        companies = self.env['res.company'].sudo().with_context(lang=lang).browse(
            [entry['id'] for entry in entries])
        names = {company.id: company.baseer_display_name for company in companies}
        for entry in entries:
            entry['name'] = names[entry['id']]
        return session_info

    @api.model
    def session_info(self):
        return self._baseer_localize_company_session_names(super().session_info())
