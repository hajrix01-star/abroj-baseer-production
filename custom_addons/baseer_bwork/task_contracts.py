"""Strict, Odoo-free wire contract for BWork's own tasks."""
import hashlib
import json
from datetime import datetime
import unicodedata

from .contracts import ProtocolError, canonical_uuid, positive_id


def _keys(payload, expected):
    if type(payload) is not dict or set(payload) != set(expected):
        raise ProtocolError('invalid_payload', 'Task payload fields do not match the v2 contract.')
    if type(payload['api_version']) is not int or payload['api_version'] != 2:
        raise ProtocolError('unsupported_version', 'Only API version 2 is supported.')


def _text(value, field, limit, *, required=False):
    if not isinstance(value, str) or '\x00' in value:
        raise ProtocolError('invalid_payload', '%s must be text.' % field)
    if required and not value.strip():
        raise ProtocolError('invalid_payload', '%s is required.' % field)
    if any(unicodedata.category(char).startswith('C')
           and (required or char not in '\n\t') for char in value):
        raise ProtocolError('invalid_payload', '%s contains a control character.' % field)
    try:
        size = len(value.encode('utf-8'))
    except UnicodeEncodeError:
        raise ProtocolError('invalid_payload', '%s must be UTF-8.' % field) from None
    if size > limit:
        raise ProtocolError('invalid_payload', '%s is too long.' % field)
    return value.strip() if required else value


def _due(value):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != 20:
        raise ProtocolError('invalid_payload', 'due_at must be a UTC ISO timestamp or null.')
    try:
        parsed = datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ')
    except ValueError:
        raise ProtocolError('invalid_payload', 'due_at must be a UTC ISO timestamp or null.') from None
    return parsed.strftime('%Y-%m-%d %H:%M:%S')


def normalize_create(payload):
    _keys(payload, ('api_version', 'company_id', 'room_id', 'client_uuid',
                    'title', 'description', 'due_at', 'assignee_id'))
    return {
        'company_id': positive_id(payload['company_id'], 'company_id'),
        'room_id': None if payload['room_id'] is None else positive_id(payload['room_id'], 'room_id'),
        'client_uuid': canonical_uuid(payload['client_uuid']),
        'title': _text(payload['title'], 'title', 160, required=True),
        'description': _text(payload['description'], 'description', 4096),
        'due_at': _due(payload['due_at']),
        'assignee_id': positive_id(payload['assignee_id'], 'assignee_id'),
    }


def normalize_transition(payload):
    _keys(payload, ('api_version', 'client_uuid', 'expected_revision', 'action',
                    'assignee_id', 'reason'))
    action = payload['action']
    if action not in ('start', 'done', 'cancel', 'reassign', 'rescue'):
        raise ProtocolError('invalid_payload', 'Unknown task action.')
    assignee = payload['assignee_id']
    if action in ('reassign', 'rescue'):
        assignee = positive_id(assignee, 'assignee_id')
    elif assignee is not None:
        raise ProtocolError('invalid_payload', 'This action cannot assign a user.')
    reason = payload['reason']
    if reason is not None:
        reason = _text(reason, 'reason', 512)
    # A short note is immutable audit context for every user-visible action.
    # It is optional except for rescue, whose recovery intent must remain clear.
    if action == 'rescue' and (reason is None or not reason.strip()):
        raise ProtocolError('invalid_payload', 'Rescue requires a reason.')
    return {
        'client_uuid': canonical_uuid(payload['client_uuid']),
        'expected_revision': positive_id(payload['expected_revision'], 'expected_revision'),
        'action': action, 'assignee_id': assignee, 'reason': reason,
    }


def digest(operation, target_id, values):
    wire = {'operation': operation, 'target_id': target_id, 'values': values}
    return hashlib.sha256(json.dumps(wire, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()
