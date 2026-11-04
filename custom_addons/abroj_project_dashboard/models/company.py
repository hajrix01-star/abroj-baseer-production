from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.abroj_contracting.models.accounting_issue import EXPENSE_TYPES


class ResCompany(models.Model):
    _inherit = 'res.company'

    abroj_project_expense_account_id = fields.Many2one(
        'account.account', string='Default project expense account', check_company=True,
        domain=[('account_type', 'in', EXPENSE_TYPES)],
    )

    @api.constrains('abroj_project_expense_account_id')
    def _check_project_expense_account(self):
        for company in self:
            if (company.abroj_project_expense_account_id
                    and company.abroj_project_expense_account_id.account_type not in EXPENSE_TYPES):
                raise ValidationError(_('The default project expense account must be an expense account.'))


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    abroj_project_expense_account_id = fields.Many2one(
        related='company_id.abroj_project_expense_account_id', readonly=False,
    )
