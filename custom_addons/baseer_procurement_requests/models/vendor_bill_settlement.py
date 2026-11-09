"""Settle one existing vendor bill against representative custody.

Purchase-batch approval creates a new supplier bill and can settle only that
bill. Agent invoices already exist, so this action posts and settles the
supplied bill in one transaction. It does not create a bill, purchase order,
receipt, funding movement, or bank/cash payment.

Petty Cash (PCUST) and Representative Petty Cash (RPC) stay on their existing
official records. An open petty cash for the representative is used alone.
RPC is used only when that company has no open petty cash for the
representative. A bill is never split across the two mechanisms.
"""
import zlib
from decimal import Decimal, InvalidOperation

from psycopg2 import IntegrityError

from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .custody import INTERNAL as CUSTODY_INTERNAL
from .representative_petty_cash import INTERNAL as RPC_INTERNAL, MONEY_QUANTUM


VENDOR_BILL_INTERNAL = 'baseer_vendor_bill_settlement_internal'
AGENT_TAG = 'AGENT: وكيل الفواتير'
KEY_MAX = 128


def ensure_vendor_bill_settlement_indexes(cr):
    """Indexes only. Never creates partners, accounts, journals, or entries."""
    cr.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS baseer_custody_settlement_vendor_bill_uniq
        ON baseer_procurement_custody_settlement (vendor_bill_id)
        WHERE vendor_bill_id IS NOT NULL AND state = 'active'
        """
    )
    cr.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS baseer_rep_invoice_settlement_vendor_bill_uniq
        ON baseer_procurement_representative_petty_cash_invoice_settlement (vendor_bill_id)
        WHERE vendor_bill_id IS NOT NULL
        """
    )
    cr.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS baseer_vendor_bill_settlement_alloc_uniq
        ON baseer_procurement_vendor_bill_settlement_allocation (settlement_id, advance_id)
        """
    )


def _same(company, left, right):
    return not company.currency_id.compare_amounts(float(left), float(right))


def _quantize(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise ValidationError(_('Enter a valid amount.')) from None
    return amount.quantize(MONEY_QUANTUM)


def _require_id(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValidationError(_('Choose a valid %(label)s.') % {'label': label})
    return value


class VendorBillSettlementAllocation(models.Model):
    """One existing RPC advance consumed by an existing vendor bill.

    The representative's aggregate balance is reduced by the invoice
    settlement. These rows reduce each advance's own remaining amount by the
    same total, so the advance list and the aggregate stay aligned.
    """

    _name = 'baseer.procurement.vendor.bill.settlement.allocation'
    _description = 'Existing vendor bill representative-advance allocation'
    _order = 'id'
    _check_company_auto = True

    settlement_id = fields.Many2one(
        'baseer.procurement.vendor.bill.settlement', required=True, readonly=True,
        ondelete='restrict', index=True,
    )
    advance_id = fields.Many2one(
        'baseer.procurement.representative.advance', required=True, readonly=True,
        ondelete='restrict', index=True, check_company=True,
    )
    company_id = fields.Many2one('res.company', required=True, readonly=True, index=True, ondelete='restrict')
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)
    amount = fields.Monetary(required=True, readonly=True, currency_field='currency_id')
    state = fields.Selection([('posted', 'Posted')], default='posted', required=True, readonly=True, index=True)

    _sql_constraints = [
        ('vendor_bill_settlement_allocation_amount_positive', 'CHECK(amount > 0)',
         'An advance allocation must be positive.'),
    ]

    @api.constrains('settlement_id', 'advance_id', 'company_id', 'amount')
    def _check_allocation(self):
        for allocation in self:
            settlement, advance = allocation.settlement_id, allocation.advance_id
            if (advance.company_id != allocation.company_id or settlement.company_id != allocation.company_id
                    or advance.movement_type != 'funding' or advance.state != 'posted'
                    or advance.representative_partner_id != settlement.representative_partner_id):
                raise ValidationError(_('An advance allocation must belong to the settlement representative and company.'))
            if allocation.amount <= 0:
                raise ValidationError(_('An advance allocation must be positive.'))

    @api.model_create_multi
    def create(self, vals_list):
        if not (self.env.su and self.env.context.get(VENDOR_BILL_INTERNAL)):
            raise AccessError(_('Advance allocations are created only by the vendor-bill settlement action.'))
        return super().create(vals_list)

    def write(self, vals):
        raise UserError(_('Vendor-bill advance allocations are immutable.'))

    def unlink(self):
        raise UserError(_('Vendor-bill advance allocations cannot be deleted.'))


class VendorBillSettlement(models.Model):
    """Idempotent settlement of one existing supplier invoice.

    Human accountants call ``action_settle_existing_vendor_bill``. The invoice
    agent calls ``settle_agent_vendor_bill`` and must present a bill whose
    reference contains ``AGENT: وكيل الفواتير``. Both return the same payload.
    """

    _name = 'baseer.procurement.vendor.bill.settlement'
    _description = 'Existing vendor bill custody settlement'
    _order = 'id desc'
    _check_company_auto = True

    company_id = fields.Many2one('res.company', required=True, readonly=True, index=True, ondelete='restrict')
    vendor_bill_id = fields.Many2one(
        'account.move', required=True, readonly=True, index=True, ondelete='restrict', check_company=True,
    )
    representative_partner_id = fields.Many2one(
        'res.partner', required=True, readonly=True, index=True, ondelete='restrict', check_company=True,
    )
    mechanism = fields.Selection(
        [('pcust', 'Petty Cash'), ('rpc', 'Representative Petty Cash')],
        required=True, readonly=True, index=True,
    )
    custody_id = fields.Many2one(
        'baseer.procurement.custody', readonly=True, index=True, ondelete='restrict', check_company=True,
    )
    custody_settlement_id = fields.Many2one(
        'baseer.procurement.custody.settlement', readonly=True, ondelete='restrict', check_company=True,
    )
    invoice_settlement_id = fields.Many2one(
        'baseer.procurement.representative.petty.cash.invoice.settlement', readonly=True,
        ondelete='restrict', check_company=True,
    )
    move_id = fields.Many2one(
        'account.move', required=True, readonly=True, ondelete='restrict', check_company=True,
    )
    account_id = fields.Many2one(
        'account.account', required=True, readonly=True, ondelete='restrict', check_company=True,
    )
    journal_id = fields.Many2one(
        'account.journal', required=True, readonly=True, ondelete='restrict', check_company=True,
    )
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)
    amount = fields.Monetary(required=True, readonly=True, currency_field='currency_id')
    idempotency_key = fields.Char(required=True, readonly=True, index=True)
    agent_tag = fields.Char(readonly=True)
    entrypoint = fields.Selection([('human', 'Human'), ('agent', 'Agent')], required=True, readonly=True)
    state = fields.Selection([('posted', 'Posted')], default='posted', required=True, readonly=True, index=True)
    allocation_ids = fields.One2many(
        'baseer.procurement.vendor.bill.settlement.allocation', 'settlement_id', readonly=True,
    )

    _vendor_bill_settlement_bill_unique = models.Constraint(
        'unique(vendor_bill_id)',
        'A vendor bill can be settled against custody only once.',
    )
    _vendor_bill_settlement_key_unique = models.Constraint(
        'unique(company_id, idempotency_key)',
        'This vendor-bill settlement reference was already used.',
    )

    def init(self):
        ensure_vendor_bill_settlement_indexes(self.env.cr)

    @api.constrains(
        'company_id', 'vendor_bill_id', 'representative_partner_id', 'mechanism',
        'custody_id', 'custody_settlement_id', 'invoice_settlement_id', 'move_id',
        'account_id', 'journal_id', 'amount',
    )
    def _check_settlement(self):
        for settlement in self:
            company = settlement.company_id
            bill = settlement.vendor_bill_id
            if (bill.company_id != company or bill.move_type != 'in_invoice'
                    or settlement.move_id.company_id != company
                    or settlement.account_id not in (
                        company.baseer_procurement_custody_account_id,
                        company.baseer_procurement_representative_petty_cash_account_id,
                    )
                    or settlement.journal_id.company_id != company or settlement.journal_id.type != 'general'
                    or settlement.amount <= 0):
                raise ValidationError(_('The vendor-bill settlement does not match its company configuration.'))
            if settlement.representative_partner_id.company_id and settlement.representative_partner_id.company_id != company:
                raise ValidationError(_('The purchase representative must belong to the vendor-bill company.'))
            if settlement.mechanism == 'pcust':
                if (not settlement.custody_id or settlement.custody_id.company_id != company
                        or not settlement.custody_settlement_id or settlement.invoice_settlement_id
                        or settlement.custody_settlement_id.vendor_bill_id != bill
                        or settlement.custody_settlement_id.move_id != settlement.move_id
                        or settlement.account_id != company.baseer_procurement_custody_account_id
                        or settlement.journal_id != company.baseer_procurement_custody_journal_id):
                    raise ValidationError(_('A petty-cash vendor-bill settlement must use the company petty-cash configuration.'))
            elif settlement.mechanism == 'rpc':
                if (settlement.custody_id or settlement.custody_settlement_id or not settlement.invoice_settlement_id
                        or settlement.invoice_settlement_id.vendor_bill_id != bill
                        or settlement.invoice_settlement_id.move_id != settlement.move_id
                        or settlement.account_id != company.baseer_procurement_representative_petty_cash_account_id
                        or settlement.journal_id != company.baseer_procurement_representative_petty_cash_journal_id):
                    raise ValidationError(_('A representative petty-cash vendor-bill settlement must use the company representative configuration.'))
            else:
                raise ValidationError(_('Choose a supported custody mechanism.'))

    @api.model_create_multi
    def create(self, vals_list):
        if not (self.env.su and self.env.context.get(VENDOR_BILL_INTERNAL)):
            raise AccessError(_('Vendor-bill custody settlements are created only by the settlement action.'))
        return super().create(vals_list)

    def write(self, vals):
        raise UserError(_('Vendor-bill custody settlements are immutable.'))

    def unlink(self):
        raise UserError(_('Vendor-bill custody settlements cannot be deleted.'))

    def _payload(self, already_settled):
        self.ensure_one()
        bill = self.vendor_bill_id
        payables = bill.line_ids.filtered(lambda line: line.account_id.account_type == 'liability_payable')
        reconciled = bool(payables) and all(payables.mapped('reconciled'))
        return {
            'settlement_id': self.id,
            'idempotency_key': self.idempotency_key,
            'agent_tag': self.agent_tag or False,
            'entrypoint': self.entrypoint,
            'mechanism': self.mechanism,
            'company_id': self.company_id.id,
            'representative_partner_id': self.representative_partner_id.id,
            'bill_id': bill.id,
            'bill_state': bill.state,
            'bill_payment_state': bill.payment_state,
            'reconciliation_state': 'reconciled' if reconciled else 'open',
            'settlement_move_id': self.move_id.id,
            'settlement_move_name': self.move_id.name,
            'custody_id': self.custody_id.id or False,
            'custody_settlement_id': self.custody_settlement_id.id or False,
            'invoice_settlement_id': self.invoice_settlement_id.id or False,
            'account_id': self.account_id.id,
            'journal_id': self.journal_id.id,
            'advance_allocations': [{
                'advance_id': allocation.advance_id.id,
                'amount': float(_quantize(allocation.amount)),
            } for allocation in self.allocation_ids.sorted('id')],
            'amount': float(_quantize(self.amount)),
            'currency_id': self.currency_id.id,
            'custody_remaining': float(self._official_remaining()),
            'already_settled': bool(already_settled),
        }

    def _official_remaining(self):
        self.ensure_one()
        company, representative = self.company_id, self.representative_partner_id
        if self.mechanism == 'pcust':
            self.env['baseer.procurement.custody.settlement'].flush_model(['custody_id', 'state', 'amount', 'representative_partner_id'])
            self.custody_id.invalidate_recordset(['balance', 'settled_amount', 'settlement_ids'])
            return _quantize(self.custody_id._representative_balance(representative))
        self.env['baseer.procurement.representative.petty.cash.invoice.settlement'].flush_model([
            'company_id', 'representative_partner_id', 'state', 'amount',
        ])
        return self.env['baseer.procurement.representative.advance']._baseer_representative_available_amount(
            company, representative,
        )

    @api.model
    def preflight_existing_vendor_bill(self, bill_id, representative_partner_id, idempotency_key, custody_id=False):
        """Read-only check for a human accountant. Does not post or settle."""
        prepared = self._prepare(
            bill_id, representative_partner_id, idempotency_key, custody_id, entrypoint='human',
        )
        return self._preflight_payload(prepared)

    @api.model
    def preflight_agent_vendor_bill(self, bill_id, representative_partner_id, idempotency_key):
        """Read-only check for the invoice agent. Does not post or settle."""
        prepared = self._prepare(
            bill_id, representative_partner_id, idempotency_key, False, entrypoint='agent',
        )
        return self._preflight_payload(prepared)

    @api.model
    def action_settle_existing_vendor_bill(self, bill_id, representative_partner_id, idempotency_key, custody_id=False):
        """Post, when needed, and settle one existing supplier invoice.

        Arguments:
            bill_id: existing ``account.move`` supplier invoice (draft or posted).
            representative_partner_id: existing purchase-representative contact.
            idempotency_key: stable per-bill reference, unique inside the company.
            custody_id: optional open petty cash when more than one would match.
                Omit it for the automatic source. The agent entrypoint cannot
                choose a custody.

        The active company must be the bill company. Accounts and journals are
        read from that company. A matching idempotency key returns the original
        payload and does not create another entry.
        """
        prepared = self._prepare(
            bill_id, representative_partner_id, idempotency_key, custody_id, entrypoint='human',
        )
        if prepared.get('existing'):
            return prepared['existing']._payload(True)
        return self._execute(prepared)

    @api.model
    def settle_agent_vendor_bill(self, bill_id, representative_partner_id, idempotency_key):
        """Agent entrypoint. The bill reference must contain the agent tag.

        Same arguments and result as ``action_settle_existing_vendor_bill``,
        without ``custody_id``. The caller must belong to the invoice-agent
        group and to the bill company. The group does not grant funding,
        purchase-batch approval, or settlement of untagged bills.
        """
        prepared = self._prepare(
            bill_id, representative_partner_id, idempotency_key, False, entrypoint='agent',
        )
        if prepared.get('existing'):
            return prepared['existing']._payload(True)
        return self._execute(prepared)

    def _preflight_payload(self, prepared):
        if prepared.get('existing'):
            payload = prepared['existing']._payload(True)
            payload['preflight'] = True
            return payload
        plan, bill, company = prepared['plan'], prepared['bill'], prepared['company']
        return {
            'preflight': True,
            'already_settled': False,
            'mechanism': plan['mechanism'],
            'company_id': company.id,
            'representative_partner_id': prepared['representative'].id,
            'bill_id': bill.id,
            'bill_state': bill.state,
            'bill_payment_state': bill.payment_state,
            'amount': float(plan['amount']),
            'currency_id': company.currency_id.id,
            'custody_id': plan['custody'].id or False,
            'account_id': plan['account'].id,
            'journal_id': plan['journal'].id,
            'advance_allocations': [{
                'advance_id': advance.id,
                'amount': float(amount),
            } for advance, amount in plan['allocations']],
            'custody_remaining': float(plan['remaining_before']),
            'custody_remaining_after': float((plan['remaining_before'] - plan['amount']).quantize(MONEY_QUANTUM)),
            'idempotency_key': prepared['key'],
            'agent_tag': prepared['agent_tag'] or False,
            'entrypoint': prepared['entrypoint'],
        }

    @api.model
    def _prepare(self, bill_id, representative_partner_id, idempotency_key, custody_id, entrypoint):
        self._check_entrypoint(entrypoint)
        company = self._active_company()
        key = self._key(idempotency_key)
        bill = self._locate_bill(bill_id, company)
        representative = self._representative(representative_partner_id, company)
        if entrypoint == 'agent':
            self._check_agent_tag(bill)
        elif custody_id:
            _require_id(custody_id, _('petty cash'))
        # A retry sees the bill already paid. Resolve that before eligibility
        # checks that apply only to a bill that has not been settled yet.
        existing = self._matching_settlement(company, bill, representative, key)
        if existing:
            return {'existing': existing}
        self._validate_unsettled_bill(bill, company)
        plan = self._plan(company, bill, representative, custody_id if entrypoint == 'human' else False)
        return {
            'company': company,
            'bill': bill,
            'representative': representative,
            'key': key,
            'agent_tag': AGENT_TAG if entrypoint == 'agent' else False,
            'entrypoint': entrypoint,
            'custody_id': custody_id if entrypoint == 'human' else False,
            'plan': plan,
        }

    def _execute(self, prepared):
        try:
            with self.env.cr.savepoint():
                return self._settle_locked(prepared)
        except IntegrityError:
            self.env.invalidate_all()
            existing = self._matching_settlement(
                prepared['company'], prepared['bill'], prepared['representative'], prepared['key'],
            )
            if existing:
                return existing._payload(True)
            raise UserError(_('This vendor-bill settlement conflicted with another request. Retry the same reference.')) from None
        except Exception:
            self.env.invalidate_all()
            raise

    def _settle_locked(self, prepared):
        company = prepared['company']
        bill = prepared['bill']
        representative = prepared['representative']
        self._lock_scope(company, representative, bill, prepared['plan'])
        bill.invalidate_recordset()
        existing = self._matching_settlement(company, bill, representative, prepared['key'])
        if existing:
            return existing._payload(True)
        plan = self._plan(company, bill, representative, prepared['custody_id'])
        if bill.state == 'draft':
            posting = self.env['account.move'].browse(bill.id).with_company(company)
            if prepared['entrypoint'] == 'agent':
                posting = posting.sudo()
            posting.action_post()
            bill.invalidate_recordset()
        if bill.state != 'posted':
            raise UserError(_('The vendor bill did not post.'))
        posted_amount = _quantize(bill.amount_total)
        if posted_amount != plan['amount']:
            raise UserError(_('The posted vendor bill total changed during settlement.'))
        self._assert_open_payable(bill, company, posted_amount)
        # Re-read the source after the bill mutex. Lock that source, then
        # read the balance once more before any settlement entry is created.
        plan = self._plan(company, bill, representative, prepared['custody_id'])
        self._lock_source(company, representative, plan)
        plan = self._plan(company, bill, representative, prepared['custody_id'])
        if plan['amount'] != posted_amount:
            raise UserError(_('The available custody balance changed during settlement.'))
        remaining_before = plan['remaining_before']
        move = self._create_settlement_move(company, bill, representative, plan)
        self._reconcile(company, bill, representative, plan, move)
        bill.invalidate_recordset(['payment_state', 'amount_residual', 'line_ids'])
        if bill.payment_state != 'paid' or not _same(company, bill.amount_residual, 0):
            raise UserError(_('The vendor bill did not reconcile against custody.'))
        settlement = self._store(prepared, plan, move)
        remaining_after = settlement._official_remaining()
        if (remaining_before - remaining_after).quantize(MONEY_QUANTUM) != posted_amount:
            raise UserError(_('The custody balance did not decrease by the settled vendor-bill amount.'))
        return settlement._payload(False)

    def _store(self, prepared, plan, move):
        company, bill, representative = prepared['company'], prepared['bill'], prepared['representative']
        context = {
            VENDOR_BILL_INTERNAL: True,
            CUSTODY_INTERNAL: True,
            RPC_INTERNAL: True,
        }
        custody_settlement = invoice_settlement = self.env['baseer.procurement.custody.settlement']
        if plan['mechanism'] == 'pcust':
            custody_settlement = self.env['baseer.procurement.custody.settlement'].sudo().with_context(**context).create({
                'company_id': company.id,
                'custody_id': plan['custody'].id,
                'representative_partner_id': representative.id,
                'vendor_bill_id': bill.id,
                'move_id': move.id,
                'amount': float(plan['amount']),
            })
        else:
            invoice_settlement = self.env['baseer.procurement.representative.petty.cash.invoice.settlement'].sudo().with_context(**context).create({
                'company_id': company.id,
                'representative_partner_id': representative.id,
                'vendor_bill_id': bill.id,
                'move_id': move.id,
                'amount': float(plan['amount']),
            })
        settlement = self.sudo().with_context(**context).create({
            'company_id': company.id,
            'vendor_bill_id': bill.id,
            'representative_partner_id': representative.id,
            'mechanism': plan['mechanism'],
            'custody_id': plan['custody'].id or False,
            'custody_settlement_id': custody_settlement.id or False,
            'invoice_settlement_id': invoice_settlement.id or False,
            'move_id': move.id,
            'account_id': plan['account'].id,
            'journal_id': plan['journal'].id,
            'amount': float(plan['amount']),
            'idempotency_key': prepared['key'],
            'agent_tag': prepared['agent_tag'] or False,
            'entrypoint': prepared['entrypoint'],
        })
        if plan['allocations']:
            self.env['baseer.procurement.vendor.bill.settlement.allocation'].sudo().with_context(**context).create([
                {
                    'settlement_id': settlement.id,
                    'advance_id': advance.id,
                    'company_id': company.id,
                    'amount': float(amount),
                }
                for advance, amount in plan['allocations']
            ])
            allocated = sum((_quantize(amount) for _advance, amount in plan['allocations']), Decimal('0.00'))
            if allocated != plan['amount']:
                raise UserError(_('The representative-advance allocation does not equal the vendor bill.'))
            advances = self.env['baseer.procurement.representative.advance'].browse([
                advance.id for advance, _amount in plan['allocations']
            ])
            advances.invalidate_recordset(['bill_allocation_ids', 'settled_amount', 'remaining_amount'])
        return settlement

    def _create_settlement_move(self, company, bill, representative, plan):
        payable = self._open_payable(bill)
        amount = plan['amount']
        label = '%s — %s' % (
            plan['custody'].name if plan['custody'] else _('Representative Petty Cash'),
            bill.name or bill.ref or bill.id,
        )
        credits = []
        if plan['mechanism'] == 'pcust':
            credits.append(Command.create({
                'name': label,
                'account_id': plan['account'].id,
                'partner_id': representative.id,
                'credit': float(amount),
                'baseer_procurement_custody_id': plan['custody'].id,
            }))
        else:
            for advance, part in plan['allocations']:
                credits.append(Command.create({
                    'name': label,
                    'account_id': plan['account'].id,
                    'partner_id': representative.id,
                    'credit': float(part),
                    'baseer_representative_petty_cash_id': advance.id,
                }))
        move = self.env['account.move'].sudo().with_company(company).with_context(**{
            CUSTODY_INTERNAL: True,
            RPC_INTERNAL: True,
            VENDOR_BILL_INTERNAL: True,
        }).create({
            'move_type': 'entry',
            'company_id': company.id,
            'journal_id': plan['journal'].id,
            'date': bill.invoice_date,
            'ref': label,
            'line_ids': [
                Command.create({
                    'name': label,
                    'account_id': payable.account_id.id,
                    'partner_id': payable.partner_id.id,
                    'debit': float(amount),
                }),
                *credits,
            ],
        })
        move.action_post()
        self._assert_settlement_move(move, company, plan, amount)
        return move

    def _assert_settlement_move(self, move, company, plan, amount):
        if move.state != 'posted' or move.company_id != company or move.journal_id != plan['journal']:
            raise UserError(_('The custody settlement entry did not post on the company custody journal.'))
        unexpected = move.line_ids.filtered(
            lambda line: line.account_id != plan['account'] and line.account_id.account_type != 'liability_payable'
        )
        if unexpected or move.line_ids.filtered(lambda line: line.account_id.account_type == 'asset_cash'):
            raise UserError(_('The settlement entry can only debit the vendor payable and credit the custody asset.'))
        if not _same(company, sum(move.line_ids.mapped('debit')), amount):
            raise UserError(_('The custody settlement entry is not balanced to the vendor bill.'))
        if not _same(company, sum(move.line_ids.mapped('credit')), amount):
            raise UserError(_('The custody settlement entry is not balanced to the vendor bill.'))

    def _reconcile(self, company, bill, representative, plan, move):
        payable = self._open_payable(bill)
        settlement_payable = move.line_ids.filtered(
            lambda line: line.account_id == payable.account_id and line.partner_id == payable.partner_id and line.debit > 0
        )
        if len(settlement_payable) != 1 or not _same(company, settlement_payable.debit, plan['amount']):
            raise UserError(_('The vendor payable settlement line is incomplete.'))
        (payable | settlement_payable).reconcile()
        account = plan['account']
        if plan['mechanism'] == 'pcust':
            credit = move.line_ids.filtered(
                lambda line: line.account_id == account and line.partner_id == representative
                and line.baseer_procurement_custody_id == plan['custody'] and line.credit > 0
            )
            if len(credit) != 1:
                raise UserError(_('The petty-cash settlement credit is incomplete.'))
            open_debits = self.env['account.move.line'].sudo().search([
                ('account_id', '=', account.id),
                ('partner_id', '=', representative.id),
                ('company_id', '=', company.id),
                ('parent_state', '=', 'posted'),
                ('reconciled', '=', False),
                ('debit', '>', 0),
                ('baseer_procurement_custody_id', '=', plan['custody'].id),
                ('id', '!=', credit.id),
            ])
            (open_debits | credit).reconcile()
            credit.invalidate_recordset(['reconciled', 'amount_residual'])
            if not credit.reconciled:
                raise UserError(_('The petty-cash settlement credit did not reconcile to the funded custody.'))
            return
        for advance, part in plan['allocations']:
            credit = move.line_ids.filtered(
                lambda line, advance=advance: line.account_id == account and line.partner_id == representative
                and line.baseer_representative_petty_cash_id == advance and line.credit > 0
            )
            if len(credit) != 1 or not _same(company, credit.credit, part):
                raise UserError(_('A representative petty-cash allocation credit is incomplete.'))
            open_debits = self.env['account.move.line'].sudo().search([
                ('account_id', '=', account.id),
                ('partner_id', '=', representative.id),
                ('company_id', '=', company.id),
                ('parent_state', '=', 'posted'),
                ('reconciled', '=', False),
                ('debit', '>', 0),
                ('baseer_representative_petty_cash_id', '=', advance.id),
                ('id', '!=', credit.id),
            ])
            (open_debits | credit).reconcile()
            credit.invalidate_recordset(['reconciled', 'amount_residual'])
            if not credit.reconciled:
                raise UserError(_('A representative advance did not reconcile for this vendor bill.'))

    def _lock_scope(self, company, representative, bill, plan):
        # Company then representative, matching the representative-balance mutex,
        # before the bill and the selected custody or advances.
        self.env['baseer.procurement.representative.advance']._baseer_lock_representative_balance(
            company, representative,
        )
        self.env.cr.execute('SELECT pg_advisory_xact_lock(%s)', [self._lock_token(company.id, bill.id)])
        self.env.cr.execute('SELECT id FROM account_move WHERE id = %s FOR UPDATE', [bill.id])
        self.env.cr.execute('UPDATE account_move SET id = id WHERE id = %s', [bill.id])
        self._lock_source(company, representative, plan)

    def _lock_source(self, company, representative, plan):
        if plan['mechanism'] == 'pcust' and plan['custody']:
            plan['custody']._lock()
            return
        if plan['mechanism'] != 'rpc':
            return
        advance_ids = self.env['baseer.procurement.representative.advance'].sudo().search([
            ('company_id', '=', company.id),
            ('representative_partner_id', '=', representative.id),
            ('movement_type', '=', 'funding'),
            ('state', '=', 'posted'),
        ], order='id').ids
        if not advance_ids:
            return
        self.env.cr.execute(
            'SELECT id FROM baseer_procurement_representative_advance WHERE id IN %s ORDER BY id FOR UPDATE',
            [tuple(advance_ids)],
        )
        self.env.cr.execute(
            'UPDATE baseer_procurement_representative_advance SET id = id WHERE id IN %s',
            [tuple(advance_ids)],
        )
        self.env['baseer.procurement.representative.advance'].browse(advance_ids).invalidate_recordset()

    @api.model
    def _plan(self, company, bill, representative, custody_id):
        amount = self._bill_amount(bill, company)
        custody = self._select_custody(company, representative, custody_id)
        if custody:
            account, journal = company._baseer_procurement_custody_ready()
            self._check_lock_date(company, journal, bill.invoice_date)
            self.env['baseer.procurement.custody.period.close'].sudo()._ensure_month_open(
                custody, representative, bill.invoice_date,
            )
            module_balance = _quantize(custody._representative_balance(representative))
            ledger_balance = self._open_debit_total(company, account, representative, [
                ('baseer_procurement_custody_id', '=', custody.id),
            ])
            spendable = min(module_balance, ledger_balance)
            if spendable < amount:
                raise UserError(_('The available petty-cash balance is not sufficient for this vendor bill.'))
            return {
                'mechanism': 'pcust',
                'custody': custody,
                'account': account,
                'journal': journal,
                'amount': amount,
                'allocations': [],
                'remaining_before': module_balance,
            }
        issue = company._baseer_representative_petty_cash_setup_issue()
        if issue:
            raise UserError(issue)
        account, journal = company._baseer_representative_petty_cash_ready()
        self._check_lock_date(company, journal, bill.invoice_date)
        available = self.env['baseer.procurement.representative.advance']._baseer_representative_available_amount(
            company, representative,
        )
        if available <= 0:
            raise UserError(_('No open funded representative petty cash is available for this purchase representative.'))
        if amount > available:
            raise UserError(_('The available representative petty-cash balance is not sufficient for this vendor bill.'))
        allocations = self._allocate_advances(company, representative, account, amount)
        return {
            'mechanism': 'rpc',
            'custody': self.env['baseer.procurement.custody'],
            'account': account,
            'journal': journal,
            'amount': amount,
            'allocations': allocations,
            'remaining_before': available,
        }

    def _allocate_advances(self, company, representative, account, amount):
        advances = self.env['baseer.procurement.representative.advance'].sudo().search([
            ('company_id', '=', company.id),
            ('representative_partner_id', '=', representative.id),
            ('movement_type', '=', 'funding'),
            ('state', '=', 'posted'),
        ], order='movement_date asc, id asc')
        remaining = amount
        allocations = []
        for advance in advances:
            advance.invalidate_recordset(['remaining_amount', 'returned_amount', 'settled_amount'])
            module_open = _quantize(advance.remaining_amount)
            ledger_open = self._open_debit_total(company, account, representative, [
                ('baseer_representative_petty_cash_id', '=', advance.id),
            ])
            spendable = min(module_open, ledger_open)
            if spendable <= 0:
                continue
            part = min(remaining, spendable)
            allocations.append((advance, part))
            remaining = (remaining - part).quantize(MONEY_QUANTUM)
            if remaining <= 0:
                break
        if remaining > 0:
            raise UserError(_('The available representative petty-cash balance is not sufficient for this vendor bill.'))
        return allocations

    def _open_debit_total(self, company, account, representative, extra_domain):
        lines = self.env['account.move.line'].sudo().search([
            ('company_id', '=', company.id),
            ('account_id', '=', account.id),
            ('partner_id', '=', representative.id),
            ('parent_state', '=', 'posted'),
            ('reconciled', '=', False),
            ('debit', '>', 0),
            *extra_domain,
        ])
        return sum((_quantize(line.amount_residual) for line in lines), Decimal('0.00')).quantize(MONEY_QUANTUM)

    def _select_custody(self, company, representative, custody_id):
        Custody = self.env['baseer.procurement.custody'].sudo().with_company(company)
        individual = Custody.browse()
        for custody in Custody.search([
            ('company_id', '=', company.id),
            ('state', '=', 'open'),
            ('is_company_pool', '=', False),
        ]):
            try:
                partner = custody._representative_partner()
            except (ValidationError, UserError):
                continue
            if partner == representative:
                individual |= custody
        pools = Custody.search([
            ('company_id', '=', company.id),
            ('state', '=', 'open'),
            ('is_company_pool', '=', True),
        ])
        if custody_id:
            chosen = Custody.browse(custody_id).exists()
            if not chosen or chosen.company_id != company or chosen.state != 'open':
                raise ValidationError(_('The selected petty cash is not an open custody in this company.'))
            if chosen.is_company_pool:
                if chosen not in pools:
                    raise ValidationError(_('The selected petty cash is not the open company custody.'))
            elif chosen not in individual:
                raise ValidationError(_('The selected petty cash does not belong to this purchase representative.'))
            return chosen
        if len(individual) > 1:
            raise UserError(_('More than one open petty cash matches this representative. The settlement source is ambiguous.'))
        if len(individual) == 1:
            return individual
        if len(pools) > 1:
            raise UserError(_('More than one company petty-cash pool is open. The settlement source is ambiguous.'))
        if len(pools) == 1:
            return pools
        return Custody.browse()

    def _matching_settlement(self, company, bill, representative, key):
        settlements = self.sudo().search([
            ('company_id', '=', company.id),
            ('state', '=', 'posted'),
            '|', ('idempotency_key', '=', key), ('vendor_bill_id', '=', bill.id),
        ])
        by_key = settlements.filtered(lambda settlement: settlement.idempotency_key == key)
        by_bill = settlements.filtered(lambda settlement: settlement.vendor_bill_id == bill)
        if len(by_key) > 1 or len(by_bill) > 1:
            raise UserError(_('Vendor-bill settlement records are duplicated. Settlement was not repeated.'))
        if by_key and by_bill and by_key == by_bill:
            if by_key.representative_partner_id != representative:
                raise UserError(_('This settlement reference was already used for a different purchase representative.'))
            return by_key
        if by_key:
            raise UserError(_('This settlement reference was already used for a different vendor bill.'))
        if by_bill:
            raise UserError(_('This vendor bill is already settled.'))
        return self.browse()

    @api.model
    def _check_entrypoint(self, entrypoint):
        if entrypoint == 'human':
            if not self.env.user.has_group('baseer_procurement_requests.group_procurement_accountant'):
                raise AccessError(_('Only a procurement accountant can settle an existing vendor bill.'))
            if not self.env.user.has_group('account.group_account_invoice'):
                raise AccessError(_('Only an invoice accountant can settle an existing vendor bill.'))
            return
        if entrypoint == 'agent':
            if not self.env.user.has_group('baseer_procurement_requests.group_procurement_invoice_agent'):
                raise AccessError(_('Only the invoice-agent settlement service can settle an agent vendor bill.'))
            return
        raise AccessError(_('This vendor-bill settlement entrypoint is not available.'))

    @api.model
    def _active_company(self):
        company = self.env.company
        if not company or company not in self.env.user.company_ids:
            raise AccessError(_('Switch to an authorized company before settling a vendor bill.'))
        return company

    @api.model
    def _key(self, idempotency_key):
        if not isinstance(idempotency_key, str):
            raise ValidationError(_('Enter a stable settlement reference.'))
        key = idempotency_key.strip()
        if not key or len(key) > KEY_MAX or any(character in key for character in ('\n', '\r', '\x00')):
            raise ValidationError(_('Enter a stable settlement reference.'))
        return key

    def _locate_bill(self, bill_id, company):
        _require_id(bill_id, _('vendor bill'))
        bill = self.env['account.move'].sudo().browse(bill_id).exists()
        if not bill or bill.company_id != company:
            raise ValidationError(_('The vendor bill must belong to the active company.'))
        return bill

    def _validate_unsettled_bill(self, bill, company):
        if bill.move_type != 'in_invoice':
            raise ValidationError(_('Only a supplier invoice can be settled against custody.'))
        if bill.state == 'cancel':
            raise ValidationError(_('A cancelled vendor bill cannot be settled.'))
        if bill.state not in ('draft', 'posted'):
            raise ValidationError(_('Only a draft or posted vendor bill can be settled.'))
        if not bill.partner_id or not bill.invoice_line_ids:
            raise ValidationError(_('The vendor bill needs a supplier and at least one invoice line.'))
        if not bill.invoice_date:
            raise ValidationError(_('The vendor bill needs an invoice date before settlement.'))
        if bill.currency_id != company.currency_id:
            raise ValidationError(_('The vendor bill currency must match the company currency.'))
        if any(line.currency_id and line.currency_id != company.currency_id for line in bill.line_ids):
            raise ValidationError(_('The vendor bill currency must match the company currency.'))
        self._bill_amount(bill, company)
        if bill.state == 'posted':
            self._assert_open_payable(bill, company, _quantize(bill.amount_total))
        return bill

    def _bill_amount(self, bill, company):
        amount = _quantize(bill.amount_total)
        if amount <= 0 or amount != _quantize(bill.amount_total):
            raise ValidationError(_('The vendor bill amount must be positive and use no more than two decimal places.'))
        if company.currency_id.compare_amounts(float(amount), 0.0) <= 0:
            raise ValidationError(_('The vendor bill amount must be positive.'))
        return amount

    def _assert_open_payable(self, bill, company, amount):
        if bill.payment_state in ('paid', 'in_payment', 'partial', 'reversed'):
            raise UserError(_('The vendor bill is already paid or has an outstanding reconciliation.'))
        payable = self._open_payable(bill)
        if payable.reconciled or payable.matched_debit_ids or payable.matched_credit_ids:
            raise UserError(_('The vendor bill is already paid or has an outstanding reconciliation.'))
        residual = _quantize(abs(payable.amount_residual))
        if residual != amount or not _same(company, bill.amount_residual, bill.amount_total):
            raise UserError(_('The vendor bill is already paid or has an outstanding reconciliation.'))
        return payable

    def _open_payable(self, bill):
        payables = bill.line_ids.filtered(lambda line: line.account_id.account_type == 'liability_payable' and not line.reconciled)
        if len(payables) != 1:
            raise UserError(_('The vendor bill payable is not available for a full custody settlement.'))
        return payables

    def _representative(self, representative_partner_id, company):
        _require_id(representative_partner_id, _('purchase representative'))
        representative = self.env['res.partner'].sudo().browse(representative_partner_id).exists()
        scoped = representative.with_company(company) if representative else representative
        if (not representative or not representative.active or representative.is_company or representative.parent_id
                or not scoped.is_purchase_representative
                or (representative.company_id and representative.company_id != company)):
            raise ValidationError(_('Choose an active purchase representative in this company.'))
        commercial = representative.commercial_partner_id
        if commercial != representative:
            raise ValidationError(_('Choose the purchase representative contact, not a related commercial record.'))
        return representative

    @api.model
    def _check_agent_tag(self, bill):
        if AGENT_TAG not in (bill.ref or ''):
            raise ValidationError(_('The vendor bill reference must include the invoice-agent tag.'))

    @api.model
    def _check_lock_date(self, company, journal, invoice_date):
        if company._get_violated_lock_dates(invoice_date, False, journal):
            raise ValidationError(_('The vendor-bill settlement date is locked.'))

    @staticmethod
    def _lock_token(company_id, record_id):
        folded = zlib.crc32(('%s:%s' % (company_id, record_id)).encode()) & 0x7FFFFFFF
        return (int(company_id) << 32) ^ folded


class RepresentativeAdvanceVendorBillRemaining(models.Model):
    _inherit = 'baseer.procurement.representative.advance'

    bill_allocation_ids = fields.One2many(
        'baseer.procurement.vendor.bill.settlement.allocation', 'advance_id',
        readonly=True, string='Existing vendor-bill allocations',
    )

    @api.depends(
        'amount', 'movement_type',
        'return_ids.amount', 'return_ids.state',
        'settlement_ids.amount', 'settlement_ids.state',
        'bill_allocation_ids.amount', 'bill_allocation_ids.state',
    )
    def _compute_returned_amount(self):
        super()._compute_returned_amount()
        grouped = {}
        if self.ids:
            allocations = self.env['baseer.procurement.vendor.bill.settlement.allocation'].search([
                ('advance_id', 'in', self.ids),
                ('state', '=', 'posted'),
            ])
            for allocation in allocations:
                grouped[allocation.advance_id.id] = grouped.get(allocation.advance_id.id, 0.0) + allocation.amount
        for record in self:
            extra = grouped.get(record.id, 0.0)
            if not extra:
                continue
            record.settled_amount += extra
            if record.movement_type == 'funding':
                record.remaining_amount = record.amount - record.returned_amount - record.settled_amount
