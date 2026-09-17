"""Invoice-level representative petty-cash payment sources.

The first representative-petty-cash release settled an entire purchase batch
from one selected RPC movement.  This extension deliberately leaves those
historical records untouched and introduces the new, invoice-level contract.
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from psycopg2 import IntegrityError

from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .representative_petty_cash import INTERNAL, MONEY_QUANTUM


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
        return (Decimal(str(funded)) - Decimal(str(returned))
                - Decimal(str(historical)) - Decimal(str(settled))).quantize(MONEY_QUANTUM)

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

    def _dashboard_data(self, representative_id=False, month_start=False):
        data = super()._dashboard_data(representative_id, month_start)
        company = self.env.company
        start, end = self._month_range(data['month_start'])
        domain = [
            ('company_id', '=', company.id), ('state', '=', 'posted'),
            ('move_id.date', '>=', start), ('move_id.date', '<', end),
        ]
        if representative_id:
            domain.append(('representative_partner_id', '=', int(representative_id)))
        current_settled = self._baseer_grouped_amount(
            self.env['baseer.procurement.representative.petty.cash.invoice.settlement'], domain,
        )
        # Dashboard's settled card remains monthly; the available card is
        # cumulative only when a representative is selected.
        data['summary']['settled'] = float(Decimal(str(data['summary']['settled'])) + Decimal(str(current_settled)))
        data['summary']['remaining'] = float((Decimal(str(data['summary']['remaining'])) - Decimal(str(current_settled))).quantize(MONEY_QUANTUM))
        if representative_id:
            representative = self.env['res.partner'].browse(int(representative_id)).exists()
            data['summary']['available'] = float(self._baseer_representative_available_amount(company, representative)) if representative else 0.0
        return data


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
        if not (can_use_representative or self.env.user.has_group('account.group_account_invoice')):
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
        if self.procurement_request_id:
            raise ValidationError(_(
                'Representative Petty Cash supplier invoices are linked to the representative balance only; '
                'do not select a purchase request on the batch header.'
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
