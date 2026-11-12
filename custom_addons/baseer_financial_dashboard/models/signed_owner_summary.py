"""Isolated dashboard arithmetic for an already-proved full payment reversal.

No Odoo reads or access decisions happen here. The caller must first prove,
in the active company, both posted moves, their structured reversal link,
currency, dates, cash lines, permissions, and absence of duplicate ownership.
It must also include those facts in the dashboard revision. The original
reader remains authoritative for every ordinary event and positive witness.

``build_signed_owner_summary(events, liquidity_totals, reversals,
reversal_totals, company_id=...)`` accepts ordinary events and positive cash
witnesses using the original contract. Each reversal is an outgoing event
with a *negative* Decimal amount, source_model='account.move', source_id equal
to reversal_move_id, and line_model='account.move.line', line_id equal to its
payment_line_id. It has positive IDs reversal_move_id, original_move_id and
original_payment_line_id, a positive Decimal original_amount, company_id, and
``original_classification='unconfirmed_bill_classification'``. When the
original event is outside the period, that last value is an assertion supplied
by the caller after it independently reads and proves the original source;
this pure reducer cannot establish its truth.
``reversal_totals`` maps that separate cash witness to its negative amount.
Only exact, whole reversals with unconfirmed bill classification are accepted;
partial, multiple, or unproved reversals stay outside this arithmetic contract.
"""

from decimal import Decimal, localcontext

from odoo.addons.baseer_operations_report.models.owner_summary import (
    _identity, _money, build_owner_summary,
)


def build_signed_owner_summary(events, liquidity_totals, reversals, reversal_totals, *, company_id):
    """Aggregate distinct proved cash witnesses, without turning refunds into sales."""
    _identity(company_id)
    if (not isinstance(events, (list, tuple)) or not isinstance(reversals, (list, tuple))
            or not isinstance(reversal_totals, dict)):
        raise ValueError('Events and reversal witnesses must be explicit collections.')
    # The old reducer checks every ordinary event, allocation, witness, company,
    # direction and precision before we consider any new negative cash facts.
    summary = build_owner_summary(events, liquidity_totals, company_id=company_id)
    negative_expected = {}
    for key, value in reversal_totals.items():
        key, value = _identity(key), _money(value)
        if value >= 0 or key in liquidity_totals:
            raise ValueError('A distinct negative cash witness is required.')
        negative_expected[key] = value
    ordinary_line_ids = {
        event.get('line_id') for event in events
        if event.get('line_model') == 'account.move.line'
    }
    original_classes = {}
    for event in events:
        if event.get('direction') == 'outgoing':
            original_classes.setdefault(event['payment_line_id'], set()).add(
                event.get('classification'))
    seen_witnesses, seen_originals, seen_moves, seen_original_moves = set(), set(), set(), set()
    total = Decimal('0.00')
    with localcontext() as context:
        context.prec = 60
        for event in reversals:
            if not isinstance(event, dict) or _identity(event.get('company_id')) != company_id:
                raise ValueError('Mixed-company or invalid reversal facts are not permitted.')
            witness = _identity(event.get('payment_line_id'))
            original_witness = _identity(event.get('original_payment_line_id'))
            move = _identity(event.get('reversal_move_id'))
            original_move = _identity(event.get('original_move_id'))
            amount = _money(event.get('amount'))
            original_amount = _money(event.get('original_amount'))
            if (event.get('direction') != 'outgoing'
                    or event.get('source_model') != 'account.move'
                    or _identity(event.get('source_id')) != move
                    or event.get('line_model') != 'account.move.line'
                    or _identity(event.get('line_id')) != witness
                    or event.get('classification') != 'unconfirmed_bill_classification'
                    or event.get('original_classification') != 'unconfirmed_bill_classification'
                    or event.get('channels')
                    or witness == original_witness or move == original_move
                    or witness in seen_witnesses or witness in ordinary_line_ids
                    or original_witness in seen_originals or move in seen_moves
                    or original_move in seen_original_moves
                    or amount >= 0 or original_amount <= 0 or -amount != original_amount
                    or negative_expected.get(witness) != amount):
                raise ValueError('Invalid, duplicate or incomplete payment reversal.')
            if original_witness in liquidity_totals and liquidity_totals[original_witness] != original_amount:
                raise ValueError('Reversal does not equal the original cash witness.')
            if (original_witness in liquidity_totals
                    and original_classes.get(original_witness) != {'unconfirmed_bill_classification'}):
                raise ValueError('Reversal classification differs from the original cash event.')
            seen_witnesses.add(witness)
            seen_originals.add(original_witness)
            seen_moves.add(move)
            seen_original_moves.add(original_move)
            total += amount
        if (seen_witnesses != set(negative_expected)
                or seen_originals & seen_witnesses or seen_original_moves & seen_moves):
            raise ValueError('Reversal allocations do not cover their cash witnesses.')
        if seen_witnesses:
            buckets = summary['outflow_buckets']
            key = 'unconfirmed_bill_classification'
            bucket = next((row for row in buckets if row['key'] == key), None)
            if bucket is None:
                bucket = {'key': key, 'amount': Decimal('0.00'), 'count': 0}
                buckets.append(bucket)
                buckets.sort(key=lambda row: row['key'])
            bucket['amount'] += total
            bucket['count'] += len(seen_witnesses)
            summary['cash_total'] += total
            summary['difference'] = summary['incoming_total'] - summary['cash_total']
            summary['cash_event_count'] += len(seen_witnesses)
            summary['has_unclassified_outflows'] = True
    return summary
