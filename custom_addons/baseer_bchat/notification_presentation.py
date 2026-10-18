"""C14/C15 display identities, never authorization or delivery/read receipts.

Only verified server callers supply database identities. The account is the
registered device's UUID, not the Android local AccountScope SHA. No Odoo import
allows the exact UTF-8/hash/privacy contract to be checked independently.
"""
import hashlib
import json
import re
import unicodedata
from uuid import UUID


MAX_DATA_BYTES = 3072  # Leaves room beneath FCM's 4096-byte data envelope.
MAX_SENT_AT_MS = 253402300799999


def notification_text(value, limit):
    if not isinstance(value, str):
        return ''
    value = re.sub(r'<[^>\r\n]{0,256}>', '', value)
    cleaned = []
    for char in value:
        if unicodedata.category(char).startswith('C'):
            cleaned.append(' ' if char in '\r\n\t' else '')
        else:
            cleaned.append(char)
    return ' '.join(''.join(cleaned).split())[:limit]


def _room_scope(account, company, room, membership):
    try:
        parsed = UUID(account)
    except (TypeError, ValueError, AttributeError):
        raise ValueError('Invalid presentation account.') from None
    if parsed.version != 4 or str(parsed) != account:
        raise ValueError('Invalid presentation account.')
    for value in (company, room, membership):
        if type(value) is not int or not 0 < value <= 2147483647:
            raise ValueError('Invalid presentation record identity.')
    return '%s|%s|%s|%s' % (account, company, room, membership)


def _digest(kind, scope, suffix=''):
    return hashlib.sha256(('bchat-pres-v1|%s|%s%s' % (kind, scope, suffix)).encode('utf-8')).hexdigest()


def room_mute_keys(account, company, room, membership):
    """Recipient room scope only; no invented message/author for room tasks."""
    scope = _room_scope(account, company, room, membership)
    return {'mute_scope_v': '1', 'mute_room_key': _digest('room', scope)}


def presentation_keys(account, company, room, membership, message, author):
    scope = _room_scope(account, company, room, membership)
    for value in (message, author):
        if type(value) is not int or not 0 < value <= 2147483647:
            raise ValueError('Invalid presentation record identity.')
    def digest(kind, suffix=''):
        return _digest(kind, scope, suffix)
    return {'presentation_v': '1', 'room_key': digest('room'),
            'message_key': digest('message', '|%s' % message),
            'sender_key': digest('sender', '|%s' % author)}


def chat_data(*, account, event, company, room, membership, message, author,
              sent_at_ms, mode, sender='', title='', is_group=False, text='', attachment=False):
    """All FCM values are strings; remove rich fields before exceeding the cap.

    The recipient's *current* membership must be passed, never the author's.
    A malformed internal identity is not repaired or guessed from an event ID.
    """
    keys = presentation_keys(account, company, room, membership, message, author)
    if type(event) is not int or not 0 < event <= 2147483647:
        raise ValueError('Invalid presentation event.')
    if type(sent_at_ms) is not int or not 0 < sent_at_ms <= MAX_SENT_AT_MS:
        raise ValueError('Invalid presentation time.')
    if mode not in ('none', 'sender', 'full') or type(is_group) is not bool or type(attachment) is not bool:
        raise ValueError('Invalid presentation preference.')
    data = {'account_key': account, 'kind': 'chat', 'event_id': str(event),
            'presentation_v': keys['presentation_v'], 'room_key': keys['room_key'],
            'message_key': keys['message_key'], 'sent_at_ms': str(sent_at_ms)}
    data.update(room_mute_keys(account, company, room, membership))
    minimal = dict(data)
    if mode in ('sender', 'full'):
        data.update(sender_key=keys['sender_key'], sender_name=notification_text(sender, 120))
    if mode == 'full':
        data.update(conversation_title=notification_text(title, 120), is_group='true' if is_group else 'false')
        preview = notification_text(text, 160)
        if preview:
            data['message_preview'] = preview
        elif attachment:
            data['message_preview_kind'] = 'attachment'
    if len(json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8')) > MAX_DATA_BYTES:
        return minimal
    return data
