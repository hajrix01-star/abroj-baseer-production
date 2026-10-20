"""Modern work-task facade. Never change the legacy task fingerprint bytes."""
import json

from . import task_contracts as legacy
from .contracts import ProtocolError, positive_id

API_VERSION = 2
WORK_TASKS_VERSION = 1
LIST_BYTES = 128 * 1024
TASK_BYTES = 12 * 1024
OPTIONS_BYTES = 512 * 1024
ASSIGNEES_BYTES = 64 * 1024


def wire_size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))


def bounded(value, limit):
    if wire_size(value) > limit:
        raise ProtocolError('bounded_capacity', 'The work-task response exceeds its supported size.', 409)
    return value


def _version(payload, keys):
    legacy._keys(payload, keys)
    if type(payload['work_tasks_version']) is not int or payload['work_tasks_version'] != 1:
        raise ProtocolError('unsupported_version', 'Only work_tasks_version 1 is supported.')


def normalize_create(payload):
    _version(payload, ('api_version', 'work_tasks_version', 'company_id', 'room_id',
                      'client_uuid', 'title', 'description', 'due_at', 'reminder_at', 'assignee_id'))
    if payload['room_id'] is not None:
        raise ProtocolError('invalid_payload', 'Modern work tasks are standalone.')
    original = {key: value for key, value in payload.items()
                if key not in ('work_tasks_version', 'reminder_at')}
    values = legacy.normalize_create(original)
    values['reminder_at'] = legacy._due(payload['reminder_at'])
    if values['reminder_at'] and (not values['due_at'] or values['reminder_at'] > values['due_at']):
        raise ProtocolError('invalid_payload', 'A reminder requires a due date and cannot follow it.')
    return values


def normalize_transition(payload):
    _version(payload, ('api_version', 'work_tasks_version', 'company_id', 'client_uuid',
                      'expected_revision', 'action', 'assignee_id', 'reason'))
    if payload['action'] not in ('start', 'done', 'cancel', 'reassign'):
        raise ProtocolError('invalid_payload', 'Unknown modern task action.')
    original = {key: value for key, value in payload.items()
                if key not in ('work_tasks_version', 'company_id')}
    values = legacy.normalize_transition(original)
    values['company_id'] = positive_id(payload['company_id'], 'company_id')
    return values


def digest(operation, target_id, values):
    return legacy.digest('work_tasks_v1:' + operation, target_id, values)


def page(envelope, rows, has_more):
    """Byte-adaptive cursor points at the last returned row, never a dropped tail."""
    selected = []
    for row in rows[:30]:
        bounded(row, TASK_BYTES)
        candidate = dict(envelope, tasks=selected + [row], next_before_id=row['id'])
        if wire_size(candidate) > LIST_BYTES:
            break
        selected.append(row)
    if rows and not selected:
        raise ProtocolError('bounded_capacity', 'A task cannot fit in its page.', 409)
    more = has_more or len(selected) < len(rows)
    return bounded(dict(envelope, tasks=selected,
                        next_before_id=selected[-1]['id'] if selected and more else None), LIST_BYTES)
