"""Read-only payment attribution; never changes a report's accounting total."""
from decimal import Decimal, ROUND_HALF_UP

UNALLOCATED = 'unallocated'


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
