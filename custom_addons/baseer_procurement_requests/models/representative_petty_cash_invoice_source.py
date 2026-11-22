"""Invoice-level representative petty-cash payment sources.

The first representative-petty-cash release settled an entire purchase batch
from one selected RPC movement.  This extension deliberately leaves those
historical records untouched and introduces the new, invoice-level contract.
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from uuid import uuid4

from dateutil.relativedelta import relativedelta

from psycopg2 import IntegrityError

from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .representative_petty_cash import INTERNAL, MONEY_QUANTUM

# Identity marker cannot be supplied by an RPC caller. It permits Odoo to
# dissolve a full match while unlinking a different, unprotected partial.
_UNLINK_UNRELATED_PARTIAL = object()
_REVERSE_CUSTODY_PARTIAL = object()


class RepresentativePettyCashInvoiceSettlement(models.Model):
    _name = 'baseer.procurement.representative.petty.cash.invoice.settlement'
    _description = 'Representative Petty Cash invoice settlement'
    _order = 'id desc'
    _check_company_auto = True

    company_id = fields.Many2one('res.company', required=True, readonly=True, index=True, ondelete='restrict')
    representative_partner_id = fields.Many2one('res.partner', required=True, readonly=True, index=True,
                                                 ondelete='restrict', check_company=True)
    batch_line_id = fields.Many2one('baseer.purchase.batch.line', required=True, readonly=True, index=True,
                                    ondelete='restrict', check_company=True)
    move_id = fields.Many2one('account.move', required=True, readonly=True, ondelete='restrict', check_company=True)
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)
    amount = fields.Monetary(required=True, readonly=True, currency_field='currency_id')
    state = fields.Selection([('posted', 'Posted')], default='posted', required=True, readonly=True, index=True)

    _sql_constraints = [
        ('baseer_rep_pc_invoice_settlement_line_unique', 'unique(batch_line_id)',
         'A supplier invoice can be settled from Representative Petty Cash only once.'),
    ]

    @api.constrains('company_id', 'representative_partner_id', 'batch_line_id', 'move_id', 'amount')
    def _check_relationships(self):
        for record in self:
            if (record.batch_line_id.company_id != record.company_id
                    or record.move_id.company_id != record.company_id
                    or (record.representative_partner_id.company_id
                        and record.representative_partner_id.company_id != record.company_id)):
                raise ValidationError(_('Representative Petty Cash invoice settlements must remain within one company.'))
            if record.amount <= 0:
                raise ValidationError(_('A Representative Petty Cash settlement amount must be positive.'))

    @api.model_create_multi
    def create(self, vals_list):
        if not (self.env.su and self.env.context.get(INTERNAL)):
            raise AccessError(_('Representative Petty Cash settlements are created only by the approval workflow.'))
        return super().create(vals_list)

    def write(self, vals):
        raise UserError(_('Representative Petty Cash invoice settlements are immutable accounting links.'))

    def unlink(self):
        raise UserError(_('Representative Petty Cash invoice settlements cannot be deleted.'))


class RepresentativeDirectBillSettlement(models.Model):
    _name = 'baseer.procurement.direct.bill.custody.settlement'
    _description = 'Direct supplier bill custody settlement'
    _order = 'id desc'
    _check_company_auto = True

    company_id = fields.Many2one('res.company', required=True, readonly=True, index=True, ondelete='restrict')
    representative_id = fields.Many2one('res.partner', required=True, readonly=True, index=True, ondelete='restrict', check_company=True)
    bill_id = fields.Many2one('account.move', required=True, readonly=True, index=True, ondelete='restrict', check_company=True)
    bill_reference_snapshot = fields.Char(readonly=True, copy=False)
    bill_supplier_snapshot = fields.Char(readonly=True, copy=False)
    bill_invoice_date_snapshot = fields.Date(readonly=True, copy=False)
    bill_accounting_date_snapshot = fields.Date(readonly=True, copy=False)
    move_id = fields.Many2one('account.move', required=True, readonly=True, index=True, ondelete='restrict', check_company=True)
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)
    amount = fields.Monetary(required=True, readonly=True, currency_field='currency_id')
    client_token = fields.Char(required=True, readonly=True, index=True, copy=False)
    created_by_id = fields.Many2one('res.users', required=True, readonly=True, ondelete='restrict')
    state = fields.Selection([('posted', 'Posted')], default='posted', required=True, readonly=True, index=True)

    _sql_constraints = [
        ('direct_custody_token_unique', 'unique(company_id, created_by_id, client_token)', 'This payment request was already recorded.'),
        ('direct_custody_move_unique', 'unique(move_id)', 'A custody settlement entry cannot be reused.'),
    ]

    @api.depends('bill_reference_snapshot', 'amount', 'currency_id', 'representative_id.name')
    def _compute_display_name(self):
        for record in self:
            reference = record.bill_reference_snapshot or _('Supplier bill')
            representative = record.representative_id.display_name or ''
            currency = record.currency_id.name or ''
            record.display_name = '%s — %s — %.2f %s' % (reference, representative, record.amount, currency)

    @api.model_create_multi
    def create(self, vals_list):
        if not (self.env.su and self.env.context.get(INTERNAL)):
            raise AccessError(_('Direct custody settlements are created only by the payment workflow.'))
        return super().create(vals_list)

    def write(self, vals):
        raise UserError(_('Direct custody settlements are immutable accounting links.'))

    def unlink(self):
        raise UserError(_('Direct custody settlements cannot be deleted.'))


    @api.model
    def submit_direct_bill_settlement(self, bill_id, representative_id, amount, settlement_date, client_token):
        advance = self.env['baseer.procurement.representative.advance']
        advance._require_accountant()
        company = self.env.company
        token = (client_token or '').strip()
        if not token or len(token) > 128:
            raise ValidationError(_('Reload the page and try saving again.'))
        try:
            bill_id, representative_id = int(bill_id), int(representative_id)
            day = fields.Date.to_date(settlement_date)
            value = Decimal(str(amount))
            if not day or not value.is_finite() or value <= 0 or value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP) != value:
                raise ValueError()
        except (ValueError, TypeError, InvalidOperation, OverflowError):
            raise ValidationError(_('Enter a valid positive amount with at most two decimal places and a valid date.')) from None
        existing = self.sudo().search([('company_id', '=', company.id), ('created_by_id', '=', self.env.user.id), ('client_token', '=', token)], limit=1)
        if existing:
            if (existing.bill_id.id != bill_id or existing.representative_id.id != representative_id
                    or Decimal(str(existing.amount)).quantize(MONEY_QUANTUM) != value
                    or existing.move_id.date != day):
                raise ValidationError(_('This payment request was already used for different details.'))
            return existing.id

        bill = self.env['account.move'].browse(bill_id).exists()
        representative = self.env['res.partner'].browse(representative_id).exists()
        if len(bill) != 1 or len(representative) != 1:
            raise ValidationError(_('Choose an eligible supplier bill and purchase representative.'))
        # Recording a settlement changes the bill's accounting state; a
        # merely readable invoice is not authority to pay it.
        bill.check_access('write')
        representative.check_access('read')
        if (bill.company_id != company or representative.company_id not in (self.env['res.company'], company)
                or not representative.active or representative.is_company or representative.parent_id
                or not representative.with_company(company).is_purchase_representative):
            raise ValidationError(_('Choose an eligible supplier bill and purchase representative in the active company.'))

        # All custody consumers serialize on company -> representative; lock
        # the bill after that, then re-read the payable and balance.
        advance._baseer_lock_representative_balance(company, representative)
        # A simultaneous retry may have committed while this request waited
        # on the representative lock. Check the token again before testing
        # the now-reduced invoice residual.
        existing = self.sudo().search([('company_id', '=', company.id), ('created_by_id', '=', self.env.user.id), ('client_token', '=', token)], limit=1)
        if existing:
            if (existing.bill_id.id != bill_id or existing.representative_id.id != representative_id
                    or Decimal(str(existing.amount)).quantize(MONEY_QUANTUM) != value
                    or existing.move_id.date != day):
                raise ValidationError(_('This payment request was already used for different details.'))
            return existing.id
        self.env.cr.execute('SELECT id FROM account_move WHERE id = %s FOR UPDATE', [bill.id])
        self.env.cr.execute('SELECT id FROM account_move_line WHERE move_id = %s ORDER BY id FOR UPDATE', [bill.id])
        bill.invalidate_recordset()
        bill.line_ids.invalidate_recordset()
        bill.line_ids.invalidate_recordset(['amount_residual', 'amount_residual_currency', 'reconciled'])
        if bill.state != 'posted' or bill.move_type != 'in_invoice' or bill.currency_id != company.currency_id:
            raise ValidationError(_('Choose a posted supplier bill in the company currency.'))
        if bill.date and day < bill.date:
            raise ValidationError(_('The settlement date cannot precede the bill accounting date.'))
        payable_lines = bill.line_ids.filtered(lambda line: line.account_id.account_type == 'liability_payable')
        if len(payable_lines) != 1:
            raise ValidationError(_('This supplier bill must have one payable line to use Representative Petty Cash.'))
        payable = payable_lines[0]
        if payable.currency_id and payable.currency_id != company.currency_id:
            raise ValidationError(_('The supplier bill payable must use the company currency.'))
        residual = Decimal(str(abs(payable.amount_residual))).quantize(MONEY_QUANTUM)
        if payable.reconciled or payable.amount_residual >= 0 or residual < value:
            raise ValidationError(_('The amount exceeds the unpaid supplier bill balance.'))
        account, journal = company._baseer_representative_petty_cash_ready()
        if ((account.currency_id and account.currency_id != company.currency_id)
                or (journal.currency_id and journal.currency_id != company.currency_id)):
            raise ValidationError(_('Representative Petty Cash settlements require company-currency accounts and journals.'))
        if company._get_violated_lock_dates(day, False, journal):
            raise ValidationError(_('The settlement date is in a locked accounting period.'))
        available = advance._baseer_representative_available_amount(company, representative)
        available_on_date = advance._baseer_representative_available_amount_on(company, representative, day)
        minimum_future = advance._baseer_representative_minimum_balance_from(company, representative, day, available_on_date)
        if value > min(available, available_on_date, minimum_future):
            raise ValidationError(_('The amount exceeds the representative balance available on the settlement date.'))
        label = _('Representative Petty Cash — %(bill)s', bill=bill.name)
        try:
            with self.env.cr.savepoint():
                move = self.env['account.move'].sudo().with_company(company).with_context(**{INTERNAL: True}).create({
                    'move_type': 'entry', 'company_id': company.id, 'journal_id': journal.id,
                    'date': day, 'ref': label,
                    'line_ids': [
                        Command.create({'name': label, 'account_id': payable.account_id.id, 'partner_id': payable.partner_id.id, 'debit': float(value)}),
                        Command.create({'name': label, 'account_id': account.id, 'partner_id': representative.id, 'credit': float(value)}),
                    ],
                })
                move.action_post()
                counterpart = move.line_ids.filtered(lambda line: line.account_id == payable.account_id and line.partner_id == payable.partner_id)
                if len(counterpart) != 1:
                    raise UserError(_('The settlement payable entry is incomplete.'))
                (payable | counterpart).reconcile()
                custody_credit = move.line_ids.filtered(lambda line: line.account_id == account and line.partner_id == representative and line.credit > 0)
                if len(custody_credit) != 1:
                    raise UserError(_('The Representative Petty Cash settlement entry is incomplete.'))
                funding_lines = self.env['account.move.line'].sudo().with_company(company).search([
                    ('company_id', '=', company.id), ('account_id', '=', account.id), ('partner_id', '=', representative.id),
                    ('parent_state', '=', 'posted'), ('date', '<=', day), ('reconciled', '=', False), ('debit', '>', 0),
                    ('baseer_representative_petty_cash_id', '!=', False),
                ], order='date, id')
                open_total = sum((Decimal(str(line.amount_residual)) for line in funding_lines), Decimal('0.00')).quantize(MONEY_QUANTUM)
                if open_total < value:
                    raise ValidationError(_('Open Representative Petty Cash funding is insufficient for reconciliation.'))
                (funding_lines | custody_credit).reconcile()
                custody_credit.invalidate_recordset(['amount_residual', 'reconciled'])
                if Decimal(str(abs(custody_credit.amount_residual))).quantize(MONEY_QUANTUM) != Decimal('0.00'):
                    raise ValidationError(_('Open Representative Petty Cash funding is insufficient for reconciliation.'))
                settlement = self.sudo().with_context(**{INTERNAL: True}).create({
                    'company_id': company.id, 'representative_id': representative.id, 'bill_id': bill.id,
                    'bill_reference_snapshot': bill.ref or bill.name,
                    'bill_supplier_snapshot': bill.partner_id.display_name,
                    'bill_invoice_date_snapshot': bill.invoice_date,
                    'bill_accounting_date_snapshot': bill.date,
                    'move_id': move.id, 'amount': float(value), 'client_token': token, 'created_by_id': self.env.user.id,
                })
                return settlement.id
        except IntegrityError:
            existing = self.sudo().search([('company_id', '=', company.id), ('created_by_id', '=', self.env.user.id), ('client_token', '=', token)], limit=1)
            if existing and existing.bill_id.id == bill_id and existing.representative_id.id == representative_id and Decimal(str(existing.amount)).quantize(MONEY_QUANTUM) == value and existing.move_id.date == day:
                return existing.id
            raise ValidationError(_('This payment request was already recorded.')) from None


class RepresentativeDirectBillSettlementReversalService(models.Model):
    _inherit = 'baseer.procurement.direct.bill.custody.settlement'

    @api.model
    def reverse_direct_bill_settlement(self, settlement_id, reason, reversal_date):
        advance = self.env['baseer.procurement.representative.advance']
        advance._require_accountant()
        reason = (reason or '').strip()
        try:
            day = fields.Date.to_date(reversal_date)
        except (ValueError, TypeError):
            day = False
        settlement = self.sudo().browse(int(settlement_id)).exists()
        if not settlement or settlement.company_id != self.env.company or not reason or len(reason) > 500 or not day:
            raise ValidationError(_('Choose a valid settlement, reason, and reversal date.'))
        bill = self.env['account.move'].browse(settlement.bill_id.id)
        bill.check_access('write')
        company, representative = settlement.company_id, settlement.representative_id
        advance._baseer_lock_representative_balance(company, representative)
        self.env.cr.execute('SELECT id FROM account_move WHERE id IN %s ORDER BY id FOR UPDATE', [tuple([bill.id, settlement.move_id.id])])
        self.env.cr.execute('SELECT id FROM account_move_line WHERE move_id IN %s ORDER BY id FOR UPDATE', [tuple([bill.id, settlement.move_id.id])])
        if self.env['baseer.procurement.direct.bill.custody.reversal'].sudo().search_count([('settlement_id', '=', settlement.id)]):
            raise ValidationError(_('This settlement was already reversed.'))
        move = settlement.move_id
        if day < move.date or day > fields.Date.context_today(self) or company._get_violated_lock_dates(day, False, move.journal_id):
            raise ValidationError(_('Choose an unlocked reversal date on or after the settlement and no later than today.'))
        lines = move.line_ids
        payable = lines.filtered(lambda line: line.account_id.account_type == 'liability_payable' and line.debit > 0)
        custody = lines.filtered(lambda line: line.account_id == company._baseer_representative_petty_cash_ready()[0] and line.credit > 0)
        if len(lines) != 2 or len(payable) != 1 or len(custody) != 1:
            raise ValidationError(_('This settlement has mixed accounting entries and cannot be reversed automatically.'))
        partials = (payable.matched_debit_ids | payable.matched_credit_ids | custody.matched_debit_ids | custody.matched_credit_ids)
        # The narrow initial workflow accepts only one supplier match and one
        # funding match, with no other matches in either full reconciliation.
        payable_matches = payable.matched_debit_ids | payable.matched_credit_ids
        custody_matches = custody.matched_debit_ids | custody.matched_credit_ids
        other_matches = partials.full_reconcile_id.partial_reconcile_ids - partials
        taxes = bill.invoice_line_ids.tax_ids
        has_cash_basis = any(tax.tax_exigibility == 'on_payment' for tax in taxes)
        if (len(payable_matches) != 1 or len(custody_matches) != 1 or other_matches or has_cash_basis
                or any(p.exchange_move_id for p in partials)
                or bill.currency_id != company.currency_id
                or any(not company.currency_id.is_zero(p.amount - settlement.amount) for p in partials)
                or payable_matches.credit_move_id.move_id != bill):
            raise ValidationError(_('This settlement has mixed reconciliations, cash-basis taxes, or exchange differences and cannot be reversed automatically.'))
        funding = custody_matches.debit_move_id
        bill_payable = payable_matches.credit_move_id
        self.env.cr.execute('SELECT id FROM account_move_line WHERE id = %s FOR UPDATE', [funding.id])
        funding.invalidate_recordset(['matched_debit_ids', 'matched_credit_ids', 'amount_residual'])
        if (not funding.baseer_representative_petty_cash_id or funding.partner_id != representative
                or (custody_matches - (funding.matched_debit_ids | funding.matched_credit_ids))
                or ((funding.matched_debit_ids | funding.matched_credit_ids) - custody_matches)
                or ((bill_payable.matched_debit_ids | bill_payable.matched_credit_ids) - payable_matches)):
            raise ValidationError(_('This settlement has mixed accounting entries and cannot be reversed automatically.'))
        old_bill_residual = abs(bill_payable.amount_residual)
        old_funding_residual = funding.amount_residual
        with self.env.cr.savepoint():
            partials.sudo().with_context(_baseer_reverse_custody_partial=_REVERSE_CUSTODY_PARTIAL).unlink()
            label = _('Reversal of Representative Petty Cash settlement — %(bill)s', bill=settlement.bill_reference_snapshot or '')
            reverse_move = self.env['account.move'].sudo().with_company(company).create({
                'move_type': 'entry', 'company_id': company.id, 'journal_id': move.journal_id.id, 'date': day, 'ref': label,
                'line_ids': [Command.create({'name': label, 'account_id': line.account_id.id, 'partner_id': line.partner_id.id,
                                            'debit': line.credit, 'credit': line.debit}) for line in lines],
            })
            reverse_move.action_post()
            (payable | reverse_move.line_ids.filtered(lambda line: line.account_id == payable.account_id)).reconcile()
            (custody | reverse_move.line_ids.filtered(lambda line: line.account_id == custody.account_id)).reconcile()
            bill_payable.invalidate_recordset(['amount_residual'])
            funding.invalidate_recordset(['amount_residual'])
            currency = company.currency_id
            if (not currency.is_zero(abs(bill_payable.amount_residual) - old_bill_residual - settlement.amount)
                    or not currency.is_zero(funding.amount_residual - old_funding_residual - settlement.amount)):
                raise ValidationError(_('The settlement could not be reversed safely.'))
            return self.env['baseer.procurement.direct.bill.custody.reversal'].sudo().with_context(**{INTERNAL: True}).create({
                'settlement_id': settlement.id, 'company_id': company.id, 'representative_id': representative.id,
                'move_id': reverse_move.id, 'amount': settlement.amount, 'reason': reason, 'created_by_id': self.env.user.id,
            }).id


class RepresentativeDirectBillSettlementReversal(models.Model):
    _name = 'baseer.procurement.direct.bill.custody.reversal'
    _description = 'Direct supplier bill custody settlement reversal'
    _check_company_auto = True

    settlement_id = fields.Many2one('baseer.procurement.direct.bill.custody.settlement', required=True, readonly=True, index=True, ondelete='restrict', check_company=True)
    company_id = fields.Many2one('res.company', required=True, readonly=True, index=True, ondelete='restrict')
    representative_id = fields.Many2one('res.partner', required=True, readonly=True, index=True, ondelete='restrict', check_company=True)
    move_id = fields.Many2one('account.move', required=True, readonly=True, ondelete='restrict', check_company=True)
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)
    amount = fields.Monetary(required=True, readonly=True, currency_field='currency_id')
    reason = fields.Char(required=True, readonly=True)
    created_by_id = fields.Many2one('res.users', required=True, readonly=True, ondelete='restrict')
    _sql_constraints = [('direct_custody_one_reversal', 'unique(settlement_id)', 'This settlement was already reversed.')]

    @api.model_create_multi
    def create(self, vals_list):
        if not (self.env.su and self.env.context.get(INTERNAL)):
            raise AccessError(_('Direct custody reversals are created only by the reversal workflow.'))
        return super().create(vals_list)

    def write(self, vals):
        raise UserError(_('Direct custody reversals cannot be modified.'))

    def unlink(self):
        raise UserError(_('Direct custody reversals cannot be deleted.'))


class RepresentativePettyCashAggregate(models.Model):
    _inherit = 'baseer.procurement.representative.advance'

    @api.model
    def _baseer_grouped_amount(self, model, domain):
        """Read a monetary total across supported Odoo aggregation formats."""
        grouped = model.sudo().read_group(domain, ['amount:sum'], [])
        if not grouped:
            return 0.0
        # Odoo 19 returns ``amount`` for an aggregate in some model/query
        # combinations, while earlier versions return ``amount_sum``.
        return grouped[0].get('amount_sum', grouped[0].get('amount', 0.0)) or 0.0

    @api.model
    def _baseer_representative_available_amount_on(self, company, representative, day):
        domain = [('company_id', '=', company.id), ('representative_partner_id', '=', representative.id), ('state', '=', 'posted')]
        def total(model, criteria):
            return Decimal(str(self._baseer_grouped_amount(model, criteria))).quantize(MONEY_QUANTUM)
        funded = total(self, domain + [('movement_date', '<=', day), ('movement_type', '=', 'funding')])
        returned = total(self, domain + [('movement_date', '<=', day), ('movement_type', 'in', ['return', 'reversal'])])
        historical = total(self.env['baseer.procurement.representative.advance.settlement'], [
            ('company_id', '=', company.id), ('advance_id.representative_partner_id', '=', representative.id),
            ('state', '=', 'posted'), ('move_id.date', '<=', day),
        ])
        batch_invoice = total(self.env['baseer.procurement.representative.petty.cash.invoice.settlement'], domain + [('move_id.date', '<=', day)])
        direct = total(self.env['baseer.procurement.direct.bill.custody.settlement'], [
            ('company_id', '=', company.id), ('representative_id', '=', representative.id),
            ('state', '=', 'posted'), ('move_id.date', '<=', day),
        ])
        direct_reversed = total(self.env['baseer.procurement.direct.bill.custody.reversal'], [
            ('company_id', '=', company.id), ('representative_id', '=', representative.id), ('move_id.date', '<=', day),
        ])
        return funded - returned - historical - batch_invoice - direct + direct_reversed

    @api.model
    def _baseer_representative_minimum_balance_from(self, company, representative, day, opening):
        """Protect every later accounting day when recording a backdated payment."""
        self.flush_model(['company_id', 'representative_partner_id', 'movement_type', 'movement_date', 'amount', 'state'])
        self.env['baseer.procurement.representative.advance.settlement'].flush_model(['company_id', 'advance_id', 'move_id', 'amount', 'state'])
        self.env['baseer.procurement.representative.petty.cash.invoice.settlement'].flush_model(['company_id', 'representative_partner_id', 'move_id', 'amount', 'state'])
        self.env['baseer.procurement.direct.bill.custody.settlement'].flush_model(['company_id', 'representative_id', 'move_id', 'amount', 'state'])
        self.env['baseer.procurement.direct.bill.custody.reversal'].flush_model(['company_id', 'representative_id', 'move_id', 'amount'])
        self.env['account.move'].flush_model(['company_id', 'date'])
        self.env.cr.execute('''
            WITH activity AS (
                SELECT a.movement_date AS day, CASE WHEN a.movement_type = 'funding' THEN a.amount::numeric ELSE -a.amount::numeric END AS amount
                  FROM baseer_procurement_representative_advance a
                 WHERE a.company_id = %(company)s AND a.representative_partner_id = %(partner)s
                   AND a.state = 'posted' AND a.movement_date > %(day)s
                UNION ALL
                SELECT m.date, -s.amount::numeric FROM baseer_procurement_representative_advance_settlement s
                  JOIN baseer_procurement_representative_advance a ON a.id = s.advance_id AND a.company_id = s.company_id
                  JOIN account_move m ON m.id = s.move_id AND m.company_id = s.company_id
                 WHERE s.company_id = %(company)s AND a.representative_partner_id = %(partner)s AND s.state = 'posted' AND m.date > %(day)s
                UNION ALL
                SELECT m.date, -s.amount::numeric FROM baseer_procurement_representative_petty_cash_invoice_settlement s
                  JOIN account_move m ON m.id = s.move_id AND m.company_id = s.company_id
                 WHERE s.company_id = %(company)s AND s.representative_partner_id = %(partner)s AND s.state = 'posted' AND m.date > %(day)s
                UNION ALL
                SELECT m.date, -s.amount::numeric FROM baseer_procurement_direct_bill_custody_settlement s
                  JOIN account_move m ON m.id = s.move_id AND m.company_id = s.company_id
                 WHERE s.company_id = %(company)s AND s.representative_id = %(partner)s AND s.state = 'posted' AND m.date > %(day)s
                UNION ALL
                SELECT m.date, r.amount::numeric FROM baseer_procurement_direct_bill_custody_reversal r
                  JOIN account_move m ON m.id = r.move_id AND m.company_id = r.company_id
                 WHERE r.company_id = %(company)s AND r.representative_id = %(partner)s AND m.date > %(day)s
            ), daily AS (SELECT day, SUM(amount) AS amount FROM activity GROUP BY day),
            balances AS (SELECT SUM(amount) OVER (ORDER BY day ROWS UNBOUNDED PRECEDING) AS change FROM daily)
            SELECT LEAST(0, COALESCE(MIN(change), 0)) FROM balances
        ''', {'company': company.id, 'partner': representative.id, 'day': day})
        return (opening + Decimal(str(self.env.cr.fetchone()[0]))).quantize(MONEY_QUANTUM)

    @api.model
    def action_open_direct_bill_custody_payment(self, representative_id=False):
        self._require_accountant()
        context = {'default_company_id': self.env.company.id}
        if representative_id:
            context['default_representative_id'] = int(representative_id)
        view = self.env.ref('baseer_procurement_requests.view_direct_bill_custody_wizard_form')
        return {'type': 'ir.actions.act_window', 'name': _('Pay supplier bill from Representative Petty Cash'),
                'res_model': 'baseer.procurement.direct.bill.custody.wizard', 'views': [(view.id, 'form')],
                'target': 'new', 'context': context}

    @api.model
    def action_open_direct_bill_custody_reversal(self, settlement_id):
        self._require_accountant()
        settlement = self.env['baseer.procurement.direct.bill.custody.settlement'].sudo().browse(int(settlement_id)).exists()
        if not settlement or settlement.company_id != self.env.company:
            raise ValidationError(_('Choose a valid settlement, reason, and reversal date.'))
        view = self.env.ref('baseer_procurement_requests.view_direct_bill_custody_reversal_wizard_form')
        return {'type': 'ir.actions.act_window', 'name': _('Reverse supplier bill custody payment'),
                'res_model': 'baseer.procurement.direct.bill.custody.reversal.wizard', 'views': [(view.id, 'form')],
                'target': 'new', 'context': {'default_settlement_id': settlement.id}}

    @api.model
    def _baseer_lock_representative_balance(self, company, representative):
        """Use the same mutex for funding, returns, and invoice settlement."""
        self.env.cr.execute('SELECT id FROM res_company WHERE id = %s FOR UPDATE', [company.id])
        self.env.cr.execute('UPDATE res_company SET id = id WHERE id = %s', [company.id])
        self.env.cr.execute('SELECT id FROM res_partner WHERE id = %s FOR UPDATE', [representative.id])
        self.env.cr.execute('UPDATE res_partner SET id = id WHERE id = %s', [representative.id])

    @api.model
    def _baseer_representative_available_amount(self, company, representative):
        """Return the server-authoritative balance for one company/representative."""
        company = company.exists()
        representative = representative.exists()
        if len(company) != 1 or len(representative) != 1:
            raise ValidationError(_('Choose one company and one purchase representative.'))
        movement_domain = [
            ('company_id', '=', company.id),
            ('representative_partner_id', '=', representative.id),
            ('state', '=', 'posted'),
        ]
        funded = self._baseer_grouped_amount(
            self, movement_domain + [('movement_type', '=', 'funding')],
        )
        returned = self._baseer_grouped_amount(
            self, movement_domain + [('movement_type', '=', 'return')],
        )
        reversed_funding = self._baseer_grouped_amount(
            self, movement_domain + [('movement_type', '=', 'reversal')],
        )
        # Pre-existing batch-level settlements still consume the representative
        # balance, but no new workflow creates them.
        historical = self._baseer_grouped_amount(
            self.env['baseer.procurement.representative.advance.settlement'], [
            ('company_id', '=', company.id),
            ('advance_id.representative_partner_id', '=', representative.id),
            ('state', '=', 'posted'),
        ])
        settled = self._baseer_grouped_amount(
            self.env['baseer.procurement.representative.petty.cash.invoice.settlement'], [
            ('company_id', '=', company.id),
            ('representative_partner_id', '=', representative.id),
            ('state', '=', 'posted'),
        ])
        direct = self._baseer_grouped_amount(self.env['baseer.procurement.direct.bill.custody.settlement'], [
            ('company_id', '=', company.id), ('representative_id', '=', representative.id), ('state', '=', 'posted'),
        ])
        direct_reversed = self._baseer_grouped_amount(self.env['baseer.procurement.direct.bill.custody.reversal'], [
            ('company_id', '=', company.id), ('representative_id', '=', representative.id),
        ])
        return (Decimal(str(funded)) - Decimal(str(returned)) - Decimal(str(reversed_funding))
                - Decimal(str(historical)) - Decimal(str(settled)) - Decimal(str(direct)) + Decimal(str(direct_reversed))).quantize(MONEY_QUANTUM)

    @api.model
    def submit_funding(self, request_id, payment_journal_id, representative_partner_id, amount, client_token,
                       movement_date=False, external_reference=False, transfer_proof=False, transfer_proof_filename=False):
        representative = self.env['res.partner'].browse(int(representative_partner_id)).exists()
        if representative:
            self._baseer_lock_representative_balance(self.env.company, representative)
        return super().submit_funding(
            request_id, payment_journal_id, representative_partner_id, amount, client_token, movement_date,
            external_reference, transfer_proof, transfer_proof_filename,
        )

    @api.model
    def submit_return(self, origin_id, payment_journal_id, amount, client_token, movement_date=False, external_reference=False):
        self._require_accountant()
        token = (client_token or '').strip()
        if not token:
            raise ValidationError(_('Reload the page and try saving again.'))
        company = self.env.company
        existing = self.search([
            ('company_id', '=', company.id), ('created_by_id', '=', self.env.user.id), ('client_token', '=', token),
        ], limit=1)
        if existing:
            return existing.id
        origin = self._lock_advance(int(origin_id))
        payment_journal = self.env['account.journal'].browse(int(payment_journal_id)).exists()
        if (not origin or origin.company_id != company or origin.movement_type != 'funding' or not payment_journal):
            raise ValidationError(_('Choose an open original movement and a company payment point.'))
        company._baseer_validate_representative_petty_cash_payment_point(payment_journal)
        try:
            return_amount = Decimal(str(amount))
        except (InvalidOperation, TypeError):
            raise ValidationError(_('Enter a valid amount.')) from None
        if return_amount <= 0 or return_amount.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP) != return_amount:
            raise ValidationError(_('The amount must be positive and use no more than two decimal places.'))
        self._baseer_lock_representative_balance(company, origin.representative_partner_id)
        available = self._baseer_representative_available_amount(company, origin.representative_partner_id)
        if return_amount > available:
            raise ValidationError(_('Returned cash cannot exceed the available Representative Petty Cash balance.'))
        values = {
            'company_id': company.id, 'movement_type': 'return',
            'representative_partner_id': origin.representative_partner_id.id, 'origin_id': origin.id,
            'payment_journal_id': payment_journal.id, 'movement_date': movement_date or fields.Date.context_today(self),
            'amount': amount, 'external_reference': (external_reference or '').strip() or False,
            'client_token': token, 'created_by_id': self.env.user.id,
        }
        try:
            with self.env.cr.savepoint():
                return self._create_and_post(values).id
        except IntegrityError:
            existing = self.search([
                ('company_id', '=', company.id), ('created_by_id', '=', self.env.user.id), ('client_token', '=', token),
            ], limit=1)
            if existing:
                return existing.id
            raise ValidationError(_('This external transfer reference was already used for the selected payment point.'))

    @api.model
    def submit_aggregate_return(self, representative_partner_id, payment_journal_id, amount, client_token,
                                movement_date=False, external_reference=False):
        """Return money against a representative's aggregate balance.

        New returns deliberately do not force the accountant to pick one old
        funding movement: invoice settlements already consume the aggregate
        balance across that representative's funding history.  Legacy linked
        returns remain supported by ``submit_return`` for historical records.
        """
        self._require_accountant()
        token = (client_token or '').strip()
        if not token:
            raise ValidationError(_('Reload the page and try saving again.'))
        company = self.env.company
        existing = self.search([
            ('company_id', '=', company.id), ('created_by_id', '=', self.env.user.id), ('client_token', '=', token),
        ], limit=1)
        if existing:
            return existing.id
        representative = self.env['res.partner'].browse(int(representative_partner_id)).exists()
        payment_journal = self.env['account.journal'].browse(int(payment_journal_id)).exists()
        scoped = representative.with_company(company)
        if (not representative or not payment_journal or not representative.active or representative.is_company
                or representative.parent_id or not scoped.is_purchase_representative
                or (representative.company_id and representative.company_id != company)):
            raise ValidationError(_('Choose an active purchase representative and a company payment point.'))
        company._baseer_validate_representative_petty_cash_payment_point(payment_journal)
        try:
            return_amount = Decimal(str(amount))
        except (InvalidOperation, TypeError):
            raise ValidationError(_('Enter a valid amount.')) from None
        if return_amount <= 0 or return_amount.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP) != return_amount:
            raise ValidationError(_('The amount must be positive and use no more than two decimal places.'))
        self._baseer_lock_representative_balance(company, representative)
        if return_amount > self._baseer_representative_available_amount(company, representative):
            raise ValidationError(_('Returned cash cannot exceed the available Representative Petty Cash balance.'))
        values = {
            'company_id': company.id, 'movement_type': 'return',
            'representative_partner_id': representative.id, 'payment_journal_id': payment_journal.id,
            'movement_date': movement_date or fields.Date.context_today(self), 'amount': amount,
            'external_reference': (external_reference or '').strip() or False,
            'client_token': token, 'created_by_id': self.env.user.id,
        }
        try:
            with self.env.cr.savepoint():
                return self._create_and_post(values).id
        except IntegrityError:
            existing = self.search([
                ('company_id', '=', company.id), ('created_by_id', '=', self.env.user.id), ('client_token', '=', token),
            ], limit=1)
            if existing:
                return existing.id
            raise ValidationError(_('This external transfer reference was already used for the selected payment point.'))

    def _dashboard_carryovers(self, company, representative_id, month_start):
        """Calculate, never post, up to 60 nonzero month-end balances.

        Show up to twelve source months before the selected month. An opening
        aggregate retains older activity, while the returned rows stay bounded.
        Company is always explicit: this SQL is used only after dashboard access
        checks, and never crosses the active company even for shared contacts.
        """
        self.flush_model(['company_id', 'representative_partner_id', 'movement_type', 'movement_date', 'amount', 'state'])
        self.env['baseer.procurement.representative.advance.settlement'].flush_model(
            ['company_id', 'advance_id', 'move_id', 'amount', 'state'])
        self.env['baseer.procurement.representative.petty.cash.invoice.settlement'].flush_model(
            ['company_id', 'representative_partner_id', 'move_id', 'amount', 'state'])
        self.env['baseer.procurement.direct.bill.custody.settlement'].flush_model(
            ['company_id', 'representative_id', 'move_id', 'amount', 'state'])
        self.env['baseer.procurement.direct.bill.custody.reversal'].flush_model(
            ['company_id', 'representative_id', 'move_id', 'amount'])
        self.env['account.move'].flush_model(['company_id', 'date'])
        params = {
            'company': company.id,
            'partner': int(representative_id) if representative_id else 0,
            'before': month_start,
            'window_start': month_start - relativedelta(months=12),
        }
        self.env.cr.execute('''
            WITH activity AS (
                SELECT a.representative_partner_id AS partner_id, a.movement_date AS day,
                       CASE WHEN a.movement_type = 'funding' THEN a.amount::numeric
                            ELSE -a.amount::numeric END AS amount
                  FROM baseer_procurement_representative_advance a
                 WHERE a.company_id = %(company)s AND a.state = 'posted'
                   AND a.movement_date < %(before)s
                   AND (%(partner)s = 0 OR a.representative_partner_id = %(partner)s)
                UNION ALL
                SELECT a.representative_partner_id, m.date, -s.amount::numeric
                  FROM baseer_procurement_representative_advance_settlement s
                  JOIN baseer_procurement_representative_advance a ON a.id = s.advance_id AND a.company_id = s.company_id
                  JOIN account_move m ON m.id = s.move_id AND m.company_id = s.company_id
                 WHERE s.company_id = %(company)s AND s.state = 'posted' AND m.date < %(before)s
                   AND (%(partner)s = 0 OR a.representative_partner_id = %(partner)s)
                UNION ALL
                SELECT s.representative_partner_id, m.date, -s.amount::numeric
                  FROM baseer_procurement_representative_petty_cash_invoice_settlement s
                  JOIN account_move m ON m.id = s.move_id AND m.company_id = s.company_id
                 WHERE s.company_id = %(company)s AND s.state = 'posted' AND m.date < %(before)s
                   AND (%(partner)s = 0 OR s.representative_partner_id = %(partner)s)
                UNION ALL
                SELECT s.representative_id, m.date, -s.amount::numeric
                  FROM baseer_procurement_direct_bill_custody_settlement s
                  JOIN account_move m ON m.id = s.move_id AND m.company_id = s.company_id
                 WHERE s.company_id = %(company)s AND s.state = 'posted' AND m.date < %(before)s
                   AND (%(partner)s = 0 OR s.representative_id = %(partner)s)
                UNION ALL
                SELECT r.representative_id, m.date, r.amount::numeric
                  FROM baseer_procurement_direct_bill_custody_reversal r
                  JOIN account_move m ON m.id = r.move_id AND m.company_id = r.company_id
                 WHERE r.company_id = %(company)s AND m.date < %(before)s
                   AND (%(partner)s = 0 OR r.representative_id = %(partner)s)
            ), totals AS (
                SELECT partner_id,
                       CASE WHEN day < %(window_start)s THEN NULL
                            ELSE date_trunc('month', day)::date END AS month,
                       SUM(amount) AS amount
                  FROM activity GROUP BY partner_id, 2
            ), partners AS (
                SELECT DISTINCT partner_id FROM totals
            ), grid AS (
                SELECT p.partner_id, months.month::date AS month,
                       COALESCE(old.amount, 0) AS opening, COALESCE(current.amount, 0) AS change
                  FROM partners p
                 CROSS JOIN generate_series(%(window_start)s::date, %(before)s::date - interval '1 month', interval '1 month') months(month)
                  LEFT JOIN totals old ON old.partner_id = p.partner_id AND old.month IS NULL
                  LEFT JOIN totals current ON current.partner_id = p.partner_id AND current.month = months.month::date
            ), balances AS (
                SELECT partner_id, month,
                       ROUND(opening + SUM(change) OVER (PARTITION BY partner_id ORDER BY month), 2) AS amount
                  FROM grid
            )
            SELECT partner_id, month, amount FROM balances
             WHERE amount <> 0 ORDER BY month DESC, partner_id LIMIT 60
        ''', params)
        rows = self.env.cr.fetchall()
        names = {p.id: p.display_name for p in self.env['res.partner'].sudo().browse([row[0] for row in rows]).exists()}
        return [{
            'representative_id': partner_id, 'representative_name': names.get(partner_id, ''),
            'source_month': fields.Date.to_string(month),
            'destination_month': fields.Date.to_string(month + relativedelta(months=1)),
            'amount': float(amount),
        } for partner_id, month, amount in rows]

    @api.model
    def dashboard_daily_movements(self, representative_id=False, month_start=False,
                                  search='', movement_type='', offset=0):
        """Search the visible monthly ledger without changing financial totals."""
        self._require_reader()
        if not isinstance(search, str) or len(search) > 200:
            raise ValidationError(_('Search must contain at most 200 characters.'))
        if movement_type not in ('', 'funding', 'purchase', 'purchase_reversal', 'return', 'reversal'):
            raise ValidationError(_('Invalid movement type.'))
        if type(offset) is not int or not 0 <= offset <= 100000:
            raise ValidationError(_('Invalid movement page.'))
        start, end = self._month_range(month_start)
        movements, truncated = self._dashboard_daily_movements(
            self.env.company, representative_id, start, end,
            search=search.strip(), movement_type=movement_type, offset=offset,
        )
        return {'daily_movements': movements, 'daily_movements_truncated': truncated}

    def _dashboard_daily_movements(self, company, representative_id, start, end,
                                   search='', movement_type='', offset=0):
        """Return a bounded, stable view of all representative activity sources."""
        self.flush_model(['company_id', 'representative_partner_id', 'procurement_request_id', 'movement_type', 'movement_date', 'name', 'amount', 'state'])
        self.env['baseer.procurement.representative.advance.settlement'].flush_model(
            ['company_id', 'advance_id', 'batch_id', 'move_id', 'amount', 'state'])
        self.env['baseer.procurement.representative.petty.cash.invoice.settlement'].flush_model(
            ['company_id', 'representative_partner_id', 'batch_line_id', 'move_id', 'amount', 'state'])
        self.env['baseer.procurement.direct.bill.custody.settlement'].flush_model(
            ['company_id', 'representative_id', 'bill_id', 'bill_reference_snapshot', 'move_id', 'amount', 'state'])
        self.env['baseer.procurement.direct.bill.custody.reversal'].flush_model(
            ['company_id', 'representative_id', 'settlement_id', 'move_id', 'amount'])
        self.env['baseer.purchase.batch'].flush_model(['company_id', 'name'])
        self.env['baseer.purchase.batch.line'].flush_model(['company_id', 'supplier_ref'])
        self.env['baseer.procurement.request'].flush_model(['company_id', 'name'])
        self.env['res.partner'].flush_model(['name'])
        self.env['account.move'].flush_model(['company_id', 'date'])
        can_see_purchase_reference = (
            self.env.user.has_group('baseer_procurement_requests.group_procurement_accountant')
            or self.env.user.has_group('baseer_procurement_requests.group_procurement_manager')
            or self.env.user.has_group('base.group_system')
        )
        params = {'company': company.id, 'partner': int(representative_id) if representative_id else 0,
                  'start': start, 'end': end, 'search': search, 'movement_type': movement_type,
                  'offset': offset, 'can_see_purchase_reference': can_see_purchase_reference}
        self.env.cr.execute('''
            SELECT activity.source, activity.id, activity.day, activity.movement_type, activity.partner_id,
                   activity.amount, activity.reference, activity.request_id, activity.request_name FROM (
                SELECT 'movement' AS source, a.id, a.movement_date AS day, a.movement_type,
                       a.representative_partner_id AS partner_id, a.amount, a.name AS reference,
                       r.id AS request_id, r.name AS request_name
                  FROM baseer_procurement_representative_advance a
                  LEFT JOIN baseer_procurement_request r ON r.id = a.procurement_request_id AND r.company_id = a.company_id
                 WHERE a.company_id = %(company)s AND a.state = 'posted'
                   AND a.movement_date >= %(start)s AND a.movement_date < %(end)s
                   AND (%(partner)s = 0 OR a.representative_partner_id = %(partner)s)
                UNION ALL
                SELECT 'historical', s.id, m.date, 'purchase', a.representative_partner_id, s.amount, b.name, NULL::integer, NULL::varchar
                  FROM baseer_procurement_representative_advance_settlement s
                  JOIN baseer_procurement_representative_advance a ON a.id = s.advance_id AND a.company_id = s.company_id
                  JOIN baseer_purchase_batch b ON b.id = s.batch_id AND b.company_id = s.company_id
                  JOIN account_move m ON m.id = s.move_id AND m.company_id = s.company_id
                 WHERE s.company_id = %(company)s AND s.state = 'posted'
                   AND m.date >= %(start)s AND m.date < %(end)s
                   AND (%(partner)s = 0 OR a.representative_partner_id = %(partner)s)
                UNION ALL
                SELECT 'invoice', s.id, m.date, 'purchase', s.representative_partner_id, s.amount, l.supplier_ref, NULL::integer, NULL::varchar
                  FROM baseer_procurement_representative_petty_cash_invoice_settlement s
                  JOIN baseer_purchase_batch_line l ON l.id = s.batch_line_id AND l.company_id = s.company_id
                  JOIN account_move m ON m.id = s.move_id AND m.company_id = s.company_id
                 WHERE s.company_id = %(company)s AND s.state = 'posted'
                   AND m.date >= %(start)s AND m.date < %(end)s
                   AND (%(partner)s = 0 OR s.representative_partner_id = %(partner)s)
                UNION ALL
                SELECT 'direct_invoice', s.id, m.date, 'purchase', s.representative_id, s.amount,
                       s.bill_reference_snapshot, NULL::integer, NULL::varchar
                  FROM baseer_procurement_direct_bill_custody_settlement s
                  JOIN account_move b ON b.id = s.bill_id AND b.company_id = s.company_id
                  JOIN account_move m ON m.id = s.move_id AND m.company_id = s.company_id
                 WHERE s.company_id = %(company)s AND s.state = 'posted'
                   AND m.date >= %(start)s AND m.date < %(end)s
                   AND (%(partner)s = 0 OR s.representative_id = %(partner)s)
                UNION ALL
                SELECT 'direct_reversal', r.id, m.date, 'purchase_reversal', r.representative_id, r.amount,
                       s.bill_reference_snapshot, NULL::integer, NULL::varchar
                  FROM baseer_procurement_direct_bill_custody_reversal r
                  JOIN baseer_procurement_direct_bill_custody_settlement s ON s.id = r.settlement_id AND s.company_id = r.company_id
                  JOIN account_move b ON b.id = s.bill_id AND b.company_id = r.company_id
                  JOIN account_move m ON m.id = r.move_id AND m.company_id = r.company_id
                 WHERE r.company_id = %(company)s AND m.date >= %(start)s AND m.date < %(end)s
                   AND (%(partner)s = 0 OR r.representative_id = %(partner)s)
            ) activity
            LEFT JOIN res_partner p ON p.id = activity.partner_id
            WHERE (%(movement_type)s = '' OR activity.movement_type = %(movement_type)s)
              AND (%(search)s = '' OR
                   strpos(lower(COALESCE(p.name, '')), lower(%(search)s)) > 0 OR
                   strpos(lower(COALESCE(activity.request_name, '')), lower(%(search)s)) > 0 OR
                   strpos(lower(activity.day::text), lower(%(search)s)) > 0 OR
                   strpos(lower(activity.amount::text), lower(%(search)s)) > 0 OR
                   ((activity.movement_type NOT IN ('purchase', 'purchase_reversal') OR %(can_see_purchase_reference)s)
                    AND strpos(lower(COALESCE(activity.reference, '')), lower(%(search)s)) > 0))
            ORDER BY activity.day DESC, activity.source DESC, activity.id DESC LIMIT 101 OFFSET %(offset)s
        ''', params)
        rows = self.env.cr.fetchall()
        visible = rows[:100]
        names = {p.id: p.display_name for p in self.env['res.partner'].sudo().browse([row[4] for row in visible]).exists()}
        reversed_ids = set(self.env['baseer.procurement.direct.bill.custody.reversal'].sudo().search([
            ('company_id', '=', company.id), ('settlement_id', 'in', [row[1] for row in visible if row[0] == 'direct_invoice']),
        ]).mapped('settlement_id').ids)
        return [{
            'key': '%s:%s' % (source, record_id), 'date': fields.Date.to_string(day), 'type': movement_type,
            'funding_id': record_id if source == 'movement' and movement_type == 'funding' else False,
            'direct_settlement_id': record_id if source == 'direct_invoice' and record_id not in reversed_ids else False,
            'representative_id': partner_id, 'representative_name': names.get(partner_id, ''),
            'amount': float(amount),
            'reference': (reference or '') if movement_type not in ('purchase', 'purchase_reversal') or can_see_purchase_reference else '',
            'request_id': request_id or False, 'request_name': request_name or '',
        } for source, record_id, day, movement_type, partner_id, amount, reference, request_id, request_name in visible], len(rows) > 100

    def _dashboard_data(self, representative_id=False, month_start=False):
        data = super()._dashboard_data(representative_id, month_start)
        company = self.env.company
        start, end = self._month_range(data['month_start'])
        # Totals come from all posted sources, not the first 100 displayed rows.
        # Historical batch-level settlements and newer invoice-level ones are
        # distinct, immutable records; both consume the same company balance.
        def total(model, domain):
            return Decimal(str(self._baseer_grouped_amount(model, domain))).quantize(MONEY_QUANTUM)

        movement = [('company_id', '=', company.id), ('state', '=', 'posted')]
        historical = [('company_id', '=', company.id), ('state', '=', 'posted')]
        invoices = [('company_id', '=', company.id), ('state', '=', 'posted')]
        direct_invoices = [('company_id', '=', company.id), ('state', '=', 'posted')]
        direct_reversals = [('company_id', '=', company.id)]
        if representative_id:
            partner_id = int(representative_id)
            movement.append(('representative_partner_id', '=', partner_id))
            historical.append(('advance_id.representative_partner_id', '=', partner_id))
            invoices.append(('representative_partner_id', '=', partner_id))
            direct_invoices.append(('representative_id', '=', partner_id))
            direct_reversals.append(('representative_id', '=', partner_id))

        def period(date_domain):
            movement_dates = [('movement_date', op, date) for op, date in date_domain]
            settlement_dates = [('move_id.date', op, date) for op, date in date_domain]
            funded = total(self, movement + movement_dates + [('movement_type', '=', 'funding')])
            returned = total(self, movement + movement_dates + [('movement_type', '=', 'return')])
            reversed_funding = total(self, movement + movement_dates + [('movement_type', '=', 'reversal')])
            settled = (
                total(self.env['baseer.procurement.representative.advance.settlement'], historical + settlement_dates)
                + total(self.env['baseer.procurement.representative.petty.cash.invoice.settlement'], invoices + settlement_dates)
                + total(self.env['baseer.procurement.direct.bill.custody.settlement'], direct_invoices + settlement_dates)
                - total(self.env['baseer.procurement.direct.bill.custody.reversal'], direct_reversals + settlement_dates)
            )
            return funded, returned, settled, reversed_funding

        previous_funded, previous_returned, previous_settled, previous_reversed = period([('<', start)])
        funded, returned, settled, reversed_funding = period([('>=', start), ('<', end)])
        opening = previous_funded - previous_returned - previous_settled - previous_reversed
        closing = opening + funded - returned - settled - reversed_funding
        data['summary'].update({
            'opening': float(opening.quantize(MONEY_QUANTUM)),
            'funded': float(funded), 'returned': float(returned), 'settled': float(settled), 'reversed': float(reversed_funding),
            'closing': float(closing.quantize(MONEY_QUANTUM)),
            'remaining': float(closing.quantize(MONEY_QUANTUM)),
        })
        if representative_id:
            representative = self.env['res.partner'].browse(int(representative_id)).exists()
            data['summary']['available'] = float(self._baseer_representative_available_amount(company, representative)) if representative else 0.0
        data['carryovers'] = self._dashboard_carryovers(company, representative_id, start)
        data['daily_movements'], data['daily_movements_truncated'] = self._dashboard_daily_movements(
            company, representative_id, start, end,
        )
        return data


class DirectBillCustodyWizard(models.TransientModel):
    _name = 'baseer.procurement.direct.bill.custody.wizard'
    _description = 'Pay a supplier bill from Representative Petty Cash'

    bill_id = fields.Many2one('account.move', string='Supplier bill', required=True, check_company=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, readonly=True)
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)
    representative_id = fields.Many2one('res.partner', string='Purchase representative', required=True, check_company=True)
    amount = fields.Monetary(required=True, currency_field='currency_id')
    available_amount = fields.Monetary(compute='_compute_available_amount', currency_field='currency_id')
    settlement_date = fields.Date(required=True, default=fields.Date.context_today)
    client_token = fields.Char(required=True, default=lambda self: str(uuid4()), readonly=True)

    @api.depends('representative_id', 'company_id')
    def _compute_available_amount(self):
        advance = self.env['baseer.procurement.representative.advance']
        for wizard in self:
            wizard.available_amount = 0
            if wizard.company_id == self.env.company and wizard.representative_id:
                advance._require_accountant()
                rep = wizard.representative_id
                if not rep.company_id or rep.company_id == wizard.company_id:
                    wizard.available_amount = float(advance._baseer_representative_available_amount(wizard.company_id, rep))

    @api.onchange('bill_id')
    def _onchange_bill_id(self):
        if self.bill_id:
            self.amount = self.bill_id.amount_residual

    def action_settle(self):
        self.ensure_one()
        self.env['baseer.procurement.representative.advance']._require_accountant()
        if self.company_id != self.env.company:
            raise ValidationError(_('Switch to the settlement company before paying.'))
        self.env['baseer.procurement.direct.bill.custody.settlement'].submit_direct_bill_settlement(
            self.bill_id.id, self.representative_id.id, self.amount, self.settlement_date, self.client_token,
        )
        return {'type': 'ir.actions.act_window_close'}


class DirectBillCustodyReversalWizard(models.TransientModel):
    _name = 'baseer.procurement.direct.bill.custody.reversal.wizard'
    _description = 'Reverse a direct supplier bill custody payment'

    settlement_id = fields.Many2one('baseer.procurement.direct.bill.custody.settlement', required=True, readonly=True)
    reason = fields.Char(required=True)
    reversal_date = fields.Date(required=True, default=fields.Date.context_today)

    def action_reverse(self):
        self.ensure_one()
        self.env['baseer.procurement.direct.bill.custody.settlement'].reverse_direct_bill_settlement(
            self.settlement_id.id, self.reason, self.reversal_date,
        )
        return {'type': 'ir.actions.act_window_close'}


class DirectBillCustodyMove(models.Model):
    _inherit = 'account.move'

    def _baseer_direct_custody_guarded(self):
        """Keep journal entries immutable; unlock a bill only when fully reversed."""
        if not self:
            return False
        Settlement = self.env['baseer.procurement.direct.bill.custody.settlement'].sudo()
        Reversal = self.env['baseer.procurement.direct.bill.custody.reversal'].sudo()
        if Settlement.search_count([('move_id', 'in', self.ids)]) or Reversal.search_count([('move_id', 'in', self.ids)]):
            return True
        settlements = Settlement.search([('bill_id', 'in', self.ids)])
        reversed_ids = Reversal.search([('settlement_id', 'in', settlements.ids)]).mapped('settlement_id').ids
        return bool(settlements - Settlement.browse(reversed_ids))

    def action_open_representative_custody_payment(self):
        self.ensure_one()
        self.check_access('read')
        advance = self.env['baseer.procurement.representative.advance']
        advance._require_accountant()
        if self.company_id != self.env.company or self.state != 'posted' or self.move_type != 'in_invoice' or self.amount_residual <= 0:
            raise ValidationError(_('Choose an unpaid posted supplier bill in the active company.'))
        action = advance.action_open_direct_bill_custody_payment()
        action['context'].update({'default_bill_id': self.id, 'default_amount': self.amount_residual})
        return action

    def _baseer_assert_custody_lifecycle(self):
        super()._baseer_assert_custody_lifecycle()
        if self._baseer_direct_custody_guarded():
            raise UserError(_('A bill or entry settled from Representative Petty Cash cannot be reset, cancelled, reversed, or deleted.'))

    def write(self, vals):
        protected = {'state', 'company_id', 'currency_id', 'partner_id', 'move_type', 'date', 'invoice_date',
                     'journal_id', 'line_ids', 'invoice_line_ids'}
        if self and protected.intersection(vals) and self._baseer_direct_custody_guarded():
            raise UserError(_('A bill or entry settled from Representative Petty Cash cannot be modified.'))
        if self and {'company_id', 'move_type'}.intersection(vals) and self.env['baseer.procurement.direct.bill.custody.settlement'].sudo().search_count([('bill_id', 'in', self.ids)]):
            raise UserError(_('The company and type of a bill with custody history cannot be modified.'))
        return super().write(vals)

    def unlink(self):
        if self and self.env['baseer.procurement.direct.bill.custody.settlement'].sudo().search_count([('bill_id', 'in', self.ids)]):
            raise UserError(_('A bill with custody settlement history cannot be deleted.'))
        return super().unlink()


class DirectBillCustodyMoveLine(models.Model):
    _inherit = 'account.move.line'

    def write(self, vals):
        protected = {'move_id', 'account_id', 'partner_id', 'debit', 'credit', 'balance', 'currency_id', 'amount_currency', 'date',
                     'tax_ids', 'tax_line_id', 'tax_repartition_line_id', 'quantity', 'price_unit', 'discount',
                     'analytic_distribution', 'display_type', 'product_id'}
        if self and protected.intersection(vals) and self.move_id._baseer_direct_custody_guarded():
            raise UserError(_('Accounting lines of a custody-settled bill cannot be modified.'))
        return super().write(vals)

    def unlink(self):
        if self and self.move_id._baseer_direct_custody_guarded():
            raise UserError(_('Accounting lines of a custody-settled bill cannot be deleted.'))
        return super().unlink()


class DirectBillCustodyReconciliation(models.Model):
    _inherit = 'account.partial.reconcile'

    def _baseer_check_direct_custody_reconciliation(self):
        move_ids = (self.debit_move_id | self.credit_move_id).move_id.ids
        if move_ids and self.env['baseer.procurement.direct.bill.custody.settlement'].sudo().search_count([('move_id', 'in', move_ids)]):
            raise UserError(_('A custody settlement reconciliation cannot be removed or modified.'))

    def unlink(self):
        if not (self.env.su and self.env.context.get('_baseer_reverse_custody_partial') is _REVERSE_CUSTODY_PARTIAL):
            self._baseer_check_direct_custody_reconciliation()
        scoped = self.with_context(_baseer_unlink_unrelated_partial=_UNLINK_UNRELATED_PARTIAL)
        return super(DirectBillCustodyReconciliation, scoped).unlink()

    def write(self, vals):
        if vals:
            self._baseer_check_direct_custody_reconciliation()
        return super().write(vals)


class DirectBillCustodyFullReconciliation(models.Model):
    _inherit = 'account.full.reconcile'

    def _baseer_check_direct_custody_full_reconciliation(self):
        moves = self.reconciled_line_ids.move_id | (self.partial_reconcile_ids.debit_move_id | self.partial_reconcile_ids.credit_move_id).move_id
        if moves and self.env['baseer.procurement.direct.bill.custody.settlement'].sudo().search_count([('move_id', 'in', moves.ids)]):
            raise UserError(_('A custody settlement reconciliation cannot be removed or modified.'))

    def unlink(self):
        if self.env.context.get('_baseer_unlink_unrelated_partial') is not _UNLINK_UNRELATED_PARTIAL:
            self._baseer_check_direct_custody_full_reconciliation()
        return super().unlink()

    def write(self, vals):
        if {'partial_reconcile_ids', 'reconciled_line_ids'}.intersection(vals):
            self._baseer_check_direct_custody_full_reconciliation()
        return super().write(vals)


class BaseerPurchaseBatchLine(models.Model):
    _inherit = 'baseer.purchase.batch.line'

    payment_source_type = fields.Selection([
        ('payment_method', 'Payment point'),
        ('representative_petty_cash', 'Representative Petty Cash'),
        ('credit', 'Credit'),
    ], string='Payment source', default='payment_method', copy=False)
    representative_petty_cash_representative_id = fields.Many2one(
        'res.partner', string='Representative Petty Cash', ondelete='restrict',
        check_company=True, index=True, copy=False,
    )
    representative_petty_cash_available_amount = fields.Monetary(
        string='Available Representative Petty Cash', compute='_compute_representative_petty_cash_available_amount',
        currency_field='currency_id', readonly=True,
    )
    representative_petty_cash_invoice_settlement_id = fields.Many2one(
        'baseer.procurement.representative.petty.cash.invoice.settlement',
        string='Representative Petty Cash settlement', readonly=True, copy=False,
        ondelete='restrict', check_company=True,
    )

    @api.model
    def payment_settlement_choices(self, company_id):
        """Return one safe, presentation-only choice list for invoice settlement.

        A payment-method line and a purchasing representative belong to two
        different Odoo models.  The UI may present them together, but the
        stored financial contract remains explicit and is still verified by
        ``_baseer_validate_payment_source`` before saving and approving.
        """
        can_use_representative = self.env.user.has_group(
            'baseer_procurement_requests.group_procurement_accountant'
        )
        # Branch operators already create company-scoped purchase drafts and
        # can save their cash/bank selection. Listing those existing payment
        # points must not require invoice-posting or representative-balance rights.
        can_submit_draft = (
            self.env.user.has_group('baseer_procurement_requests.group_procurement_cashier')
            and self.env['baseer.purchase.batch'].check_access_rights('create', raise_exception=False)
        )
        if not (can_use_representative or can_submit_draft
                or self.env.user.has_group('account.group_account_invoice')):
            raise AccessError(_('Only an invoice accountant can choose an invoice settlement method.'))
        try:
            company_id = int(company_id)
        except (TypeError, ValueError):
            raise ValidationError(_('Choose the active batch company.')) from None
        company = self.env['res.company'].browse(company_id).exists()
        if len(company) != 1 or company != self.env.company or company not in self.env.user.company_ids:
            raise AccessError(_('Switch to an authorized batch company before choosing a settlement method.'))

        methods = self.env['account.payment.method.line'].search([
            ('company_id', '=', company.id), ('payment_type', '=', 'outbound'), ('code', '=', 'manual'),
            ('journal_id.active', '=', True), ('journal_id.type', 'in', ['bank', 'cash']),
            ('payment_account_id.account_type', '=', 'asset_cash'),
        ], order='journal_id, id').filtered(lambda method: (
            method.payment_account_id == method.journal_id.default_account_id
            and (not method.journal_id.currency_id or method.journal_id.currency_id == company.currency_id)
        ))
        representatives = self.env['res.partner']
        if can_use_representative:
            representatives = representatives.with_company(company).search([
                ('is_purchase_representative', '=', True), ('company_id', 'in', [False, company.id]),
                ('is_company', '=', False), ('parent_id', '=', False), ('active', '=', True),
            ], order='name, id')
        Advance = self.env['baseer.procurement.representative.advance']
        return {
            'payment_points': [{
                'id': method.id,
                'name': method.journal_id.display_name or method.display_name,
            } for method in methods],
            'representatives': [{
                'id': representative.id,
                'name': representative.display_name,
                'available_balance': float(Advance._baseer_representative_available_amount(company, representative)),
            } for representative in representatives],
            'can_use_representative': can_use_representative,
        }

    @api.depends('company_id', 'representative_petty_cash_representative_id')
    def _compute_representative_petty_cash_available_amount(self):
        Advance = self.env['baseer.procurement.representative.advance']
        for line in self:
            if line.company_id and line.representative_petty_cash_representative_id:
                line.representative_petty_cash_available_amount = float(
                    Advance._baseer_representative_available_amount(
                        line.company_id, line.representative_petty_cash_representative_id,
                    )
                )
            else:
                line.representative_petty_cash_available_amount = 0.0

    def _baseer_source_values(self, values, creating=False):
        values = dict(values)
        source = values.get('payment_source_type') or (False if creating else self.payment_source_type)
        representative_id = values.get('representative_petty_cash_representative_id')
        if representative_id is None and not creating:
            representative_id = self.representative_petty_cash_representative_id.id
        if not source:
            source = ('representative_petty_cash' if representative_id else
                      'credit' if values.get('is_credit', False if creating else self.is_credit) else
                      'payment_method')
            values['payment_source_type'] = source
        if source == 'representative_petty_cash':
            if not self.env.su and not self.env.user.has_group(
                    'baseer_procurement_requests.group_procurement_accountant'):
                raise AccessError(_('Only a procurement accountant can use Representative Petty Cash.'))
            if values.get('payment_method_line_id'):
                raise ValidationError(_('Choose either a payment point or Representative Petty Cash for an invoice, not both.'))
            values.update({'is_credit': True, 'payment_method_line_id': False})
        elif source == 'payment_method':
            if representative_id:
                raise ValidationError(_('A payment-point invoice cannot also select Representative Petty Cash.'))
            values.update({'is_credit': False, 'representative_petty_cash_representative_id': False})
        elif source == 'credit':
            if representative_id or values.get('payment_method_line_id'):
                raise ValidationError(_('A credit invoice cannot also select a payment source.'))
            values.update({'is_credit': True, 'payment_method_line_id': False,
                           'representative_petty_cash_representative_id': False})
        else:
            raise ValidationError(_('Choose a valid invoice payment source.'))
        return values

    def _baseer_validate_payment_source(self):
        for line in self:
            source = line.payment_source_type
            representative = line.representative_petty_cash_representative_id
            if source == 'representative_petty_cash':
                if not representative or not line.is_credit or line.payment_method_line_id:
                    raise ValidationError(_('A Representative Petty Cash invoice requires one representative and no direct payment method.'))
                scoped = representative.with_company(line.company_id)
                if (not representative.active or representative.is_company or representative.parent_id
                        or not scoped.is_purchase_representative
                        or (representative.company_id and representative.company_id != line.company_id)):
                    raise ValidationError(_('Choose an active purchase-representative contact in the batch company.'))
                if line.batch_id.procurement_custody_id:
                    raise ValidationError(_('Historical Petty Cash cannot be mixed with Representative Petty Cash invoice sources.'))
            elif source == 'payment_method':
                if line.is_credit or representative or not line.payment_method_line_id:
                    raise ValidationError(_('Choose one valid cash or bank payment point for this invoice.'))
            elif source == 'credit':
                if not line.is_credit or representative or line.payment_method_line_id:
                    raise ValidationError(_('A credit invoice cannot have another payment source.'))
            else:
                raise ValidationError(_('Choose a payment source for every invoice.'))

    @api.onchange('payment_source_type')
    def _onchange_baseer_payment_source_type(self):
        for line in self:
            if line.payment_source_type == 'representative_petty_cash':
                line.is_credit = True
                line.payment_method_line_id = False
            elif line.payment_source_type == 'payment_method':
                line.is_credit = False
                line.representative_petty_cash_representative_id = False
            elif line.payment_source_type == 'credit':
                line.is_credit = True
                line.payment_method_line_id = False
                line.representative_petty_cash_representative_id = False

    @api.model_create_multi
    def create(self, vals_list):
        if any('representative_petty_cash_invoice_settlement_id' in values for values in vals_list):
            raise AccessError(_('Representative Petty Cash settlement links are controlled by the server.'))
        records = super().create([self._baseer_source_values(values, creating=True) for values in vals_list])
        records._baseer_validate_payment_source()
        return records

    def write(self, values):
        protected = {'payment_source_type', 'representative_petty_cash_representative_id'}
        if self.filtered(lambda line: line.batch_state == 'approved') and protected & set(values):
            raise UserError(_('Approved invoice payment sources are immutable.'))
        if 'representative_petty_cash_invoice_settlement_id' in values:
            raise AccessError(_('Representative Petty Cash settlement links are controlled by the server.'))
        result = super().write(self._baseer_source_values(values))
        self._baseer_validate_payment_source()
        return result


class BaseerPurchaseBatch(models.Model):
    _inherit = 'baseer.purchase.batch'

    def _baseer_representative_lines(self):
        return self.line_ids.filtered(lambda line: line.payment_source_type == 'representative_petty_cash')

    def _baseer_lock_representatives(self, representatives):
        """Lock the business balance in a stable order before recalculating it."""
        self.ensure_one()
        representatives = representatives.exists().sorted('id')
        self.env.cr.execute('SELECT id FROM res_company WHERE id = %s FOR UPDATE', [self.company_id.id])
        self.env.cr.execute('UPDATE res_company SET id = id WHERE id = %s', [self.company_id.id])
        if representatives:
            self.env.cr.execute('SELECT id FROM res_partner WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(representatives.ids)])
            self.env.cr.execute('UPDATE res_partner SET id = id WHERE id IN %s', [tuple(representatives.ids)])

    def _baseer_representative_totals(self):
        totals = {}
        for line in self._baseer_representative_lines():
            representative = line.representative_petty_cash_representative_id
            totals[representative] = totals.get(representative, Decimal('0.00')) + Decimal(str(line.gross_amount)).quantize(MONEY_QUANTUM)
        return totals

    def _baseer_validate_representative_lines(self):
        self.ensure_one()
        lines = self._baseer_representative_lines()
        if not lines:
            return
        if self.representative_petty_cash_id:
            raise ValidationError(_('Historical Representative Petty Cash cannot be mixed with invoice-level payment sources.'))
        if self.procurement_request_id and not self.procurement_auto_draft:
            raise ValidationError(_(
                'Representative Petty Cash supplier invoices are linked to the representative balance only; '
                'do not select a purchase request on the batch header.'
            ))
        if self.procurement_auto_draft:
            request_representative = self.procurement_request_id.representative_partner_id
            if not request_representative or any(
                line.representative_petty_cash_representative_id != request_representative
                for line in lines
            ):
                raise ValidationError(_(
                    'An automatic receipt invoice draft can use only the purchase representative on its receipt.'
                ))
        lines._baseer_validate_payment_source()
        self._baseer_lock_representatives(lines.mapped('representative_petty_cash_representative_id'))
        Advance = self.env['baseer.procurement.representative.advance']
        for representative, total in self._baseer_representative_totals().items():
            available = Advance._baseer_representative_available_amount(self.company_id, representative)
            if total > available:
                raise UserError(_('Supplier invoices for %(representative)s exceed the available Representative Petty Cash balance.') % {
                    'representative': representative.display_name,
                })

    def _baseer_settle_representative_lines(self):
        Settlement = self.env['baseer.procurement.representative.petty.cash.invoice.settlement']
        for batch in self:
            lines = batch._baseer_representative_lines().filtered(lambda line: not line.representative_petty_cash_invoice_settlement_id)
            if not lines:
                continue
            batch._baseer_lock_representatives(lines.mapped('representative_petty_cash_representative_id'))
            batch._baseer_validate_representative_lines()
            account, journal = batch.company_id._baseer_representative_petty_cash_ready()
            if batch.company_id._get_violated_lock_dates(batch.entry_date, False, journal):
                raise ValidationError(_('The Representative Petty Cash settlement date is locked.'))
            for representative in lines.mapped('representative_petty_cash_representative_id').sorted('id'):
                representative_lines = lines.filtered(lambda line: line.representative_petty_cash_representative_id == representative)
                payables, total = [], Decimal('0.00')
                for line in representative_lines:
                    bill = line.move_id
                    payable = bill.line_ids.filtered(lambda item: item.account_id.account_type == 'liability_payable' and not item.reconciled)
                    expected = Decimal(str(line.gross_amount)).quantize(MONEY_QUANTUM)
                    if (not bill or bill.state != 'posted' or len(payable) != 1
                            or Decimal(str(abs(payable.amount_residual))).quantize(MONEY_QUANTUM) != expected):
                        raise UserError(_('A supplier bill payable is not available for full Representative Petty Cash settlement.'))
                    payables.append((line, payable))
                    total += expected
                if total > self.env['baseer.procurement.representative.advance']._baseer_representative_available_amount(batch.company_id, representative):
                    raise UserError(_('Supplier invoices for %(representative)s exceed the available Representative Petty Cash balance.') % {
                        'representative': representative.display_name,
                    })
                label = '%s — %s' % (_('Representative Petty Cash'), batch.name)
                move = self.env['account.move'].sudo().with_company(batch.company_id).with_context(**{INTERNAL: True}).create({
                    'move_type': 'entry', 'company_id': batch.company_id.id, 'journal_id': journal.id,
                    'date': batch.entry_date, 'ref': '%s — %s' % (label, representative.display_name),
                    'line_ids': [
                        *[Command.create({'name': label, 'account_id': payable.account_id.id,
                                          'partner_id': payable.partner_id.id, 'debit': line.gross_amount})
                          for line, payable in payables],
                        Command.create({'name': label, 'account_id': account.id, 'partner_id': representative.id,
                                        'credit': float(total)}),
                    ],
                })
                move.action_post()
                settlement_payables = move.line_ids.filtered(lambda item: item.account_id.account_type == 'liability_payable')
                if len(settlement_payables) != len(payables):
                    raise UserError(_('The Representative Petty Cash settlement payable is incomplete.'))
                for index, (line, payable) in enumerate(payables):
                    settled_payable = settlement_payables[index]
                    if (settled_payable.account_id != payable.account_id
                            or settled_payable.partner_id != payable.partner_id
                            or Decimal(str(settled_payable.debit)).quantize(MONEY_QUANTUM)
                            != Decimal(str(abs(payable.amount_residual))).quantize(MONEY_QUANTUM)):
                        raise UserError(_('The Representative Petty Cash settlement payable is incomplete.'))
                    (payable | settled_payable).reconcile()
                    settlement = Settlement.sudo().with_context(**{INTERNAL: True}).create({
                        'company_id': batch.company_id.id, 'representative_partner_id': representative.id,
                        'batch_line_id': line.id, 'move_id': move.id, 'amount': float(line.gross_amount),
                    })
                    # Generic batch approval makes invoice rows immutable
                    # before this accounting settlement is posted.  Store
                    # only the resulting immutable audit link, guarded so it
                    # can never overwrite an existing settlement.
                    self.env.cr.execute(
                        '''
                        UPDATE baseer_purchase_batch_line
                           SET representative_petty_cash_invoice_settlement_id = %s
                         WHERE id = %s
                           AND representative_petty_cash_invoice_settlement_id IS NULL
                        ''',
                        [settlement.id, line.id],
                    )
                    if self.env.cr.rowcount != 1:
                        raise UserError(_('The Representative Petty Cash settlement link was already created.'))
                    line.invalidate_recordset(['representative_petty_cash_invoice_settlement_id'])
                counterparty = move.line_ids.filtered(
                    lambda item: item.account_id == account and item.partner_id == representative and item.credit > 0
                )
                open_funding = self.env['account.move.line'].search([
                    ('account_id', '=', account.id), ('partner_id', '=', representative.id),
                    ('parent_state', '=', 'posted'), ('reconciled', '=', False), ('debit', '>', 0),
                    ('baseer_representative_petty_cash_id', '!=', False),
                ])
                (open_funding | counterparty).reconcile()
                if any(line.move_id.payment_state != 'paid' for line, _payable in payables):
                    raise UserError(_('A supplier bill did not reconcile after Representative Petty Cash settlement.'))

    @api.model_create_multi
    def create(self, vals_list):
        if any(values.get('representative_petty_cash_id') for values in vals_list):
            raise ValidationError(_('Choose Representative Petty Cash on each invoice, not on the purchase-batch header.'))
        return super().create(vals_list)

    def write(self, values):
        if values.get('representative_petty_cash_id'):
            raise ValidationError(_('Choose Representative Petty Cash on each invoice, not on the purchase-batch header.'))
        return super().write(values)

    def action_approve(self):
        self.ensure_one()
        representative_lines = self._baseer_representative_lines()
        if representative_lines and not self.env.user.has_group('baseer_procurement_requests.group_procurement_accountant'):
            raise AccessError(_('Only a procurement accountant can approve a Representative Petty Cash supplier invoice.'))
        with self.env.cr.savepoint():
            self._lock_batches()
            if self.state != 'approved':
                self._baseer_validate_representative_lines()
            result = super().action_approve()
            self._baseer_settle_representative_lines()
            return result
