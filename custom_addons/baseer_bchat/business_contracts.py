"""Pure native-business contracts. No ORM, network or activation switch."""
from datetime import timedelta
from decimal import Decimal
import hashlib
import json
import re
from uuid import UUID

PURPOSES = ('chat', 'tasks', 'procurement', 'sales', 'invoice_intake')
NATIVE_EVENTS = {
    'task_created': ('project.task', 'tasks'),
    'procurement_submitted': ('baseer.procurement.request', 'procurement'),
    'pos_session_closed': ('pos.session', 'sales'),
}
CARD_BATCH = 20
MAX_CARD_ATTEMPTS = 5


class BusinessRejected(ValueError):
    """Stable private code; never include sensitive source content."""


def record_id(value):
    if type(value) is not int or not 0 < value <= 2147483647:
        raise BusinessRejected('invalid_record_id')
    return value


def version(value):
    if type(value) is not int or not 0 <= value <= 2147483647:
        raise BusinessRejected('invalid_revision')
    return value


def uuid4(value):
    try:
        parsed = UUID(value) if isinstance(value, str) and len(value) == 36 else None
    except (ValueError, AttributeError):
        parsed = None
    if not parsed or parsed.version != 4 or str(parsed) != value.lower():
        raise BusinessRejected('invalid_uuid')
    return str(parsed)


def text(value, limit, *, empty=False):
    if not isinstance(value, str) or '\x00' in value or (not empty and not value.strip()):
        raise BusinessRejected('invalid_text')
    try:
        if len(value.encode('utf-8')) > limit:
            raise BusinessRejected('text_too_long')
    except UnicodeEncodeError:
        raise BusinessRejected('invalid_text') from None
    return value


def _keys(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        raise BusinessRejected('invalid_fields')


def quantity(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,9}(?:\.[0-9]{1,2})?', value):
        raise BusinessRejected('invalid_quantity')
    number = Decimal(value)
    if not number.is_finite() or number <= 0:
        raise BusinessRejected('invalid_quantity')
    return format(number.quantize(Decimal('0.01')), 'f')


def _encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(_encoded(value)).hexdigest()


def normalize_draft(kind, payload):
    if kind == 'task':
        _keys(payload, ('project_id', 'title', 'description', 'assignee_user_ids'))
        members = payload['assignee_user_ids']
        if type(members) is not list or len(members) > 50:
            raise BusinessRejected('invalid_assignees')
        ids = [record_id(value) for value in members]
        if len(set(ids)) != len(ids):
            raise BusinessRejected('duplicate_assignee')
        result = {'project_id': record_id(payload['project_id']), 'title': text(payload['title'], 256),
                  'description': text(payload['description'], 16384, empty=True), 'assignee_user_ids': sorted(ids)}
    elif kind == 'procurement':
        _keys(payload, ('warehouse_id', 'representative_partner_id', 'lines'))
        if type(payload['lines']) is not list or not 1 <= len(payload['lines']) <= 200:
            raise BusinessRejected('invalid_lines')
        lines = []
        for line in payload['lines']:
            _keys(line, ('option_id', 'quantity'))
            lines.append({'option_id': record_id(line['option_id']), 'quantity': quantity(line['quantity'])})
        if len({line['option_id'] for line in lines}) != len(lines):
            raise BusinessRejected('duplicate_option')
        result = {'warehouse_id': record_id(payload['warehouse_id']),
                  'representative_partner_id': record_id(payload['representative_partner_id']),
                  'lines': sorted(lines, key=lambda line: line['option_id'])}
    else:
        raise BusinessRejected('invalid_kind')
    if len(_encoded(result)) > 65536:
        raise BusinessRejected('draft_too_large')
    return result


def draft_identity(company_id, binding_id, kind, client_uuid, payload):
    return {'company_id': record_id(company_id), 'binding_id': record_id(binding_id),
            'kind': kind, 'client_uuid': uuid4(client_uuid), 'payload': normalize_draft(kind, payload)}


def event_identity(company_id, binding_id, event, res_model, res_id):
    contract = NATIVE_EVENTS.get(event)
    if not contract or contract[0] != res_model:
        raise BusinessRejected('invalid_event_source')
    return {'company_id': record_id(company_id), 'binding_id': record_id(binding_id),
            'event': event, 'res_model': res_model, 'res_id': record_id(res_id)}


def event_key(identity):
    value = event_identity(**identity)
    # Audience belongs to the immutable digest, not the dedupe key. Rebinding
    # an event must conflict rather than publishing it to a second audience.
    return '%s:%s:%s:%s' % (value['company_id'], value['event'], value['res_model'], value['res_id'])


def require_same_event(existing, candidate):
    if event_key(existing) != event_key(candidate) or digest(existing) != digest(candidate):
        raise BusinessRejected('event_conflict')


def delivery_failure(attempt, now):
    if type(attempt) is not int or attempt < 1:
        raise BusinessRejected('invalid_attempt')
    if attempt >= MAX_CARD_ATTEMPTS:
        return {'state': 'failed', 'next_attempt_at': False}
    return {'state': 'retry', 'next_attempt_at': now + timedelta(minutes=2 ** (attempt - 1))}


def procurement_status(state):
    labels = {'draft': 'request_recorded', 'sent': 'sent_for_purchase', 'received': 'manager_quantity_receipt',
              'purchased': 'quantity_receipt_completed', 'cancel': 'cancelled'}
    if state not in labels:
        raise BusinessRejected('unknown_procurement_state')
    return {'quantity_status': labels[state], 'payment_status': 'not_established'}


def completion_transition(*, review_required, review_state, action, is_reviewer):
    if type(review_required) is not bool or type(is_reviewer) is not bool:
        raise BusinessRejected('invalid_review_policy')
    if review_state not in ('not_required', 'not_requested', 'pending', 'approved', 'changes_requested'):
        raise BusinessRejected('invalid_review_state')
    if action == 'request':
        if not review_required:
            return {'state': '1_done', 'review_state': 'not_required'}
        if review_state == 'approved':
            return {'state': '1_done', 'review_state': 'approved'}
        return {'state': '01_in_progress', 'review_state': 'pending'}
    if action not in ('approve', 'reject') or not review_required or not is_reviewer:
        raise BusinessRejected('review_not_permitted')
    if review_state != 'pending':
        raise BusinessRejected('review_not_pending')
    return {'state': '1_done' if action == 'approve' else '02_changes_requested',
            'review_state': 'approved' if action == 'approve' else 'changes_requested'}


def canonical_attachment(value):
    _keys(value, ('attachment_id', 'company_id', 'res_model', 'res_id', 'checksum', 'sha256', 'mimetype', 'size', 'purpose'))
    result = dict(value)
    for field in ('attachment_id', 'company_id', 'res_id'):
        result[field] = record_id(value[field])
    if value['res_model'] not in ('discuss.channel', 'project.task', 'baseer.procurement.request', 'account.move', 'pos.session'):
        raise BusinessRejected('unsupported_attachment_owner')
    if value['purpose'] not in PURPOSES:
        raise BusinessRejected('invalid_purpose')
    for field, length in (('checksum', 40), ('sha256', 64)):
        if not isinstance(value[field], str) or not re.fullmatch('[0-9a-f]{%d}' % length, value[field]):
            raise BusinessRejected('invalid_content_digest')
    if type(value['size']) is not int or value['size'] <= 0:
        raise BusinessRejected('invalid_size')
    result['mimetype'] = text(value['mimetype'], 127)
    return result
