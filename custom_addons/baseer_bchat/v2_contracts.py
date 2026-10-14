"""Strict, Odoo-independent wire contract for BChat text and replies."""
import hashlib
import json

from .contracts import ProtocolError, _text, canonical_uuid, positive_id


API_VERSION = 2
MAX_TEXT_BYTES = 16384


def normalize_send(payload):
    expected = {'api_version', 'membership_id', 'client_uuid', 'text'}
    allowed_optional = {'reply_to_message_id', 'media_id', 'document_type',
                        'invoice_case_id', 'policy_version'}
    if (type(payload) is not dict or not expected <= set(payload)
            or set(payload) - expected - allowed_optional):
        raise ProtocolError('invalid_payload', 'Payload fields do not match the v2 contract.')
    if type(payload['api_version']) is not int or payload['api_version'] != API_VERSION:
        raise ProtocolError('unsupported_version', 'Only API version 2 is supported.')
    text = payload['text']
    if 'media_id' in payload and text == '':
        clean_text = ''
    else:
        clean_text = _text(text, 'text', MAX_TEXT_BYTES)
    normalized = {
        'membership_id': positive_id(payload['membership_id'], 'membership_id'),
        'client_uuid': canonical_uuid(payload['client_uuid']),
        'text': clean_text,
    }
    if 'reply_to_message_id' in payload:
        normalized['reply_to_message_id'] = positive_id(payload['reply_to_message_id'], 'reply_to_message_id')
    if 'media_id' in payload:
        normalized['media_id'] = positive_id(payload['media_id'], 'media_id')
    document_fields = {'document_type', 'invoice_case_id', 'policy_version'} & set(payload)
    if document_fields and 'media_id' not in payload:
        raise ProtocolError('invalid_payload', 'Document fields require media.')
    if 'document_type' in payload:
        if type(payload['document_type']) is not str or payload['document_type'] not in (
                'invoice', 'payment_receipt', 'other'):
            raise ProtocolError('invalid_payload', 'Unknown document type.')
        normalized['document_type'] = payload['document_type']
    if 'invoice_case_id' in payload:
        normalized['invoice_case_id'] = positive_id(payload['invoice_case_id'], 'invoice_case_id')
    if 'policy_version' in payload:
        normalized['policy_version'] = positive_id(payload['policy_version'], 'policy_version')
    return normalized


def digest(room_id, normalized):
    body = {
        'room_id': room_id,
        'membership_id': normalized['membership_id'],
        'client_uuid': normalized['client_uuid'],
        'text': normalized['text'],
    }
    if 'reply_to_message_id' in normalized:
        body['reply_to_message_id'] = normalized['reply_to_message_id']
    if 'media_id' in normalized:
        body['media_id'] = normalized['media_id']
        body['media_sha256'] = normalized['media_sha256']
    for key in ('document_type', 'invoice_case_id', 'policy_version'):
        if key in normalized:
            body[key] = normalized[key]
    encoded = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def ack(room_id, normalized, message_id):
    result = {
        'api_version': API_VERSION,
        'room_id': room_id,
        'membership_id': normalized['membership_id'],
        'client_uuid': normalized['client_uuid'],
        'message_id': message_id,
        'state': 'sent',
    }
    if 'media_id' in normalized:
        result['media_id'] = normalized['media_id']
    return result
