"""Posted purchases plus operating balances; no posting or source-document totals."""
from decimal import Decimal

from odoo.exceptions import AccessError, ValidationError
from odoo.fields import Domain

from ..contracts import MAX_SOURCE_ROWS, ZERO


EXPENSE_TYPES = ('expense', 'expense_other', 'expense_direct_cost', 'expense_depreciation')
BILL_TYPES = ('in_invoice', 'in_refund')
BATCH = 1000


def unavailable():
    # Never include private source names/IDs/amounts in this error.
    raise ValidationError('The spending source cannot be safely classified or read. The report is unavailable.')


class SpendingBudget:
    """One conservative source-work budget across every company and period."""
    def __init__(self, remaining=MAX_SOURCE_ROWS):
        self.remaining = remaining
        self.seen = set()

    def reserve(self, count):
        self.remaining -= count
        if self.remaining < 0:
            raise ValidationError('This dashboard exceeds 100,000 source rows; no rows have been omitted.')

    def linked(self, records):
        keys = {(records._name, record_id) for record_id in records.ids}
        unseen = keys - self.seen
        self.reserve(len(unseen))
        self.seen.update(unseen)


class SpendingReader:
    def __init__(self, env, company, ranges, budget):
        self.env, self.company, self.ranges, self.budget = env, company, ranges, budget
        self.purchases, self.operating = [], []
        self.excluded = 0  # internal accounting trace only; no private rows in wire payload
        self.asset_cost_moves = set()

    @staticmethod
    def _number(value):
        result = Decimal(str(value))
        if not result.is_finite():
            unavailable()
        return result

    def _check(self, records, fields):
        if not records:
            return
        self.budget.linked(records)
        records.check_access('read')
        for offset in range(0, len(records), BATCH):
            records[offset:offset+BATCH].read(fields)  # native field-group checks

    def _search(self, model, domain, reserved=None):
        source = self.env[model].with_context(active_test=False)
        source.check_access('read')
        count = source.search_count(domain, limit=self.budget.remaining + 1) if reserved is None else reserved
        if reserved is None:
            self.budget.reserve(count)
        cursor, result = 0, source.browse()
        while True:
            rows = source.search(domain & Domain('id', '>', cursor), order='id', limit=BATCH)
            if not rows:
                break
            result |= rows
            if len(result) > count:
                unavailable()
            cursor = rows[-1].id
        if len(result) != count:
            unavailable()
        # Initial rows already reserved; linked reads charge only newly encountered IDs.
        self.budget.seen.update((model, record_id) for record_id in result.ids)
        return result

    def _bill_lines(self, bills):
        # Coverage/capacity count only, on <=1000 already-authorized exact move
        # IDs. No hidden line IDs, amounts or other fields are read or returned.
        # A visible-only AML search must not certify a partially hidden bill.
        self.env.cr.execute('SELECT COUNT(*) FROM (SELECT 1 FROM account_move_line WHERE move_id = ANY(%s) LIMIT %s) bounded',
                            [bills.ids, self.budget.remaining + 1])
        native_count = self.env.cr.fetchone()[0]
        self.budget.reserve(native_count)
        source = self.env['account.move.line']
        source.check_access('read')
        domain = Domain('move_id', 'in', bills.ids)
        if source.search_count(domain, limit=native_count + 1) != native_count:
            raise AccessError('The spending source is not fully readable. The report is unavailable.')
        return self._search('account.move.line', domain, reserved=native_count)

    def _dates(self, field):
        return Domain.OR([Domain(field, '>=', first) & Domain(field, '<=', last)
                          for first, last in self.ranges])

    def _links(self, lines):
        self._check(lines, ['company_id', 'move_id', 'account_id', 'journal_id',
                            'parent_state', 'date', 'balance', 'display_type'])
        moves = lines.move_id
        fields = ['company_id', 'state', 'move_type', 'date', 'reversed_entry_id']
        self._check(moves, fields)
        self._check(lines.account_id, ['company_ids', 'account_type'])
        self._check(lines.journal_id, ['company_id'])
        for line in lines:
            if (line.company_id != self.company or line.move_id.company_id != self.company
                    or line.journal_id.company_id != self.company
                    or (line.account_id and self.company not in line.account_id.company_ids)
                    or line.parent_state != 'posted' or line.move_id.state != 'posted'):
                unavailable()
            if not line.account_id and line.balance:
                unavailable()
        return moves

    def _expense_links(self, lines):
        # Only provenance used for classification is traversed. No unused payroll
        # names/records are read and no HR access is conferred by accounting access.
        if 'expense_id' in lines._fields:
            lines.read(['expense_id'])
            expenses = lines.expense_id
            self._check(expenses, ['company_id', 'account_move_id'])
            for line in lines.filtered('expense_id'):
                if line.expense_id.company_id != self.company or line.expense_id.account_move_id != line.move_id:
                    unavailable()

    def _stock_provenance(self, moves):
        if not moves:
            return set()
        if len(moves) > BATCH:
            result = set()
            for offset in range(0, len(moves), BATCH):
                result.update(self._stock_provenance(moves[offset:offset+BATCH]))
            return result
        valuation_moves = set()
        if 'stock_move_ids' in moves._fields:
            field = moves._fields['stock_move_ids']
            if (field.type != 'one2many' or field.comodel_name != 'stock.move'
                    or field.inverse_name != 'account_move_id' or self.env['stock.move']._table != 'stock_move'):
                unavailable()
            inverse = self.env['stock.move']._fields.get(field.inverse_name)
            if not inverse or not inverse.store or inverse.type != 'many2one' or inverse.comodel_name != 'account.move':
                unavailable()
            # Coverage/capacity only, exact already-authorized current or
            # ancestor entry IDs. No hidden stock IDs/amounts/names are read.
            self.env.cr.execute('SELECT COUNT(*) FROM (SELECT 1 FROM stock_move WHERE account_move_id = ANY(%s) LIMIT %s) bounded',
                                [moves.ids, self.budget.remaining + 1])
            stock_count = self.env.cr.fetchone()[0]
            self.budget.reserve(stock_count)
            stock = self.env['stock.move'].browse()
            if stock_count:
                stock.check_access('read')
                stock_domain = Domain(field.inverse_name, 'in', moves.ids)
                if stock.search_count(stock_domain, limit=stock_count + 1) != stock_count:
                    raise AccessError('The spending source is not fully readable. The report is unavailable.')
                stock = self._search('stock.move', stock_domain, reserved=stock_count)
            self._check(stock, ['company_id', field.inverse_name])
            if any(row.company_id != self.company for row in stock):
                unavailable()
            valuation_moves = set(stock.mapped(field.inverse_name).ids)
        return valuation_moves

    def _classify(self, lines):
        moves = self._links(lines)
        moves = lines.filtered(lambda row: row.move_id.move_type == 'entry'
                               and row.display_type != 'cogs'
                               and row.account_id.account_type in EXPENSE_TYPES).move_id
        # A bill-target entry reversal may be the only cancellation, rather than
        # an already-counted in_refund. Follow exact ancestry or refuse it.
        ancestors, frontier = self.env['account.move'].browse(), moves.reversed_entry_id
        while frontier:
            if len(ancestors) >= 64 or (frontier & ancestors):
                unavailable()
            self._check(frontier, ['company_id', 'state', 'move_type', 'reversed_entry_id'])
            if any(move.company_id != self.company or move.move_type in BILL_TYPES for move in frontier):
                unavailable()
            ancestors |= frontier
            frontier = frontier.reversed_entry_id
        if self._stock_provenance(ancestors):
            # An entry reversal does not inherit the original valuation O2M.
            # Until a supported stock-reversal contract exists, refuse the
            # whole report rather than count only its negative expense leg.
            unavailable()
        valuation_moves = self._stock_provenance(moves)
        admitted = []
        for line in lines:
            move, kind = line.move_id, line.account_id.account_type
            if move.move_type in BILL_TYPES:
                continue
            if kind not in EXPENSE_TYPES:
                continue
            if line.display_type == 'cogs':
                self.excluded += 1
                continue
            if move.move_type != 'entry':
                # Vendor documents never enter operating, independent of dates/FX.
                unavailable()
            if any(name in move._fields for name in ('asset_id', 'asset_ids', 'asset_depreciation_ids')):
                unavailable()  # installed asset profile is not part of the QA contract
            valuation = move.id in valuation_moves
            if kind == 'expense_depreciation' or valuation or line.display_type == 'cogs':
                self.excluded += 1
                continue
            if move.id in self.asset_cost_moves:
                unavailable()
            if kind == 'expense_direct_cost':
                # No unproven direct-cost-to-operating mapping. Its presence is
                # reported unavailable instead of disappearing from the total.
                unavailable()
            if kind not in ('expense', 'expense_other'):
                unavailable()
            admitted.append(line.id)
        contributing = lines.browse(admitted)
        self._expense_links(contributing)
        self.operating.extend((line.date, self._number(line.balance)) for line in contributing)

    def collect(self):
        self._check(self.company, ['currency_id'])
        self._check(self.company.currency_id, ['name'])
        if self.company.currency_id.name != 'SAR':
            unavailable()
        common = Domain('company_id', '=', self.company.id)
        bills = self._search('account.move', common & Domain('state', '=', 'posted')
            & Domain('move_type', 'in', BILL_TYPES) & self._dates('invoice_date'))
        for offset in range(0, len(bills), BATCH):
            batch = bills[offset:offset+BATCH]
            self._check(batch, ['company_id', 'journal_id', 'state', 'move_type',
                                'invoice_date', 'amount_total_signed'])
            self._check(batch.journal_id, ['company_id'])
            linked_lines = self._bill_lines(batch)
            for index in range(0, len(linked_lines), BATCH):
                self._links(linked_lines[index:index+BATCH])
            for bill in batch:
                if (bill.company_id != self.company or bill.journal_id.company_id != self.company
                        or bill.state != 'posted' or bill.move_type not in BILL_TYPES or not bill.invoice_date):
                    unavailable()
                self.purchases.append((bill.invoice_date, -self._number(bill.amount_total_signed)))
        # Check all relevant types before excluding any. Native invoice/refund
        # expense lines are globally partitioned out, not filtered by bill date.
        # Do not use dotted move/account predicates here: independent rules on
        # those comodels could hide a contributing visible AML before checks.
        # All posted lines in the bounded period are checked first, then their
        # already-readable parents/types partition bills and operating balances.
        domain = common & Domain('parent_state', '=', 'posted') & self._dates('date')
        candidates = self._search('account.move.line', domain)
        # Validate the entire bounded set before deciding whether an expense
        # move also contains an unproven asset-cost adjustment. No cross-batch
        # parent shape can disappear at the1000-row boundary.
        for offset in range(0, len(candidates), BATCH):
            batch = candidates[offset:offset+BATCH]
            self._links(batch)
            self.asset_cost_moves.update(batch.filtered(lambda row: row.account_id.account_type in (
                'asset_fixed', 'asset_current', 'asset_non_current', 'asset_prepayments')).move_id.ids)
        for offset in range(0, len(candidates), BATCH):
            self._classify(candidates[offset:offset+BATCH])
        return self

    def totals(self, bounds):
        first, last = bounds
        purchases = sum((value for day, value in self.purchases if first <= day <= last), ZERO)
        operating = sum((value for day, value in self.operating if first <= day <= last), ZERO)
        return purchases, operating
