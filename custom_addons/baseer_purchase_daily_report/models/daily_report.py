"""Read-only, narrowly scoped supplier bill projections for Baseer roles."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


PAGE_SIZE = 50
MAX_DAYS = 366
ZERO = Decimal('0')
PAYMENT_STATES = frozenset(('all', 'not_paid', 'partial', 'in_payment', 'paid', 'reversed', 'blocked'))
STATUS_FILTERS = PAYMENT_STATES | frozenset(('draft', 'unapproved'))
METHOD_SPECIAL = frozenset(('all', 'osama', 'cash'))
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
        if not isinstance(status, str) or status not in STATUS_FILTERS:
            raise ValidationError(self.env._('Choose a valid payment status.'))
        domain = [
            ('company_id', '=', company.id),
            ('move_type', 'in', ('in_invoice', 'in_refund')),
            ('invoice_date', '>=', first),
            ('invoice_date', '<=', last),
        ]
        if status == 'draft':
            domain.append(('state', '=', 'draft'))
        elif status == 'unapproved':
            # Distinct definition from drafts: not reviewed, and not cancelled.
            # In production restaurants this currently matches state=draft,
            # because every draft has checked=False and every posted bill is reviewed.
            domain.extend([('checked', '=', False), ('state', '!=', 'cancel')])
        else:
            domain.append(('state', '=', 'posted'))
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
        moves = counterparts.mapped('move_id')
        moves.mapped('line_ids.account_id')
        moves.mapped('line_ids.partner_id')
        moves.mapped('journal_id.bank_account_id')

    @api.model
    def _method_key_valid(self, key):
        if not isinstance(key, str):
            return False
        if key in METHOD_SPECIAL:
            return True
        if key.startswith('journal:'):
            suffix = key[8:]
            return suffix.isdigit() and int(suffix) > 0
        return False

    @api.model
    def _text_blob(self, *parts):
        return ' '.join(str(part or '') for part in parts)

    @api.model
    def _is_osama_settlement(self, journal, move, accounts, line_partners):
        """Osama custody: his journal/account, account ending 1994, or a settlement in his name."""
        bank = journal.bank_account_id
        numbers = self._text_blob(getattr(bank, 'acc_number', ''), getattr(bank, 'sanitized_acc_number', ''))
        names = self._text_blob(
            journal.display_name, journal.name, journal.code,
            move.ref, move.narration if 'narration' in move._fields else '',
            *[account.display_name for account in accounts],
            *[account.name for account in accounts],
            *[partner.display_name for partner in line_partners],
            *[partner.name for partner in line_partners],
        )
        lowered = names.casefold()
        if 'عهدة أسامة' in names or 'أسامة' in names or 'osama' in lowered:
            return True
        if 'عهدة مندوبي' in names or 'representative petty cash' in lowered:
            return True
        compact = ''.join(character for character in numbers if character.isdigit())
        if compact.endswith('1994') or '1994' in numbers:
            return True
        return False

    @api.model
    def _settlement_counterparts(self, bill):
        """Yield unique counterpart moves that settled this bill's payable terms."""
        seen = set()
        terms = bill.line_ids.filtered(lambda line: line.account_id.account_type == 'liability_payable')
        for term in terms:
            for partial in term.matched_debit_ids | term.matched_credit_ids:
                counterpart = partial.credit_move_id if partial.debit_move_id == term else partial.debit_move_id
                other = counterpart.move_id
                if other.id == bill.id or other.id in seen:
                    continue
                seen.add(other.id)
                yield other

    @api.model
    def _bill_methods(self, bill):
        """Classify how this bill was paid, matching production settlement journals."""
        methods = []
        seen = set()
        osama_label = self.env._('Paid via Osama')
        cash_label = self.env._('Paid in cash')

        def add(key, label):
            if key not in seen:
                seen.add(key)
                methods.append({'key': key, 'label': label})

        for other in self._settlement_counterparts(bill):
            journal = other.journal_id
            accounts = other.line_ids.mapped('account_id')
            liquidity_partners = other.line_ids.filtered(
                lambda line: line.account_id.account_type in ('asset_cash', 'asset_current')
            ).mapped('partner_id')
            if self._is_osama_settlement(journal, other, accounts, liquidity_partners):
                add('osama', osama_label)
                continue
            if journal.type == 'cash':
                add('cash', cash_label)
                continue
            add(f'journal:{journal.id}', journal.display_name or journal.name or journal.code or '')
        return methods

    @api.model
    def _status_card_rows(self, company, first, last, method):
        """Counts follow the date range and the selected payment-method card."""
        currency = company.currency_id
        cards = []
        for key, label in (
            ('not_paid', self.env._('Unpaid')),
            ('unapproved', self.env._('Unapproved')),
            ('draft', self.env._('Drafts')),
        ):
            moves = self.env['account.move'].sudo().search(self._domain(company, first, last, key))
            if method != 'all':
                self._prefetch_cash_allocation(moves)
                moves = moves.filtered(lambda move: any(item['key'] == method for item in self._bill_methods(move)))
            total = sum((-_decimal(move.amount_total_signed) for move in moves), ZERO)
            cards.append({
                'key': key, 'label': label, 'count': len(moves),
                'total': _money(total, currency),
            })
        return cards

    @api.model
    def get_days(self, date_from, date_to, status='all', method='all'):
        company = self._scope()
        first, last = self._date(date_from), self._date(date_to)
        if first > last or (last - first).days + 1 > MAX_DAYS:
            raise ValidationError(self.env._('Choose a date range of at most 366 days.'))
        if not self._method_key_valid(method):
            raise ValidationError(self.env._('Choose a valid payment method.'))
        domain = self._domain(company, first, last, status)
        currency = company.currency_id
        by_date = {}
        paid_totals = {}
        methods_acc = {}

        def day_row(invoice_date):
            key = fields.Date.to_string(invoice_date)
            if key not in by_date:
                by_date[key] = {
                    'date': key, 'count': 0, 'total': ZERO, 'residual': ZERO,
                    'paid': ZERO, 'paid_pending': False, 'paid_unavailable': False,
                }
                paid_totals[key] = ZERO
            return key

        last_id = 0
        Move = self.env['account.move'].sudo()
        while True:
            batch = Move.search(domain + [('id', '>', last_id)], order='id', limit=200)
            if not batch:
                break
            self._prefetch_cash_allocation(batch)
            for bill in batch:
                bill_methods = self._bill_methods(bill)
                total = -_decimal(bill.amount_total_signed)
                for item in bill_methods:
                    bucket = methods_acc.setdefault(item['key'], {'key': item['key'], 'label': item['label'], 'count': 0, 'total': ZERO})
                    bucket['count'] += 1
                    bucket['total'] += total
                if method != 'all' and method not in {item['key'] for item in bill_methods}:
                    continue
                key = day_row(bill.invoice_date)
                by_date[key]['count'] += 1
                by_date[key]['total'] += total
                by_date[key]['residual'] += -_decimal(bill.amount_residual_signed)
                paid, pending, unavailable = self._cash_allocation(bill)
                paid_totals[key] += paid
                by_date[key]['paid_pending'] |= pending
                by_date[key]['paid_unavailable'] |= unavailable
            last_id = batch[-1].id
        days = []
        for key in sorted(by_date, reverse=True):
            day = by_date[key]
            days.append({
                'date': day['date'], 'count': day['count'],
                'total': _money(day['total'], currency),
                'residual': _money(day['residual'], currency),
                'paid': None if day['paid_unavailable'] else _money(paid_totals[key], currency),
                'paid_pending': day['paid_pending'],
                'paid_unavailable': day['paid_unavailable'],
            })
        method_cards = []
        for key in ('osama', 'cash'):
            if key in methods_acc:
                method_cards.append(methods_acc.pop(key))
        method_cards.extend(sorted(methods_acc.values(), key=lambda item: (-item['count'], item['label'])))
        for card in method_cards:
            card['total'] = _money(card['total'], currency)
        return {
            'company': {'id': company.id, 'name': company.name, 'currency': currency.name},
            'days': days,
            'methods': method_cards,
            'statuses': self._status_card_rows(company, first, last, method),
        }

    @api.model
    def _entry_sources(self, moves):
        """Identify the audit creator of the actual input, without guessing a human actor."""
        if not moves:
            return {}
        company = moves[0].company_id
        lines = self.env['baseer.purchase.batch.line'].sudo().search([
            ('company_id', '=', company.id), ('move_id', 'in', moves.ids),
        ])
        by_move = {}
        for line in lines:
            by_move.setdefault(line.move_id.id, []).append(line)
        result = {}
        for move in moves:
            batch_lines = by_move.get(move.id, [])
            if len(batch_lines) == 1:
                result[move.id] = (batch_lines[0].create_uid.name or '', 'batch')
            elif batch_lines:
                result[move.id] = ('', 'unknown')
            else:
                result[move.id] = (move.create_uid.name or '', 'invoice')
        return result

    @api.model
    def _bill_row(self, move, entry_sources=None):
        currency = move.currency_id
        company_currency = move.company_currency_id
        sign = -1 if move.move_type == 'in_refund' else 1
        paid, pending, unavailable = self._cash_allocation(move)
        entered_by, entry_source = (entry_sources if entry_sources is not None else self._entry_sources(move)).get(move.id, ('', 'unknown'))
        return {
            'id': move.id, 'number': move.name or '',
            'vendor': move.partner_id.display_name or '', 'reference': move.ref or '',
            'date': fields.Date.to_string(move.invoice_date),
            'status': 'draft' if move.state == 'draft' else (move.payment_state or 'not_paid'), 'kind': move.move_type,
            'currency': currency.name,
            'total': _money(sign * _decimal(move.amount_total), currency),
            'residual': _money(sign * _decimal(move.amount_residual), currency),
            'company_total': _money(-_decimal(move.amount_total_signed), company_currency),
            'company_residual': _money(-_decimal(move.amount_residual_signed), company_currency),
            'paid': None if unavailable else _money(paid, currency),
            'paid_pending': pending, 'paid_unavailable': unavailable,
            'entered_by': entered_by, 'entry_source': entry_source,
            'payment_methods': self._bill_methods(move),
        }

    @api.model
    def get_day(self, day, status='all', offset=0, method='all'):
        company = self._scope()
        selected = self._date(day)
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValidationError(self.env._('Choose a valid page.'))
        if not self._method_key_valid(method):
            raise ValidationError(self.env._('Choose a valid payment method.'))
        domain = self._domain(company, selected, selected, status)
        moves = self.env['account.move'].sudo()
        records = moves.search(domain, order='id desc')
        self._prefetch_cash_allocation(records)
        if method != 'all':
            records = records.filtered(lambda move: any(item['key'] == method for item in self._bill_methods(move)))
        count = len(records)
        page = records[offset:offset + PAGE_SIZE]
        entry_sources = self._entry_sources(page)
        return {
            'day': selected.isoformat(), 'rows': [self._bill_row(move, entry_sources) for move in page],
            'offset': offset, 'count': count, 'has_more': offset + len(page) < count,
        }

    @api.model
    def get_invoice(self, invoice_id):
        company = self._scope()
        if isinstance(invoice_id, bool) or not isinstance(invoice_id, int) or invoice_id <= 0:
            raise AccessError(self.env._('This purchase document is not available.'))
        # Revalidate type, state and exact company on every document request.
        move = self.env['account.move'].sudo().search([
            ('id', '=', invoice_id), ('company_id', '=', company.id),
            ('state', 'in', ('posted', 'draft')),
            ('move_type', 'in', ('in_invoice', 'in_refund')),
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
