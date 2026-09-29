from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    baseer_document_seal_enabled = fields.Boolean(
        string='Company Seal',
        help='Add this company’s dynamic seal to every report using the standard Odoo document layout.',
    )
