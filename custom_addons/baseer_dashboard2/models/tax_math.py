"""Pure arithmetic for allocating recorded tax and rebasing targets.

The caller is responsible for selecting eligible tax lines and matching base
lines within the same move. No tax rates are inferred here.
"""

from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP


def _decimal(value):
    return Decimal(str(value))


def allocate_tax(amount, bases):
    """Allocate a tax line in cents using signed base balances.

    ``bases`` is an iterable of (stable line identifier, signed balance).
    Return None when allocation is impossible; callers must report the entire
    tax line as unallocated. Ties are resolved in input order.
    """
    bases = [(key, _decimal(balance)) for key, balance in bases]
    total = sum((balance for _, balance in bases), Decimal(0))
    if not bases or not total:
        return None
    cents = int((_decimal(amount) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    exact = [Decimal(cents) * balance / total for _, balance in bases]
    floors = [int(value.to_integral_value(rounding=ROUND_FLOOR)) for value in exact]
    remainder = cents - sum(floors)
    for index in sorted(range(len(bases)), key=lambda i: (-(exact[i] - floors[i]), i))[:remainder]:
        floors[index] += 1
    return [(key, Decimal(value) / 100) for (key, _), value in zip(bases, floors)]


def convert_target(key, target, sales_net, sales_gross, food_net, food_gross, salaries, net_net, net_gross):
    """Convert a target using observed totals; return None if not computable."""
    target, sales_net, sales_gross, food_net, food_gross, salaries, net_net, net_gross = map(
        _decimal, (target, sales_net, sales_gross, food_net, food_gross, salaries, net_net, net_gross))
    if not sales_net or not sales_gross:
        return None
    if key == 'food_pct':
        if not food_net:
            return None
        value = target * food_gross / food_net * sales_net / sales_gross
    elif key == 'salaries_pct':
        value = target * sales_net / sales_gross
    elif key == 'prime_pct':
        if not food_net + salaries:
            return None
        value = target * (food_gross + salaries) / (food_net + salaries) * sales_net / sales_gross
    elif key == 'net_margin_pct':
        value = (target / 100 * sales_net + net_gross - net_net) / sales_gross * 100
    else:
        return None
    return float(value.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP))
