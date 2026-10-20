"""Pure wire/Decimal helpers; no source queries or Odoo dependencies."""
import calendar
import re
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from odoo.addons.baseer_bwork.contracts import ProtocolError

ZERO = Decimal('0')
CENT = Decimal('0.01')
MAX_COMPANIES = 10
MAX_SOURCE_ROWS = 100000
MAX_RESPONSE_BYTES = 1024 * 1024


def amount(value):
    if value is None:
        return {'value': None, 'display': '—', 'available': False}
    value = Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
    if not value.is_finite():
        raise ValueError('Non-finite financial amount')
    if not value:
        value = abs(value)
    return {'value': str(value), 'display': f'{value:,.2f}', 'available': True}


def ratio(value, denominator):
    return amount(value * Decimal(100) / denominator if denominator > ZERO else None)


def change(current, previous, available=True):
    return ratio(current - previous, previous) if available else amount(None)


def month_start(value, offset=0):
    year, month = divmod(value.year * 12 + value.month - 1 + offset, 12)
    return date(year, month + 1, 1)


def month_end(value):
    return value.replace(day=calendar.monthrange(value.year, value.month)[1])


def parse_query(args, today):
    allowed = {'company_id', 'month', 'period', 'date'}
    if (set(args) - allowed or not {'month', 'period'} <= set(args)
            or any(len(args.getlist(key)) != 1 for key in args)):
        raise ProtocolError('invalid_payload', 'Unexpected, missing or repeated dashboard query fields.')
    raw_month, period = args['month'], args['period']
    try:
        if not re.fullmatch(r'[0-9]{4}-[0-9]{2}', raw_month):
            raise ValueError
        first = date.fromisoformat(raw_month + '-01')
        # A previous calendar and native same-length comparison must exist.
        if not 1900 <= first.year <= 9998:
            raise ValueError
        if period not in ('today', 'yesterday', 'month', 'date'):
            raise ValueError
        raw_id = args.get('company_id')
        if raw_id is not None and not re.fullmatch(r'[1-9][0-9]{0,9}', raw_id):
            raise ValueError
        if ('date' in args) != (period == 'date'):
            raise ValueError
        if period == 'date':
            if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', args['date']):
                raise ValueError
            selected = date.fromisoformat(args['date'])
            if selected.replace(day=1) != first:
                raise ValueError
        else:
            selected = today - timedelta(days=period == 'yesterday')
        start, end = (first, month_end(first)) if period == 'month' else (selected, selected)
        return {'company_id': int(raw_id) if raw_id else None, 'month': raw_month,
                'period': period, 'first': start, 'last': end, 'calendar_first': first}
    except (ValueError, TypeError, OverflowError):
        raise ProtocolError('invalid_payload', 'Choose a valid company, month and dashboard period.') from None


def merge_ranges(ranges):
    result = []
    for first, last in sorted((first, last) for first, last in ranges if first and last and first <= last):
        if result and (first - result[-1][1]).days <= 1:
            result[-1] = (result[-1][0], max(last, result[-1][1]))
        else:
            result.append((first, last))
    return result
