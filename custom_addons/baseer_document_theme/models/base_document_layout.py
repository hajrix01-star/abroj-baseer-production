from odoo import fields, models


class BaseDocumentLayout(models.TransientModel):
    _inherit = 'base.document.layout'

    baseer_document_seal_enabled = fields.Boolean(
        related='company_id.baseer_document_seal_enabled',
        readonly=False,
    )
    baseer_document_seal_image = fields.Binary(
        related='company_id.baseer_document_seal_image',
        readonly=False,
    )
    baseer_document_seal_image_filename = fields.Char(
        related='company_id.baseer_document_seal_image_filename',
        readonly=False,
    )
    baseer_document_seal_position = fields.Selection(
        related='company_id.baseer_document_seal_position',
        readonly=False,
    )
    baseer_document_seal_scope = fields.Selection(
        related='company_id.baseer_document_seal_scope',
        readonly=False,
    )
    baseer_document_seal_model_ids = fields.Many2many(
        related='company_id.baseer_document_seal_model_ids',
        readonly=False,
    )
