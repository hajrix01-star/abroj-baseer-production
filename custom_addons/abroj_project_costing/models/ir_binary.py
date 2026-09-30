from odoo import models
from odoo.exceptions import AccessError
from odoo.http import request


class AbrojCostIrBinary(models.AbstractModel):
    _inherit = 'ir.binary'

    def _find_record(
        self, xmlid=None, res_model='ir.attachment', res_id=None,
        access_token=None, field=None,
    ):
        if xmlid or res_model != 'abroj.cost.material' or field != 'image_1920':
            return super()._find_record(xmlid, res_model, res_id, access_token, field)

        # This library is never a public, token-shared image collection.
        if access_token:
            raise AccessError(self.env._('Material images require company access.'))

        # Image URLs are separate HTTP requests, so they do not inherit the
        # selected company context supplied by the web client's RPC calls.
        # Odoo's company switcher stores that selection in the cids cookie.
        try:
            selected_company = int(request.httprequest.cookies.get('cids', '').split('-')[0])
        except (AttributeError, RuntimeError, TypeError, ValueError):
            selected_company = None

        if selected_company:
            if selected_company not in self.env.user.company_ids.ids:
                raise AccessError(self.env._('You cannot access this company.'))
            scoped = self.with_context(allowed_company_ids=[selected_company])
            return super(AbrojCostIrBinary, scoped)._find_record(
                xmlid, res_model, res_id, access_token, field,
            )

        # Non-browser callers (including report generation) retain Odoo's
        # ordinary ACL and record-rule checks under their existing context.
        return super()._find_record(xmlid, res_model, res_id, access_token, field)
