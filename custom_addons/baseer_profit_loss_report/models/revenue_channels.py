"""Read-only payment attribution; never changes a report's accounting total."""
from decimal import Decimal, ROUND_HALF_UP

UNALLOCATED = 'unallocated'


def noorix_gross_channels(event, company):
    """Classify one already-validated Noorix ledger event without allocating VAT.

    The caller must obtain the event from the guarded Noorix ledger reader,
    which proves source identity, visibility, posted gross and uniqueness.
    Return None if the source does not unambiguously name each funding line.
    Reversals require their own original-line provenance and are left to the
    caller until that provenance can be proved.
    """
    if not event.get('original'):
        return None
    move = event['move']
    labels = ('cash', 'bank', 'keeta', 'hunger', 'jahez')
    income = move.line_ids.filtered(lambda line: line.account_id.account_type in ('income', 'income_other'))
    accounts = income.mapped('account_id')
    if len(accounts) != 1:
        return None
    amounts = {}
    account_by_label = {}
    for line in move.line_ids:
        balance = Decimal(str(line.balance))
        if line.company_id != company or line.currency_id != company.currency_id:
            return None
        if balance <= 0:
            continue
        label = next((key for key in labels
                      if line.name == f'Noorix sales {key} {move.date.isoformat()}'), None)
        if not label or line.account_id.internal_group != 'asset':
            return None
        if label in account_by_label and account_by_label[label] != line.account_id.id:
            return None
        account_by_label[label] = line.account_id.id
        amounts[label] = amounts.get(label, Decimal('0')) + balance
    total = sum(amounts.values(), Decimal('0'))
    if not amounts or total != event['amount']:
        return None
    return accounts.id, amounts, account_by_label


def reconcile_order_amounts(order_amounts, posted_amount, rounding):
    """Absorb at most one currency unit per move/account, never per order.

    The posted ledger remains authoritative. Call only after proving source
    completeness, company, access and account mapping. Larger differences or
    zero/opposite net sources cannot be explained by a rounding residual.
    """
    total = sum((value for _order, value in order_amounts), Decimal('0'))
    difference = posted_amount - total
    if not order_amounts:
        return None
    if not difference:
        return list(order_amounts)
    if rounding <= 0 or abs(difference) > rounding or total * posted_amount <= 0:
        return None
    result = list(order_amounts)
    for index in range(len(result) - 1, -1, -1):
        order, value = result[index]
        if value * posted_amount > 0 and (value + difference) * value > 0:
            result[index] = (order, value + difference)
            return result
    return None


def tender_matches_order(payments, order_total, rounding):
    total = sum((Decimal(str(value)) for _key, _name, value in payments), Decimal('0'))
    return (bool(total) and total * order_total > 0
            and abs(total - order_total) <= rounding)


def allocate_channels(amount, payments, rounding):
    """Signed net payments (including change/refunds), stable last residual."""
    weights = {}
    for key, name, value in payments:
        previous = weights.get(key, (name, Decimal('0')))
        weights[key] = (name, previous[1] + Decimal(str(value)))
    weights = {key: item for key, item in weights.items() if item[1]}
    total = sum((item[1] for item in weights.values()), Decimal('0'))
    if not total or not weights or rounding <= 0 or amount * total < 0:
        return {UNALLOCATED: ('', amount)}
    # Mixed payment signs can represent a refund/change, but a net channel
    # pointing against the sale cannot safely be called revenue attribution.
    if any(value * total < 0 for _name, value in weights.values()):
        return {UNALLOCATED: ('', amount)}
    result, remaining = {}, amount
    ordered = sorted(weights.items())
    for index, (key, (name, value)) in enumerate(ordered):
        allocated = (remaining if index == len(ordered) - 1 else
                     (amount * value / total / rounding).quantize(
                         Decimal('1'), rounding=ROUND_HALF_UP) * rounding)
        result[key] = (name, allocated)
        remaining -= allocated
    return result
