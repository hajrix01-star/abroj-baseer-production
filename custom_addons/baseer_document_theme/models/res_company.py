from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    baseer_document_seal_enabled = fields.Boolean(
        string='Add Company Stamp',
        help='Print the uploaded transparent stamp image on standard documents for this company.',
    )
    baseer_document_seal_image = fields.Binary(
        string='Company Stamp Image',
        attachment=True,
        help='Upload the approved company stamp as a transparent PNG image.',
    )
    baseer_document_seal_image_filename = fields.Char(
        string='Company Stamp Filename',
    )
    baseer_document_seal_position = fields.Selection(
        [('left', 'Left'), ('right', 'Right')],
        string='Company Stamp Position',
        default='left',
        required=True,
        help='Place the company stamp in the final quarter of the document on the selected side.',
    )
    baseer_document_seal_scope = fields.Selection(
        [('all', 'All Standard Documents'), ('selected', 'Selected Document Types')],
        string='Company Stamp Scope',
        default='all',
        required=True,
        help='Choose whether the company stamp appears on every standard document or only selected document types.',
    )
    baseer_document_seal_model_ids = fields.Many2many(
        'ir.model',
        string='Stamped Document Types',
        help='The company stamp is printed only for these document types when the selected scope is used.',
    )
