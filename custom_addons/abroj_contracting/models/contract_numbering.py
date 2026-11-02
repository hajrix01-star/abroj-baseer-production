from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

PLACEHOLDER = '/'


def _ensure_unique_index(cr, table, column):
    cr.execute(
        f'CREATE UNIQUE INDEX IF NOT EXISTS {table}_{column}_company_uniq '
        f'ON {table} (company_id, {column}) WHERE {column} IS NOT NULL AND {column} != %s',
        (PLACEHOLDER,))


class Subcontractor(models.Model):
    _inherit = 'abroj.contracting.subcontractor'

    contract_number = fields.Char('رقم العقد', readonly=True, copy=False, default=PLACEHOLDER, index=True,
                                  help='يصدر من التسلسل SC- عند الضغط على إصدار رقم العقد؛ لا يعدل يدويا.')

    def init(self):
        super().init()
        _ensure_unique_index(self.env.cr, self._table, 'contract_number')

    @api.constrains('contract_number', 'company_id')
    def _check_contract_number_unique(self):
        for r in self.filtered(lambda x: x.contract_number and x.contract_number != PLACEHOLDER):
            if self.search_count([('id', '!=', r.id), ('company_id', '=', r.company_id.id),
                                  ('contract_number', '=', r.contract_number)]):
                raise ValidationError('رقم العقد مستخدم مسبقا في هذه الشركة.')

    def action_issue_contract(self):
        for r in self:
            if r.contract_number and r.contract_number != PLACEHOLDER:
                continue
            number = self.env['ir.sequence'].with_company(r.company_id).next_by_code('abroj.contracting.subcontract')
            if not number:
                raise UserError('تسلسل أرقام عقود الباطن غير موجود.')
            r.contract_number = number
        return True


class Project(models.Model):
    _inherit = 'project.project'

    abroj_contract_number = fields.Char('رقم عقد العميل', readonly=True, copy=False, default=PLACEHOLDER, index=True,
                                        help='يصدر من التسلسل CC- عند الضغط على إصدار رقم العقد؛ لا يعدل يدويا.')

    def init(self):
        super().init()
        _ensure_unique_index(self.env.cr, self._table, 'abroj_contract_number')

    @api.constrains('abroj_contract_number', 'company_id')
    def _check_abroj_contract_number_unique(self):
        for r in self.filtered(lambda x: x.abroj_contract_number and x.abroj_contract_number != PLACEHOLDER):
            if self.with_context(active_test=False).search_count([('id', '!=', r.id), ('company_id', '=', r.company_id.id),
                                                                  ('abroj_contract_number', '=', r.abroj_contract_number)]):
                raise ValidationError('رقم عقد العميل مستخدم مسبقا في هذه الشركة.')

    def action_issue_client_contract(self):
        for r in self:
            if r.abroj_contract_number and r.abroj_contract_number != PLACEHOLDER:
                continue
            number = self.env['ir.sequence'].with_company(r.company_id).next_by_code('abroj.contracting.client.contract')
            if not number:
                raise UserError('تسلسل أرقام عقود العملاء غير موجود.')
            r.abroj_contract_number = number
        return True
