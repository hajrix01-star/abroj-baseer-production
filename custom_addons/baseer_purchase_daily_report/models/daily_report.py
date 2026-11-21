"""Read-only, narrowly scoped supplier bill projections for Baseer roles."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


PAGE_SIZE = 50
MAX_DAYS = 366
ZERO = Decimal('0')
PAYMENT_STATES = frozenset(('all', 'not_paid', 'partial', 'in_payment', 'paid', 'reversed', 'blocked'))
ALLOWED_ROLES = (
    'baseer_access_roles.group_owner',
    'baseer_access_roles.group_accountant',
    'baseer_access_roles.group_cashier',  # Branch manager, not POS cashier.
)


def _decimal(value):
    return Decimal(str(value or 0))


def _money(value, currency):
    """Render using the document currency's decimal places and western digits."""
    digits = currency.decimal_places
    unit = Decimal(1).scaleb(-digits)
    value = _decimal(value).quantize(unit, rounding=ROUND_HALF_UP)
    # Avoid the confusing accounting presentation of negative zero.
    if not value:
        value = abs(value)
    return f'{value:,.{digits}f}'


def _quantity(value):
    # Preserve meaningful product precision in the read-only detail.
    value = _decimal(value).quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP)
    return format(value, 'f').rstrip('0').rstrip('.') or '0'


class PurchaseDailyReport(models.AbstractModel):
    _name = 'baseer.purchase.daily.report'
    _description = 'Daily purchase report service'

    @api.model
    def _scope(self):
        # Authorize against the real user BEFORE any privileged data access.
        if not any(self.env.user.has_group(group) for group in ALLOWED_ROLES):
            raise AccessError(self.env._('You do not have access to the purchase report.'))
        company = self.env.company
        if company.id not in self.env.user.company_ids.ids:
            raise AccessError(self.env._('The active company is not available to you.'))
        return company

    @api.model
    def _date(self, value):
        if not isinstance(value, str):
            raise ValidationError(self.env._('Enter a valid date.'))
        try:
            result = date.fromisoformat(value)
        except (TypeError, ValueError):
            raise ValidationError(self.env._('Enter a valid date.'))
        if result.isoformat() != value:
            raise ValidationError(self.env._('Enter a valid date.'))
        return result

    @api.model
    def _domain(self, company, first, last, status):
        if not isinstance(status, str) or status not in PAYMENT_STATES:
            raise ValidationError(self.env._('Choose a valid payment status.'))
        domain = [
            ('company_id', '=', company.id),
            ('state', '=', 'posted'),
            ('move_type', 'in', ('in_invoice', 'in_refund')),
            ('invoice_date', '>=', first),
            ('invoice_date', '<=', last),
        ]
        if status != 'all':
            domain.append(('payment_state', '=', status))
        return domain

    @api.model
    def _cash_allocation(self, bill):
        """Return proven cash allocated to this bill, never total less residual.

        Foreign currency and mixed write-offs cannot be attributed to cash
        without an additional policy; fail closed rather than invent a value.
        """
        company = bill.company_id
        currency = company.currency_id
        pending = False
        unavailable = bill.currency_id != currency
        amount = ZERO
        sign = Decimal('-1') if bill.move_type == 'in_refund' else Decimal('1')
        expected_type = 'inbound' if sign < 0 else 'outbound'
        expected_sign = -1 if sign < 0 else 1
        partial_ids = set()
        allocated_payment_ids = set()

        for payment in bill.matched_payment_ids:
            if payment.company_id != company:
                unavailable = True
            elif payment.state == 'in_process':
                pending = True
            elif payment.state == 'paid' and not payment.move_id:
                unavailable = True

        terms = bill.line_ids.filtered(lambda line: line.account_id.account_type == 'liability_payable')
        for term in terms:
            for partial in term.matched_debit_ids | term.matched_credit_ids:
                if partial.id in partial_ids:
                    continue
                partial_ids.add(partial.id)
                counterpart = partial.credit_move_id if partial.debit_move_id == term else partial.debit_move_id
                other = counterpart.move_id
                payment = other.origin_payment_id or counterpart.payment_id
                statement = other.statement_line_id or counterpart.statement_line_id
                if not payment and not statement:
                    # A posted manual entry can settle payable against a bank
                    # account without a payment/statement model. We cannot
                    # safely infer its cash attribution; never report zero as
                    # an established payment amount in that case. Credit notes
                    # and entries with no cash leg remain noncash settlements.
                    if (other.move_type == 'entry' and other.line_ids.filtered(
                            lambda line: line.account_id.account_type == 'asset_cash'
                            and not currency.is_zero(line.balance))):
                        unavailable = True
                    continue
                if payment:
                    allocated_payment_ids.add(payment.id)
                if (other.company_id != company or other.state != 'posted'
                        or counterpart.company_id != company
                        or expected_sign * counterpart.balance <= 0):
                    unavailable = True
                    continue
                if payment:
                    if payment.company_id != company or payment.payment_type != expected_type:
                        unavailable = True
                        continue
                    if payment.state == 'in_process':
                        pending = True
                        continue
                    if payment.state != 'paid':
                        unavailable = True
                        continue
                    if payment.currency_id != currency or payment.journal_id.type not in ('bank', 'cash'):
                        unavailable = True
                        continue
                    liquidity, payable, writeoffs = payment._seek_for_lines()
                    # One payable leg and one liquidity leg prove direct allocation.
                    if (len(liquidity) != 1 or len(payable) != 1 or writeoffs
                            or payable != counterpart
                            or liquidity.company_id != company
                            or liquidity.account_id.account_type != 'asset_cash'
                            or not currency.is_zero(abs(liquidity.balance) - abs(counterpart.balance))
                            or not currency.is_zero(abs(payment.amount) - abs(counterpart.balance))):
                        unavailable = True
                        continue
                else:
                    # Direct bank-statement posting: one liquidity and one payable
                    # line, with no extra lines that might contain write-offs.
                    lines = other.line_ids.filtered(lambda line: not currency.is_zero(line.balance))
                    liquidity = lines.filtered(lambda line: line.account_id.account_type == 'asset_cash')
                    if (statement.company_id != company or statement.currency_id != currency
                            or other.journal_id.type not in ('bank', 'cash')
                            or len(lines) != 2 or len(liquidity) != 1
                            or counterpart not in lines
                            or expected_sign * liquidity.balance >= 0
                            or not currency.is_zero(abs(liquidity.balance) - abs(counterpart.balance))):
                        unavailable = True
                        continue
                if bill.currency_id != currency:
                    unavailable = True
                    continue
                amount += sign * _decimal(partial.amount)
        # A matched confirmed payment that has no payable allocation is not
        # evidence of a zero paid amount for this particular invoice.
        if any(payment.state == 'paid' and payment.id not in allocated_payment_ids
               for payment in bill.matched_payment_ids):
            unavailable = True
        return amount, pending, unavailable

    @api.model
    def _prefetch_cash_allocation(self, bills):
        """Prime relational caches for one bounded invoice batch."""
        lines = bills.mapped('line_ids')
        bills.mapped('matched_payment_ids')
        partials = lines.mapped('matched_debit_ids') | lines.mapped('matched_credit_ids')
        counterparts = partials.mapped('debit_move_id') | partials.mapped('credit_move_id')
        counterparts.mapped('move_id.line_ids')

    @api.model
    def get_days(self, date_from, date_to, status='all'):
        company = self._scope()
        first, last = self._date(date_from), self._date(date_to)
        if first > last or (last - first).days + 1 > MAX_DAYS:
            raise ValidationError(self.env._('Choose a date range of at most 366 days.'))
        domain = self._domain(company, first, last, status)
        # The sole privileged query is bounded by the verified company/domain.
        rows = self.env['account.move'].sudo()._read_group(
            domain, ['invoice_date:day'],
            ['amount_total_signed:sum', 'amount_residual_signed:sum', '__count'],
        )
        currency = company.currency_id
        days = []
        for invoice_date, signed_total, signed_residual, count in rows:
            total, residual = -_decimal(signed_total), -_decimal(signed_residual)
            days.append({
                'date': fields.Date.to_string(invoice_date), 'count': count,
                'total': _money(total, currency), 'residual': _money(residual, currency),
                'paid': _money(ZERO, currency), 'paid_pending': False,
                'paid_unavailable': False,
            })
        by_date = {day['date']: day for day in days}
        totals = {key: ZERO for key in by_date}
        # Iterate bounded batches; a day's 50-row UI page must not truncate totals.
        last_id = 0
        Move = self.env['account.move'].sudo()
        while True:
            batch = Move.search(domain + [('id', '>', last_id)], order='id', limit=200)
            if not batch:
                break
            # Explicit bulk prefetch: one2many and many2many relations otherwise
            # trigger queries per bill when accessed through singleton calls.
            self._prefetch_cash_allocation(batch)
            for bill in batch:
                key = fields.Date.to_string(bill.invoice_date)
                paid, pending, unavailable = self._cash_allocation(bill)
                totals[key] += paid
                by_date[key]['paid_pending'] |= pending
                by_date[key]['paid_unavailable'] |= unavailable
            last_id = batch[-1].id
        for key, day in by_date.items():
            day['paid'] = None if day['paid_unavailable'] else _money(totals[key], currency)
        days.sort(key=lambda item: item['date'], reverse=True)
        return {'company': {'id': company.id, 'name': company.name, 'currency': currency.name}, 'days': days}

    @api.model
    def _bill_row(self, move):
        currency = move.currency_id
        company_currency = move.company_currency_id
        sign = -1 if move.move_type == 'in_refund' else 1
        paid, pending, unavailable = self._cash_allocation(move)
        return {
            'id': move.id, 'number': move.name or '',
            'vendor': move.partner_id.display_name or '', 'reference': move.ref or '',
            'date': fields.Date.to_string(move.invoice_date),
            'status': move.payment_state or 'not_paid', 'kind': move.move_type,
            'currency': currency.name,
            'total': _money(sign * _decimal(move.amount_total), currency),
            'residual': _money(sign * _decimal(move.amount_residual), currency),
            'company_total': _money(-_decimal(move.amount_total_signed), company_currency),
            'company_residual': _money(-_decimal(move.amount_residual_signed), company_currency),
            'paid': None if unavailable else _money(paid, currency),
            'paid_pending': pending, 'paid_unavailable': unavailable,
        }

    @api.model
    def get_day(self, day, status='all', offset=0):
        company = self._scope()
        selected = self._date(day)
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValidationError(self.env._('Choose a valid page.'))
        domain = self._domain(company, selected, selected, status)
        moves = self.env['account.move'].sudo()
        count = moves.search_count(domain)
        records = moves.search(domain, order='id desc', offset=offset, limit=PAGE_SIZE)
        self._prefetch_cash_allocation(records)
        return {
            'day': selected.isoformat(), 'rows': [self._bill_row(move) for move in records],
            'offset': offset, 'count': count, 'has_more': offset + len(records) < count,
        }

    @api.model
    def get_invoice(self, invoice_id):
        company = self._scope()
        if isinstance(invoice_id, bool) or not isinstance(invoice_id, int) or invoice_id <= 0:
            raise AccessError(self.env._('This purchase document is not available.'))
        # Revalidate type, state and exact company on every document request.
        move = self.env['account.move'].sudo().search([
            ('id', '=', invoice_id), ('company_id', '=', company.id),
            ('state', '=', 'posted'), ('move_type', 'in', ('in_invoice', 'in_refund')),
        ], limit=1)
        if not move:
            raise AccessError(self.env._('This purchase document is not available.'))
        result = self._bill_row(move)
        currency = move.currency_id
        sign = -1 if move.move_type == 'in_refund' else 1
        result.update({
            'due_date': fields.Date.to_string(move.invoice_date_due) if move.invoice_date_due else '',
            'untaxed': _money(sign * _decimal(move.amount_untaxed), currency),
            'tax': _money(sign * _decimal(move.amount_tax), currency),
            'lines': [{
                'description': line.name or '',
                'kind': line.display_type,
                'quantity': _quantity(line.quantity),
                'discount': _quantity(line.discount),
                # Unit prices may have more precision than a currency amount.
                'unit_price': _quantity(line.price_unit),
                'subtotal': _money(sign * _decimal(line.price_subtotal), currency),
                'total': _money(sign * _decimal(line.price_total), currency),
            } for line in move.invoice_line_ids],
            # These native accounting adjustment lines are not included in
            # invoice_line_ids; present them independently rather than folding
            # them into the product subtotal or omitting their effect.
            'adjustments': [{
                'description': line.name or '', 'kind': line.display_type,
                'amount': _money(line.balance, move.company_currency_id),
            } for line in move.line_ids if line.display_type in (
                'discount', 'rounding', 'epd', 'non_deductible_product',
                'non_deductible_product_total', 'non_deductible_tax',
            )],
        })
        return result
