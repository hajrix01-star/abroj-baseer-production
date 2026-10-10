"""Read-only payment attribution; never changes a report's accounting total."""
from decimal import Decimal, ROUND_HALF_UP

UNALLOCATED = 'unallocated'


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
