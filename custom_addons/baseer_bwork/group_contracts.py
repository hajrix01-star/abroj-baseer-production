"""Strict wire validation for self-service BWork group operations."""
import hashlib
import json
import unicodedata

from .contracts import ProtocolError, canonical_uuid, positive_id


MAX_GROUP_MEMBERS = 50
MAX_GROUP_DESCRIPTION_BYTES = 1024


def _name(value):
    if (type(value) is not str or not value.strip()
            or any(unicodedata.category(char).startswith('C') for char in value)):
        raise ProtocolError('invalid_payload', 'A group name is required.')
    try:
        size = len(value.encode('utf-8'))
    except UnicodeEncodeError:
        raise ProtocolError('invalid_payload', 'Invalid group name.') from None
    if size > 256:
        raise ProtocolError('invalid_payload', 'Group name is too long.')
    return value.strip()


def _description(value):
    if type(value) is not str:
        raise ProtocolError('invalid_payload', 'Invalid group description.')
    cleaned = value.replace('\r\n', '\n').strip()
    if any(unicodedata.category(char).startswith('C') and char != '\n'
           for char in cleaned):
        raise ProtocolError('invalid_payload', 'Invalid group description.')
    try:
        size = len(cleaned.encode('utf-8'))
    except UnicodeEncodeError:
        raise ProtocolError('invalid_payload', 'Invalid group description.') from None
    if size > MAX_GROUP_DESCRIPTION_BYTES:
        raise ProtocolError('invalid_payload', 'Group description is too long.')
    return cleaned


def _version(payload, required, optional=frozenset()):
    if (type(payload) is not dict or not required <= set(payload)
            or set(payload) - required - optional):
        raise ProtocolError('invalid_payload', 'Unexpected group fields.')
    if type(payload['api_version']) is not int or payload['api_version'] != 2:
        raise ProtocolError('unsupported_version', 'Only API version 2 is supported.')


def normalize_create(payload):
    _version(payload, {'api_version', 'client_uuid', 'company_id', 'name', 'member_user_ids'},
             {'description'})
    members = payload['member_user_ids']
    # The creator is an additional member; the total group limit is 50.
    if type(members) is not list or len(members) >= MAX_GROUP_MEMBERS:
        raise ProtocolError('invalid_payload', 'Group member list exceeds its limit.')
    member_ids = [positive_id(value, 'member_user_id') for value in members]
    if len(set(member_ids)) != len(member_ids):
        raise ProtocolError('invalid_payload', 'Duplicate group member.')
    normalized = {
        'client_uuid': canonical_uuid(payload['client_uuid']),
        'company_id': positive_id(payload['company_id'], 'company_id'),
        'name': _name(payload['name']),
        'member_user_ids': sorted(member_ids),
    }
    if 'description' in payload:
        description = _description(payload['description'])
        if description:
            normalized['description'] = description
    return normalized


def create_digest(normalized):
    wire = json.dumps(normalized, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(wire).hexdigest()


def normalize_change(payload):
    if type(payload) is not dict or payload.get('api_version') != 2:
        raise ProtocolError('invalid_payload', 'Invalid group operation.')
    action = payload.get('action')
    if action == 'rename':
        _version(payload, {'api_version', 'action', 'name'})
        return {'action': action, 'name': _name(payload['name'])}
    if action == 'set_description':
        _version(payload, {'api_version', 'action', 'description'})
        return {'action': action, 'description': _description(payload['description'])}
    if action in ('add_member', 'remove_member', 'promote_admin', 'demote_admin'):
        _version(payload, {'api_version', 'action', 'user_id'})
        return {'action': action, 'user_id': positive_id(payload['user_id'], 'user_id')}
    if action == 'leave':
        _version(payload, {'api_version', 'action'})
        return {'action': action}
    raise ProtocolError('invalid_payload', 'Unknown group operation.')
