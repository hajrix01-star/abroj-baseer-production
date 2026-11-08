"""One payroll payment screen, orchestrating native payment registration."""
from decimal import Decimal

from odoo import _, api, fields, models, Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.misc import clean_context

from .common import INTERNAL, decimal, money, validate_money, require_manager


def _internal(record):
    return record.env.context.get('baseer_payroll_internal') is INTERNAL


class PayrollSettlement(models.TransientModel):
    _name = 'baseer.payroll.settlement'
    _description = 'Pay Monthly Payroll'

    run_id = fields.Many2one('hr.payslip.run', required=True, readonly=True, ondelete='cascade')
    company_id = fields.Many2one(related='run_id.company_id')
    currency_id = fields.Many2one(related='company_id.currency_id')
    payment_date = fields.Date(required=True, default=fields.Date.context_today)
    # These are required by confirmation and the view; initial creation only needs a run.
    journal_id = fields.Many2one('account.journal', domain="[('company_id', '=', company_id), ('type', 'in', ['bank', 'cash'])]")
    payment_method_line_id = fields.Many2one('account.payment.method.line',
        domain="[('id', 'in', available_payment_method_line_ids)]")
    available_payment_method_line_ids = fields.Many2many('account.payment.method.line', compute='_compute_methods')
    eligible_journal_ids = fields.Many2many('account.journal', compute='_compute_eligible_journals')
    used_treasury_ids = fields.Many2many('account.account', compute='_compute_used_treasuries')
    funding_line_ids = fields.One2many('baseer.payroll.settlement.funding', 'settlement_id', copy=False)
    has_split = fields.Boolean(compute='_compute_used_treasuries')
    line_ids = fields.One2many('baseer.payroll.settlement.line', 'settlement_id', readonly=False, copy=False)
    state = fields.Selection([('draft', 'Draft'), ('done', 'Recorded')], default='draft', required=True, readonly=True)
    payment_ids = fields.Many2many('account.payment', readonly=True, copy=False)
    amount_total = fields.Monetary(compute='_compute_total')
    amount_primary = fields.Monetary(compute='_compute_total')

    @api.depends('journal_id.outbound_payment_method_line_ids.payment_account_id', 'journal_id.default_account_id')
    def _compute_methods(self):
        for wizard in self:
            wizard.available_payment_method_line_ids = wizard._direct_methods(wizard.journal_id)

    @api.model
    def _direct_methods(self, journal):
        return journal.outbound_payment_method_line_ids.filtered(
            lambda method: journal.default_account_id and method.payment_account_id == journal.default_account_id
        )

    @api.depends('company_id', 'currency_id')
    def _compute_eligible_journals(self):
        Journal = self.env['account.journal']
        for wizard in self:
            if not wizard.company_id or not self.env.user.has_group('account.group_account_user'):
                wizard.eligible_journal_ids = Journal
                continue
            journals = Journal.search([
                ('company_id', '=', wizard.company_id.id),
                ('type', 'in', ['bank', 'cash']),
                ('currency_id', 'in', [False, wizard.currency_id.id]),
                ('default_account_id.account_type', '=', 'asset_cash'),
                ('default_account_id.reconcile', '=', False),
                ('default_account_id.active', '=', True),
                ('default_account_id.company_ids', 'in', wizard.company_id.ids),
            ])
            wizard.eligible_journal_ids = journals.filtered(wizard._direct_methods)

    @api.depends('journal_id.default_account_id', 'funding_line_ids.journal_id.default_account_id')
    def _compute_used_treasuries(self):
        for wizard in self:
            wizard.used_treasury_ids = (
                wizard.journal_id.default_account_id | wizard.funding_line_ids.journal_id.default_account_id
            )
            wizard.has_split = bool(wizard.funding_line_ids)

    @api.onchange('journal_id')
    def _onchange_journal(self):
        for wizard in self:
            available = wizard._direct_methods(wizard.journal_id)
            if wizard.payment_method_line_id not in available:
                wizard.payment_method_line_id = available[:1]

    @api.depends('line_ids.amount', 'funding_line_ids.amount')
    def _compute_total(self):
        for wizard in self:
            total = money(sum((decimal(line.amount) for line in wizard.line_ids), Decimal('0')))
            wizard.amount_total = float(total)
            wizard.amount_primary = float(total - sum(decimal(line.amount) for line in wizard.funding_line_ids))

    @api.model_create_multi
    def create(self, vals_list):
        require_manager(self)
        protected = ['state', 'line_ids', 'payment_ids', 'amount_total', 'amount_primary', 'company_id',
                     'currency_id', 'available_payment_method_line_ids', 'funding_line_ids',
                     'eligible_journal_ids', 'used_treasury_ids', 'has_split']
        defaults = self.default_get(protected + ['run_id'])
        runs = self.env['hr.payslip.run']
        for vals in vals_list:
            effective = dict(defaults, **vals)
            if not _internal(self) and (
                effective.get('state', 'draft') != 'draft'
                or any(effective.get(key) for key in protected if key != 'state')
            ):
                raise AccessError(_('Payroll payment rows and results are generated by the payroll workflow.'))
            run = self.env['hr.payslip.run'].browse(effective.get('run_id')).exists()
            if not run or len(run) != 1:
                raise ValidationError(_('Choose a payroll run.'))
            require_manager(run)
            if not run.baseer_managed or run.state != 'done':
                raise UserError(_('Approve the monthly payroll before recording salary payments.'))
            # The payroll period owns the suggested date; an explicit actual date wins.
            vals.setdefault('payment_date', self.env.context.get('default_payment_date', run.date_end))
            runs |= run
        runs.slip_ids._lock()
        records = super().create(vals_list)
        for wizard in records:
            candidates = wizard.run_id.slip_ids.filtered(lambda slip: slip.baseer_managed and slip.state == 'done')
            candidates.invalidate_recordset()
            rows = []
            for slip in candidates.sorted(lambda slip: (slip.employee_id.id, slip.id)):
                remaining = money(slip.baseer_residual)
                if remaining > 0:
                    rows.append(Command.create({'slip_id': slip.id, 'remaining': float(remaining), 'amount': float(remaining)}))
            if not rows:
                raise UserError(_('These salaries are already fully paid.'))
            wizard.with_context(baseer_payroll_internal=INTERNAL).write({'line_ids': rows})
        return records

    def _lock(self):
        require_manager(self)
        # Parent first, then the same sorted employee advisory locks used by native payment registration.
        for wizard in self.sorted('id'):
            self.env.cr.execute('SELECT id FROM baseer_payroll_settlement WHERE id = %s FOR UPDATE', [wizard.id])
            if not self.env.cr.fetchone():
                raise UserError(_('This payment screen has expired. Reopen it from the payroll run.'))
        self.invalidate_recordset()
        self.run_id.slip_ids._lock()

    def write(self, vals):
        if not _internal(self):
            self._lock()
            if self.filtered(lambda wizard: wizard.state == 'done'):
                raise UserError(_('This payroll payment has already been recorded. Open a new payment for the remaining salaries.'))
            if set(vals) - {'payment_date', 'journal_id', 'payment_method_line_id', 'line_ids', 'funding_line_ids'}:
                raise AccessError(_('Payroll payment sources and results cannot be changed manually.'))
            for command in vals.get('funding_line_ids', []):
                if len(command) != 3 or command[0] not in (Command.CREATE, Command.UPDATE, Command.DELETE):
                    raise AccessError(_('Payment sources must be added, edited or removed within this payment screen.'))
                if command[0] != Command.CREATE:
                    source = self.env['baseer.payroll.settlement.funding'].browse(command[1])
                    if source.settlement_id not in self:
                        raise AccessError(_('Payment sources must be added, edited or removed within this payment screen.'))
            # Native editable one2many saves updates through the parent. Only amounts may change.
            for command in vals.get('line_ids', []):
                if len(command) != 3 or command[0] != Command.UPDATE:
                    raise AccessError(_('Employee payment rows cannot be added or removed manually.'))
                line = self.env['baseer.payroll.settlement.line'].browse(command[1])
                if line.settlement_id not in self or set(command[2]) != {'amount'}:
                    raise AccessError(_('Only the amount of an existing employee payment row may be changed.'))
                validate_money(command[2]['amount'])
        return super().write(vals)

    def unlink(self):
        if not self.env.su and not _internal(self):
            self._lock()
            if self.filtered(lambda wizard: wizard.state == 'done'):
                raise UserError(_('Completed payroll payment screens cannot be deleted manually.'))
        return super().unlink()

    def _check_payment_configuration(self, journal, method):
        self.ensure_one()
        company = self.company_id
        if not self.env.user.has_group('account.group_account_user'):
            raise AccessError(_('Accounting access is required to record salary payments.'))
        if not journal or not journal.active or journal.company_id != company or journal.type not in ('bank', 'cash'):
            raise ValidationError(_('Choose a bank or cash journal belonging to this company.'))
        if not method or method not in journal.outbound_payment_method_line_ids:
            raise ValidationError(_('Choose an outbound payment method from the selected journal.'))
        if self.currency_id.decimal_places != 2 or (journal.currency_id and journal.currency_id != self.currency_id):
            raise ValidationError(_('Use a payment journal in the company currency with two decimal places.'))
        treasury = journal.default_account_id
        if not treasury or not treasury.active or treasury.account_type != 'asset_cash' or company not in treasury.company_ids:
            raise ValidationError(_('Configure the bank or cash account on the selected journal.'))
        if treasury.reconcile:
            raise ValidationError(_('Direct salary payment requires a bank or cash account without reconciliation enabled. Ask Accounting to review the journal account setup, or use the standard payment and bank matching workflow.'))
        if method.payment_account_id != treasury:
            raise ValidationError(_('For direct salary payment, configure this payment method to use the journal bank or cash account. An outstanding payment account requires a separate bank matching step.'))
        if not self.payment_date:
            raise ValidationError(_('Choose the payment date.'))
        if company._get_violated_lock_dates(self.payment_date, False, journal):
            raise ValidationError(_('The selected salary payment date is in a locked accounting period.'))

    def _allocation_lines(self):
        self.ensure_one()
        return self.line_ids.sorted(lambda line: (line.employee_id.id, line.slip_id.id))

    def action_confirm(self):
        self.ensure_one()
        self._lock()
        if self.state == 'done':
            return self.run_id._baseer_open_run()
        self._check_payment_configuration(self.journal_id, self.payment_method_line_id)
        if self.run_id.state != 'done' or not self.run_id.baseer_managed:
            raise ValidationError(_('The payroll run must remain approved before payment.'))
        lines = self._allocation_lines()
        lines.invalidate_recordset()
        seen = set()
        amounts = []
        for line in lines:
            slip = line.slip_id
            if slip.id in seen or slip not in self.run_id.slip_ids or slip.company_id != self.company_id or slip.state != 'done' or not slip.baseer_managed:
                raise ValidationError(_('The employee payment rows do not match the approved payroll run.'))
            seen.add(slip.id)
            slip.invalidate_recordset()
            remaining = money(slip.baseer_residual)
            if remaining != money(line.remaining):
                raise ValidationError(_('A salary balance changed after this payment screen was opened. Reopen payment to review the current balances.'))
            amount = validate_money(line.amount)
            if amount > remaining:
                raise ValidationError(_('An employee payment cannot exceed the remaining salary.'))
            if amount and self.payment_date < slip.move_id.date:
                raise ValidationError(_('The salary payment date cannot precede the payroll accounting date.'))
            if amount:
                amounts.append((line, amount, remaining))
        total = sum((amount for _, amount, _ in amounts), Decimal('0'))
        if not total:
            raise ValidationError(_('Enter a positive payment amount for at least one employee.'))

        primary = total
        used_accounts = {self.journal_id.default_account_id.id}
        sources = []
        for source in self.funding_line_ids.sorted('id'):
            journal, method = source.journal_id, source.payment_method_line_id
            self._check_payment_configuration(journal, method)
            treasury_id = journal.default_account_id.id
            if treasury_id in used_accounts:
                raise ValidationError(_('Each payment source must use a different bank or cash account.'))
            used_accounts.add(treasury_id)
            amount = validate_money(source.amount)
            if not amount:
                raise ValidationError(_('Enter a positive amount for every added payment source.'))
            primary -= amount
            sources.append((journal, method, amount))
        if primary <= 0:
            raise ValidationError(_('The added payment amounts must leave a positive amount for the first account.'))
        # Consume sources in entry order while preserving each employee total.
        budgets = iter([(self.journal_id, self.payment_method_line_id, primary), *sources])
        journal, method, budget = next(budgets)
        with self.env.cr.savepoint():
            payments = self.env['account.payment']
            for line, amount, remaining in amounts:
                recorded = self.env['account.payment']
                while amount:
                    if not budget:
                        journal, method, budget = next(budgets)
                    share = min(budget, amount)
                    recorded |= self._record_allocation(line.slip_id, share, remaining, journal, method)
                    budget -= share
                    amount -= share
                    remaining -= share
                line.with_context(baseer_payroll_internal=INTERNAL).write({'payment_ids': [Command.set(recorded.ids)]})
                payments |= recorded
            self.with_context(baseer_payroll_internal=INTERNAL).write({
                'state': 'done', 'payment_ids': [Command.set(payments.ids)],
            })
        return self.run_id._baseer_open_run()

    def _record_allocation(self, slip, amount, remaining, journal, method):
        action = slip.action_pay()
        context = dict(clean_context(self.env.context), **action['context'])
        register = self.env['account.payment.register'].with_context(context).create({
            'payment_date': self.payment_date,
            'journal_id': journal.id,
            'payment_method_line_id': method.id,
            'amount': float(amount),
            'group_payment': True,
            'payment_difference_handling': 'open',
        })
        recorded = register._create_payments()
        slip.invalidate_recordset()
        liquidity = recorded.move_id.line_ids.filtered(lambda line: line.account_id == journal.default_account_id)
        if (not recorded or money(sum((decimal(payment.amount) for payment in recorded), Decimal('0'))) != amount
            or money(slip.baseer_residual) != remaining - amount
            or money(sum((decimal(line.balance) for line in liquidity), Decimal('0'))) != -amount
            or any(payment.company_id != self.company_id or payment.currency_id != self.currency_id
                   or payment.journal_id != journal or payment.payment_method_line_id != method
                   or payment.date != self.payment_date or payment.state != 'paid'
                   or payment.move_id.state != 'posted' or payment.move_id.date != self.payment_date for payment in recorded)):
            raise ValidationError(_('The recorded payment does not match the selected amount, account and date. No payroll payment was committed.'))
        return recorded


class PayrollSettlementLine(models.TransientModel):
    _name = 'baseer.payroll.settlement.line'
    _description = 'Employee Salary Payment'
    _order = 'id'
    # Expire the whole wizard together; dropping a row would change its payment total.
    _transient_max_hours = 0
    _transient_max_count = 0

    settlement_id = fields.Many2one('baseer.payroll.settlement', required=True, readonly=True, ondelete='cascade', index=True)
    slip_id = fields.Many2one('hr.payslip', required=True, readonly=True)
    employee_id = fields.Many2one(related='slip_id.employee_id')
    company_id = fields.Many2one(related='settlement_id.company_id')
    currency_id = fields.Many2one(related='settlement_id.currency_id')
    remaining = fields.Monetary(required=True, readonly=True)
    amount = fields.Monetary(required=True)
    has_split = fields.Boolean(related='settlement_id.has_split')
    allocation_order = fields.Integer(compute='_compute_allocation_order')
    payment_ids = fields.Many2many('account.payment', readonly=True, copy=False)

    @api.depends('settlement_id.line_ids')
    def _compute_allocation_order(self):
        positions = {
            line.id: position
            for wizard in self.settlement_id
            for position, line in enumerate(wizard._allocation_lines(), start=1)
        }
        for line in self:
            line.allocation_order = positions.get(line.id, 0)

    @api.model_create_multi
    def create(self, vals_list):
        if not _internal(self):
            raise AccessError(_('Employee payment rows are generated by the payroll run.'))
        return super().create(vals_list)

    def write(self, vals):
        if not _internal(self):
            self.settlement_id._lock()
            if self.settlement_id.filtered(lambda wizard: wizard.state != 'draft'):
                raise UserError(_('A completed employee payment cannot be changed.'))
            if set(vals) != {'amount'}:
                raise AccessError(_('Only the employee payment amount can be edited.'))
            validate_money(vals['amount'])
        return super().write(vals)

    def unlink(self):
        # Transient vacuum removes complete wizard records through native FK cascade.
        if not self.env.su and not _internal(self):
            raise AccessError(_('Employee payment rows cannot be removed manually.'))
        return super().unlink()


class PayrollSettlementFunding(models.TransientModel):
    _name = 'baseer.payroll.settlement.funding'
    _description = 'Additional Payroll Payment Source'
    _order = 'id'
    # Parent deletion cascades; independent expiry would silently shift the first account's share.
    _transient_max_hours = 0
    _transient_max_count = 0

    settlement_id = fields.Many2one('baseer.payroll.settlement', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='settlement_id.company_id')
    currency_id = fields.Many2one(related='settlement_id.currency_id')
    journal_id = fields.Many2one('account.journal', required=True)
    payment_method_line_id = fields.Many2one('account.payment.method.line', required=True)
    amount = fields.Monetary(required=True)
    available_method_ids = fields.Many2many('account.payment.method.line', compute='_compute_methods')
    allocation_order = fields.Integer(compute='_compute_allocation_order')

    @api.depends('journal_id.outbound_payment_method_line_ids.payment_account_id', 'journal_id.default_account_id')
    def _compute_methods(self):
        for source in self:
            source.available_method_ids = self.env['baseer.payroll.settlement']._direct_methods(source.journal_id)

    @api.onchange('journal_id')
    def _onchange_journal(self):
        for source in self:
            if source.payment_method_line_id not in source.available_method_ids:
                source.payment_method_line_id = source.available_method_ids[:1]

    @api.depends('settlement_id.funding_line_ids')
    def _compute_allocation_order(self):
        positions = {
            line: position
            for wizard in self.settlement_id
            for position, line in enumerate(wizard.funding_line_ids, start=2)
        }
        for line in self:
            line.allocation_order = positions.get(line, 0)

    @api.model
    def _check_draft(self, settlements):
        settlements._lock()
        if settlements.filtered(lambda wizard: wizard.state != 'draft'):
            raise UserError(_('Recorded payroll payment sources cannot be changed.'))

    @api.model_create_multi
    def create(self, vals_list):
        settlements = self.env['baseer.payroll.settlement']
        defaults = self.default_get(['settlement_id', 'amount'])
        for vals in vals_list:
            if set(vals) - {'settlement_id', 'journal_id', 'payment_method_line_id', 'amount'}:
                raise AccessError(_('Only the account, payment method and amount may be set on a payment source.'))
            effective = dict(defaults, **vals)
            parent = settlements.browse(effective.get('settlement_id')).exists()
            if len(parent) != 1:
                raise AccessError(_('Add payment sources from a payroll payment screen.'))
            settlements |= parent
            validate_money(effective.get('amount'))
        self._check_draft(settlements)
        return super().create(vals_list)

    def write(self, vals):
        if set(vals) - {'journal_id', 'payment_method_line_id', 'amount'}:
            raise AccessError(_('Only the account, payment method and amount may be set on a payment source.'))
        self._check_draft(self.settlement_id)
        if 'amount' in vals:
            validate_money(vals['amount'])
        return super().write(vals)

    def unlink(self):
        if not self.env.su:
            self._check_draft(self.settlement_id)
        return super().unlink()
