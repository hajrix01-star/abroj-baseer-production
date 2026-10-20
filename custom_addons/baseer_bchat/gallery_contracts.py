"""Pure, strict gallery keysets and backend-owned integer byte formatting."""
import base64
import binascii
import json
import re

from .contracts import ProtocolError

MAX_PAGE = 60
DEFAULT_PAGE = 30
MAX_BYTES = 128 * 1024
KINDS = ('all', 'image', 'file', 'audio')
ORDERS = ('newest', 'oldest', 'largest')


def options(kind='all', order='newest', limit=DEFAULT_PAGE):
    if (type(kind) is not str or kind not in KINDS
            or type(order) is not str or order not in ORDERS
            or type(limit) is not int or not 1 <= limit <= MAX_PAGE):
        raise ProtocolError('invalid_payload', 'Invalid gallery filters or page size.')
    return kind, order, limit


def query(args):
    if (set(args) - {'kind', 'order', 'limit', 'cursor'}
            or any(len(args.getlist(key)) != 1 for key in args)):
        raise ProtocolError('invalid_payload', 'Invalid gallery query fields.')
    raw = args.get('limit', str(DEFAULT_PAGE))
    if not isinstance(raw, str) or not re.fullmatch(r'[1-9][0-9]{0,2}', raw):
        raise ProtocolError('invalid_payload', 'Invalid gallery page size.')
    kind, order, limit = options(args.get('kind', 'all'), args.get('order', 'newest'), int(raw))
    cursor = args.get('cursor')
    if cursor is not None and (not cursor or len(cursor) > 256):
        raise ProtocolError('invalid_cursor', 'The gallery cursor is invalid.')
    return dict(kind=kind, order=order, limit=limit, cursor=cursor)


def cursor_for(room, member, kind, order, message, size):
    value = [1, room, member, kind, order, message, size]
    return base64.urlsafe_b64encode(json.dumps(value, separators=(',', ':')).encode()).rstrip(b'=').decode()


def anchor(cursor, room, member, kind, order):
    if cursor is None:
        return None
    try:
        if type(cursor) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,256}', cursor):
            raise ValueError()
        value = json.loads(base64.b64decode(cursor + '=' * (-len(cursor) % 4), altchars=b'-_', validate=True))
        if (type(value) is not list or len(value) != 7
                or any(type(value[index]) is not int or not 0 < value[index] <= 2147483647
                       for index in (0, 1, 2, 5, 6))
                or value[:5] != [1, room, member, kind, order]
                or cursor_for(*value[1:]) != cursor):
            raise ValueError()
        return value[5], value[6]
    except (ValueError, TypeError, UnicodeError, binascii.Error):
        raise ProtocolError('invalid_cursor', 'Restart the gallery for this room and filter.') from None


def size_label(size):
    if type(size) is not int or size < 0:
        raise ValueError('Invalid byte count')
    for divisor, suffix in ((1073741824, 'GiB'), (1048576, 'MiB'), (1024, 'KiB')):
        if size >= divisor:
            hundredths = (size * 100 + divisor // 2) // divisor
            return '%d.%02d %s' % (hundredths // 100, hundredths % 100, suffix)
    return '%d B' % size


def encoded_size(payload):
    # Default separators match Odoo's JSON response's conservative wire size.
    return len(json.dumps(payload, ensure_ascii=False).encode('utf-8'))


def response(room, company, member, kind, order, items, more):
    rows = list(items)
    result = {'api_version': 2, 'gallery_version': 1, 'room_id': room,
              'company_id': company, 'membership_id': member,
              'kind': kind, 'order': order, 'items': rows, 'next_cursor': None}
    while rows:
        last = rows[-1]
        result['next_cursor'] = cursor_for(room, member, kind, order, last['id'],
                                           last['media']['size']) if more else None
        if encoded_size(result) <= MAX_BYTES:
            return result
        rows.pop()
        more = True
    if items:
        raise ProtocolError('payload_too_large', 'A gallery item exceeds its response limit.', 413)
    return result
