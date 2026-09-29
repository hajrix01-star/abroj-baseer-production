from odoo import fields, models


class BaseDocumentLayout(models.TransientModel):
    _inherit = 'base.document.layout'

    baseer_document_seal_enabled = fields.Boolean(
        related='company_id.baseer_document_seal_enabled',
        readonly=False,
    )
