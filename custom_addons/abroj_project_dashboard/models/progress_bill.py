from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    abroj_budget_line_id = fields.Many2one('abroj.project.budget.line', string='بند الميزانية', ondelete='set null')
    abroj_subcontractor_id = fields.Many2one('abroj.contracting.subcontractor', string='عقد المقاول', ondelete='set null')


class Subcontractor(models.Model):
    _inherit = 'abroj.contracting.subcontractor'

    state = fields.Selection([('open', 'مفتوح'), ('closed', 'منتهي')], default='open', required=True, copy=False)
    progress_bill_ids = fields.One2many('account.move', 'abroj_subcontractor_id', string='المستخلصات')
    progress_bill_partner_id = fields.Many2one('res.partner', string='جهة الاتصال المحاسبية', copy=False, check_company=True)

    def _progress_bill_partner(self):
        self.ensure_one()
        partner = self.partner_id or self.progress_bill_partner_id
        if not partner:
            partners = (self.voucher_ids.mapped('payment_id.partner_id') | self.voucher_ids.mapped('accounting_partner_id'))
            if len(partners) > 1:
                raise UserError(_('This contract has multiple accounting partners; select one on the contract.'))
            partner = partners or self.env['res.partner'].create({
                'name': self.party_id.name, 'phone': self.party_id.phone, 'vat': self.party_id.vat,
                'company_id': self.company_id.id,
            })
            self.progress_bill_partner_id = partner
        return partner

    def action_create_progress_bill(self, amount, date=None, by_agent=False):
        self.ensure_one()
        if amount <= 0:
            raise UserError(_('The bill amount must be positive.'))
        company = self.company_id
        partner = self._progress_bill_partner().with_company(company)
        review = self.env['abroj.project.voucher.review'].with_company(company)
        # The review helpers only use these voucher attributes.
        voucher = self.env['abroj.contracting.voucher'].new({
            'project_id': self.project_id.id, 'company_id': company.id, 'kind': 'payment',
            'date': date or fields.Date.context_today(self),
        })
        defaults = review._direct_defaults(voucher, partner, self.budget_line_id)
        account = self.budget_line_id.account_id or company.abroj_project_expense_account_id or self.env['account.account'].browse(defaults['account_id'])
        if not account:
            raise UserError(_('Configure an expense account for this bill.'))
        distribution = review._default_direct_distribution(voucher, account)
        ref = 'مستخلص %s' % self.display_name
        if by_agent:
            ref += ' - AGENT: مساعد البرمجة'
        bill = self.env['account.move'].with_company(company).create({
            'move_type': 'in_invoice', 'company_id': company.id, 'partner_id': partner.id,
            'invoice_date': date or fields.Date.context_today(self), 'ref': ref,
            'abroj_budget_line_id': self.budget_line_id.id, 'abroj_subcontractor_id': self.id,
            'invoice_line_ids': [fields.Command.create({
                'name': ref, 'account_id': account.id, 'price_unit': amount,
                'analytic_distribution': distribution, 'tax_ids': [fields.Command.clear()],
            })],
        })
        bill.action_post()
        payable = bill.line_ids.filtered(lambda l: l.account_id.account_type == 'liability_payable' and not l.reconciled)
        vouchers = self.voucher_ids.filtered(lambda v: v.kind == 'payment' and v.payment_purpose == 'advance'
            and v.state == 'issued' and v.payment_id.move_id.state == 'posted').sorted(key=lambda v: (v.payment_id.date, v.payment_id.id))
        for advance in vouchers:
            payment = advance.payment_id
            for line in payment.move_id.line_ids.filtered(lambda l: l.account_id.account_type == 'liability_payable' and not l.reconciled):
                targets = payable.filtered(lambda l: not l.reconciled and l.account_id == line.account_id and l.partner_id.commercial_partner_id == line.partner_id.commercial_partner_id)
                if targets:
                    (targets | line).reconcile()
        return bill

    def _open_progress_bill_wizard(self, mode):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'مستخلص', 'res_model': 'abroj.contract.progress.bill.wizard',
                'view_mode': 'form', 'target': 'new', 'context': {'default_contract_id': self.id, 'default_mode': mode}}

    def action_open_progress_bill(self):
        return self._open_progress_bill_wizard('progress')

    def action_open_final_bill(self):
        return self._open_progress_bill_wizard('final')


class ProgressBillWizard(models.TransientModel):
    _name = 'abroj.contract.progress.bill.wizard'
    _description = 'Contract progress bill'

    contract_id = fields.Many2one('abroj.contracting.subcontractor', required=True)
    currency_id = fields.Many2one(related='contract_id.currency_id')
    amount = fields.Monetary(required=True)
    date = fields.Date(required=True, default=fields.Date.context_today)
    mode = fields.Selection([('progress', 'مستخلص'), ('final', 'إنهاء العقد')], required=True, default='progress')

    @api.model
    def default_get(self, field_list):
        values = super().default_get(field_list)
        if values.get('mode') == 'final' and values.get('contract_id') and 'amount' in field_list:
            contract = self.env['abroj.contracting.subcontractor'].browse(values['contract_id'])
            values['amount'] = sum(contract.voucher_ids.filtered(lambda v: v.kind == 'payment' and v.state == 'issued' and v.payment_id.move_id.state == 'posted').mapped('amount'))
        return values

    def action_confirm(self):
        self.ensure_one()
        bill = self.contract_id.action_create_progress_bill(self.amount, self.date, by_agent=False)
        if self.mode == 'final':
            self.contract_id.state = 'closed'
        return {'type': 'ir.actions.act_window', 'res_model': 'account.move', 'view_mode': 'form', 'res_id': bill.id}
