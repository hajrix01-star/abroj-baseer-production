"""Transport contracts only. This module deliberately has no Odoo dependency."""
import hashlib
import json
from uuid import UUID


API_VERSION = 1
MAX_PAYLOAD_BYTES = 65536
MAX_TEXT_BYTES = 16384
MAX_MEMBERS = 50
HISTORY_POLICIES = ('since_join', 'all_history')
DEFAULT_HISTORY_POLICY = 'since_join'
RELEASE_BLOCKERS = (
    'per_user_session_device_qa',
    'global_history_policy',
    'native_company_group_file_acl_qa',
    'transactional_outbox_concurrency_qa',
    'explicit_company_purpose_binding_qa',
    'native_task_procurement_pos_acceptance',
    'canonical_attachment_hold_and_restore_qa',
    'existing_invoice_binding_and_hold_migration',
    'retention_and_provider_decisions',
)


class ProtocolError(ValueError):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code = code
        self.status = status

    def as_payload(self):
        return {'api_version': API_VERSION, 'error': {
            'code': self.code, 'message': str(self),
        }}


def require_released():
    """No parameter, context flag, setting, admin or client can enable this build.

    Replace only through a reviewed future implementation and acceptance suite.
    This gate does not claim to implement native Discuss history restrictions.
    """
    raise ProtocolError(
        'integration_disabled',
        'BWork business integration is unavailable pending security acceptance.',
        503,
    )


def capabilities():
    return {
        'api_version': API_VERSION,
        'integration_enabled': False,
        'authentication': 'odoo_user_session',
        'capabilities': {
            'messages': False, 'conversations': False, 'attachments': False,
            'history': False, 'membership': False, 'tasks': False,
            'shifts': False, 'procurement': False, 'report_events': False,
            'delivery_receipts': False, 'read_receipts': False,
        },
        'history_policy': {
            'default': DEFAULT_HISTORY_POLICY,
            'enforced_globally': False,
            'activation_blocked': True,
        },
        'release_blockers': list(RELEASE_BLOCKERS),
    }


def positive_id(value, field):
    if type(value) is not int or value <= 0 or value > 2147483647:
        raise ProtocolError('invalid_payload', '%s must be a positive record ID.' % field)
    return value


def canonical_uuid(value):
    if not isinstance(value, str) or len(value) != 36:
        raise ProtocolError('invalid_payload', 'client_uuid must be a UUIDv4.')
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError):
        raise ProtocolError('invalid_payload', 'client_uuid must be a UUIDv4.') from None
    if parsed.version != 4 or str(parsed) != value.lower():
        raise ProtocolError('invalid_payload', 'client_uuid must be a UUIDv4.')
    return str(parsed)


def _text(value, field, byte_limit):
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        raise ProtocolError('invalid_payload', '%s must contain text.' % field)
    try:
        length = len(value.encode('utf-8'))
    except UnicodeEncodeError:
        raise ProtocolError('invalid_payload', '%s must be valid UTF-8 text.' % field) from None
    if length > byte_limit:
        raise ProtocolError('invalid_payload', '%s is too long.' % field)
    return value  # Preserve exact user text for the immutable payload hash.


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError('invalid_payload', 'Duplicate JSON keys are not allowed.')
        result[key] = value
    return result


def parse_payload(raw):
    if not isinstance(raw, str):
        raise ProtocolError('invalid_payload', 'A JSON payload form field is required.')
    try:
        size = len(raw.encode('utf-8'))
    except UnicodeEncodeError:
        raise ProtocolError('invalid_payload', 'Payload must be UTF-8.') from None
    if size > MAX_PAYLOAD_BYTES:
        raise ProtocolError('payload_too_large', 'Payload exceeds 64 KiB.', 413)
    try:
        value = json.loads(raw, object_pairs_hook=_object,
                           parse_constant=lambda value: _reject_constant())
    except (ValueError, RecursionError) as error:
        if isinstance(error, ProtocolError):
            raise
        raise ProtocolError('invalid_payload', 'Payload must be a valid JSON object.') from None
    if type(value) is not dict:
        raise ProtocolError('invalid_payload', 'Payload must be a JSON object.')
    return value


def _reject_constant():
    raise ProtocolError('invalid_payload', 'Non-finite JSON numbers are not allowed.')


def _check_keys(payload, fields):
    if type(payload) is not dict or set(payload) != set(fields):
        raise ProtocolError('invalid_payload', 'Payload fields do not match the v1 contract.')
    if type(payload['api_version']) is not int or payload['api_version'] != API_VERSION:
        raise ProtocolError('unsupported_version', 'Only API version 1 is supported.')


def normalize_message(payload):
    _check_keys(payload, (
        'api_version', 'company_id', 'channel_id', 'client_uuid', 'text',
        'attachment_ids', 'reply_to_id',
    ))
    attachments = payload['attachment_ids']
    if type(attachments) is not list or len(attachments) > 20:
        raise ProtocolError('invalid_payload', 'attachment_ids must be a bounded list.')
    for attachment in attachments:
        positive_id(attachment, 'attachment_ids')
    if payload['reply_to_id'] is not None:
        positive_id(payload['reply_to_id'], 'reply_to_id')
    normalized = {
        'api_version': API_VERSION,
        'company_id': positive_id(payload['company_id'], 'company_id'),
        'channel_id': positive_id(payload['channel_id'], 'channel_id'),
        'client_uuid': canonical_uuid(payload['client_uuid']),
        'text': _text(payload['text'], 'text', MAX_TEXT_BYTES),
        'attachment_ids': sorted(set(attachments)),
        'reply_to_id': payload['reply_to_id'],
    }
    # No upload, linking, quoted text or parent message lookup is implemented.
    # Do not let a valid-looking attachment ID fall through to message_post.
    if attachments or payload['reply_to_id'] is not None:
        raise ProtocolError('capability_unavailable',
                            'Attachments and replies are unavailable in this increment.', 409)
    return normalized


def normalize_conversation(payload):
    _check_keys(payload, (
        'api_version', 'company_id', 'client_uuid', 'name', 'member_user_ids',
    ))
    members = payload['member_user_ids']
    if type(members) is not list or not 1 <= len(members) <= MAX_MEMBERS:
        raise ProtocolError('invalid_payload', 'Choose between 1 and 50 member user IDs.')
    for member in members:
        positive_id(member, 'member_user_ids')
    if len(set(members)) != len(members):
        raise ProtocolError('invalid_payload', 'Duplicate members are not allowed.')
    return {
        'api_version': API_VERSION,
        'company_id': positive_id(payload['company_id'], 'company_id'),
        'client_uuid': canonical_uuid(payload['client_uuid']),
        'name': _text(payload['name'], 'name', 256),
        'member_user_ids': sorted(members),
    }


def payload_digest(normalized):
    """Server computes this after validation; never trust a supplied hash."""
    encoded = json.dumps(normalized, sort_keys=True, ensure_ascii=False,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def persisted_ack(normalized, message_id):
    """Serialize a VERIFIED stored receipt, never a network/push result.

    This pure helper cannot establish durability. The future transactional
    adapter must call it only for the canonical persisted native mail.message.
    """
    return {
        'api_version': API_VERSION,
        'client_uuid': normalized['client_uuid'],
        'company_id': normalized['company_id'],
        'channel_id': normalized['channel_id'],
        'message_id': positive_id(message_id, 'message_id'),
        'state': 'sent',
    }


def replay_ack(normalized, stored_digest, message_id):
    if payload_digest(normalized) != stored_digest:
        raise ProtocolError('idempotency_conflict',
                            'The UUID is already associated with another payload.', 409)
    return persisted_ack(normalized, message_id)
