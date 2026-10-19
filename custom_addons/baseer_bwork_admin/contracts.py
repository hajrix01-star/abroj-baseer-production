"""Pure, bounded metadata contract; no ORM, storage scans or business writes."""
from decimal import Decimal, ROUND_HALF_UP
import json

MAX_COMPANIES = 10
MAX_SOURCE_ROWS = 100000
MAX_RESPONSE_BYTES = 1048576
DEFAULT_PAGE = 80
MAX_PAGE = 200
MAX_WARNING_MIB = 10485760
PUSH_ERRORS = ('configuration', 'transport', 'unregistered', 'access_revoked')


def company_ids(value):
    if (type(value) is not list or not 1 <= len(value) <= MAX_COMPANIES
            or any(type(item) is not int or item <= 0 for item in value)
            or len(set(value)) != len(value)):
        raise ValueError('invalid_company_scope')
    return sorted(value)


def pagination(offset=0, limit=DEFAULT_PAGE):
    if (type(offset) is not int or not 0 <= offset <= MAX_SOURCE_ROWS
            or type(limit) is not int or not 1 <= limit <= MAX_PAGE):
        raise ValueError('invalid_page')
    return offset, limit


def warning(value):
    if type(value) is not int or not 0 <= value <= MAX_WARNING_MIB:
        raise ValueError('invalid_warning')
    return value


def mib(value):
    return format((Decimal(value) / Decimal(1048576)).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP), '.2f')


def bounded_response(value):
    if len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')) > MAX_RESPONSE_BYTES:
        raise ValueError('limit_exceeded')
    return value


def warning_status(size_bytes, warning_mib):
    return 'disabled' if not warning_mib else (
        'reached' if size_bytes >= warning_mib * 1048576 else 'below')
