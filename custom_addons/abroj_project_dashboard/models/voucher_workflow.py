"""Native recognition and settlement for contracting cash documents.

Cash is recorded once by account.payment. Recognition is recorded once by an
invoice. Reviewed source links explain the two; they never add another amount.
"""
from decimal import Decimal

from odoo import _, api, Command, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.addons.abroj_contracting.models.accounting_issue import (
    ACCOUNTING_GROUPS, EXPENSE_TYPES, can_account, check_source, move_action,
    require_accountant, validate_amount, validate_project_distribution, validate_review_distribution_values,
)
from odoo.addons.abroj_contracting.models.contracting import FrozenDocument


PURPOSES = [
    ('direct', 'Direct expense / earned income'),
    ('settlement', 'Settle an existing invoice'),
    ('advance', 'Advance payment / collection'),
    ('supplier_refund', 'Supplier refund against a credit note'),
]
VOUCHER_LINKS = {'workflow_reviewed', 'workflow_reviewed_by', 'workflow_reviewed_at',
                 'workflow_evidence', 'recognition_move_id', 'abroj_budget_line_id'}


def linked_moves(moves):
    return moves.filtered(lambda m: m.abroj_recognition_voucher_id or m.abroj_voucher_id)


class Voucher(models.Model):
    _inherit = 'abroj.contracting.voucher'

    payment_purpose = fields.Selection(PURPOSES, string='Payment purpose', copy=False)
    workflow_reviewed = fields.Boolean(string='Purpose reviewed', readonly=True, copy=False)
    workflow_reviewed_by = fields.Many2one('res.users', string='Reviewed by', readonly=True, copy=False)
    workflow_reviewed_at = fields.Datetime(string='Reviewed at', readonly=True, copy=False)
    workflow_evidence = fields.Text(string='Review evidence', readonly=True, copy=False)
    recognition_move_id = fields.Many2one('account.move', string='Recognition document', readonly=True,
        check_company=True, copy=False, ondelete='restrict', index=True, groups=ACCOUNTING_GROUPS)
    abroj_budget_line_id = fields.Many2one('abroj.project.budget.line', string='Cost category',
        readonly=True, check_company=True, copy=False, ondelete='restrict')
    workflow_status = fields.Selection([('pending', 'Needs purpose review'), ('reviewed', 'Reviewed')],
        string='Purpose review', compute='_compute_workflow_status')

    @api.depends('workflow_reviewed')
    def _compute_workflow_status(self):
        for voucher in self:
            voucher.workflow_status = 'reviewed' if voucher.workflow_reviewed else 'pending'

    @api.model_create_multi
    def create(self, vals_list):
        if (any(VOUCHER_LINKS & vals.keys() for vals in vals_list)
                or any('default_' + name in self.env.context for name in VOUCHER_LINKS)):
            raise AccessError(_('Accounting links are managed by the review action.'))
        records = super().create(vals_list)
        visible = VOUCHER_LINKS - {'recognition_move_id'}
        if any(any(record[name] for name in visible) for record in records):
            raise AccessError(_('Accounting links are managed by the review action.'))
        return records

    def write(self, vals):
        if VOUCHER_LINKS & vals.keys():
            raise AccessError(_('Accounting links are managed by the review action.'))
        return super().write(vals)

    def action_issue(self):
        for voucher in self:
            if not voucher.payment_purpose:
                raise ValidationError(_('Choose the payment purpose before issuing the voucher.'))
            if voucher.payment_purpose == 'supplier_refund' and voucher.kind != 'receipt':
                raise ValidationError(_('A supplier refund must be a receipt voucher.'))
            if voucher.kind == 'receipt' and voucher.subcontractor_id and voucher.payment_purpose != 'supplier_refund':
                raise ValidationError(_('A subcontractor receipt must use the supplier refund purpose.'))
        return super().action_issue()

    @api.constrains('kind', 'partner_id', 'party_id', 'project_id', 'subcontractor_id', 'payment_purpose')
    def _check_client_party(self):
        return super(Voucher, self.filtered(lambda v: v.payment_purpose != 'supplier_refund'))._check_client_party()

    @api.onchange('project_id', 'kind', 'subcontractor_id', 'payment_purpose')
    def _onchange_contract_party(self):
        return super(Voucher, self.filtered(lambda v: v.payment_purpose != 'supplier_refund'))._onchange_contract_party()

    def action_accounting_approve(self):
        require_accountant(self.env)
        raise UserError(_('Use Review payment purpose to approve or link this voucher.'))

    def action_open_accounting_issue(self):
        return self.action_open_voucher_review()

    def action_open_voucher_review(self):
        check_source(self)
        if self.state != 'issued':
            raise UserError(_('Issue the voucher before reviewing its accounting purpose.'))
        if self.workflow_reviewed and self.payment_purpose != 'advance':
            return move_action(self.recognition_move_id or self.payment_id.move_id)
        return {'type': 'ir.actions.act_window', 'name': _('Review payment purpose'),
                'res_model': 'abroj.project.voucher.review', 'view_mode': 'form', 'target': 'new',
                'context': dict(self.env.context, default_voucher_id=self.id)}

    def action_open_recognition(self):
        self.ensure_one()
        require_accountant(self.env)
        return move_action(self.recognition_move_id)


class OldIssueWizard(models.TransientModel):
    _inherit = 'abroj.contracting.accounting.issue'

    budget_line_id = fields.Many2one('abroj.project.budget.line', string='Cost category', check_company=True)

    def _prepare_bill_line_values(self, cost, unit):
        values = super()._prepare_bill_line_values(cost, unit)
        if cost.project_id.abroj_budget_line_ids and not self.budget_line_id:
            raise ValidationError(_('Choose a cost category from this project.'))
        if self.budget_line_id:
            self.budget_line_id.check_access('read')
            if self.budget_line_id.project_id != cost.project_id:
                raise ValidationError(_('Choose a cost category from this project.'))
            values['abroj_budget_line_id'] = self.budget_line_id.id
        return values

    def action_issue(self):
        if self.filtered('voucher_id'):
            require_accountant(self.env)
            raise UserError(_('Use Review payment purpose to approve or link this voucher.'))
        return super().action_issue()


class Payment(models.Model):
    _inherit = 'account.payment'

    _abroj_voucher_payment_unique = models.Constraint('UNIQUE(abroj_voucher_id)',
        'This voucher already has a payment.')

    @api.model_create_multi
    def create(self, vals_list):
        if any(v.get('abroj_voucher_id') for v in vals_list):
            raise AccessError(_('Voucher payment links are managed by the review action.'))
        records = super().create(vals_list)
        if records.filtered('abroj_voucher_id'):
            raise AccessError(_('Voucher payment links are managed by the review action.'))
        return records

    def write(self, vals):
        if 'abroj_voucher_id' in vals:
            raise AccessError(_('Voucher payment links are managed by the review action.'))
        protected = {'amount', 'date', 'partner_id', 'partner_type', 'payment_type', 'journal_id',
                     'currency_id', 'company_id', 'destination_account_id', 'payment_method_line_id', 'move_id'}
        if protected & vals.keys() and self.filtered(lambda p: p.abroj_voucher_id and p.move_id.state == 'posted'):
            raise UserError(_('Correct the original voucher payment through a native reversal.'))
        if vals.get('state') in ('draft', 'canceled', 'cancel', 'rejected') and self.filtered('abroj_voucher_id'):
            raise UserError(_('Correct the original voucher payment through a native reversal.'))
        return super().write(vals)

    def unlink(self):
        if self.filtered('abroj_voucher_id'):
            raise UserError(_('Correct the original voucher payment through a native reversal.'))
        return super().unlink()


class RecognitionMove(models.Model):
    _inherit = 'account.move'

    abroj_recognition_voucher_id = fields.Many2one('abroj.contracting.voucher',
        string='Recognition source voucher', readonly=True, copy=False, check_company=True,
        ondelete='restrict', index=True)
    _abroj_recognition_unique = models.Constraint('UNIQUE(abroj_recognition_voucher_id)',
        'This voucher already has a recognition document.')

    @api.model_create_multi
    def create(self, vals_list):
        if any(v.get('abroj_recognition_voucher_id') or v.get('abroj_voucher_id') for v in vals_list):
            raise AccessError(_('Recognition links are managed by the review action.'))
        records = super().create(vals_list)
        if linked_moves(records):
            raise AccessError(_('Recognition links are managed by the review action.'))
        return records

    def write(self, vals):
        if {'abroj_recognition_voucher_id', 'abroj_voucher_id'} & vals.keys():
            raise AccessError(_('Recognition links are managed by the review action.'))
        protected = {'company_id', 'currency_id', 'partner_id', 'journal_id', 'move_type',
                     'invoice_date', 'date', 'line_ids', 'invoice_line_ids', 'abroj_project_id'}
        if protected & vals.keys() and linked_moves(self).filtered(lambda m: m.state == 'posted'):
            raise UserError(_('Correct the recognition document through a native credit note or reversal.'))
        if vals.get('state') in ('draft', 'cancel') and linked_moves(self):
            raise UserError(_('Correct the recognition document through a native credit note or reversal.'))
        return super().write(vals)

    def unlink(self):
        if linked_moves(self):
            raise UserError(_('Correct the recognition document through a native credit note or reversal.'))
        return super().unlink()

    def button_draft(self):
        if linked_moves(self):
            raise UserError(_('Correct the recognition document through a native credit note or reversal.'))
        return super().button_draft()

    def button_cancel(self):
        if linked_moves(self):
            raise UserError(_('Correct the recognition document through a native credit note or reversal.'))
        return super().button_cancel()


class RecognitionLine(models.Model):
    _inherit = 'account.move.line'

    abroj_budget_line_id = fields.Many2one('abroj.project.budget.line', string='Cost category',
        check_company=True, ondelete='restrict', copy=True)

    @api.constrains('abroj_budget_line_id', 'analytic_distribution', 'company_id')
    def _check_workflow_category(self):
        for line in self.filtered('abroj_budget_line_id'):
            category = line.abroj_budget_line_id
            key = str(category.project_id.account_id.id)
            allocation = sum(Decimal(str(value)) for ids, value in (line.analytic_distribution or {}).items() if key in ids.split(','))
            if category.company_id != line.company_id or allocation != Decimal('100') or line.account_id.account_type not in EXPENSE_TYPES:
                raise ValidationError(_('The cost category must match the expense company and 100% project allocation.'))

    def _prepare_analytic_lines(self):
        values = super()._prepare_analytic_lines()
        if self.abroj_budget_line_id:
            for value in values:
                if value.get('account_id') == self.abroj_budget_line_id.project_id.account_id.id:
                    value['abroj_budget_line_id'] = self.abroj_budget_line_id.id
        return values

    @api.model_create_multi
    def create(self, vals_list):
        destinations = {v.get('move_id', self.env.context.get('default_move_id')) for v in vals_list}
        moves = self.env['account.move'].browse([i for i in destinations if i]).exists()
        if linked_moves(moves).filtered(lambda m: m.state == 'posted'):
            raise UserError(_('Correct the recognition document through a native credit note or reversal.'))
        records = super().create(vals_list)
        if linked_moves(records.move_id).filtered(lambda m: m.state == 'posted'):
            raise UserError(_('Correct the recognition document through a native credit note or reversal.'))
        return records

    def write(self, vals):
        protected = {'move_id', 'company_id', 'account_id', 'partner_id', 'currency_id', 'debit', 'credit',
                     'balance', 'amount_currency', 'price_unit', 'quantity', 'tax_ids', 'analytic_distribution',
                     'abroj_budget_line_id', 'display_type', 'discount', 'product_id', 'product_uom_id',
                     'tax_line_id', 'tax_repartition_line_id', 'tax_tag_ids', 'date', 'date_maturity'}
        moves = self.move_id | self.env['account.move'].browse(vals.get('move_id', []))
        if protected & vals.keys() and linked_moves(moves).filtered(lambda m: m.state == 'posted'):
            raise UserError(_('Correct the recognition document through a native credit note or reversal.'))
        return super().write(vals)

    def unlink(self):
        if linked_moves(self.move_id).filtered(lambda m: m.state == 'posted'):
            raise UserError(_('Correct the recognition document through a native credit note or reversal.'))
        return super().unlink()


class VoucherReview(models.TransientModel):
    _name = 'abroj.project.voucher.review'
    _inherit = 'analytic.mixin'
    _description = 'Review contracting payment purpose'
    _check_company_auto = True

    voucher_id = fields.Many2one('abroj.contracting.voucher', required=True, readonly=True, ondelete='cascade')
    kind = fields.Selection(related='voucher_id.kind')
    project_id = fields.Many2one(related='voucher_id.project_id')
    company_id = fields.Many2one(related='voucher_id.company_id')
    currency_id = fields.Many2one(related='voucher_id.currency_id')
    amount = fields.Monetary(related='voucher_id.amount')
    existing_payment_id = fields.Many2one(related='voucher_id.payment_id')
    purpose = fields.Selection(PURPOSES, required=True, string='Payment purpose')
    partner_id = fields.Many2one('res.partner', string='Accounting partner', required=True, check_company=True)
    journal_id = fields.Many2one('account.journal', string='Payment journal', check_company=True)
    invoice_journal_id = fields.Many2one('account.journal', string='Invoice journal', check_company=True)
    invoice_id = fields.Many2one('account.move', string='Existing posted invoice / credit note', check_company=True)
    expense_id = fields.Many2one('abroj.contracting.cost', string='Existing confirmed expense', check_company=True)
    name = fields.Char(string='Description', required=True)
    document_reference = fields.Char(string='Source reference')
    evidence_note = fields.Text(string='Evidence and review decision', required=True)
    account_id = fields.Many2one('account.account', string='Expense / income account', check_company=True)
    budget_line_id = fields.Many2one('abroj.project.budget.line', string='Cost category', check_company=True)
    tax_ids = fields.Many2many('account.tax', string='Reviewed taxes', check_company=True)
    invoice_date = fields.Date(string='Invoice date', default=fields.Date.context_today)
    date = fields.Date(string='Recognition date', default=fields.Date.context_today)
    payment_account_id = fields.Many2one('account.account', string='Payment posting account', compute='_compute_posting_account')
    uses_clearing_account = fields.Boolean(compute='_compute_posting_account')

    def _sanitize_values(self, vals, decimal_precision):
        validate_review_distribution_values(self, vals)
        return super()._sanitize_values(vals, decimal_precision)

    @api.depends('existing_payment_id', 'journal_id', 'partner_id', 'purpose')
    def _compute_posting_account(self):
        for wizard in self:
            payment = wizard.existing_payment_id
            if payment:
                account = payment.outstanding_account_id
            elif wizard.journal_id:
                outbound = wizard.voucher_id.kind == 'payment'
                methods = wizard.journal_id.outbound_payment_method_line_ids if outbound else wizard.journal_id.inbound_payment_method_line_ids
                payment = self.env['account.payment'].with_company(wizard.company_id).new({
                    'payment_type': 'outbound' if outbound else 'inbound',
                    'partner_type': 'supplier' if outbound or wizard.purpose == 'supplier_refund' else 'customer',
                    'partner_id': wizard.partner_id.id, 'company_id': wizard.company_id.id,
                    'currency_id': wizard.currency_id.id, 'amount': wizard.amount,
                    'journal_id': wizard.journal_id.id, 'payment_method_line_id': methods[:1].id})
                account = payment.outstanding_account_id
            else:
                account = self.env['account.account']
            wizard.payment_account_id = account
            wizard.uses_clearing_account = bool(account and account.account_type != 'asset_cash')

    @api.onchange('purpose')
    def _onchange_purpose(self):
        self.invoice_id = False
        if self.purpose != 'direct':
            self.expense_id = False
            self.budget_line_id = False
            self.tax_ids = [Command.clear()]
            self.analytic_distribution = False
        elif self.project_id.account_id:
            self.analytic_distribution = {str(self.project_id.account_id.id): 100}

    @api.model
    def default_get(self, names):
        vals = super().default_get(names)
        voucher = self.env['abroj.contracting.voucher'].browse(vals.get('voucher_id')).exists()
        if voucher:
            check_source(voucher)
            vals.update(purpose=voucher.payment_purpose,
                        partner_id=(voucher.payment_id.partner_id or voucher.accounting_partner_id or voucher.partner_id).id,
                        journal_id=voucher.journal_id.id, name=voucher.memo or voucher.name,
                        invoice_date=voucher.date, date=voucher.date)
            if voucher.payment_purpose == 'direct':
                vals.setdefault('analytic_distribution', {str(voucher.project_id.account_id.id): 100})
        return vals

    def _validate(self, voucher):
        validate_amount(voucher.amount, self.env)
        if voucher.state != 'issued' or voucher.currency_id != voucher.company_id.currency_id:
            raise ValidationError(_('Use an issued voucher in the company currency.'))
        if not self.evidence_note or not self.evidence_note.strip():
            raise ValidationError(_('Record the evidence and accounting decision.'))
        for record in (self.partner_id, self.journal_id, self.invoice_journal_id, self.invoice_id,
                       self.expense_id, self.account_id, self.budget_line_id, self.tax_ids):
            if record:
                record.check_access('read')
        if (not self.partner_id or (self.partner_id.company_id and self.partner_id.company_id != voucher.company_id)
                or (voucher.partner_id and voucher.partner_id.commercial_partner_id != self.partner_id.commercial_partner_id)):
            raise ValidationError(_('Choose the source document accounting partner from the same company.'))
        analytic = voucher.project_id.account_id
        if not analytic or analytic.plan_id._column_name() != 'account_id' or (analytic.company_id and analytic.company_id != voucher.company_id):
            raise ValidationError(_('Select an analytic account from the native project plan.'))
        analytic.check_access('read')
        if self.purpose == 'supplier_refund' and voucher.kind != 'receipt':
            raise ValidationError(_('A supplier refund must be a receipt voucher.'))
        if voucher.kind == 'receipt' and voucher.subcontractor_id and self.purpose != 'supplier_refund':
            raise ValidationError(_('A subcontractor receipt must use the supplier refund purpose.'))
        if self.purpose == 'advance' and (self.invoice_id or self.expense_id or self.budget_line_id or self.tax_ids or self.analytic_distribution):
            raise ValidationError(_('An advance cannot contain an invoice, expense, cost category or taxes.'))
    def _payment(self, voucher):
        payment = voucher.payment_id
        partner_type = 'supplier' if voucher.kind == 'payment' or self.purpose == 'supplier_refund' else 'customer'
        if payment:
            payment.check_access('read')
            if (not payment.partner_id or payment.partner_id.commercial_partner_id != self.partner_id.commercial_partner_id
                    or payment.partner_type != partner_type or payment.company_id != voucher.company_id
                    or payment.currency_id != voucher.currency_id or payment.move_id.state != 'posted'
                    or payment.payment_type != ('outbound' if voucher.kind == 'payment' else 'inbound')
                    or voucher.currency_id.compare_amounts(payment.amount, voucher.amount)):
                raise ValidationError(_('The original payment needs accountant reclassification; its party, company, direction and amount must match.'))
            return payment
        if voucher.issued_by == self.env.user and not self.env.user.has_group('base.group_system'):
            raise AccessError(_('The voucher issuer cannot approve their own payment.'))
        journal = self.journal_id
        expected = 'cash' if voucher.method == 'cash' else 'bank'
        if not journal or journal.type != expected or journal.company_id != voucher.company_id or not journal.active:
            raise ValidationError(_('Choose an active cash or bank journal matching the voucher payment method.'))
        outbound = voucher.kind == 'payment'
        methods = journal.outbound_payment_method_line_ids if outbound else journal.inbound_payment_method_line_ids
        if not methods:
            raise ValidationError(_('Configure a native payment method for this journal.'))
        payment = self.env['account.payment'].with_company(voucher.company_id).create({
            'payment_type': 'outbound' if outbound else 'inbound', 'partner_type': partner_type,
            'partner_id': self.partner_id.id, 'amount': voucher.amount, 'date': voucher.date,
            'currency_id': voucher.currency_id.id, 'journal_id': journal.id,
            'payment_method_line_id': methods[0].id, 'company_id': voucher.company_id.id, 'memo': voucher.name})
        payment._generate_journal_entry()
        if not payment.move_id:
            raise ValidationError(_('The payment journal must generate a native accounting entry.'))
        payment.move_id.write({'ref': voucher.name, 'abroj_project_id': voucher.project_id.id})
        payment.action_post()
        super(Payment, payment).write({'abroj_voucher_id': voucher.id})
        super(RecognitionMove, payment.move_id).write({'abroj_voucher_id': voucher.id})
        super(FrozenDocument, voucher).write({'payment_id': payment.id, 'accounting_partner_id': self.partner_id.id})
        return payment

    def _recognize(self, voucher):
        expense = voucher.kind == 'payment'
        company = voucher.company_id
        account = self.account_id
        journal = self.invoice_journal_id
        distribution = validate_project_distribution(voucher.project_id,
            self.analytic_distribution or {str(voucher.project_id.account_id.id): 100})
        if (not self.date or not self.invoice_date or not self.document_reference
                or not account or not account.active or company not in account.company_ids
                or account.account_type not in (EXPENSE_TYPES if expense else ('income', 'income_other'))
                or not journal or journal.company_id != company or not journal.active
                or journal.type != ('purchase' if expense else 'sale')):
            raise ValidationError(_('Review the source reference, dates, recognition account and invoice journal.'))
        if expense and (not self.budget_line_id or self.budget_line_id.project_id != voucher.project_id):
            raise ValidationError(_('Choose a cost category from this project.'))
        if not expense and (self.budget_line_id or self.expense_id):
            raise ValidationError(_('Customer income cannot use an expense source or cost category.'))
        move_type = 'in_invoice' if expense else 'out_invoice'
        Move = self.env['account.move'].with_company(company)
        duplicate = Move.search_count([('company_id', '=', company.id), ('partner_id', '=', self.partner_id.id),
                                      ('move_type', '=', move_type), ('ref', '=', self.document_reference), ('state', '!=', 'cancel')])
        if duplicate:
            raise UserError(_('This source reference already has an invoice. Settle the existing invoice instead.'))
        if any(t.company_id != company or not t.active or t.type_tax_use != ('purchase' if expense else 'sale')
               or t.amount_type != 'percent' or t.include_base_amount or t.amount < 0 for t in self.tax_ids) or len(set(self.tax_ids.mapped('price_include'))) > 1:
            raise ValidationError(_('Choose supported, explicitly reviewed percentage taxes from this company.'))
        unit = voucher.amount
        if self.tax_ids and not self.tax_ids[0].price_include:
            unit = self.tax_ids.with_company(company).with_context(force_price_include=True, round_base=False).compute_all(
                voucher.amount, currency=voucher.currency_id, quantity=1, partner=self.partner_id)['total_excluded']
        cost = self.expense_id
        if cost:
            check_source(cost)
            if (not expense or cost.state != 'confirmed' or cost.project_id != voucher.project_id
                    or cost.account_move_id or (cost.partner_id and cost.partner_id != self.partner_id)
                    or voucher.currency_id.compare_amounts(cost.amount, voucher.amount)):
                raise ValidationError(_('The confirmed expense must match this project, supplier and amount and have no accounting document.'))
        # A subcontract payment is part of its existing contract commitment;
        # never create a second standalone commitment for the same work.
        if expense and not cost and not voucher.subcontractor_id:
            cost = self.env['abroj.contracting.cost'].create({'project_id': voucher.project_id.id,
                'partner_id': self.partner_id.id, 'party_id': voucher.party_id.id, 'name': self.name,
                'amount': voucher.amount, 'date': self.invoice_date, 'invoice_number': self.document_reference})
            cost.action_confirm()
        move = Move.create({'move_type': move_type, 'company_id': company.id, 'currency_id': voucher.currency_id.id,
            'partner_id': self.partner_id.id, 'journal_id': journal.id, 'invoice_date': self.invoice_date,
            'date': self.date, 'ref': self.document_reference, 'abroj_project_id': voucher.project_id.id,
            'invoice_line_ids': [Command.create({'name': self.name, 'account_id': account.id, 'quantity': 1,
                'price_unit': unit, 'tax_ids': [Command.set(self.tax_ids.ids)],
                'analytic_distribution': distribution,
                'abroj_budget_line_id': self.budget_line_id.id if expense else False})]})
        if cost:
            move._abroj_bind_cost(cost)
        super(RecognitionMove, move).write({'abroj_recognition_voucher_id': voucher.id})
        move.action_post()
        if move.date != self.date or voucher.currency_id.compare_amounts(move.amount_total, voucher.amount):
            raise ValidationError(_('The native invoice date or total changed. Review the period and taxes.'))
        return move

    def _validate_invoice(self, voucher, invoice):
        expected = 'in_refund' if self.purpose == 'supplier_refund' else ('in_invoice' if voucher.kind == 'payment' else 'out_invoice')
        if (not invoice or invoice.state != 'posted' or invoice.move_type != expected
                or invoice.company_id != voucher.company_id or invoice.currency_id != voucher.currency_id
                or invoice.partner_id.commercial_partner_id != self.partner_id.commercial_partner_id
                or invoice.abroj_project_id != voucher.project_id):
            raise ValidationError(_('Choose a posted invoice matching the purpose, company, currency, partner and project.'))
        key = str(voucher.project_id.account_id.id)
        types = EXPENSE_TYPES if expected in ('in_invoice', 'in_refund') else ('income', 'income_other')
        lines = invoice.invoice_line_ids.filtered(lambda l: l.display_type == 'product')
        if not lines or any(l.account_id.account_type not in types or sum(Decimal(str(value))
                for ids, value in (l.analytic_distribution or {}).items() if key in ids.split(',')) != Decimal('100') for l in lines):
            raise ValidationError(_('The invoice recognition lines must allocate 100% to this project.'))
        if expected in ('in_invoice', 'in_refund') and voucher.project_id.abroj_budget_line_ids:
            for line in lines:
                category = line.abroj_budget_line_id
                entries = line.analytic_line_ids.filtered(lambda a: a.account_id == voucher.project_id.account_id)
                if (not category or category.project_id != voucher.project_id
                        or (line.balance and not entries)
                        or any(a.abroj_budget_line_id != category for a in entries)):
                    raise ValidationError(_('Classify every expense line and its analytics under this project budget before settling the invoice.'))
        if voucher.kind == 'payment' and self.budget_line_id:
            if self.budget_line_id.project_id != voucher.project_id or any(l.abroj_budget_line_id != self.budget_line_id for l in lines):
                raise ValidationError(_('Use the cost category already recorded on the posted invoice.'))

    def _settle(self, voucher, payment, invoice):
        account_type = 'liability_payable' if payment.partner_type == 'supplier' else 'asset_receivable'
        source = payment.move_id.line_ids.filtered(lambda l: l.account_id.account_type == account_type)
        target = invoice.line_ids.filtered(lambda l: l.account_id.account_type == account_type)
        lines = source | target
        lines.check_access('write')
        self.env.cr.execute('SELECT id FROM account_move_line WHERE id IN %s ORDER BY id FOR NO KEY UPDATE', [tuple(sorted(lines.ids))])
        lines.invalidate_recordset()
        source = source.filtered(lambda l: not l.reconciled)
        target = target.filtered(lambda l: not l.reconciled)
        if not source or not target or len(source.account_id) != 1 or source.account_id != target.account_id:
            raise ValidationError(_('The payment and invoice must have open lines on the same receivable or payable account.'))
        if any(not l.partner_id or l.partner_id.commercial_partner_id != self.partner_id.commercial_partner_id for l in source | target):
            raise ValidationError(_('Every settlement line must have the reviewed original accounting partner.'))
        available = abs(sum(Decimal(str(l.amount_residual)) for l in source))
        due = abs(sum(Decimal(str(l.amount_residual)) for l in target))
        if available <= 0 or available > due:
            raise ValidationError(_('The payment residual exceeds the invoice residual. Keep the excess as an explicit advance.'))
        if sum(source.mapped('balance')) * sum(target.mapped('balance')) >= 0:
            raise ValidationError(_('The payment and invoice settlement directions must be opposite.'))
        (source | target).reconcile()
        source.invalidate_recordset()
        if any(not l.reconciled for l in source):
            raise ValidationError(_('The original payment was not fully matched; review its open balance.'))

    def action_apply(self):
        self.ensure_one()
        voucher = self.voucher_id
        check_source(voucher)
        with self.env.cr.savepoint():
            self.env.cr.execute('SELECT id FROM abroj_contracting_voucher WHERE id=%s FOR NO KEY UPDATE', [voucher.id])
            voucher.invalidate_recordset()
            if voucher.workflow_reviewed and voucher.payment_purpose != 'advance':
                return move_action(voucher.recognition_move_id or voucher.payment_id.move_id)
            if voucher.workflow_reviewed and self.purpose == 'advance':
                return move_action(voucher.payment_id.move_id)
            if voucher.recognition_move_id:
                return move_action(voucher.recognition_move_id)
            self._validate(voucher)
            super(FrozenDocument, voucher).write({'write_date': fields.Datetime.now()})
            invoice = self.env['account.move']
            if self.purpose in ('settlement', 'supplier_refund'):
                invoice = self.invoice_id
                self.env.cr.execute('SELECT id FROM account_move WHERE id=%s FOR NO KEY UPDATE', [invoice.id or 0])
                invoice.invalidate_recordset()
                self._validate_invoice(voucher, invoice)
                # Materialize a row version so a competing voucher under RR
                # retries against the newly consumed invoice residual.
                invoice.write({'write_date': fields.Datetime.now()})
            elif self.purpose == 'direct':
                invoice = self._recognize(voucher)
            elif self.purpose != 'advance':
                raise ValidationError(_('Choose a supported payment purpose.'))
            payment = self._payment(voucher)
            if invoice:
                self._settle(voucher, payment, invoice)
            previous = voucher.workflow_evidence or ''
            audit = '%s | %s | %s\n%s' % (fields.Datetime.now(), self.env.user.display_name, self.purpose, self.evidence_note)
            super(FrozenDocument, voucher).write({'payment_purpose': self.purpose, 'workflow_reviewed': True,
                'workflow_reviewed_by': self.env.uid, 'workflow_reviewed_at': fields.Datetime.now(),
                'workflow_evidence': previous + ('\n\n' if previous else '') + audit,
                'recognition_move_id': invoice.id, 'abroj_budget_line_id': self.budget_line_id.id})
            return move_action(invoice or payment.move_id)


class ProjectRecognition(models.Model):
    _inherit = 'project.project'

    @api.depends('voucher_ids.amount', 'voucher_ids.state', 'voucher_ids.kind',
                 'voucher_ids.subcontractor_id', 'voucher_ids.payment_purpose')
    def _compute_customer_received(self):
        for project in self:
            project.abroj_customer_received = sum((Decimal(str(v.amount)) for v in project.voucher_ids
                if v.state == 'issued' and v.kind == 'receipt' and not v.subcontractor_id
                and v.payment_purpose != 'supplier_refund'), Decimal('0'))

    @api.depends('contract_value', 'estimated_cost', 'company_id.currency_id', 'voucher_ids.amount',
                 'voucher_ids.state', 'voucher_ids.kind', 'voucher_ids.subcontractor_id', 'voucher_ids.payment_purpose',
                 'invoice_ids.amount', 'invoice_ids.state', 'cost_ids.amount', 'cost_ids.state',
                 'subcontractor_ids.agreed_amount', 'subcontractor_ids.materials_total')
    def _compute_totals(self):
        super()._compute_totals()
        for project in self:
            project.remaining = Decimal(str(project.contract_value)) - Decimal(str(project.abroj_customer_received))

    def _abroj_data(self, *args, **kwargs):
        data = super()._abroj_data(*args, **kwargs)
        readable = all(self.env[name].has_access('read') for name in
                       ('account.analytic.line', 'account.move.line', 'account.move', 'account.account'))
        if not readable:
            data.update(recognized_revenue=None, recognized_profit=None)
            return data
        entries = self.env['account.analytic.line'].search([
            ('account_id', '=', self.account_id.id or 0), ('company_id', '=', self.company_id.id),
            ('move_line_id.move_id.state', '=', 'posted'),
            ('move_line_id.account_id.account_type', 'in', ('income', 'income_other'))])
        revenue = sum((Decimal(str(line.amount)) for line in entries), Decimal('0'))
        data.update(recognized_revenue=float(revenue),
                    recognized_profit=float(revenue - Decimal(str(data['actual']))))
        return data

    @api.model
    def _abroj_financial_summary(self, projects):
        data = super()._abroj_financial_summary(projects)
        for name in ('recognized_revenue', 'recognized_profit'):
            data[name] = (float(sum((Decimal(str(p[name])) for p in projects), Decimal('0')))
                          if projects and all(p.get(name) is not None for p in projects) else None)
        return data

    def action_approve_detailed_budget(self):
        self.ensure_one()
        if not self.env.user.has_group('project.group_project_manager'):
            raise AccessError(_('Only a project manager may approve the comparison budget.'))
        self.check_access('write')
        total = sum((Decimal(str(line.budget)) for line in self.abroj_budget_line_ids), Decimal('0'))
        validate_amount(total, self.env)
        if any(line.budget < 0 for line in self.abroj_budget_line_ids):
            raise ValidationError(_('Budget categories cannot have negative amounts.'))
        self.write({'abroj_budget': float(total)})
        self.message_post(body=_('Detailed budget approved for comparison: %s', total))
        return True
