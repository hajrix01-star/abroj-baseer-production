from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


RECEIPT_LAYOUT_MODES = [
    ('native', 'Original Odoo receipt'),
    ('baseer_80', 'Baseer professional 80 mm receipt'),
]


class ResCompany(models.Model):
    _inherit = 'res.company'

    baseer_receipt_profile_enabled = fields.Boolean(
        string='Apply POS receipt defaults to new registers',
        help='New POS registers inherit this company profile. Existing registers are never changed.',
    )
    baseer_receipt_profile_printer_id = fields.Many2one(
        'baseer.print.printer', string='Default receipt printer', ondelete='restrict',
    )
    baseer_receipt_profile_copies = fields.Integer(string='Default receipt copies', default=1)
    baseer_receipt_profile_layout_mode = fields.Selection(
        RECEIPT_LAYOUT_MODES, string='Default receipt layout', default='native', required=True,
    )
    baseer_receipt_profile_close_report = fields.Boolean(string='Print closing report by default')

    @api.constrains(
        'baseer_receipt_profile_enabled', 'baseer_receipt_profile_printer_id',
        'baseer_receipt_profile_copies', 'baseer_receipt_profile_layout_mode',
    )
    def _check_baseer_receipt_profile(self):
        for company in self:
            if not 1 <= company.baseer_receipt_profile_copies <= 10:
                raise ValidationError(_('Receipt copies must be between 1 and 10.'))
            if not company.baseer_receipt_profile_enabled:
                continue
            printer = company.baseer_receipt_profile_printer_id
            if not printer or not printer.active:
                raise ValidationError(_('Choose an active default receipt printer before enabling the company profile.'))
            if printer.paper_width != '80':
                raise ValidationError(_('The professional receipt profile requires an authorized 80 mm printer.'))
            if not printer._allows_company(company):
                raise ValidationError(_('The default receipt printer is not authorized for this company.'))

    def _baseer_receipt_profile_values(self):
        self.ensure_one()
        if not self.baseer_receipt_profile_enabled:
            return {}
        return {
            'baseer_direct_print_enabled': True,
            'baseer_receipt_printer_id': self.baseer_receipt_profile_printer_id.id,
            'baseer_receipt_copies': self.baseer_receipt_profile_copies,
            'baseer_native_receipt_enabled': True,
            'baseer_print_session_close_report': self.baseer_receipt_profile_close_report,
            'baseer_receipt_layout_mode': self.baseer_receipt_profile_layout_mode,
        }
