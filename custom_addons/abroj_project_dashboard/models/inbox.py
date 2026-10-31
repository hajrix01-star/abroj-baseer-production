from odoo import fields, models


class Inbox(models.Model):
    _inherit = 'abroj.contracting.inbox'

    abroj_invoice_bill_id = fields.Many2one('account.move', string='Vendor bill', ondelete='set null', copy=False)

    def _ensure_project_note(self):
        # Invoice inbox entries belong to the bot and bill, not project notes.
        return super(Inbox, self.filtered(lambda item: not item.abroj_invoice_bill_id))._ensure_project_note()


class Attachment(models.Model):
    _inherit = 'ir.attachment'

    abroj_is_invoice = fields.Boolean(string='Invoice attachment', default=False, copy=False)
