"""Apply BWork user switches before the optional DMS invoice-case search."""

from odoo import api, models


class BWorkDocumentPermissionGuardService(models.AbstractModel):
    _inherit = 'baseer.bwork.service'

    @api.model
    def _v2_invoice_cases(self, room_id):
        self._require_bwork_permission('chat_view')
        self._require_bwork_permission('media')
        return super()._v2_invoice_cases(room_id)
