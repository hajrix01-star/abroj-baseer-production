"""V2 presentation metadata, kept outside the frozen legacy V1 boundary."""
from odoo import api, models
from odoo.exceptions import AccessError

from ..company_display import compact_name, wire_name


class BWorkCompanyDisplayService(models.AbstractModel):
    _inherit = 'baseer.bwork.service'

    @api.model
    def _bwork_visible_companies(self, user=None):
        actor = self._require_user()
        if user is not None and user.id != actor.id:
            raise AccessError(self.env._('The company is outside your authorized companies.'))
        companies = actor.company_ids.sorted('id')
        # Safe configuration metadata only, after native authorization. Return
        # the original recordset, never a privileged reporting environment.
        hidden = set(companies.sudo().filtered('bwork_hidden').ids)
        return companies.filtered(lambda company: company.id not in hidden)

    @api.model
    def _bwork_company_label(self, company, language=None):
        actor = self._require_user()
        company.ensure_one()
        if company.id not in actor.company_ids.ids:
            raise AccessError(self.env._('The company is outside your authorized companies.'))
        language = 'ar' if (language or self.env.lang or 'en').startswith('ar') else 'en'
        metadata = company.sudo()
        explicit = metadata['bwork_short_name_' + language]
        if explicit:
            return explicit
        field = 'baseer_name_' + language
        localized = metadata[field] if field in metadata._fields else None
        return compact_name(metadata.name, language, localized) or str(company.id)

    @api.model
    def _bwork_company_preferences(self):
        user = self._require_user()
        return [{'id': company.id, 'name': wire_name(company.name),
                 'short_name_ar': self._bwork_company_label(company, 'ar'),
                 'short_name_en': self._bwork_company_label(company, 'en'),
                 'hidden': bool(company.sudo().bwork_hidden)}
                for company in user.company_ids.sorted('id')]
