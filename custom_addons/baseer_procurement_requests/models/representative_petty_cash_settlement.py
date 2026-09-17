"""Representative petty-cash settlement for native supplier-bill batches.

The old custody pool is deliberately not reused here.  A settlement spends one
immutable representative advance against the payable lines created by one
purchase batch, and reconciles both sides in the native Odoo ledger.
"""
from decimal import Decimal

from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .representative_petty_cash import INTERNAL, MONEY_QUANTUM


class RepresentativePettyCashSettlement(models.Model):
    _name = 'baseer.procurement.representative.advance.settlement'
    _description = 'Representative Petty Cash supplier settlement'
    _order = 'id desc'
    _check_company_auto = True

    company_id = fields.Many2one('res.company', required=True, readonly=True, index=True, ondelete='restrict')
    advance_id = fields.Many2one(
        'baseer.procurement.representative.advance', required=True, readonly=True, index=True,
        ondelete='restrict', check_company=True,
    )
    batch_id = fields.Many2one('baseer.purchase.batch', required=True, readonly=True, index=True,
                               ondelete='restrict', check_company=True)
    move_id = fields.Many2one('account.move', required=True, readonly=True, ondelete='restrict', check_company=True)
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)
    amount = fields.Monetary(required=True, readonly=True, currency_field='currency_id')
    state = fields.Selection([('posted', 'Posted')], default='posted', required=True, readonly=True, index=True)

    _sql_constraints = [
        ('representative_petty_cash_settlement_batch_unique', 'unique(batch_id)',
         'A purchase batch can be settled from Representative Petty Cash only once.'),
    ]

    @api.constrains('company_id', 'advance_id', 'batch_id', 'move_id', 'amount')
    def _check_relationships(self):
        for settlement in self:
            if (settlement.advance_id.company_id != settlement.company_id
                    or settlement.batch_id.company_id != settlement.company_id
                    or settlement.move_id.company_id != settlement.company_id):
                raise ValidationError(_('Representative Petty Cash settlements must remain within one company.'))
            if settlement.amount <= 0:
                raise ValidationError(_('A Representative Petty Cash settlement amount must be positive.'))

    @api.model_create_multi
    def create(self, vals_list):
        if not (self.env.su and self.env.context.get(INTERNAL)):
            raise AccessError(_('Representative Petty Cash settlements are created only by the approval workflow.'))
        return super().create(vals_list)

    def write(self, vals):
        raise UserError(_('Representative Petty Cash settlements are immutable accounting links.'))

    def unlink(self):
        raise UserError(_('Representative Petty Cash settlements cannot be deleted.'))


class RepresentativePettyCash(models.Model):
    _inherit = 'baseer.procurement.representative.advance'

    settlement_ids = fields.One2many(
        'baseer.procurement.representative.advance.settlement', 'advance_id', readonly=True,
        string='Supplier settlements',
    )
    settled_amount = fields.Monetary(compute='_compute_returned_amount', currency_field='currency_id', readonly=True)

    @api.depends('amount', 'return_ids.amount', 'return_ids.state', 'settlement_ids.amount', 'settlement_ids.state')
    def _compute_returned_amount(self):
        returns_by_origin = {}
        settlements_by_advance = {}
        if self.ids:
            posted_returns = self.search([
                ('origin_id', 'in', self.ids), ('state', '=', 'posted'),
            ])
            posted_settlements = self.env['baseer.procurement.representative.advance.settlement'].search([
                ('advance_id', 'in', self.ids), ('state', '=', 'posted'),
            ])
            for movement in posted_returns:
                returns_by_origin[movement.origin_id.id] = (
                    returns_by_origin.get(movement.origin_id.id, 0.0) + movement.amount
                )
            for settlement in posted_settlements:
                settlements_by_advance[settlement.advance_id.id] = (
                    settlements_by_advance.get(settlement.advance_id.id, 0.0) + settlement.amount
                )
        for record in self:
            record.returned_amount = returns_by_origin.get(record.id, 0.0)
            record.settled_amount = settlements_by_advance.get(record.id, 0.0)
            record.remaining_amount = (
                record.amount - record.returned_amount - record.settled_amount
                if record.movement_type == 'funding' else 0.0
            )

    def name_search(self, name='', args=None, operator='ilike', limit=100):
        """Limit batch selectors at the server, not only in their XML domain."""
        args = list(args or [])
        request_id = self.env.context.get('baseer_representative_petty_cash_request_id')
        if request_id:
            company_id = int(self.env.context.get('baseer_representative_petty_cash_company_id') or self.env.company.id)
            args.extend([
                ('movement_type', '=', 'funding'), ('state', '=', 'posted'),
                ('procurement_request_id', '=', int(request_id)),
                ('company_id', '=', company_id),
            ])
            candidates = self.search(args, order='movement_date desc, id desc', limit=200)
            candidates = candidates.filtered(
                lambda advance: advance.remaining_amount > 0
                and advance.representative_partner_id == advance.procurement_request_id.representative_partner_id
            )
            # Delegate the text/operator semantics to Odoo after applying the
            # server-side eligibility filter.  The selector therefore supports
            # normal lookup by movement number without exposing closed advances.
            return super().name_search(name=name, args=[('id', 'in', candidates.ids)], operator=operator, limit=limit)
        return super().name_search(name=name, args=args, operator=operator, limit=limit)


class BaseerPurchaseBatchLine(models.Model):
    _inherit = 'baseer.purchase.batch.line'

    def _representative_petty_cash_values(self, values):
        values = dict(values)
        has_route = self.env.context.get('baseer_representative_petty_cash_route')
        batch_id = values.get('batch_id')
        if not has_route and batch_id:
            has_route = self.env['baseer.purchase.batch'].browse(batch_id).representative_petty_cash_id
        if not has_route and self:
            has_route = any(self.mapped('batch_id.representative_petty_cash_id'))
        if has_route:
            if values.get('procurement_custody_id') or values.get('procurement_allocation_ids'):
                raise ValidationError(_(
                    'Representative Petty Cash batches cannot contain historical Petty Cash row links or allocations.'
                ))
            values.update({'is_credit': True, 'payment_method_line_id': False})
        return values

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([self._representative_petty_cash_values(values) for values in vals_list])

    def write(self, values):
        return super().write(self._representative_petty_cash_values(values))


class BaseerPurchaseBatch(models.Model):
    _inherit = 'baseer.purchase.batch'

    representative_petty_cash_id = fields.Many2one(
        'baseer.procurement.representative.advance', string='Representative Petty Cash',
        ondelete='restrict', check_company=True, index=True, copy=False,
    )
    representative_petty_cash_representative_id = fields.Many2one(
        related='representative_petty_cash_id.representative_partner_id', string='Selected advance representative', readonly=True,
    )
    representative_petty_cash_available_amount = fields.Monetary(
        related='representative_petty_cash_id.remaining_amount', string='Available Representative Petty Cash',
        currency_field='currency_id', readonly=True,
    )
    representative_petty_cash_settled_amount = fields.Monetary(
        related='representative_petty_cash_id.settled_amount', string='Settled from Representative Petty Cash',
        currency_field='currency_id', readonly=True,
    )
    representative_petty_cash_settlement_id = fields.Many2one(
        'baseer.procurement.representative.advance.settlement', compute='_compute_representative_petty_cash_settlement',
        string='Representative Petty Cash settlement', readonly=True,
    )
    representative_petty_cash_settlement_move_id = fields.Many2one(
        'account.move', compute='_compute_representative_petty_cash_settlement',
        string='Representative Petty Cash settlement entry', readonly=True,
    )

    @api.depends('representative_petty_cash_id', 'representative_petty_cash_id.settlement_ids')
    def _compute_representative_petty_cash_settlement(self):
        settlements = self.env['baseer.procurement.representative.advance.settlement'].sudo().search([
            ('batch_id', 'in', self.ids),
        ])
        by_batch = {settlement.batch_id.id: settlement for settlement in settlements}
        for batch in self:
            settlement = by_batch.get(batch.id)
            batch.representative_petty_cash_settlement_id = settlement
            batch.representative_petty_cash_settlement_move_id = settlement.move_id if settlement else False

    @api.onchange('representative_petty_cash_id')
    def _onchange_representative_petty_cash(self):
        for batch in self:
            if batch.representative_petty_cash_id:
                batch.procurement_custody_id = False
                batch.line_ids.write({'is_credit': True, 'payment_method_line_id': False})

    @api.constrains('representative_petty_cash_id', 'procurement_request_id', 'company_id', 'line_ids')
    def _check_representative_petty_cash_header(self):
        for batch in self:
            advance = batch.representative_petty_cash_id
            if not advance:
                continue
            request = batch.procurement_request_id
            if batch.procurement_custody_id:
                raise ValidationError(_('Choose either Representative Petty Cash or the historical Petty Cash source, not both.'))
            if batch.line_ids.filtered(lambda line: line.procurement_custody_id or line.procurement_allocation_ids):
                raise ValidationError(_(
                    'Representative Petty Cash batches cannot contain historical Petty Cash row links or allocations.'
                ))
            if (not request or advance.company_id != batch.company_id or request.company_id != batch.company_id
                    or advance.movement_type != 'funding' or advance.state != 'posted'
                    or advance.procurement_request_id != request
                    or advance.representative_partner_id != request.representative_partner_id):
                raise ValidationError(_('Representative Petty Cash must match this company, purchase request, and purchase representative.'))
            if batch.company_id.currency_id.is_zero(advance.remaining_amount) or advance.remaining_amount < 0:
                raise ValidationError(_('Choose a Representative Petty Cash movement with an available remaining amount.'))

    def _force_representative_petty_cash_route(self):
        for batch in self.filtered('representative_petty_cash_id'):
            batch.line_ids.write({'is_credit': True, 'payment_method_line_id': False})

    @staticmethod
    def _has_legacy_line_values(values):
        """Reject a hidden/imported PCUST row before Odoo creates the batch."""
        for command in values.get('line_ids', []):
            if isinstance(command, (tuple, list)) and len(command) >= 3 and command[0] == Command.CREATE:
                line_values = command[2] or {}
                if line_values.get('procurement_custody_id') or line_values.get('procurement_allocation_ids'):
                    return True
        return False

    @api.model_create_multi
    def create(self, vals_list):
        if any(values.get('procurement_custody_id') for values in vals_list):
            raise ValidationError(_('Historical Petty Cash cannot be selected for a new purchase batch. Choose Representative Petty Cash.'))
        if any(values.get('representative_petty_cash_id') and self._has_legacy_line_values(values) for values in vals_list):
            raise ValidationError(_(
                'Representative Petty Cash batches cannot contain historical Petty Cash row links or allocations.'
            ))
        records = super().create(vals_list)
        records._force_representative_petty_cash_route()
        records._check_representative_petty_cash_header()
        return records

    def write(self, values):
        protected = {'representative_petty_cash_id'}
        if protected & set(values) and self.filtered(lambda batch: batch.state == 'approved'):
            raise UserError(_('Approved Representative Petty Cash links are immutable.'))
        if values.get('procurement_custody_id') and self.filtered(lambda batch: not batch.procurement_custody_id):
            raise ValidationError(_('Historical Petty Cash cannot be selected for a new purchase batch. Choose Representative Petty Cash.'))
        result = super().write(values)
        if 'representative_petty_cash_id' in values:
            self._force_representative_petty_cash_route()
        return result

    def _lock_representative_petty_cash(self, advance):
        self.env.cr.execute(
            'SELECT id FROM baseer_procurement_representative_advance WHERE id = %s FOR UPDATE', [advance.id],
        )
        self.env.cr.execute(
            'UPDATE baseer_procurement_representative_advance SET id = id WHERE id = %s', [advance.id],
        )
        advance.invalidate_recordset(['return_ids', 'settlement_ids', 'returned_amount', 'settled_amount', 'remaining_amount'])
        return advance.exists()

    def _validate_representative_petty_cash_batch(self):
        self.ensure_one()
        advance = self.representative_petty_cash_id
        if not advance:
            return
        self._lock_representative_petty_cash(advance)
        self._check_representative_petty_cash_header()
        if self.procurement_request_id.state != 'purchased':
            raise ValidationError(_('Only a completed purchase request can be settled from Representative Petty Cash.'))
        if any(not line.is_credit or line.payment_method_line_id for line in self.line_ids):
            raise ValidationError(_('A Representative Petty Cash batch cannot create direct bank or cash payments.'))
        total = Decimal(str(self.amount_gross)).quantize(MONEY_QUANTUM)
        available = Decimal(str(advance.remaining_amount)).quantize(MONEY_QUANTUM)
        if total > available:
            raise UserError(_('The supplier invoices exceed the available Representative Petty Cash amount.'))

    def action_resettle_custody(self):
        """PCUST remains historical/read-only after the representative route replaces it."""
        if self.filtered('procurement_custody_id'):
            raise UserError(_('Historical Petty Cash batches are read-only and cannot be resettled.'))
        return super().action_resettle_custody()

    def _settle_representative_petty_cash(self):
        Settlement = self.env['baseer.procurement.representative.advance.settlement']
        for batch in self.filtered('representative_petty_cash_id'):
            if Settlement.search_count([('batch_id', '=', batch.id)]):
                continue
            advance = batch.representative_petty_cash_id
            batch._lock_representative_petty_cash(advance)
            batch._validate_representative_petty_cash_batch()
            account, journal = batch.company_id._baseer_representative_petty_cash_ready()
            if batch.company_id._get_violated_lock_dates(batch.entry_date, False, journal):
                raise ValidationError(_('The Representative Petty Cash settlement date is locked.'))
            payables = []
            total = Decimal('0.00')
            for line in batch.line_ids:
                bill = line.move_id
                if not bill or bill.state != 'posted':
                    raise UserError(_('Approve the supplier bill before settling it from Representative Petty Cash.'))
                payable = bill.line_ids.filtered(
                    lambda item: item.account_id.account_type == 'liability_payable' and not item.reconciled
                )
                expected = Decimal(str(line.gross_amount)).quantize(MONEY_QUANTUM)
                if len(payable) != 1 or Decimal(str(abs(payable.amount_residual))).quantize(MONEY_QUANTUM) != expected:
                    raise UserError(_('A supplier bill payable is not available for full Representative Petty Cash settlement.'))
                payables.append((line, payable))
                total += expected
            available = Decimal(str(advance.remaining_amount)).quantize(MONEY_QUANTUM)
            if total > available:
                raise UserError(_('The supplier invoices exceed the available Representative Petty Cash amount.'))
            label = '%s — %s' % (advance.name, batch.name)
            lines = [
                Command.create({
                    'name': label, 'account_id': payable.account_id.id, 'partner_id': payable.partner_id.id,
                    'debit': line.gross_amount,
                })
                for line, payable in payables
            ]
            lines.append(Command.create({
                'name': label, 'account_id': account.id, 'partner_id': advance.representative_partner_id.id,
                'credit': float(total), 'baseer_representative_petty_cash_id': advance.id,
            }))
            move = self.env['account.move'].sudo().with_company(batch.company_id).with_context(**{INTERNAL: True}).create({
                'move_type': 'entry', 'company_id': batch.company_id.id, 'journal_id': journal.id,
                'date': batch.entry_date, 'ref': label, 'line_ids': lines,
            })
            move.action_post()
            settlement_payables = move.line_ids.filtered(lambda item: item.account_id.account_type == 'liability_payable')
            if len(settlement_payables) != len(payables):
                raise UserError(_('The Representative Petty Cash settlement payables are incomplete.'))
            for index, (_line, payable) in enumerate(payables):
                settlement_payable = settlement_payables[index]
                if (settlement_payable.account_id != payable.account_id
                        or settlement_payable.partner_id != payable.partner_id
                        or Decimal(str(settlement_payable.debit)).quantize(MONEY_QUANTUM)
                        != Decimal(str(abs(payable.amount_residual))).quantize(MONEY_QUANTUM)):
                    raise UserError(_('The Representative Petty Cash settlement payable is incomplete.'))
                (payable | settlement_payable).reconcile()
            if any(line.move_id.payment_state != 'paid' for line, _payable in payables):
                raise UserError(_('A supplier bill did not reconcile after Representative Petty Cash settlement.'))
            advance_line = move.line_ids.filtered(lambda item: item.account_id == account and item.credit > 0)
            open_advance = self.env['account.move.line'].search([
                ('account_id', '=', account.id), ('partner_id', '=', advance.representative_partner_id.id),
                ('parent_state', '=', 'posted'), ('reconciled', '=', False),
                ('baseer_representative_petty_cash_id', '=', advance.id), ('id', '!=', advance_line.id),
            ])
            (open_advance.filtered(lambda item: item.debit > 0) | advance_line).reconcile()
            Settlement.sudo().with_context(**{INTERNAL: True}).create({
                'company_id': batch.company_id.id, 'advance_id': advance.id, 'batch_id': batch.id,
                'move_id': move.id, 'amount': float(total),
            })
            advance.invalidate_recordset(['settlement_ids', 'settled_amount', 'remaining_amount'])

    def action_approve(self):
        self.ensure_one()
        if self.representative_petty_cash_id and not self.env.user.has_group('baseer_procurement_requests.group_procurement_accountant'):
            raise AccessError(_('Only a procurement accountant can approve a Representative Petty Cash supplier batch.'))
        with self.env.cr.savepoint():
            self._lock_batches()
            if self.state != 'approved':
                self._force_representative_petty_cash_route()
                self._validate_representative_petty_cash_batch()
            result = super().action_approve()
            self._settle_representative_petty_cash()
            return result
