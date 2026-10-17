"""Real two-connection CAS/replay probe; disposable bchat_maturity_test_* only.

No database/lock/service is mocked. A barrier immediately before the genuine
room lock aligns the absent-row CAS race. Only external push scheduling and
provider configuration are disabled, so no synthetic token reaches FCM.
Call run(env) from an authorized isolated Odoo shell; this is NOT auto-imported.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, local
from unittest.mock import patch
from uuid import uuid4

from psycopg2.errors import SerializationFailure

from odoo import Command, api, fields

from ..contracts import ProtocolError
from ..models.push import _PUSH_TOKEN


def run(env):
    if not env.cr.dbname.startswith('bchat_maturity_test_'):
        raise RuntimeError('Refusing social race outside a disposable bchat_maturity_test_* database')
    registry = env.registry
    admin = env.ref('base.user_admin')
    company_id, admin_id = admin.company_id.id, admin.id
    marker = uuid4().hex
    users = env['res.users'].with_context(no_reset_password=True, mail_create_nosubscribe=True).create([{
        'name': 'Social race %s %s' % (label, marker),
        'login': 'bchat-social-race-%s-%s' % (label, marker),
        'company_id': company_id, 'company_ids': [Command.set([company_id])],
        'group_ids': [Command.set([env.ref('base.group_user').id])],
    } for label in ('owner', 'reader')])
    owner, reader = users
    reader_id, fixture_ids = reader.id, users.ids
    created = env['baseer.bchat.service'].with_user(owner)._v2_group_create({
        'api_version': 2, 'company_id': company_id, 'client_uuid': str(uuid4()),
        'name': 'Social race ' + marker, 'member_user_ids': [reader_id],
    })
    room_id = created['room_id']
    member_id = env['baseer.bchat.membership'].sudo().search([
        ('room_id', '=', room_id), ('user_id', '=', reader_id), ('active', '=', True)], limit=1).id
    registrations = []
    for number in range(2):
        registrations.append(env['baseer.bchat.service'].with_user(reader)._v2_push_register({
            'api_version': 2, 'installation_id': str(uuid4()),
            'fcm_token': 'synthetic-social-%s-%s-' % (marker, number) + 'x' * 40,
        }))
    env.cr.commit()
    service_class = type(env['baseer.bchat.service'])
    event_class = type(env['baseer.bchat.push.event'])
    original_scope = service_class._room_preference_scope
    state = local()
    backend_pids = set()
    phase_results = {}
    room_barrier = Barrier(2)

    def aligned_scope(service, target_room, membership_id, *, mutate=False):
        if mutate and getattr(state, 'align_room', False) and not getattr(state, 'aligned', False):
            state.aligned = True
            room_barrier.wait(timeout=10)
        return original_scope(service, target_room, membership_id, mutate=mutate)

    def execute(start, action, align_room, quota_snapshot):
        state.align_room, state.aligned = align_room, False
        initial_backend_pid = None
        isolation = None
        for attempt in range(6):
            try:
                with registry.cursor() as cursor:
                    cursor.execute("SET LOCAL statement_timeout = '8s'")
                    cursor.execute("SET LOCAL lock_timeout = '5s'")
                    if attempt == 0:
                        cursor.execute('SHOW transaction_isolation')
                        isolation = cursor.fetchone()[0].strip().lower()
                        if isolation != 'repeatable read':
                            raise AssertionError('Social race requires actual PostgreSQL REPEATABLE READ isolation')
                    cursor.execute('SELECT pg_backend_pid()')
                    backend_pid = cursor.fetchone()[0]
                    backend_pids.add(backend_pid)
                    if attempt == 0:
                        initial_backend_pid = backend_pid
                        if quota_snapshot:
                            cursor.execute('''SELECT COUNT(*) FROM baseer_bchat_push_event
                                WHERE recipient_id=%s AND event_kind='diagnostic'
                                  AND create_date>NOW()-INTERVAL '1 day' ''', [reader_id])
                            if cursor.fetchone()[0] != 9:
                                raise AssertionError('Both stale quota snapshots must start at exactly nine tests')
                        # Both real independent transactions establish their
                        # RR snapshot before either can acquire a service lock.
                        start.wait(timeout=10)
                    fresh = api.Environment(cursor, reader_id, {'allowed_company_ids': [company_id]})
                    result = action(fresh['baseer.bchat.service'])
                    cursor.commit()
                    return {'state': 'ok', 'attempts': attempt + 1,
                            'initial_backend_pid': initial_backend_pid, 'isolation': isolation, 'result': result}
            except SerializationFailure:
                if attempt == 5:
                    raise
            except ProtocolError as error:
                if error.code not in ('revision_conflict', 'rate_limited'):
                    raise
                return {'state': error.code, 'attempts': attempt + 1,
                        'initial_backend_pid': initial_backend_pid, 'isolation': isolation,
                        'status': error.status,
                        'retry_after_seconds': getattr(error, 'retry_after_seconds', None)}
            # DeadlockDetected/lock timeouts are deliberately not swallowed.

    def race(actions, align_room=False, quota_snapshot=False):
        start = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(execute, start, action, align_room, quota_snapshot) for action in actions]
            result = [future.result(timeout=40) for future in futures]
        if len({row['initial_backend_pid'] for row in result}) != 2:
            raise AssertionError('The race did not use independent PostgreSQL backends')
        return result

    try:
        with patch.object(service_class, '_room_preference_scope', aligned_scope), \
                patch.object(event_class, '_schedule_fast_dispatch', return_value=None), \
                patch.object(event_class, '_fcm_config', return_value=None):
            room_payload = {'api_version': 2, 'membership_id': member_id,
                            'expected_revision': 1, 'muted_until': None, 'mute_forever': False,
                            'pinned': False, 'archived': True}
            before = env['baseer.bchat.membership.preference'].sudo().search_count([('membership_id', '=', member_id)])
            if before:
                raise AssertionError('Absent-row fixture was not empty')
            payloads = [{**room_payload, 'client_uuid': str(uuid4()), 'pinned': bool(number)} for number in range(2)]
            phase_results['absent_room_preference_cas'] = race([
                lambda service, payload=payload: service._v2_set_room_preferences(room_id, payload)
                for payload in payloads
            ], align_room=True)
            if sorted(row['state'] for row in phase_results['absent_room_preference_cas']) != ['ok', 'revision_conflict']:
                raise AssertionError('The first preference CAS did not have one winner')
            preview = {'api_version': 2, 'installation_id': registrations[0]['installation_id'],
                       'account_key': registrations[0]['account_key'], 'client_uuid': str(uuid4()),
                       'expected_revision': 1, 'preview_mode': 'full'}
            phase_results['preview_same_uuid'] = race([
                lambda service: service._v2_notification_set_preferences(preview),
                lambda service: service._v2_notification_set_preferences(preview),
            ])
            if any(row['state'] != 'ok' or row['result']['operation_revision'] != 2
                   for row in phase_results['preview_same_uuid']):
                raise AssertionError('Concurrent preview retry did not resolve one intent')
            diagnostic = {'api_version': 2, 'installation_id': registrations[1]['installation_id'],
                          'account_key': registrations[1]['account_key'], 'client_uuid': str(uuid4())}
            phase_results['diagnostic_same_uuid'] = race([
                lambda service: service._v2_notification_test(diagnostic),
                lambda service: service._v2_notification_test(diagnostic),
            ])
            event_ids = {row['result']['test']['event_id'] for row in phase_results['diagnostic_same_uuid']}
            if len(event_ids) != 1:
                raise AssertionError('Concurrent diagnostic retry duplicated its event')
            with registry.cursor() as preparation:
                prepared = api.Environment(preparation, reader_id, {'allowed_company_ids': [company_id]})
                devices = prepared['baseer.bchat.push.device'].sudo().search([
                    ('user_id', '=', reader_id), ('active', '=', True)], order='id')
                if len(devices) != 2:
                    raise AssertionError('Daily quota race requires two distinct current installations')
                prepared['baseer.bchat.push.event']._queue_verified([{
                    'recipient_id': reader_id, 'device_id': devices[number % 2].id,
                    'company_id': company_id, 'event_kind': 'diagnostic',
                    'diagnostic_uuid': str(uuid4()), 'state': 'pending', 'next_attempt_at': fields.Datetime.now(),
                } for number in range(8)], _PUSH_TOKEN)
                # Fixture clock adjustment only: avoid the device minute limit
                # so this phase specifically proves the account daily quota.
                preparation.execute('''UPDATE baseer_bchat_push_event
                    SET create_date=NOW()-INTERVAL '2 minutes'
                    WHERE recipient_id=%s AND event_kind='diagnostic' ''', [reader_id])
                preparation.commit()
            daily = [{'api_version': 2, 'installation_id': row['installation_id'],
                      'account_key': row['account_key'], 'client_uuid': str(uuid4())}
                     for row in registrations]
            phase_results['diagnostic_distinct_devices_daily_quota'] = race([
                lambda service, payload=payload: service._v2_notification_test(payload)
                for payload in daily
            ], quota_snapshot=True)
            quota_results = phase_results['diagnostic_distinct_devices_daily_quota']
            if sorted(row['state'] for row in quota_results) != ['ok', 'rate_limited']:
                raise AssertionError('The final daily slot must have exactly one winner across two devices')
            denied = next(row for row in quota_results if row['state'] == 'rate_limited')
            if denied['status'] != 429 or not denied['retry_after_seconds']:
                raise AssertionError('Daily quota loser did not return an explicit rate limit')
            direct_a = {'api_version': 2, 'company_id': company_id,
                        'peer_user_id': reader_id, 'client_uuid': str(uuid4())}
            direct_b = {'api_version': 2, 'company_id': company_id,
                        'peer_user_id': owner.id, 'client_uuid': str(uuid4())}
            phase_results['direct_reverse_pair'] = race([
                lambda service: service.with_user(owner.id)._v2_direct_room(direct_a),
                lambda service: service._v2_direct_room(direct_b),
            ])
            if len({row['result']['room_id'] for row in phase_results['direct_reverse_pair']}) != 1:
                raise AssertionError('Reverse direct creation produced more than one room')
        with registry.cursor() as cursor:
            cursor.execute('SELECT revision FROM baseer_bchat_membership_preference WHERE membership_id = %s', [member_id])
            if cursor.fetchall() != [(2,)]:
                raise AssertionError('The absent-row CAS created duplicate state or lost its revision')
            cursor.execute('SELECT COUNT(*) FROM baseer_bchat_push_event WHERE recipient_id = %s', [reader_id])
            if cursor.fetchone()[0] != 10:
                raise AssertionError('The distinct-device daily quota race exceeded ten tests')
            cursor.execute('SELECT COUNT(*) FROM baseer_bchat_social_operation WHERE actor_id = %s', [reader_id])
            if cursor.fetchone()[0] != 5:
                raise AssertionError('A failed/replayed operation duplicated its immutable receipt')
        return {'independent_backends': len(backend_pids), 'phases': phase_results,
                'room_preference_rows': 1, 'diagnostic_events': 10,
                'diagnostic_idempotent_events': 1, 'daily_quota_winners': 1}
    finally:
        with registry.cursor() as cursor:
            cursor.execute('SELECT name FROM baseer_bchat_room WHERE id = %s', [room_id])
            if cursor.fetchone() != ('Social race ' + marker,):
                raise RuntimeError('Refusing cleanup: synthetic room marker changed')
            cursor.execute('SELECT login FROM res_users WHERE id = ANY(%s)', [fixture_ids])
            if {row[0] for row in cursor.fetchall()} != {
                    'bchat-social-race-%s-%s' % (label, marker) for label in ('owner', 'reader')}:
                raise RuntimeError('Refusing cleanup: synthetic user markers changed')
            cursor.execute('DELETE FROM baseer_bchat_push_event WHERE recipient_id = ANY(%s)', [fixture_ids])
            cursor.execute('DELETE FROM baseer_bchat_push_device WHERE user_id = ANY(%s)', [fixture_ids])
            cursor.execute('DELETE FROM baseer_bchat_social_operation WHERE actor_id = ANY(%s)', [fixture_ids])
            cursor.execute('''DELETE FROM baseer_bchat_membership_preference WHERE membership_id IN
                              (SELECT id FROM baseer_bchat_membership WHERE room_id = %s)''', [room_id])
            cursor.execute('DELETE FROM baseer_bchat_change WHERE user_id = ANY(%s) OR room_id = %s', [fixture_ids, room_id])
            cursor.execute('DELETE FROM baseer_bchat_group_event WHERE room_id = %s', [room_id])
            cursor.execute('''SELECT id, room_id FROM baseer_bchat_direct_pair
                              WHERE company_id = %s AND low_user_id = %s AND high_user_id = %s''',
                           [company_id, min(fixture_ids), max(fixture_ids)])
            direct_pairs = cursor.fetchall()
            for pair_id, direct_room_id in direct_pairs:
                cursor.execute('SELECT name, company_id FROM baseer_bchat_room WHERE id = %s', [direct_room_id])
                direct_marker = cursor.fetchone()
                if not direct_marker or marker not in direct_marker[0] or direct_marker[1] != company_id:
                    raise RuntimeError('Refusing cleanup: synthetic direct room marker changed')
                cursor.execute('DELETE FROM baseer_bchat_membership WHERE room_id = %s', [direct_room_id])
                cursor.execute('UPDATE baseer_bchat_room SET direct_pair_id = NULL WHERE id = %s', [direct_room_id])
                cursor.execute('DELETE FROM baseer_bchat_direct_pair WHERE id = %s', [pair_id])
                cursor.execute('DELETE FROM baseer_bchat_room WHERE id = %s', [direct_room_id])
            cursor.execute('DELETE FROM baseer_bchat_membership WHERE room_id = %s', [room_id])
            cursor.execute('DELETE FROM baseer_bchat_room WHERE id = %s', [room_id])
            cursor.execute('DELETE FROM baseer_bchat_change_cursor WHERE user_id = ANY(%s)', [fixture_ids])
            api.Environment(cursor, admin_id, {})['res.users'].sudo().browse(fixture_ids).unlink()
            cursor.commit()
