"""Strict C32 projections; absent reaction/saved state has revision zero."""
from .contracts import ProtocolError, canonical_uuid, positive_id


EMOJIS = ('👍', '❤️', '😂', '😮', '😢', '🙏')


def mutation(payload, value_key):
    if (type(payload) is not dict or set(payload) != {
            'api_version', 'membership_id', 'client_uuid', 'expected_revision', value_key}
            or type(payload['api_version']) is not int or payload['api_version'] != 2):
        raise ProtocolError('invalid_payload', 'Unexpected social message fields.')
    revision = payload['expected_revision']
    if type(revision) is not int or not 0 <= revision < 2147483647:
        raise ProtocolError('invalid_payload', 'A nonnegative social revision is required.')
    value = payload[value_key]
    if value_key == 'emoji':
        if value is not None and (type(value) is not str or value not in EMOJIS):
            raise ProtocolError('invalid_payload', 'Choose a supported reaction or null.')
    elif value_key == 'saved':
        if type(value) is not bool:
            raise ProtocolError('invalid_payload', 'A Boolean saved state is required.')
    else:
        raise ValueError('Unsupported internal projection')
    return {**payload, 'membership_id': positive_id(payload['membership_id'], 'membership_id'),
            'client_uuid': canonical_uuid(payload['client_uuid'])}


def message_ids(values):
    if type(values) is not list or not 1 <= len(values) <= 30:
        raise ProtocolError('invalid_payload', 'Choose between one and thirty visible messages.')
    ids = [positive_id(value, 'message_id') for value in values]
    if len(set(ids)) != len(ids):
        raise ProtocolError('invalid_payload', 'Message references must be unique.')
    return ids
