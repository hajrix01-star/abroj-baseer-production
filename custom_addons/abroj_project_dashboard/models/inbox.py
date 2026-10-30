from odoo import fields, models


class Inbox(models.Model):
    _inherit = 'abroj.contracting.inbox'

    abroj_invoice_bill_id = fields.Many2one('account.move', string='Vendor bill', ondelete='set null', copy=False)
