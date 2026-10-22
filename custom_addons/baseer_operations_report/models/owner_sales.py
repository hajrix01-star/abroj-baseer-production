"""Private stored sales headers. Sales and tender labels never attest cash.

No tax calculation or line-price allocation belongs to this reader. SQL reads
only identities to prove ORM visibility and parent membership under this user.
"""

from decimal import Decimal, InvalidOperation, localcontext

from pytz import UTC

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

from .operations import INVOICE_TYPES, POS_STATES


class OperationsOwnerSales(models.AbstractModel):
    _inherit = 'baseer.operations.report'

    def _owner_sales_money(self, value, currency):
        try:
            amount = Decimal(str(value))
            rounding = Decimal(str(currency.rounding))
            if (not amount.is_finite() or abs(amount) >= Decimal('1e18')
                    or not rounding.is_finite() or rounding <= 0
                    or amount != amount.quantize(Decimal('.01'))
                    or amount % rounding):
                self._deny_incomplete_source()
            return amount.quantize(Decimal('.01'))
        except (InvalidOperation, ValueError, TypeError):
            self._deny_incomplete_source()

    def _owner_sales_currency(self, source, company):
        source.currency_id.check_access('read')
        if source.currency_id != company.currency_id:
            raise AccessError(_('Foreign-currency sales are not supported by this private reader.'))

    def _owner_sales_pairs(self, parents, field_name, child_model, inverse):
        """Batch one-to-many evidence; an accessible union is not sufficient."""
        children = parents[field_name]
        children.check_access('read')
        child = self.env[child_model]
        child.flush_model([inverse])
        self.env.cr.execute(
            'SELECT "%s", id FROM "%s" WHERE "%s"=ANY(%%s)' % (
                inverse, child._table, inverse), [parents.ids],
        )
        if set(self.env.cr.fetchall()) != {
                (row[inverse].id, row.id) for row in children}:
            self._deny_incomplete_source()
        return children

    def _owner_sales_orders(self, orders, company):
        orders.check_access('read')
        sessions = orders.session_id
        configs = sessions.config_id
        journals = configs.journal_id
        for records in (sessions, configs, journals, orders.config_id):
            records.check_access('read')
        closed = sessions.filtered(lambda session: session.state == 'closed')
        closed_moves = closed.move_id
        closed_moves.check_access('read')
        closed_moves.journal_id.check_access('read')
        closing_sessions = self._owner_sales_pairs(
            closed_moves, 'pos_session_ids', 'pos.session', 'move_id')
        closing_sessions.config_id.check_access('read')
        closing_sessions.config_id.journal_id.check_access('read')
        # A closing entry's entire inverse is evidence, including sessions
        # with no selected-period orders. Never validate only the visible period.
        for session in closed | closing_sessions:
            move = session.move_id
            config = session.config_id
            if (session.state != 'closed' or session.company_id != company
                    or not config or config.company_id != company
                    or not config.journal_id or config.journal_id.company_id != company
                    or not move or move not in closed_moves
                    or move.state != 'posted' or move.company_id != company
                    or move.journal_id != config.journal_id
                    or session not in move.pos_session_ids):
                self._deny_incomplete_source()
        zone = self._company_timezone(company) if orders.filtered(lambda order: order.source == 'pos') else None
        lines = self._pos_lines_batch(orders)
        payments = self._owner_sales_pairs(
            orders, 'payment_ids', 'pos.payment', 'pos_order_id')
        methods = payments.payment_method_id
        methods.check_access('read')
        summaries = orders.baseer_summary_id
        summaries.check_access('read')
        # Each summary session has exactly its approved source order.
        summary_sessions = summaries.session_id
        summary_sessions.check_access('read')
        self._owner_sales_pairs(summary_sessions, 'order_ids', 'pos.order', 'session_id')
        payment_map = {order.id: [] for order in orders}
        for payment in payments:
            method = payment.payment_method_id
            if (not method or method.company_id != company
                    or payment.company_id != company
                    or payment.session_id != payment.pos_order_id.session_id):
                self._deny_incomplete_source()
            payment_map[payment.pos_order_id.id].append((
                'payment_%s' % method.id, method.name,
                self._owner_sales_money(payment.amount, company.currency_id),
            ))
        result = {}
        for order in orders:
            session, config = order.session_id, order.session_id.config_id
            if (order.company_id != company or order.state not in POS_STATES
                    or order.source not in ('pos', 'baseer_summary')
                    or not session or session.company_id != company
                    or not config or config.company_id != company
                    or order.config_id != config or not config.journal_id
                    or config.journal_id.company_id != company):
                self._deny_incomplete_source()
            self._owner_sales_currency(order, company)
            amount = self._owner_sales_money(order.amount_total, company.currency_id)
            amount = -abs(amount) if order.is_refund else amount
            if order.source == 'baseer_summary':
                summary = order.baseer_summary_id
                if (not summary or summary.state != 'approved'
                        or summary.company_id != company or summary.order_id != order
                        or summary.session_id != session or session.baseer_summary_id != summary
                        or session.order_ids != order or summary.zero_sales
                        or self._owner_sales_money(summary.amount_gross, company.currency_id) != amount):
                    self._deny_incomplete_source()
                self._owner_sales_currency(summary, company)
                day = summary.business_date
            else:
                if order.baseer_summary_id or not order.date_order:
                    self._deny_incomplete_source()
                day = UTC.localize(fields.Datetime.to_datetime(order.date_order)).astimezone(
                    zone).date()
            if not day:
                self._deny_incomplete_source()
            if not lines[order.id]:
                if not self._is_proven_empty_native_pos_order(order, company, lines[order.id]):
                    self._deny_incomplete_source()
                result[order.id] = None
                continue
            tenders = payment_map[order.id]
            valid = bool(tenders) and sum((item[2] for item in tenders), Decimal(0)) == amount
            valid = valid and all(value * amount >= 0 and (amount or not value)
                                  for _key, _name, value in tenders)
            channels = {}
            if valid:
                for key, name, value in tenders:
                    previous = channels.get(key, (name, Decimal(0)))
                    channels[key] = (name, previous[1] + value)
            else:
                channels['unallocated'] = (_('Unallocated'), amount)
            result[order.id] = {
                'company_id': company.id, 'direction': 'incoming',
                'source_model': 'pos.order', 'source_id': order.id,
                'line_model': 'pos.order', 'line_id': order.id,
                'amount': amount, 'date': day, 'ledger_confirmed': False,
                'sales_posted': False,
                'channels': [(key, name, value) for key, (name, value) in sorted(channels.items())],
            }
        return result

    def _owner_sales_invoices(self, moves, company):
        moves.check_access('read')
        moves.journal_id.check_access('read')
        for move in moves:
            self._owner_sales_currency(move, company)
        lines = self._owner_sales_pairs(moves, 'line_ids', 'account.move.line', 'move_id')
        accounts = lines.account_id
        accounts.check_access('read')
        by_move = {move.id: [] for move in moves}
        for line in lines:
            if (line.company_id != company or line.journal_id != line.move_id.journal_id
                    or line.currency_id != company.currency_id
                    or not line.account_id or company not in line.account_id.company_ids):
                self._deny_incomplete_source()
            balance = self._owner_sales_money(line.balance, company.currency_id)
            debit = self._owner_sales_money(line.debit, company.currency_id)
            credit = self._owner_sales_money(line.credit, company.currency_id)
            if (debit < 0 or credit < 0 or debit - credit != balance
                    or self._owner_sales_money(line.amount_currency, company.currency_id) != balance):
                self._deny_incomplete_source()
            by_move[line.move_id.id].append((line.account_id.account_type, balance))
        result = {}
        for move in moves:
            if (move.company_id != company or move.state != 'posted'
                    or move.move_type not in INVOICE_TYPES or not move.invoice_date
                    or not move.journal_id or move.journal_id.company_id != company):
                self._deny_incomplete_source()
            total = self._owner_sales_money(move.amount_total, company.currency_id)
            amount = -total if move.move_type == 'out_refund' else total
            rows = by_move[move.id]
            receivable = [value for kind, value in rows if kind == 'asset_receivable']
            if (not rows or not receivable or sum((value for _kind, value in rows), Decimal(0))
                    or sum(receivable, Decimal(0)) != amount):
                self._deny_incomplete_source()
            result[move.id] = {
                'company_id': company.id, 'direction': 'incoming',
                'source_model': 'account.move', 'source_id': move.id,
                'line_model': 'account.move', 'line_id': move.id,
                'amount': amount, 'date': move.invoice_date,
                'ledger_confirmed': False, 'sales_posted': True,
                'channels': [('unallocated', _('Unallocated'), amount)],
            }
        return result

    @api.model
    def _owner_sales(self, company, start, end, journal_ids):
        """Stored signed headers only, under the current user's active company."""
        company.ensure_one()
        if (company.id != self.env.company.id or company.id not in {1, 2, 3, 56}
                or company.id not in self.env.user.company_ids.ids):
            raise AccessError(_('Only an authorized active company may be reported.'))
        company = self.env['res.company'].browse(company.id)
        company.check_access('read')
        company.currency_id.check_access('read')
        start, end = fields.Date.to_date(start), fields.Date.to_date(end)
        if not start or not end or start > end:
            self._deny_incomplete_source()
        if (not isinstance(journal_ids, (list, tuple))
                or any(type(item) is not int or item <= 0 for item in journal_ids)):
            self._deny_incomplete_source()
        journals = self.env['account.journal'].browse(journal_ids).exists()
        journals.check_access('read')
        if set(journals.ids) != set(journal_ids) or any(row.company_id != company for row in journals):
            self._deny_incomplete_source()
        self._require_read((
            'pos.order', 'pos.order.line', 'pos.session', 'pos.config',
            'pos.payment', 'pos.payment.method', 'baseer.pos.summary',
            'account.move', 'account.move.line', 'account.account', 'account.journal',
        ))
        with localcontext() as context:
            context.prec = 60
            orders = self._pos_records(company, start, end, list(journal_ids))
            period_moves = self._invoice_records(company, start, end, list(journal_ids))
            orders.check_access('read')
            moves = period_moves | orders.account_move
            moves.check_access('read')
            # The inverse census intentionally has no date/company restriction.
            # Every source linked to an excluded invoice must be proven.
            linked = self._owner_sales_pairs(moves, 'pos_order_ids', 'pos.order', 'account_move')
            order_facts = self._owner_sales_orders(orders | linked, company)
            invoice_facts = self._owner_sales_invoices(moves, company)
            skipped = set()
            for move in moves:
                linked_orders = move.pos_order_ids
                if linked_orders:
                    if any(order.account_move != move or order_facts[order.id] is None
                           for order in linked_orders):
                        self._deny_incomplete_source()
                    if sum((order_facts[order.id]['amount'] for order in linked_orders), Decimal(0)) != invoice_facts[move.id]['amount']:
                        self._deny_incomplete_source()
                    skipped.add(move.id)
            events = []
            for order in orders:
                fact = order_facts[order.id]
                if fact is not None:
                    if order.account_move:
                        if order.account_move.id not in skipped or order not in order.account_move.pos_order_ids:
                            self._deny_incomplete_source()
                        fact['linked_invoice_id'] = order.account_move.id
                        fact['invoice_not_readded'] = True
                    events.append(fact)
            events.extend(invoice_facts[move.id] for move in period_moves if move.id not in skipped)
            return events
