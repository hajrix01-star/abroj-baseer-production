"""Employee advances. Native receivable residuals are the balance authority."""
from decimal import Decimal
import re
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models, Command
from odoo.exceptions import AccessError, UserError, ValidationError

from .common import INTERNAL, decimal, money, validate_money, require_manager, lock_employee


def _internal(record):
    return record.env.context.get('baseer_payroll_internal') is INTERNAL


def _matches_source_reference(reference, label):
    """Match a complete reference token, never a prefix of another reference."""
    reference = reference or ''
    if reference != reference.strip():
        return False
    if not re.fullmatch(r'[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+', reference):
        return False
    return bool(re.search(r'(?<![A-Za-z0-9_-])' + re.escape(reference) + r'(?![A-Za-z0-9_-])', label or ''))


def _protected_legacy_lines(lines):
    """Test existence only; never expose employee information to the caller."""
    if not lines:
        return False
    if lines.filtered(lambda line: line.move_id.baseer_legacy_origin_move_id):
        return True
    lines.env.cr.execute("SELECT 1 FROM baseer_hr_loan WHERE source_type = 'legacy' AND state IN ('running', 'closed') AND principal_line_id IN %s LIMIT 1", [tuple(lines.ids)])
    return bool(lines.env.cr.fetchone())


class BaseerLoan(models.Model):
    _name = 'baseer.hr.loan'
    _description = 'Employee Advance'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'
    _check_company_auto = True

    name = fields.Char(required=True, default=lambda self: _('Employee advance'), tracking=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    employee_id = fields.Many2one('hr.employee', required=True, check_company=True, index=True, tracking=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    amount = fields.Monetary(required=True, tracking=True)
    date = fields.Date(required=True, default=fields.Date.context_today, tracking=True)
    repayment_mode = fields.Selection([('scheduled', 'Scheduled installments'), ('flexible', 'Flexible repayment')],
                                      required=True, default='scheduled')
    first_due_date = fields.Date(default=fields.Date.context_today)
    installment_count = fields.Integer(default=1, required=True)
    journal_id = fields.Many2one('account.journal', check_company=True,
                                 domain="[('type', 'in', ['bank', 'cash']), ('company_id', '=', company_id)]")
    source_type = fields.Selection([('regular', 'Regular'), ('legacy', 'Migrated opening balance')],
                                   required=True, default='regular', copy=False, index=True)
    source_reference = fields.Char(copy=False, index=True)
    principal_line_id = fields.Many2one('account.move.line', copy=False, ondelete='restrict', check_company=True, index=True)
    historical_original_amount = fields.Monetary(copy=False)
    historical_recovery_amount = fields.Monetary(copy=False)
    historical_recovery_evidence = fields.Text(copy=False, help='Record the dates, amounts and source references of historical recoveries. These are evidence, not new payments.')
    legacy_identity_evidence = fields.Text(copy=False)
    legacy_identity_employee_id = fields.Many2one('hr.employee', readonly=True, copy=False, ondelete='restrict')
    legacy_identity_partner_id = fields.Many2one('res.partner', readonly=True, copy=False, ondelete='restrict')
    legacy_identity_principal_id = fields.Many2one('account.move.line', readonly=True, copy=False, ondelete='restrict')
    legacy_identity_reference = fields.Char(readonly=True, copy=False)
    legacy_identity_confirmed_by = fields.Many2one('res.users', readonly=True, copy=False, ondelete='restrict')
    legacy_identity_confirmed_at = fields.Datetime(readonly=True, copy=False)
    _legacy_reference_active_unique = models.UniqueIndex(
        "(company_id, source_reference) WHERE source_type = 'legacy' AND state != 'cancel' AND source_reference IS NOT NULL",
        'The migration source reference already exists for this company.')
    _legacy_principal_active_unique = models.UniqueIndex(
        "(principal_line_id) WHERE source_type = 'legacy' AND state != 'cancel' AND principal_line_id IS NOT NULL",
        'This receivable is already linked to an advance.')
    state = fields.Selection([('draft', 'Draft'), ('running', 'Outstanding'), ('closed', 'Repaid'), ('cancel', 'Cancelled')],
                             default='draft', required=True, readonly=True, index=True, tracking=True, copy=False)
    move_id = fields.Many2one('account.move', readonly=True, copy=False, check_company=True, ondelete='restrict')
    reversal_move_id = fields.Many2one('account.move', readonly=True, copy=False, ondelete='restrict')
    line_ids = fields.One2many('baseer.hr.loan.line', 'loan_id', readonly=True, copy=False)
    allocation_ids = fields.One2many('baseer.hr.loan.allocation', 'loan_id', readonly=True, copy=False)
    defer_ids = fields.One2many('baseer.hr.loan.defer', 'loan_id', readonly=True, copy=False)
    paid_amount = fields.Monetary(compute='_compute_balances', store=True)
    balance = fields.Monetary(compute='_compute_balances', store=True)
    is_noorix_import_draft = fields.Boolean(compute='_compute_is_noorix_import_draft')

    @api.depends('name')
    def _compute_is_noorix_import_draft(self):
        for loan in self:
            name = loan.name or ''
            loan.is_noorix_import_draft = 'Noorix ADV-' in name and 'DRAFT ONLY' in name

    def init(self):
        super().init()
        # Only early, pre-release candidate builds created these full-table
        # constraints. Replace them on upgrade with the partial unique indexes
        # above; the live predecessor need not have either constraint.
        self.env.cr.execute('ALTER TABLE baseer_hr_loan DROP CONSTRAINT IF EXISTS baseer_hr_loan_legacy_reference_unique')
        self.env.cr.execute('ALTER TABLE baseer_hr_loan DROP CONSTRAINT IF EXISTS baseer_hr_loan_legacy_principal_unique')

    @api.model
    def _assert_legacy_unique_indexes(self):
        """Fail closed if Odoo could not build the migration uniqueness indexes."""
        expected = {
            'baseer_hr_loan_legacy_reference_active_unique': (
                ['company_id', 'source_reference'],
                "source_type='legacy'andstate<>'cancel'andsource_referenceisnotnull"),
            'baseer_hr_loan_legacy_principal_active_unique': (
                ['principal_line_id'],
                "source_type='legacy'andstate<>'cancel'andprincipal_line_idisnotnull"),
        }
        self.env.cr.execute("""
            SELECT c.relname, i.indisunique, i.indisvalid, i.indisready,
                   pg_get_expr(i.indpred, i.indrelid),
                   ARRAY(SELECT pg_get_indexdef(i.indexrelid, n, true)
                         FROM generate_series(1, i.indnkeyatts) AS n ORDER BY n)
              FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
             WHERE i.indrelid = 'baseer_hr_loan'::regclass AND c.relname IN %s
        """, [tuple(expected)])
        rows = {row[0]: row[1:] for row in self.env.cr.fetchall()}
        for name, (columns, predicate) in expected.items():
            row = rows.get(name)
            if not row or not all(row[:3]) or not row[3] or list(row[4]) != columns:
                raise UserError(_('Migrated advance uniqueness protection is unavailable. Contact the system administrator.'))
            actual = re.sub(r'::(?:character varying|varchar|text)', '', row[3], flags=re.IGNORECASE)
            actual = re.sub(r'[\s()"]', '', actual).lower()
            if actual != predicate:
                raise UserError(_('Migrated advance uniqueness protection is unavailable. Contact the system administrator.'))

    @api.constrains('source_reference', 'source_type')
    def _check_source_reference(self):
        for loan in self.filtered(lambda row: row.source_type == 'legacy' and row.source_reference):
            if not re.fullmatch(r'[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+', loan.source_reference):
                raise ValidationError(_('Enter the complete source reference without spaces.'))

    @api.depends('amount', 'principal_line_id.amount_residual', 'move_id.line_ids.amount_residual', 'move_id.line_ids.debit',
                 'move_id.line_ids.account_id.reconcile', 'move_id.state', 'state', 'reversal_move_id')
    def _compute_balances(self):
        for loan in self:
            residual = sum((decimal(line.amount_residual) for line in loan._principal_lines()), Decimal('0'))
            # An unissued draft is a request, not an employee receivable.
            loan.balance = float(money(residual if loan.move_id else 0))
            loan.paid_amount = float(money(decimal(loan.amount) - decimal(loan.balance))) if loan.move_id and not loan.reversal_move_id else 0

    def _principal_lines(self):
        self.ensure_one()
        if self.source_type == 'legacy':
            return self.principal_line_id
        return self.move_id.line_ids.filtered(lambda line: line.debit > 0 and line.account_id.reconcile)

    def _uses_open_repayment(self):
        self.ensure_one()
        return self.source_type == 'legacy' or self.repayment_mode == 'flexible'

    @api.onchange('repayment_mode', 'source_type')
    def _onchange_repayment_mode(self):
        if self._uses_open_repayment():
            self.installment_count = 0
            self.first_due_date = False
        elif not self.first_due_date:
            self.first_due_date = self.date or fields.Date.context_today(self)
            self.installment_count = 1

    @api.constrains('amount', 'installment_count', 'employee_id', 'company_id', 'date', 'first_due_date', 'journal_id', 'repayment_mode', 'source_type')
    def _check_setup(self):
        for loan in self:
            validate_money(loan.amount)
            if decimal(loan.amount) <= 0:
                raise ValidationError(_('The advance amount must be greater than zero.'))
            if loan.employee_id.company_id != loan.company_id:
                raise ValidationError(_('The employee must belong to the advance company.'))
            if loan.source_type == 'regular' and loan.journal_id.company_id != loan.company_id:
                raise ValidationError(_('The employee and payment journal must belong to the advance company.'))
            if loan._uses_open_repayment():
                continue
            if loan.installment_count < 1 or loan.installment_count > 120:
                raise ValidationError(_('Choose between 1 and 120 installments.'))
            if money(decimal(loan.amount) / loan.installment_count) <= 0:
                raise ValidationError(_('The amount is too small for this number of installments.'))
            if not loan.first_due_date or loan.first_due_date < loan.date:
                raise ValidationError(_('The first installment cannot precede the advance date.'))

    @api.model_create_multi
    def create(self, vals_list):
        require_manager(self)
        protected = ('move_id', 'reversal_move_id', 'line_ids', 'allocation_ids', 'defer_ids', 'state', 'paid_amount', 'balance', 'currency_id', 'legacy_identity_employee_id', 'legacy_identity_partner_id', 'legacy_identity_principal_id', 'legacy_identity_reference', 'legacy_identity_confirmed_by', 'legacy_identity_confirmed_at')
        defaults = self.default_get(list(protected) + ['company_id', 'employee_id', 'amount', 'source_type', 'repayment_mode'])
        if any(dict(defaults, **vals).get('source_type', 'regular') == 'legacy' for vals in vals_list):
            self._assert_legacy_unique_indexes()
        for vals in vals_list:
            effective = dict(defaults, **vals)
            if effective.get('source_type') == 'legacy' or effective.get('repayment_mode') == 'flexible':
                vals.update(installment_count=0, first_due_date=False)
            validate_money(effective.get('amount', 0))
            if not _internal(self):
                if effective.get('state', 'draft') != 'draft' or any(effective.get(k) for k in protected if k != 'state'):
                    raise AccessError(_('Advance financial history is managed by the payroll workflow.'))
            company = self.env['res.company'].browse(effective.get('company_id') or self.env.company.id)
            if company != self.env.company:
                raise AccessError(_('You cannot create an advance for this company.'))
            if effective.get('employee_id'):
                lock_employee(self.env, effective['employee_id'], company.id)
        return super().create(vals_list)

    def _lock(self):
        for loan in self.sorted(lambda l: (l.company_id.id, l.employee_id.id, l.id)):
            lock_employee(self.env, loan.employee_id.id, loan.company_id.id)
            self.env.cr.execute('UPDATE baseer_hr_loan SET write_date=write_date WHERE id=%s', [loan.id])
        self.invalidate_recordset()

    def write(self, vals):
        if _internal(self):
            return super().write(vals)
        require_manager(self)
        self._lock()
        if set(vals) & {'move_id', 'reversal_move_id', 'line_ids', 'allocation_ids', 'defer_ids', 'state', 'paid_amount', 'balance', 'currency_id', 'legacy_identity_employee_id', 'legacy_identity_partner_id', 'legacy_identity_principal_id', 'legacy_identity_reference', 'legacy_identity_confirmed_by', 'legacy_identity_confirmed_at'}:
            raise AccessError(_('Advance financial history is managed by the payroll workflow.'))
        business = {'name', 'company_id', 'employee_id', 'amount', 'date', 'first_due_date', 'installment_count', 'journal_id', 'source_type', 'source_reference', 'principal_line_id', 'historical_original_amount', 'historical_recovery_amount', 'historical_recovery_evidence', 'legacy_identity_evidence', 'repayment_mode'}
        if set(vals) & business and any(loan.state != 'draft' for loan in self):
            raise UserError(_('An issued or cancelled advance cannot be edited.'))
        if set(vals) & business and any(loan.legacy_identity_confirmed_by for loan in self):
            raise UserError(_('Confirmed migrated identity cannot be changed. Cancel and prepare a new reviewed record.'))
        if 'name' in vals and self.filtered('is_noorix_import_draft'):
            raise UserError(_('The reference of an imported Noorix advance cannot be renamed.'))
        if 'amount' in vals:
            validate_money(vals['amount'])
        if 'employee_id' in vals or 'company_id' in vals:
            for loan in self:
                if vals.get('company_id', loan.company_id.id) != self.env.company.id:
                    raise AccessError(_('Switch to the company that owns this record.'))
                lock_employee(self.env, vals.get('employee_id', loan.employee_id.id), vals.get('company_id', loan.company_id.id))
        if set(vals) & {'source_type', 'repayment_mode', 'installment_count', 'first_due_date'}:
            open_loans = self.filtered(lambda loan: vals.get('source_type', loan.source_type) == 'legacy'
                                      or vals.get('repayment_mode', loan.repayment_mode) == 'flexible')
            if open_loans:
                super(BaseerLoan, open_loans).write(dict(vals, installment_count=0, first_due_date=False))
            scheduled = self - open_loans
            return super(BaseerLoan, scheduled).write(vals) if scheduled else True
        return super().write(vals)

    def unlink(self):
        require_manager(self)
        self._lock()
        if any(loan.legacy_identity_confirmed_by for loan in self):
            raise UserError(_('An advance with a confirmed historical identity cannot be deleted. Cancel the draft and keep its review history.'))
        if any(loan.move_id or loan.state not in ('draft', 'cancel') for loan in self):
            raise UserError(_('Issued advances and their history cannot be deleted.'))
        return super().unlink()

    def _accounts(self, journal):
        self.ensure_one()
        company = self.company_id
        account = self._principal_lines().account_id if self.move_id else company.baseer_loan_account_id
        if self.currency_id.decimal_places != 2:
            raise UserError(_('Employee advances currently require a currency with two decimal places.'))
        if not account or not account.reconcile or company not in account.company_ids or account.account_type not in ('asset_receivable', 'asset_current', 'asset_non_current'):
            raise UserError(_('Configure a reconcilable employee advance account for this company.'))
        if journal.company_id != company or journal.type not in ('bank', 'cash'):
            raise UserError(_('Choose a bank or cash journal belonging to this company.'))
        cash = journal.default_account_id
        if not cash or cash == account or company not in cash.company_ids or cash.account_type != 'asset_cash':
            raise UserError(_('Configure a separate default treasury account on the payment journal.'))
        if journal.currency_id and journal.currency_id != company.currency_id:
            raise UserError(_('Use a payment journal in the company currency.'))
        if not self.employee_id.work_contact_id:
            raise UserError(_('Set a work contact on the employee before issuing an advance.'))
        return account, cash

    def _make_move(self, amount, date, journal, repayment=False):
        self.ensure_one()
        account, cash = self._accounts(journal)
        date = fields.Date.to_date(date)
        if self.company_id._get_violated_lock_dates(date, False, journal):
            raise UserError(_('This advance transaction falls in a locked accounting period. Choose an open transaction date.'))
        partner = self.employee_id.work_contact_id
        amount = float(money(amount))
        debit, credit = (cash, account) if repayment else (account, cash)
        label = _('%s — %s', self.name, _('Advance repayment') if repayment else _('Advance disbursement'))
        move = self.env['account.move'].with_company(self.company_id).with_context(baseer_payroll_internal=INTERNAL).create({
            'move_type': 'entry', 'date': date, 'journal_id': journal.id, 'company_id': self.company_id.id,
            'ref': label, 'baseer_loan_id': self.id,
            'line_ids': [Command.create({'name': label, 'account_id': debit.id, 'partner_id': partner.id, 'debit': amount}),
                         Command.create({'name': label, 'account_id': credit.id, 'partner_id': partner.id, 'credit': amount})],
        })
        move.action_post()
        if move.date != date:
            raise ValidationError(_('The accounting date changed during posting. The advance transaction was not recorded; choose an open date.'))
        return move

    def action_disburse(self):
        require_manager(self)
        self._lock()
        for loan in self:
            if loan.source_type == 'legacy' or loan.is_noorix_import_draft:
                raise UserError(_('A migrated opening balance cannot be disbursed.'))
            if loan.move_id and loan.state in ('running', 'closed'):
                continue
            if loan.state != 'draft':
                raise UserError(_('Only a draft advance can be issued.'))
            schedule = []
            if not loan._uses_open_repayment():
                amount = money(loan.amount)
                installment = money(amount / loan.installment_count)
                # Allocate cents to the final installment; never lose or create principal.
                last = amount - installment * (loan.installment_count - 1)
                if last <= 0:
                    raise ValidationError(_('Use fewer installments for this advance amount.'))
                schedule = [Command.create({'sequence': i + 1,
                    'amount': float(last if i == loan.installment_count - 1 else installment),
                    'due_date': loan.first_due_date + relativedelta(months=i),
                    'original_due_date': loan.first_due_date + relativedelta(months=i)})
                    for i in range(loan.installment_count)]
            move = loan._make_move(loan.amount, loan.date, loan.journal_id)
            loan.with_context(baseer_payroll_internal=INTERNAL).write({
                'move_id': move.id, 'state': 'running', 'line_ids': schedule})
            if loan._uses_open_repayment():
                loan.employee_id._baseer_invalidate_draft_payroll()
            loan.message_post(body=_('Advance issued. The journal entry records the cash or bank disbursement; no external transfer is sent.'))
        return True

    def action_link_legacy(self):
        """Attach already-posted receivables without creating a treasury move."""
        require_manager(self)
        self._assert_legacy_unique_indexes()
        if not self.env.user.has_group('account.group_account_user'):
            raise AccessError(_('Accounting access is required to link migrated advances.'))
        self._lock()
        for loan in self:
            if loan.company_id != self.env.company or loan.state != 'draft' or loan.source_type != 'legacy' or loan.move_id:
                raise ValidationError(_('Only a draft migrated advance in the active company can be linked.'))
            principal = loan.principal_line_id
            if principal:
                principal.check_access('read')
                origin = principal.move_id
                origin.check_access('read')
                self.env.cr.execute('SELECT id FROM account_move WHERE id=%s FOR UPDATE', [origin.id])
                self.env.cr.execute('SELECT id FROM account_move_line WHERE id=%s FOR UPDATE', [principal.id])
                principal.invalidate_recordset()
                origin.invalidate_recordset()
                if principal.move_id != origin or not loan._valid_legacy_opening(principal):
                    raise ValidationError(_('Select an unallocated opening receivable in the company currency.'))
            original = validate_money(loan.historical_original_amount)
            recovered = validate_money(loan.historical_recovery_amount)
            if (not loan.source_reference or not principal or not principal.partner_id
                    or loan.legacy_identity_employee_id != loan.employee_id
                    or loan.legacy_identity_principal_id != principal
                    or loan.legacy_identity_partner_id != principal.partner_id
                    or loan.legacy_identity_reference != loan.source_reference
                    or not loan.legacy_identity_confirmed_by or not loan.legacy_identity_confirmed_at
                    or not (loan.legacy_identity_evidence or '').strip()
                    or principal.company_id != loan.company_id or principal.move_id.state != 'posted'
                    or principal.account_id != loan.company_id.baseer_loan_account_id
                    or not principal.account_id.reconcile or principal.debit <= 0
                    or not _matches_source_reference(loan.source_reference, principal.name)
                    or money(principal.amount_residual) != money(loan.amount)
                    or original <= 0 or recovered < 0 or (recovered and not (loan.historical_recovery_evidence or '').strip())
                    or money(original - recovered) != money(loan.amount)):
                raise ValidationError(_('The source, historical recovery and posted receivable must match this advance.'))
            loan.with_context(baseer_payroll_internal=INTERNAL).write({'move_id': principal.move_id.id, 'state': 'running',
                'repayment_mode': 'flexible', 'installment_count': 0, 'first_due_date': False})
            # Force a concurrent accounting writer with an older snapshot to retry.
            self.env.cr.execute('UPDATE account_move_line SET write_date=write_date WHERE id=%s', [principal.id])
        self.mapped('employee_id')._baseer_invalidate_draft_payroll()
        return True

    def _valid_legacy_opening(self, principal):
        self.ensure_one()
        origin = principal.move_id
        currency = self.company_id.currency_id
        if (origin.move_type != 'entry' or origin.journal_id.type != 'general'
                or origin.company_id != self.company_id or origin.state != 'posted'
                or origin.baseer_loan_id or origin.baseer_legacy_origin_move_id
                or origin.baseer_payslip_id or origin.reversed_entry_id
                or origin.reversal_move_ids.filtered(lambda move: move.state != 'cancel')
                or principal.matched_credit_ids or principal.matched_debit_ids
                or currency.decimal_places != 2 or principal.currency_id != currency
                or money(principal.amount_residual_currency) != money(principal.amount_residual)
                or self.env['baseer.hr.loan'].sudo().search_count([
                    ('move_id', '=', origin.id), ('source_type', '=', 'regular'),
                ], limit=1)):
            return False
        debits = origin.line_ids.filtered(lambda line: line.debit > 0)
        credits = origin.line_ids.filtered(lambda line: line.credit > 0)
        return (principal in debits and bool(credits)
                and all(line.account_id == self.company_id.baseer_loan_account_id for line in debits)
                and all(line.account_id.account_type in ('equity', 'equity_unaffected') for line in credits))

    def action_attest_legacy_identity(self):
        """Record explicit human review of employee-to-historical-partner evidence."""
        require_manager(self)
        self._assert_legacy_unique_indexes()
        if not self.env.user.has_group('account.group_account_user'):
            raise AccessError(_('Accounting access is required to attest migrated identities.'))
        self._lock()
        for loan in self:
            principal = loan.principal_line_id
            if (loan.source_type != 'legacy' or loan.state != 'draft' or loan.company_id != self.env.company
                    or loan.legacy_identity_confirmed_by or not loan.employee_id or not principal
                    or not principal.partner_id or principal.company_id != loan.company_id
                    or principal.move_id.state != 'posted' or not loan.source_reference
                    or not _matches_source_reference(loan.source_reference, principal.name)
                    or not (loan.legacy_identity_evidence or '').strip()):
                raise ValidationError(_('Review the employee, historical partner, source reference and evidence before attesting.'))
            loan.with_context(baseer_payroll_internal=INTERNAL).write({
                'legacy_identity_employee_id': loan.employee_id.id,
                'legacy_identity_partner_id': principal.partner_id.id,
                'legacy_identity_principal_id': principal.id,
                'legacy_identity_reference': loan.source_reference,
                'legacy_identity_confirmed_by': self.env.user.id,
                'legacy_identity_confirmed_at': fields.Datetime.now(),
            })
        return True

    def action_cancel(self):
        require_manager(self)
        self._lock()
        if any(loan.state != 'draft' or loan.move_id for loan in self):
            raise UserError(_('Only draft advances can be cancelled. Issued advances require a controlled accounting correction.'))
        self.with_context(baseer_payroll_internal=INTERNAL).write({'state': 'cancel'})
        return True

    def action_repay(self):
        self.ensure_one()
        require_manager(self)
        if self.state != 'running':
            raise UserError(_('Only an outstanding advance can be repaid.'))
        default_amount = self.balance
        if self.source_type == 'legacy':
            loans = self.env['baseer.hr.loan'].search([('company_id', '=', self.company_id.id),
                ('employee_id', '=', self.employee_id.id), ('source_type', '=', 'legacy'), ('state', '=', 'running')])
            default_amount = float(loans._open_balance(fields.Date.context_today(self)))
        return {'type': 'ir.actions.act_window', 'name': _('Repay advance'), 'res_model': 'baseer.hr.loan.repay',
                'view_mode': 'form', 'target': 'new', 'context': {'default_loan_id': self.id, 'default_amount': default_amount}}

    def action_view_moves(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Advance accounting history'), 'res_model': 'account.move',
                'view_mode': 'list,form', 'domain': [('id', 'in', (self.move_id | self.allocation_ids.move_id | self.allocation_ids.bridge_move_id).ids)]}

    def _due_lines(self, date_to):
        return self.filtered(lambda l: l.state == 'running' and not l._uses_open_repayment()).line_ids.filtered(
            lambda line: line.due_date <= fields.Date.to_date(date_to) and money(line.balance) > 0
        ).sorted(lambda line: (line.due_date, line.loan_id.date, line.loan_id.id, line.sequence))

    def _due_amount(self, date_to):
        return money(sum((decimal(line.balance) for line in self._due_lines(date_to)), Decimal('0')))

    def _defer_due(self, date_to, reason):
        require_manager(self)
        self._lock()
        if not reason or not reason.strip():
            raise ValidationError(_('Enter a reason for deferring an installment.'))
        for line in self._due_lines(date_to):
            # Arrears deferred during this run must move beyond this run's cutoff.
            anchor = max(line.due_date, fields.Date.to_date(date_to))
            next_date = anchor + relativedelta(months=1)
            self.env['baseer.hr.loan.defer'].with_context(baseer_payroll_internal=INTERNAL).create({
                'loan_id': line.loan_id.id, 'line_id': line.id, 'old_date': line.due_date,
                'new_date': next_date, 'reason': reason.strip(), 'user_id': self.env.user.id,
            })
            line.with_context(baseer_payroll_internal=INTERNAL).write({'due_date': next_date})
            line.loan_id.message_post(body=_('Installment deferred to %s. Reason: %s', next_date, reason))

    def _allocate(self, amount, move, date, kind, payslip=False, cutoff=False):
        """Allocate and reconcile explicitly so one loan never consumes another loan's credit."""
        remaining = money(amount)
        candidates = self._due_lines(cutoff) if cutoff else self.line_ids.filtered(
            lambda line: money(line.balance) > 0).sorted(lambda line: (line.due_date, line.loan_id.id, line.sequence))
        for line in candidates:
            if remaining <= 0:
                break
            loan = line.loan_id
            portion = min(remaining, money(line.balance))
            account = loan._principal_lines().account_id
            credits = move.line_ids.filtered(lambda ml: ml.account_id == account and ml.partner_id == loan.employee_id.work_contact_id and ml.credit > 0)
            needed = portion
            for debit in loan._principal_lines():
                for credit in credits:
                    take = min(needed, money(debit.amount_residual), money(-decimal(credit.amount_residual)))
                    if take <= 0:
                        continue
                    self.env['account.partial.reconcile'].with_context(baseer_payroll_internal=INTERNAL).create({
                        'debit_move_id': debit.id, 'credit_move_id': credit.id, 'amount': float(take),
                        'debit_amount_currency': float(take), 'credit_amount_currency': float(take),
                    })
                    needed -= take
                    if needed <= 0:
                        break
                if needed <= 0:
                    break
            if needed:
                raise ValidationError(_('The advance recovery does not match its receivable journal entry.'))
            self.env['baseer.hr.loan.allocation'].with_context(baseer_payroll_internal=INTERNAL).create({
                'loan_id': loan.id, 'line_id': line.id, 'amount': float(portion), 'date': date,
                'move_id': move.id, 'payslip_id': payslip.id if payslip else False, 'kind': kind,
            })
            remaining -= portion
        if remaining:
            raise ValidationError(_('The repayment exceeds the available installments.'))
        for loan in self:
            loan.invalidate_recordset(['balance', 'paid_amount'])
            if money(loan.balance) == 0 and loan.state == 'running':
                loan.with_context(baseer_payroll_internal=INTERNAL).write({'state': 'closed'})
            recovered = sum((decimal(a.amount) for a in loan.allocation_ids.filtered(lambda a: not a.reversal_move_id)), Decimal('0'))
            if money(recovered) != money(loan.paid_amount):
                raise ValidationError(_('The advance schedule and accounting balance do not agree.'))

    def _open_available(self, cutoff):
        cutoff = fields.Date.to_date(cutoff)
        return self.filtered(lambda loan: loan._uses_open_repayment() and loan.state == 'running'
                             and loan.move_id.state == 'posted' and loan.move_id.date <= cutoff
                             and loan.date <= cutoff and len(loan._principal_lines()) == 1
                             and money(loan._principal_lines().amount_residual) > 0).sorted(
                                 lambda loan: (loan.date, loan.source_reference or '', loan.id))

    def _open_balance(self, cutoff):
        return money(sum((decimal(loan._principal_lines().amount_residual)
                          for loan in self._open_available(cutoff)), Decimal(0)))

    def _allocate_open(self, amount, move, date, kind, payslip=False):
        """Allocate FIFO against exact original lines, bridging different partners atomically."""
        open_loans = self.filtered(lambda loan: loan._uses_open_repayment() and loan.state == 'running')
        if open_loans.filtered(lambda loan: loan.source_type == 'legacy'):
            self._assert_legacy_unique_indexes()
        principals = open_loans.mapped(lambda loan: loan._principal_lines())
        if principals:
            self.env.cr.execute('SELECT id FROM account_move_line WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(principals.ids))])
            principals.invalidate_recordset(['amount_residual'])
            self.invalidate_recordset(['balance'])
        remaining = money(amount)
        allocations = []
        for loan in open_loans._open_available(date):
            portion = min(remaining, money(loan._principal_lines().amount_residual))
            if portion > 0:
                allocations.append((loan, portion))
                remaining -= portion
            if not remaining:
                break
        if remaining:
            raise ValidationError(_('The selected recovery exceeds the migrated advance balance.'))
        if not allocations:
            return
        company = move.company_id
        employee = allocations[0][0].employee_id
        account = allocations[0][0]._principal_lines().account_id
        work_partner = employee.work_contact_id
        if (not work_partner or any(loan.company_id != company or loan.employee_id != employee
                or loan._principal_lines().account_id != account for loan, _portion in allocations)):
            raise ValidationError(_('Migrated advance employee, account or company mismatch.'))
        credits = move.line_ids.filtered(lambda line: line.account_id == account and line.partner_id == work_partner and line.credit > 0)
        allocated_principals = self.browse([loan.id for loan, _portion in allocations]).mapped(lambda loan: loan._principal_lines())
        for line in credits | allocated_principals:
            if (line.currency_id != company.currency_id
                    or money(line.amount_residual_currency) != money(line.amount_residual)):
                raise ValidationError(_('Migrated advance recovery requires journal items in the company currency.'))
        if sum((money(-decimal(line.amount_residual)) for line in credits), Decimal(0)) < money(amount):
            raise ValidationError(_('The recovery entry does not contain the expected employee credit.'))
        mismatched = [(loan, portion) for loan, portion in allocations if loan._principal_lines().partner_id != work_partner]
        if any(loan.source_type != 'legacy' for loan, _portion in mismatched):
            raise ValidationError(_('The advance receivable must match the employee accounting contact.'))
        bridge = self.env['account.move']
        if mismatched:
            bridge_lines = [Command.create({'name': _('Migrated advance partner reclassification'), 'account_id': account.id,
                                           'partner_id': work_partner.id, 'debit': float(sum((p for _l, p in mismatched), Decimal(0)))})]
            for loan, portion in mismatched:
                bridge_lines.append(Command.create({'name': loan.source_reference, 'account_id': account.id,
                                                   'partner_id': loan.principal_line_id.partner_id.id, 'credit': float(portion)}))
            bridge = self.env['account.move'].with_company(company).with_context(baseer_payroll_internal=INTERNAL).create({
                'move_type': 'entry', 'date': date, 'journal_id': move.journal_id.id, 'company_id': company.id,
                'baseer_legacy_origin_move_id': move.id,
                'ref': _('Advance partner reclassification: %s', move.display_name), 'line_ids': bridge_lines})
            bridge.action_post()
            if bridge.date != fields.Date.to_date(date):
                raise ValidationError(_('The reclassification accounting date changed.'))
            bridge_debit = bridge.line_ids.filtered(lambda line: line.account_id == account and line.debit > 0)
            needed = sum((p for _l, p in mismatched), Decimal(0))
            for credit in credits:
                take = min(needed, money(-decimal(credit.amount_residual)))
                if take > 0:
                    self.env['account.partial.reconcile'].with_context(baseer_payroll_internal=INTERNAL).create({
                        'debit_move_id': bridge_debit.id, 'credit_move_id': credit.id, 'amount': float(take),
                        'debit_amount_currency': float(take), 'credit_amount_currency': float(take)})
                    needed -= take
                if not needed:
                    break
            if needed:
                raise ValidationError(_('The payroll recovery could not be reclassified.'))
        for loan, portion in allocations:
            principal = loan._principal_lines()
            if principal.partner_id == work_partner:
                eligible = credits
            else:
                eligible = bridge.line_ids.filtered(lambda line: line.account_id == account and line.credit > 0
                                                    and line.partner_id == principal.partner_id and line.name == loan.source_reference)
            needed = portion
            for credit in eligible:
                take = min(needed, money(principal.amount_residual), money(-decimal(credit.amount_residual)))
                if take > 0:
                    self.env['account.partial.reconcile'].with_context(baseer_payroll_internal=INTERNAL).create({
                        'debit_move_id': principal.id, 'credit_move_id': credit.id, 'amount': float(take),
                        'debit_amount_currency': float(take), 'credit_amount_currency': float(take)})
                    needed -= take
                if not needed:
                    break
            if needed:
                raise ValidationError(_('The migrated receivable could not be reconciled.'))
            self.env['baseer.hr.loan.allocation'].with_context(baseer_payroll_internal=INTERNAL).create({
                'loan_id': loan.id, 'amount': float(portion), 'date': date, 'move_id': move.id,
                'bridge_move_id': bridge.id or False, 'payslip_id': payslip.id if payslip else False, 'kind': kind})
            loan.invalidate_recordset(['balance', 'paid_amount'])
            if money(loan.balance) == 0:
                loan.with_context(baseer_payroll_internal=INTERNAL).write({'state': 'closed'})
        self.mapped('employee_id')._baseer_invalidate_draft_payroll()

    def _apply_payroll(self, slip, move):
        require_manager(self)
        self._lock()
        if not slip.baseer_managed or move.state != 'posted' or move.company_id != slip.company_id:
            raise ValidationError(_('A posted payroll entry is required to recover advances.'))
        if any(l.company_id != slip.company_id or l.employee_id != slip.employee_id for l in self):
            raise ValidationError(_('Advance recovery must match the payslip employee and company.'))
        amount = money(slip.baseer_loan_amount)
        if amount <= 0:
            return
        if self.env['baseer.hr.loan.allocation'].search_count([('payslip_id', '=', slip.id)]):
            raise UserError(_('Advance deductions have already been recorded for this payslip.'))
        legacy_amount = money(slip.baseer_legacy_repayment)
        regular_amount = money(amount - legacy_amount)
        if regular_amount < 0 or regular_amount > self._due_amount(slip.date_to):
            raise ValidationError(_('Advance installments changed. Refresh the draft payroll before approving it.'))
        if self.allocation_ids and slip.date_to < max(self.allocation_ids.mapped('date')):
            raise ValidationError(_('This payroll period precedes an already recorded advance recovery. Process recoveries in date order.'))
        if regular_amount:
            self.filtered(lambda loan: loan.source_type == 'regular')._allocate(regular_amount, move, slip.date_to, 'payroll', payslip=slip, cutoff=slip.date_to)
        if legacy_amount:
            self._allocate_open(legacy_amount, move, slip.date_to, 'payroll', payslip=slip)


class LoanInstallment(models.Model):
    _name = 'baseer.hr.loan.line'
    _description = 'Advance Installment'
    _order = 'due_date, sequence, id'
    _rec_name = 'sequence'

    loan_id = fields.Many2one('baseer.hr.loan', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='loan_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='loan_id.currency_id')
    employee_id = fields.Many2one(related='loan_id.employee_id', store=True, index=True)
    sequence = fields.Integer(required=True)
    amount = fields.Monetary(required=True)
    due_date = fields.Date(required=True, index=True)
    original_due_date = fields.Date(required=True)
    allocation_ids = fields.One2many('baseer.hr.loan.allocation', 'line_id')
    paid_amount = fields.Monetary(compute='_compute_balance', store=True)
    balance = fields.Monetary(compute='_compute_balance', store=True)
    state = fields.Selection([('pending', 'Pending'), ('partial', 'Partially recovered'), ('paid', 'Recovered'), ('cancel', 'Cancelled')], compute='_compute_balance', store=True)

    @api.depends('amount', 'allocation_ids.amount', 'allocation_ids.reversal_move_id', 'loan_id.reversal_move_id')
    def _compute_balance(self):
        for line in self:
            paid = money(sum((decimal(a.amount) for a in line.allocation_ids.filtered(lambda a: not a.reversal_move_id)), Decimal('0')))
            if line.loan_id.reversal_move_id:
                line.paid_amount, line.balance, line.state = 0, 0, 'cancel'
                continue
            balance = money(decimal(line.amount) - paid)
            line.paid_amount, line.balance = float(paid), float(balance)
            line.state = 'paid' if balance == 0 else ('partial' if paid else 'pending')

    @api.model_create_multi
    def create(self, vals_list):
        if not _internal(self):
            raise AccessError(_('Installments are created by the advance workflow.'))
        return super().create(vals_list)

    def write(self, vals):
        if not _internal(self):
            raise AccessError(_('Use the payroll defer action to change an installment.'))
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda l: l.loan_id.move_id):
            raise UserError(_('Issued advance installments cannot be deleted.'))
        if not _internal(self):
            raise AccessError(_('Installments are managed by the advance workflow.'))
        return super().unlink()


class LoanAllocation(models.Model):
    _name = 'baseer.hr.loan.allocation'
    _description = 'Advance Recovery History'
    _order = 'date desc, id desc'

    loan_id = fields.Many2one('baseer.hr.loan', required=True, ondelete='restrict', index=True)
    line_id = fields.Many2one('baseer.hr.loan.line', ondelete='restrict', index=True)
    company_id = fields.Many2one(related='loan_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='loan_id.currency_id')
    amount = fields.Monetary(required=True)
    date = fields.Date(required=True, index=True)
    move_id = fields.Many2one('account.move', required=True, ondelete='restrict', index=True)
    bridge_move_id = fields.Many2one('account.move', readonly=True, ondelete='restrict')
    payslip_id = fields.Many2one('hr.payslip', ondelete='restrict', index=True)
    kind = fields.Selection([('payroll', 'Payroll deduction'), ('repayment', 'Direct repayment')], required=True)
    reversal_move_id = fields.Many2one('account.move', readonly=True, copy=False, ondelete='restrict')

    @api.model_create_multi
    def create(self, vals_list):
        if not _internal(self):
            raise AccessError(_('Advance recoveries are created only by payroll or repayment.'))
        records = super().create(vals_list)
        for row in records:
            if (row.amount <= 0 or row.move_id.company_id != row.company_id
                    or (not row.loan_id._uses_open_repayment() and row.line_id.loan_id != row.loan_id)
                    or (row.loan_id._uses_open_repayment() and row.line_id)):
                raise ValidationError(_('Invalid advance recovery allocation.'))
        return records

    def write(self, vals):
        if _internal(self) and set(vals) == {'reversal_move_id'} and not self.filtered('reversal_move_id'):
            return super().write(vals)
        raise AccessError(_('Advance recovery history is immutable.'))

    def unlink(self):
        raise AccessError(_('Advance recovery history cannot be deleted.'))


class LoanDefer(models.Model):
    _name = 'baseer.hr.loan.defer'
    _description = 'Advance Deferral History'
    _order = 'date desc, id desc'

    loan_id = fields.Many2one('baseer.hr.loan', required=True, ondelete='restrict', index=True)
    line_id = fields.Many2one('baseer.hr.loan.line', required=True, ondelete='restrict')
    company_id = fields.Many2one(related='loan_id.company_id', store=True, index=True)
    old_date = fields.Date(required=True)
    new_date = fields.Date(required=True)
    reason = fields.Char(required=True)
    date = fields.Datetime(default=fields.Datetime.now, required=True)
    user_id = fields.Many2one('res.users', default=lambda self: self.env.user, required=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not _internal(self):
            raise AccessError(_('Deferral history is created by the payroll workflow.'))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_('Deferral history is immutable.'))

    def unlink(self):
        raise AccessError(_('Deferral history cannot be deleted.'))


class LoanRepay(models.TransientModel):
    _name = 'baseer.hr.loan.repay'
    _description = 'Repay Employee Advance'

    loan_id = fields.Many2one('baseer.hr.loan', required=True, readonly=True)
    company_id = fields.Many2one(related='loan_id.company_id')
    currency_id = fields.Many2one(related='loan_id.currency_id')
    amount = fields.Monetary(required=True)
    date = fields.Date(default=fields.Date.context_today, required=True)
    journal_id = fields.Many2one('account.journal', required=True, domain="[('type', 'in', ['bank', 'cash']), ('company_id', '=', company_id)]")
    move_id = fields.Many2one('account.move', readonly=True)
    legacy_is_employee = fields.Boolean(compute='_compute_legacy_is_employee')
    legacy_employee_balance = fields.Monetary(compute='_compute_legacy_is_employee')

    @api.depends('loan_id', 'date')
    def _compute_legacy_is_employee(self):
        for repayment in self:
            loan = repayment.loan_id
            repayment.legacy_is_employee = bool(loan and loan.source_type == 'legacy')
            if loan and repayment.legacy_is_employee:
                loans = self.env['baseer.hr.loan'].search([('company_id', '=', loan.company_id.id),
                    ('employee_id', '=', loan.employee_id.id), ('source_type', '=', 'legacy'), ('state', '=', 'running')])
                repayment.legacy_employee_balance = float(loans._open_balance(repayment.date or fields.Date.context_today(repayment)))
            else:
                repayment.legacy_employee_balance = 0

    @api.model_create_multi
    def create(self, vals_list):
        require_manager(self)
        defaults = self.default_get(['amount', 'move_id'])
        for vals in vals_list:
            effective = dict(defaults, **vals)
            validate_money(effective.get('amount', 0))
            if effective.get('move_id'):
                raise AccessError(_('Repayment results cannot be supplied manually.'))
        return super().create(vals_list)

    def write(self, vals):
        if not _internal(self):
            require_manager(self)
            self.loan_id._lock()
            self.invalidate_recordset()
            if 'loan_id' in vals or 'move_id' in vals or self.filtered('move_id'):
                raise AccessError(_('A completed repayment cannot be changed.'))
            if 'amount' in vals:
                validate_money(vals['amount'])
        return super().write(vals)

    def action_confirm(self):
        self.ensure_one()
        require_manager(self.loan_id)
        loan = self.loan_id
        loan._lock()
        self.invalidate_recordset()
        if self.move_id:
            return {'type': 'ir.actions.act_window_close'}
        amount = money(self.amount)
        legacy_loans = self.env['baseer.hr.loan']
        if loan.source_type == 'legacy':
            legacy_loans = self.env['baseer.hr.loan'].search([('company_id', '=', loan.company_id.id),
                ('employee_id', '=', loan.employee_id.id), ('source_type', '=', 'legacy'), ('state', '=', 'running')])
            legacy_loans._lock()
            available = legacy_loans._open_balance(self.date)
        else:
            available = money(loan.balance)
        if loan.source_type != 'legacy' and loan._uses_open_repayment():
            available = loan._open_balance(self.date)
        if loan.state != 'running' or amount <= 0 or amount > available:
            raise ValidationError(_('Enter a positive repayment no greater than the outstanding advance.'))
        previous_allocations = (legacy_loans or loan).allocation_ids
        if self.date < loan.date or (previous_allocations and self.date < max(previous_allocations.mapped('date'))):
            raise ValidationError(_('The repayment date cannot precede the advance or an already recorded recovery.'))
        move = loan._make_move(amount, self.date, self.journal_id, repayment=True)
        if loan.source_type == 'legacy':
            legacy_loans._allocate_open(amount, move, self.date, 'repayment')
        elif loan._uses_open_repayment():
            loan._allocate_open(amount, move, self.date, 'repayment')
        else:
            loan._allocate(amount, move, self.date, 'repayment')
        self.with_context(baseer_payroll_internal=INTERNAL).write({'move_id': move.id})
        loan.message_post(body=_('Direct repayment recorded: %s. Journal entry: %s', amount, move.display_name))
        return {'type': 'ir.actions.act_window_close'}


class LoanAccountMove(models.Model):
    _inherit = 'account.move'

    baseer_loan_id = fields.Many2one('baseer.hr.loan', readonly=True, copy=False, ondelete='restrict', index=True)
    baseer_legacy_origin_move_id = fields.Many2one('account.move', readonly=True, copy=False, ondelete='restrict', index=True)
    _legacy_origin_unique = models.Constraint('UNIQUE(baseer_legacy_origin_move_id)', 'A partner reclassification already exists for this recovery.')

    @api.model_create_multi
    def create(self, vals_list):
        defaults = self.default_get(['baseer_loan_id', 'baseer_legacy_origin_move_id'])
        if not _internal(self) and any(vals.get('baseer_loan_id', defaults.get('baseer_loan_id')) or vals.get('baseer_legacy_origin_move_id', defaults.get('baseer_legacy_origin_move_id')) for vals in vals_list):
            raise AccessError(_('Advance journal entries must be created through the advance workflow.'))
        return super().create(vals_list)

    def write(self, vals):
        if not _internal(self):
            if {'baseer_loan_id', 'baseer_legacy_origin_move_id'} & set(vals):
                raise AccessError(_('Advance source links cannot be changed.'))
            if 'ref' in vals and _protected_legacy_lines(self.line_ids):
                raise UserError(_('Posted advance entries are protected. Use a controlled advance correction.'))
            if (self.filtered(lambda m: (m.baseer_loan_id or m.baseer_legacy_origin_move_id) and m.state == 'posted') or _protected_legacy_lines(self.line_ids)) and set(vals) & {
                'state', 'date', 'journal_id', 'company_id', 'currency_id', 'line_ids', 'partner_id', 'move_type',
            }:
                raise UserError(_('Posted advance entries are protected. Use a controlled advance correction.'))
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda move: move.baseer_loan_id or move.baseer_legacy_origin_move_id) or _protected_legacy_lines(self.line_ids):
            raise UserError(_('Advance journal entries cannot be deleted.'))
        return super().unlink()

    def _reverse_moves(self, default_values_list=None, cancel=False):
        if self.filtered(lambda move: move.baseer_loan_id or move.baseer_legacy_origin_move_id) or _protected_legacy_lines(self.line_ids):
            raise UserError(_('Advance reversal is not available until its schedule and recoveries can be corrected together.'))
        return super()._reverse_moves(default_values_list=default_values_list, cancel=cancel)


class LoanAccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    @api.model_create_multi
    def create(self, vals_list):
        if not _internal(self):
            default_move = self.default_get(['move_id']).get('move_id')
            move_ids = [v.get('move_id', default_move) for v in vals_list]
            moves = self.env['account.move'].browse([move_id for move_id in move_ids if move_id])
            if (moves.filtered(lambda m: (m.baseer_loan_id or m.baseer_legacy_origin_move_id) and m.state == 'posted')
                    or _protected_legacy_lines(moves.line_ids)):
                raise UserError(_('Lines cannot be added to posted advance entries.'))
        return super().create(vals_list)

    def write(self, vals):
        moves = self.move_id | self.env['account.move'].browse(vals.get('move_id') or [])
        if not _internal(self) and 'name' in vals and _protected_legacy_lines(self):
            raise UserError(_('Posted advance journal lines are protected.'))
        if not _internal(self) and set(vals) & {
            'debit', 'credit', 'balance', 'amount_currency', 'currency_id', 'account_id', 'partner_id', 'move_id',
            'company_id', 'date', 'tax_ids', 'tax_line_id', 'reconciled', 'matched_debit_ids', 'matched_credit_ids',
            'amount_residual', 'amount_residual_currency',
        } and (moves.filtered(lambda move: (move.baseer_loan_id or move.baseer_legacy_origin_move_id) and move.state == 'posted')
               or _protected_legacy_lines(moves.line_ids)):
            raise UserError(_('Posted advance journal lines are protected.'))
        return super().write(vals)

    def unlink(self):
        if (self.filtered(lambda l: l.move_id.baseer_loan_id or l.move_id.baseer_legacy_origin_move_id)
                or _protected_legacy_lines(self.move_id.line_ids)):
            raise UserError(_('Advance journal lines cannot be deleted.'))
        return super().unlink()


class LoanPartialReconcile(models.Model):
    _inherit = 'account.partial.reconcile'

    @api.model_create_multi
    def create(self, vals_list):
        if not _internal(self):
            keys = ('debit_move_id', 'credit_move_id')
            defaults = self.default_get(list(keys))
            ids = [v.get(key, defaults.get(key)) for v in vals_list for key in keys]
            ids = [line_id for line_id in ids if line_id]
            lines = self.env['account.move.line'].browse(ids)
            if lines.filtered(lambda l: l.move_id.baseer_loan_id and l.account_id.reconcile and l.account_id.account_type != 'asset_cash') or _protected_legacy_lines(lines):
                raise UserError(_('Recover employee advances using payroll or the advance repayment action so the installment history remains consistent.'))
        return super().create(vals_list)

    def write(self, vals):
        financial = {'amount', 'debit_amount_currency', 'credit_amount_currency', 'debit_move_id', 'credit_move_id', 'company_id'}
        destinations = self.env['account.move.line'].browse([
            vals[key] for key in ('debit_move_id', 'credit_move_id') if vals.get(key)
        ])
        affected = self.debit_move_id | self.credit_move_id | destinations
        if not _internal(self) and financial.intersection(vals) and (affected.filtered(lambda l: l.move_id.baseer_loan_id and l.account_id.account_type != 'asset_cash') or _protected_legacy_lines(affected)):
            raise UserError(_('Advance recovery reconciliations cannot be changed manually.'))
        return super().write(vals)

    def unlink(self):
        affected = self.debit_move_id | self.credit_move_id
        if not _internal(self) and (affected.filtered(lambda l: l.move_id.baseer_loan_id and l.account_id.account_type != 'asset_cash') or _protected_legacy_lines(affected)):
            raise UserError(_('Advance recovery reconciliations cannot be removed independently of their repayment history.'))
        return super().unlink()
