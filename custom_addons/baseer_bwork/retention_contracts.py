"""Bounded, scope/revision-bound retention reconciliation; no history coverage."""
import base64
import binascii
import hashlib
import json
import re

from .contracts import ProtocolError

MAX_IDS = 200
MAX_BYTES = 128 * 1024


def reconcile_payload(value):
    if (type(value) is not dict or set(value) - {'api_version', 'membership_id', 'content_revision', 'media_ids', 'cursor'}
            or not {'api_version', 'membership_id', 'content_revision', 'media_ids'} <= set(value)
            or type(value['api_version']) is not int or value['api_version'] != 2
            or type(value['membership_id']) is not int or not 0 < value['membership_id'] <= 2147483647
            or type(value['content_revision']) is not int or not 0 <= value['content_revision'] <= 2147483647):
        raise ProtocolError('invalid_payload', 'Invalid content-state request.')
    ids = value['media_ids']
    if (type(ids) is not list or not 1 <= len(ids) <= MAX_IDS
            or any(type(i) is not int or not 0 < i <= 2147483647 for i in ids)
            or ids != sorted(set(ids))):
        raise ProtocolError('invalid_payload', 'Choose up to 200 distinct sorted media IDs.')
    cursor = value.get('cursor')
    if cursor is not None and (type(cursor) is not str or not re.fullmatch('[A-Za-z0-9_-]{1,256}', cursor)):
        raise ProtocolError('invalid_cursor', 'Restart content-state reconciliation.')
    return value['membership_id'], value['content_revision'], ids, cursor


def ids_digest(ids):
    return hashlib.sha256(json.dumps(ids, separators=(',', ':')).encode()).hexdigest()


def cursor_for(scope, index):
    return base64.urlsafe_b64encode(json.dumps([1, *scope, index], separators=(',', ':')).encode()).rstrip(b'=').decode()


def cursor_index(cursor, scope, count):
    if cursor is None:
        return 0
    try:
        value = json.loads(base64.b64decode(cursor + '=' * (-len(cursor) % 4), altchars=b'-_', validate=True))
        if (type(value) is not list or value[:-1] != [1, *scope] or type(value[-1]) is not int
                or not 0 < value[-1] < count or cursor_for(scope, value[-1]) != cursor):
            raise ValueError()
        return value[-1]
    except (ValueError, TypeError, UnicodeError, binascii.Error):
        raise ProtocolError('invalid_cursor', 'Restart content-state reconciliation.') from None


def encoded_size(payload):
    return len(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
