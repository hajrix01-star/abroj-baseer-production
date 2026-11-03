"""Explicit, atomic native accounting for confirmed contracting expenses."""
from decimal import Decimal, InvalidOperation

from odoo import _, api, Command, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .contracting import FrozenDocument


EXPENSE_TYPES = ('expense', 'expense_direct_cost', 'expense_depreciation')
ACCOUNTING_GROUPS = 'account.group_account_invoice,account.group_account_manager'


def can_account(env):
    return (not env.user.has_group('abroj_contracting.group_extraction_agent')
            and (env.user.has_group('account.group_account_invoice')
                 or env.user.has_group('account.group_account_manager')))


def require_accountant(env):
    if not can_account(env):
        raise AccessError(env._('Only an accountant can issue accounting entries.'))


def validate_amount(value, env):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError(env._('Enter a positive amount with at most two decimals.'))
    try:
        valid = number.is_finite() and number > 0 and number == number.quantize(Decimal('0.01'))
    except InvalidOperation:
        valid = False
    if not valid:
        raise ValidationError(env._('Enter a positive amount with at most two decimals.'))


def check_source(source):
    env = source.env
    source.ensure_one()
    require_accountant(source.env)
    source.check_access('read')
    source.check_access('write')
    source.project_id.check_access('read')
    if source.company_id not in source.env.companies:
        raise AccessError(env._('Select an allowed company for this document.'))


def move_action(move):
    env = move.env
    move.check_access('read')
    return {'type': 'ir.actions.act_window', 'name': env._('Journal entry'),
            'res_model': 'account.move', 'res_id': move.id,
            'view_mode': 'form', 'target': 'current'}


class ContractingCost(models.Model):
    _inherit = 'abroj.contracting.cost'

    account_move_ids = fields.One2many('account.move', 'abroj_cost_id', readonly=True, groups=ACCOUNTING_GROUPS)
    account_move_id = fields.Many2one('account.move', string='Accounting document',
        compute='_compute_accounting', compute_sudo=False, groups=ACCOUNTING_GROUPS)
    accounting_stage = fields.Selection([('draft', 'Draft'), ('confirmed', 'Pending accounting'),
        ('posted', 'Posted')], string='Accounting status', compute='_compute_accounting',
        compute_sudo=False, groups=ACCOUNTING_GROUPS)
    abroj_can_accounting_issue = fields.Boolean(compute='_compute_can_issue')

    @api.depends('state', 'account_move_ids.state')
    @api.depends_context('uid')
    def _compute_accounting(self):
        for cost in self:
            move = cost.account_move_ids[:1]
            cost.account_move_id = move
            cost.accounting_stage = 'posted' if move.state == 'posted' else cost.state

    @api.depends('state', 'account_move_ids')
    @api.depends_context('uid')
    def _compute_can_issue(self):
        for cost in self:
            cost.abroj_can_accounting_issue = can_account(self.env) and cost.state == 'confirmed' and not cost.account_move_ids

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if {'account_move_id', 'account_move_ids', 'accounting_stage'} & vals.keys():
                raise AccessError(_('Accounting links are managed by the issue action.'))
            if 'amount' in vals:
                validate_amount(vals['amount'], self.env)
        return super().create(vals_list)

    def write(self, vals):
        if {'account_move_id', 'account_move_ids', 'accounting_stage'} & vals.keys():
            raise AccessError(_('Accounting links are managed by the issue action.'))
        if 'amount' in vals:
            validate_amount(vals['amount'], self.env)
        return super().write(vals)

    def action_open_accounting_issue(self):
        check_source(self)
        existing = self.env['account.move'].search([('abroj_cost_id', '=', self.id)], limit=1)
        if existing:
            return move_action(existing)
        if self.state != 'confirmed':
            raise UserError(_('Confirm the expense before issuing its accounting entry.'))
        return {'type': 'ir.actions.act_window', 'name': _('Issue accounting entry'),
                'res_model': 'abroj.contracting.accounting.issue', 'view_mode': 'form',
                'target': 'new', 'context': dict(self.env.context, default_cost_id=self.id)}

    def action_open_journal_entry(self):
        self.ensure_one()
        self.check_access('read')
        require_accountant(self.env)
        if not self.account_move_id:
            raise UserError(_('This expense has no accounting document yet.'))
        return move_action(self.account_move_id)


class ContractingVoucher(models.Model):
    _inherit = 'abroj.contracting.voucher'

    accounting_partner_id = fields.Many2one('res.partner', string='Accounting partner',
        readonly=True, copy=False, check_company=True, ondelete='restrict')

    @api.model_create_multi
    def create(self, vals_list):
        if any('accounting_partner_id' in vals for vals in vals_list):
            raise AccessError(_('Accounting links are managed by the issue action.'))
        records = super().create(vals_list)
        if records.filtered('accounting_partner_id'):
            raise AccessError(_('Accounting links are managed by the issue action.'))
        return records

    def write(self, vals):
        if 'accounting_partner_id' in vals:
            raise AccessError(_('Accounting links are managed by the issue action.'))
        return super().write(vals)

    def action_open_accounting_issue(self):
        check_source(self)
        if self.payment_id:
            return self.action_open_journal_entry()
        if not self.abroj_can_accounting_approve:
            raise AccessError(_('This voucher is not available for accounting approval.'))
        return {'type': 'ir.actions.act_window', 'name': _('Issue accounting entry'),
                'res_model': 'abroj.contracting.accounting.issue', 'view_mode': 'form',
                'target': 'new', 'context': dict(self.env.context, default_voucher_id=self.id)}


class AccountingMove(models.Model):
    _inherit = 'account.move'

    abroj_cost_id = fields.Many2one('abroj.contracting.cost', string='Contracting expense',
        readonly=True, index=True, copy=False, check_company=True, ondelete='restrict')
    _abroj_cost_unique = models.Constraint('UNIQUE(abroj_cost_id)', 'This expense already has an accounting document.')

    @api.model_create_multi
    def create(self, vals_list):
        if any(vals.get('abroj_cost_id') for vals in vals_list):
            raise AccessError(_('Accounting links are managed by the issue action.'))
        moves = super().create(vals_list)
        if moves.filtered('abroj_cost_id'):
            raise AccessError(_('Accounting links are managed by the issue action.'))
        return moves

    def _abroj_bind_cost(self, cost):
        self.ensure_one()
        check_source(cost)
        self.check_access('write')
        if self.abroj_cost_id or self.company_id != cost.company_id:
            raise UserError(_('The accounting document is already linked or belongs to another company.'))
        # Private server-only binding; RPC context cannot bypass the write guard.
        result = super().write({'abroj_cost_id': cost.id})
        cost.invalidate_recordset(['account_move_ids', 'account_move_id', 'accounting_stage'])
        return result

    def write(self, vals):
        if 'abroj_cost_id' in vals:
            raise AccessError(_('Accounting links are managed by the issue action.'))
        protected = {'company_id', 'currency_id', 'partner_id', 'journal_id', 'move_type',
                     'invoice_line_ids', 'line_ids', 'abroj_project_id', 'invoice_date', 'date'}
        if protected & vals.keys() and self.filtered(lambda m: m.abroj_cost_id and m.state == 'posted'):
            raise UserError(_('Correct a linked expense through a credit note or reversal.'))
        if vals.get('state') in ('draft', 'cancel') and self.filtered('abroj_cost_id'):
            raise UserError(_('Correct a linked expense through a credit note or reversal.'))
        return super().write(vals)

    def unlink(self):
        if self.filtered('abroj_cost_id'):
            raise UserError(_('Correct a linked expense through a credit note or reversal.'))
        return super().unlink()

    def button_draft(self):
        if self.filtered('abroj_cost_id'):
            raise UserError(_('Correct a linked expense through a credit note or reversal.'))
        return super().button_draft()

    def button_cancel(self):
        if self.filtered('abroj_cost_id'):
            raise UserError(_('Correct a linked expense through a credit note or reversal.'))
        return super().button_cancel()

    def action_open_abroj_cost(self):
        self.ensure_one()
        self.check_access('read')
        self.abroj_cost_id.check_access('read')
        return {'type': 'ir.actions.act_window', 'res_model': 'abroj.contracting.cost',
                'res_id': self.abroj_cost_id.id, 'view_mode': 'form', 'target': 'current'}


class AccountingMoveLine(models.Model):
    _inherit = 'account.move.line'

    @api.model_create_multi
    def create(self, vals_list):
        move_ids = {vals.get('move_id', self.env.context.get('default_move_id')) for vals in vals_list}
        moves = self.env['account.move'].browse([ident for ident in move_ids if ident]).exists()
        if moves.filtered(lambda move: move.abroj_cost_id and move.state == 'posted'):
            raise UserError(_('Correct a linked expense through a credit note or reversal.'))
        lines = super().create(vals_list)
        if lines.move_id.filtered(lambda m: m.abroj_cost_id and m.state == 'posted'):
            raise UserError(_('Correct a linked expense through a credit note or reversal.'))
        return lines

    def write(self, vals):
        protected = {'move_id', 'company_id', 'account_id', 'partner_id', 'currency_id',
            'debit', 'credit', 'balance', 'amount_currency', 'price_unit', 'quantity',
            'discount', 'tax_ids', 'analytic_distribution', 'display_type', 'product_id'}
        destination = self.env['account.move'].browse(vals.get('move_id')).exists()
        if protected & vals.keys() and (self.move_id | destination).filtered(lambda m: m.abroj_cost_id and m.state == 'posted'):
            raise UserError(_('Correct a linked expense through a credit note or reversal.'))
        return super().write(vals)

    def unlink(self):
        if self.move_id.filtered(lambda m: m.abroj_cost_id and m.state == 'posted'):
            raise UserError(_('Correct a linked expense through a credit note or reversal.'))
        return super().unlink()


class AccountingIssue(models.TransientModel):
    _name = 'abroj.contracting.accounting.issue'
    _description = 'Contracting accounting review'
    _check_company_auto = True

    cost_id = fields.Many2one('abroj.contracting.cost', string='Expense', readonly=True, ondelete='cascade')
    voucher_id = fields.Many2one('abroj.contracting.voucher', string='Voucher', readonly=True, ondelete='cascade')
    company_id = fields.Many2one('res.company', compute='_compute_source')
    currency_id = fields.Many2one('res.currency', compute='_compute_source')
    amount = fields.Monetary(string='Gross amount including selected taxes', compute='_compute_source')
    mode = fields.Selection([('create', 'Create accounting document'), ('existing', 'Link existing posted bill')], default='create', required=True)
    partner_id = fields.Many2one('res.partner', string='Accounting partner', required=True, check_company=True)
    journal_id = fields.Many2one('account.journal', string='Journal', check_company=True)
    expense_account_id = fields.Many2one('account.account', string='Expense account', check_company=True)
    tax_ids = fields.Many2many('account.tax', string='Purchase taxes', check_company=True)
    invoice_date = fields.Date(string='Invoice date', default=fields.Date.context_today)
    date = fields.Date(string='Accounting date', default=fields.Date.context_today, required=True)
    existing_move_id = fields.Many2one('account.move', string='Existing posted bill', check_company=True)
    payment_account_id = fields.Many2one('account.account', string='Payment posting account', compute='_compute_payment_account')
    payment_uses_clearing = fields.Boolean(compute='_compute_payment_account')

    @api.depends('voucher_id', 'journal_id', 'partner_id')
    def _compute_payment_account(self):
        for wizard in self:
            wizard.payment_account_id = False
            wizard.payment_uses_clearing = False
            voucher = wizard.voucher_id
            if not voucher or not wizard.journal_id:
                continue
            direction = 'outbound' if voucher.kind == 'payment' else 'inbound'
            methods = wizard.journal_id.outbound_payment_method_line_ids if direction == 'outbound' else wizard.journal_id.inbound_payment_method_line_ids
            if not methods:
                continue
            preview = self.env['account.payment'].with_company(voucher.company_id).new({
                'journal_id': wizard.journal_id.id, 'payment_method_line_id': methods[0].id,
                'payment_type': direction, 'partner_type': 'supplier' if direction == 'outbound' else 'customer',
                'partner_id': wizard.partner_id.id, 'company_id': voucher.company_id.id,
                'currency_id': voucher.currency_id.id, 'amount': voucher.amount,
            })
            wizard.payment_account_id = preview.outstanding_account_id
            wizard.payment_uses_clearing = bool(preview.outstanding_account_id and preview.outstanding_account_id.account_type != 'asset_cash')

    @api.depends('cost_id', 'voucher_id')
    def _compute_source(self):
        for wizard in self:
            source = wizard.cost_id or wizard.voucher_id
            wizard.company_id = source.company_id
            wizard.currency_id = source.currency_id
            wizard.amount = source.amount

    @api.model
    def default_get(self, names):
        require_accountant(self.env)
        vals = super().default_get(names)
        source = (self.env['abroj.contracting.cost'].browse(vals.get('cost_id')).exists()
                  or self.env['abroj.contracting.voucher'].browse(vals.get('voucher_id')).exists())
        if source:
            check_source(source)
            vals.update(partner_id=source.partner_id.id or False,
                        invoice_date=source.date, date=source.date)
            kind = 'purchase' if source._name == 'abroj.contracting.cost' else ('cash' if source.method == 'cash' else 'bank')
            journal = self.env['account.journal'].search([('company_id', '=', source.company_id.id), ('type', '=', kind)], limit=1)
            vals['journal_id'] = journal.id
        return vals

    def _validate_review(self, source):
        check_source(source)
        company = source.company_id
        for record in (self.partner_id, self.journal_id, self.expense_account_id, self.tax_ids, self.existing_move_id):
            if record:
                record.check_access('read')
        if not self.partner_id or (self.partner_id.company_id and self.partner_id.company_id != company):
            raise ValidationError(_('Choose an accounting partner from the document company.'))
        if source.partner_id and source.partner_id != self.partner_id:
            raise ValidationError(_('The accounting partner must match the source document supplier.'))
        if not (self.cost_id and self.mode == 'existing') and (not self.journal_id or self.journal_id.company_id != company or not self.journal_id.active):
            raise ValidationError(_('Choose an active journal from the document company.'))
        validate_amount(source.amount, self.env)
        analytic = source.project_id.account_id
        if (not analytic or analytic.plan_id._column_name() != 'account_id'
                or (analytic.company_id and analytic.company_id != company)):
            raise ValidationError(_('Select an analytic account from the native project plan.'))
        analytic.check_access('read')

    def _validate_existing(self, cost, move):
        if (not move or move.state != 'posted' or move.move_type != 'in_invoice'
                or move.company_id != cost.company_id or move.currency_id != cost.currency_id
                or move.partner_id != self.partner_id or move.abroj_cost_id
                or (cost.invoice_number and move.ref != cost.invoice_number)
                or (move.abroj_project_id and move.abroj_project_id != cost.project_id)
                or cost.currency_id.compare_amounts(move.amount_total, cost.amount)):
            raise ValidationError(_('The existing bill must match the expense supplier, company, currency, total and project.'))
        lines = move.invoice_line_ids.filtered(lambda l: l.display_type == 'product')
        key = str(cost.project_id.account_id.id)
        for line in lines:
            distribution = line.analytic_distribution or {}
            allocated = sum(Decimal(str(value)) for ids, value in distribution.items() if key in ids.split(','))
            if line.account_id.account_type not in EXPENSE_TYPES or allocated != Decimal('100'):
                raise ValidationError(_('Every expense line must allocate 100% to this project.'))
        if not lines or not cost.project_id.account_id:
            raise ValidationError(_('Every expense line must allocate 100% to this project.'))

    def _create_bill(self, cost):
        company = cost.company_id
        account = self.expense_account_id
        if (self.journal_id.type != 'purchase' or not self.invoice_date or not self.date
                or not account or account.account_type not in EXPENSE_TYPES
                or company not in account.company_ids or not account.active
                or not cost.project_id.account_id):
            raise ValidationError(_('Choose a purchase journal, an expense account and the project analytic account.'))
        if any(t.company_id != company or t.type_tax_use != 'purchase' or not t.active
               or t.amount_type != 'percent' or t.include_base_amount or t.amount < 0 for t in self.tax_ids):
            raise ValidationError(_('Choose supported purchase percentage taxes from this company.'))
        if len(set(self.tax_ids.mapped('price_include'))) > 1:
            raise ValidationError(_('Choose taxes with the same price-inclusion setting.'))
        Move = self.env['account.move'].with_company(company)
        if cost.invoice_number and Move.search_count([('company_id', '=', company.id), ('partner_id', '=', self.partner_id.id),
                ('move_type', '=', 'in_invoice'), ('state', '!=', 'cancel'), ('ref', '=', cost.invoice_number)]):
            raise UserError(_('A supplier bill with this reference already exists. Use Link existing posted bill.'))
        unit = cost.amount
        if self.tax_ids and not self.tax_ids[0].price_include:
            unit = self.tax_ids.with_company(company).with_context(force_price_include=True, round_base=False).compute_all(
                cost.amount, currency=cost.currency_id, quantity=1, partner=self.partner_id)['total_excluded']
        move = Move.create({'move_type': 'in_invoice', 'company_id': company.id,
            'currency_id': cost.currency_id.id, 'journal_id': self.journal_id.id,
            'partner_id': self.partner_id.id, 'invoice_date': self.invoice_date, 'date': self.date,
            'ref': cost.invoice_number or 'COST/%s' % cost.id, 'abroj_project_id': cost.project_id.id,
            'invoice_line_ids': [Command.create({'name': cost.name, 'account_id': account.id,
                'quantity': 1, 'price_unit': unit, 'tax_ids': [Command.set(self.tax_ids.ids)],
                'analytic_distribution': {str(cost.project_id.account_id.id): 100}})]})
        if cost.currency_id.compare_amounts(move.amount_total, cost.amount):
            raise ValidationError(_('The native bill total does not match the confirmed gross expense. Review the selected taxes.'))
        move._abroj_bind_cost(cost)
        move.action_post()
        if move.date != self.date or cost.currency_id.compare_amounts(move.amount_total, cost.amount):
            raise ValidationError(_('The accounting date or total changed during posting. Review the accounting period and taxes.'))
        return move

    def action_issue(self):
        self.ensure_one()
        require_accountant(self.env)
        if bool(self.cost_id) == bool(self.voucher_id):
            raise ValidationError(_('Choose exactly one source document.'))
        source = self.cost_id or self.voucher_id
        check_source(source)
        with self.env.cr.savepoint():
            if self.cost_id:
                self.env.cr.execute('SELECT id FROM abroj_contracting_cost WHERE id=%s FOR NO KEY UPDATE', [source.id])
                source.invalidate_recordset()
                move = self.env['account.move'].search([('abroj_cost_id', '=', source.id)], limit=1)
                if move:
                    return move_action(move)
                if source.state != 'confirmed':
                    raise UserError(_('Confirm the expense before issuing its accounting entry.'))
                # Touch audit metadata under the lock so Odoo's repeatable-read
                # retry sees the newly linked bill after a concurrent issue.
                # Financial source values remain frozen; failures roll back it.
                super(FrozenDocument, source).write({'write_date': fields.Datetime.now()})
                self._validate_review(source)
                if self.mode == 'existing':
                    move = self.existing_move_id
                    self.env.cr.execute('SELECT id FROM account_move WHERE id=%s FOR NO KEY UPDATE', [move.id or 0])
                    move.invalidate_recordset()
                    self._validate_existing(source, move)
                    move._abroj_bind_cost(source)
                else:
                    move = self._create_bill(source)
                return move_action(move)
            self.env.cr.execute('SELECT id FROM abroj_contracting_voucher WHERE id=%s FOR NO KEY UPDATE', [source.id])
            source.invalidate_recordset()
            if source.payment_id:
                return source.action_open_journal_entry()
            if not source.abroj_can_accounting_approve:
                raise AccessError(_('This voucher is not available for accounting approval.'))
            self._validate_review(source)
            expected_type = 'cash' if source.method == 'cash' else 'bank'
            if self.date != source.date:
                raise ValidationError(_('Keep the accounting date of the issued voucher.'))
            if self.journal_id.type != expected_type or (source.partner_id and source.partner_id != self.partner_id):
                raise ValidationError(_('The journal and accounting partner must match the issued voucher.'))
            super(FrozenDocument, source).write({'journal_id': self.journal_id.id, 'accounting_partner_id': self.partner_id.id})
            source.action_accounting_approve()
            return source.action_open_journal_entry()
