"""Terminal room-preference cancellation, real primary PostgreSQL witnesses.

Explicit isolated-shell invocation only; not imported by the ORM test suite.
The two service transactions really contend on the same advisory key. Pauses
surround genuine receipt creation/fresh replay, never replace a DB/service result.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, local
import json
import time
from unittest.mock import patch
from uuid import uuid4

from psycopg2.errors import SerializationFailure
from odoo import Command, api

from ..contracts import ProtocolError


DATABASE = 'bchat_maturity_test_20261017'


def run(env):
    if env.cr.dbname != DATABASE:
        raise RuntimeError('Refusing cancellation probe outside the exact isolated test database')
    registry = env.registry
    admin = env.ref('base.user_admin')
    company_id, admin_id = admin.company_id.id, admin.id
    marker = uuid4().hex
    users = env['res.users'].with_context(no_reset_password=True, mail_create_nosubscribe=True).create([{
        'name': 'Cancellation race %s %s' % (label, marker),
        'login': 'bchat-cancel-race-%s-%s' % (label, marker),
        'company_id': company_id, 'company_ids': [Command.set([company_id])],
        'group_ids': [Command.set([env.ref('base.group_user').id])],
    } for label in ('owner', 'reader')])
    owner, reader = users
    fixture_ids, reader_id = users.ids, reader.id
    phases = ('cancel_before_original', 'original_before_cancel',
              'rr_wait_applied_current', 'late_original_payload_conflict')
    fixtures = {}
    for phase in phases:
        name = 'Cancellation race %s %s' % (phase, marker)
        created = env['baseer.bchat.service'].with_user(owner)._v2_group_create({
            'api_version': 2, 'company_id': company_id, 'client_uuid': str(uuid4()),
            'name': name, 'member_user_ids': [reader_id],
        })
        room_id = created['room_id']
        member_id = env['baseer.bchat.membership'].sudo().search([
            ('room_id', '=', room_id), ('user_id', '=', reader_id), ('active', '=', True)], limit=1).id
        fixtures[phase] = {'room_id': room_id, 'membership_id': member_id, 'name': name,
                           'payload': {'api_version': 2, 'membership_id': member_id,
                                       'client_uuid': str(uuid4()), 'expected_revision': 1,
                                       'muted_until': None, 'mute_forever': False,
                                       'pinned': True, 'archived': True}}
    env.cr.commit()
    service_class = type(env['baseer.bchat.service'])
    complete = service_class._social_complete_operation
    applied_replay = service_class._room_preference_applied_replay
    replay_scope = service_class._room_preference_replay_scope
    state = local()
    phase_output = {}
    evidence = {'database': env.cr.dbname, 'phases': phase_output}
    active = {}

    def connection(cursor):
        cursor.execute("SET LOCAL statement_timeout = '8s'")
        cursor.execute("SET LOCAL lock_timeout = '5s'")
        cursor.execute('SHOW transaction_isolation')
        isolation = cursor.fetchone()[0].strip().lower()
        cursor.execute('SELECT pg_backend_pid(), txid_current()')
        pid, txid = cursor.fetchone()
        if isolation != 'repeatable read':
            raise AssertionError('Cancellation witness requires genuine REPEATABLE READ')
        return pid, txid, isolation

    def paused_complete(service, action, token, digest, result):
        value = complete(service, action, token, digest, result)
        if (action == 'room_preferences' and getattr(state, 'role', None) == 'winner'
                and token == active['payload']['client_uuid']):
            active['created'].set()
            if not active['release'].wait(6):
                raise AssertionError('Bounded genuine receipt pause was not released')
        return value

    def paused_applied_replay(service, intent, token, revision):
        if getattr(state, 'role', None) == 'waiter' and active.get('phase') == 'rr_wait_applied_current':
            active['before_fresh'].set()
            if not active['fresh_release'].wait(6):
                raise AssertionError('Bounded fresh-replay pause was not released')
        state.in_applied_replay = True
        try:
            return applied_replay(service, intent, token, revision)
        finally:
            state.in_applied_replay = False

    def observed_scope(service, intent):
        result = replay_scope(service, intent)
        if getattr(state, 'in_applied_replay', False):
            service.env.cr.execute('SHOW transaction_read_only')
            readonly = service.env.cr.fetchone()[0]
            service.env.cr.execute('SHOW transaction_isolation')
            isolation = service.env.cr.fetchone()[0].strip().lower()
            service.env.cr.execute('SELECT pg_backend_pid(), txid_current()')
            pid, txid = service.env.cr.fetchone()
            state.fresh = {'backend_pid': pid, 'txid': txid, 'read_only': readonly, 'isolation': isolation}
        return result

    def execute(role, method, payload, barrier=None):
        state.role, state.fresh = role, None
        initial = None
        retries = []
        for attempt in range(6):
            try:
                with registry.cursor() as cursor:
                    pid, txid, isolation = connection(cursor)
                    cursor.execute('SELECT revision FROM baseer_bchat_membership_preference WHERE membership_id=%s',
                                   [active['membership_id']])
                    initial_revision = cursor.fetchone()
                    if attempt == 0:
                        initial = {'backend_pid': pid, 'txid': txid, 'isolation': isolation,
                                   'snapshot_revision': initial_revision[0] if initial_revision else 1}
                        active['pids'][role] = pid
                        if barrier:
                            barrier.wait(timeout=8)
                        if role == 'waiter' and active.get('hold_winner') and not active['created'].wait(6):
                            raise AssertionError('Winner never persisted its real immutable receipt')
                    service = api.Environment(cursor, reader_id, {'allowed_company_ids': [company_id]})['baseer.bchat.service']
                    result = getattr(service, method)(active['room_id'], payload)
                    cursor.commit()
                    return {'state': 'ok', 'initial': initial, 'attempts': attempt + 1,
                            'retry_sqlstates': retries, 'result': result, 'fresh': state.fresh,
                            'final_backend_pid': pid, 'final_txid': txid}
            except SerializationFailure:
                retries.append('40001')
                if attempt == 5:
                    raise
            except ProtocolError as error:
                if error.code != 'idempotency_conflict' or error.status != 409:
                    raise
                return {'state': error.code, 'status': error.status, 'initial': initial,
                        'attempts': attempt + 1, 'retry_sqlstates': retries}
        raise AssertionError('Unreachable bounded retry exhaustion')

    def wait_advisory():
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            pid = active['pids'].get('waiter')
            if pid:
                with registry.cursor() as cursor:
                    cursor.execute('''SELECT a.pid,a.wait_event_type,a.wait_event,COUNT(l.pid)
                        FROM pg_stat_activity a JOIN pg_locks l ON l.pid=a.pid
                        WHERE a.pid=%s AND NOT l.granted AND l.locktype='advisory'
                        GROUP BY a.pid,a.wait_event_type,a.wait_event''', [pid])
                    row = cursor.fetchone()
                    if row and row[1] == 'Lock' and row[3] > 0:
                        return {'backend_pid': row[0], 'wait_event_type': row[1],
                                'wait_event': row[2], 'ungranted_advisory_locks': row[3]}
            time.sleep(.02)
        raise AssertionError('No genuine PostgreSQL advisory-lock waiter was observed')

    def postcheck(phase, expected_revision, expected_journals, expected_hints, baseline):
        fixture = fixtures[phase]
        with registry.cursor() as cursor:
            cursor.execute('SELECT revision FROM baseer_bchat_membership_preference WHERE membership_id=%s',
                           [fixture['membership_id']])
            revisions = cursor.fetchall()
            if revisions != ([] if expected_revision == 1 else [(expected_revision,)]):
                raise AssertionError('Cancellation changed or lost the actual preference revision')
            cursor.execute('''SELECT payload_digest,result_json FROM baseer_bchat_social_operation
                WHERE actor_id=%s AND action='room_preferences' AND client_uuid=%s''',
                           [reader_id, fixture['payload']['client_uuid']])
            operations = cursor.fetchall()
            expected = {'cancelled': True} if expected_revision == 1 else {'revision': 2}
            if len(operations) != 1 or json.loads(operations[0][1]) != expected:
                raise AssertionError('A terminal operation was duplicated, overwritten or forged')
            cursor.execute('''SELECT COUNT(*) FROM baseer_bchat_social_operation
                WHERE actor_id=%s AND action='room_preferences'
                  AND client_uuid=ANY(%s)''',
                           [reader_id, active['operation_uuids']])
            journals = cursor.fetchone()[0]
            cursor.execute('SELECT COUNT(*) FROM baseer_bchat_change WHERE user_id=%s AND room_id=%s',
                           [reader_id, fixture['room_id']])
            hints = cursor.fetchone()[0] - baseline
            if journals != expected_journals or hints != expected_hints:
                raise AssertionError('Cancellation/late original produced a duplicate receipt or change hint')
            return {'preference_revisions': [row[0] for row in revisions], 'operation_count': journals,
                    'original_result': json.loads(operations[0][1]), 'change_hint_delta': hints}

    try:
        with patch.object(service_class, '_social_complete_operation', paused_complete), \
                patch.object(service_class, '_room_preference_applied_replay', paused_applied_replay), \
                patch.object(service_class, '_room_preference_replay_scope', observed_scope):
            for phase in phases:
                active.clear()
                active.update(fixtures[phase])
                active.update({'phase': phase, 'pids': {}, 'created': Event(), 'release': Event(),
                               'before_fresh': Event(), 'fresh_release': Event(),
                               'hold_winner': phase != 'late_original_payload_conflict',
                               'operation_uuids': [fixtures[phase]['payload']['client_uuid']]})
                with registry.cursor() as cursor:
                    cursor.execute('SELECT COUNT(*) FROM baseer_bchat_change WHERE user_id=%s AND room_id=%s',
                                   [reader_id, active['room_id']])
                    baseline = cursor.fetchone()[0]
                if phase == 'late_original_payload_conflict':
                    execute('seed', '_v2_cancel_room_preferences', active['payload'])
                barrier = Barrier(2)
                first_cancel = phase in ('cancel_before_original', 'late_original_payload_conflict')
                winner_method = '_v2_cancel_room_preferences' if first_cancel else '_v2_set_room_preferences'
                waiter_method = '_v2_set_room_preferences' if first_cancel else '_v2_cancel_room_preferences'
                waiter_payload = ({**active['payload'], 'pinned': False}
                                  if phase == 'late_original_payload_conflict' else active['payload'])
                with ThreadPoolExecutor(max_workers=2) as pool:
                    winner = pool.submit(execute, 'winner', winner_method, active['payload'], barrier)
                    waiter = pool.submit(execute, 'waiter', waiter_method, waiter_payload, barrier)
                    try:
                        witness = wait_advisory() if active['hold_winner'] else None
                        active['release'].set()
                        first = winner.result(timeout=20)
                        if phase == 'rr_wait_applied_current':
                            if not active['before_fresh'].wait(6):
                                raise AssertionError('The RR waiter did not reach real applied replay')
                            newer = {**active['payload'], 'client_uuid': str(uuid4()), 'expected_revision': 2,
                                     'pinned': False, 'archived': False, 'mute_forever': True}
                            active['operation_uuids'].append(newer['client_uuid'])
                            # A real different-UUID service mutation MUST commit while
                            # replay is paused: it proves replay holds no main room lock.
                            advanced = execute('advance', '_v2_set_room_preferences', newer)
                            if advanced['result']['revision'] != 3:
                                raise AssertionError('Concurrent current state did not advance before fresh replay')
                            active['fresh_release'].set()
                        second = waiter.result(timeout=20)
                    finally:
                        active['release'].set()
                        active['fresh_release'].set()
                records = [first, second]
                if len({row['initial']['backend_pid'] for row in records}) != 2:
                    raise AssertionError('Cancellation race did not use two independent PostgreSQL backends')
                if any(row['initial']['isolation'] != 'repeatable read' for row in records):
                    raise AssertionError('Missing actual RR evidence')
                if len({row['initial']['txid'] for row in records}) != 2 or any(row['initial']['snapshot_revision'] != 1 for row in records):
                    raise AssertionError('Both independent transactions must establish the genuine initial revision-one snapshot')
                if phase == 'late_original_payload_conflict':
                    if first['state'] != 'ok' or second['state'] != 'idempotency_conflict' or not first['result']['cancelled']:
                        raise AssertionError('Late different-payload original was not rejected after terminal cancellation')
                elif first_cancel:
                    if any(row['state'] != 'ok' for row in records) or first['result'] != second['result'] or not first['result']['cancelled']:
                        raise AssertionError('Cancel winner did not fence the waiting original with the same exact receipt')
                else:
                    replay = second['result']
                    current_revision = 3 if phase == 'rr_wait_applied_current' else 2
                    if (first['state'] != 'ok' or second['state'] != 'ok' or replay.get('cancelled') is not None
                            or replay['replayed'] is not True or replay['operation_revision'] != 2 or replay['revision'] != current_revision):
                        raise AssertionError('Applied winner did not return an authorized current replay ACK')
                    fresh = second['fresh']
                    if (not fresh or fresh['read_only'] != 'on' or fresh['isolation'] != 'repeatable read'
                            or fresh['backend_pid'] == second['final_backend_pid'] or fresh['txid'] == second['final_txid']):
                        raise AssertionError('Applied RR replay did not use a separate real read-only snapshot')
                    if phase == 'rr_wait_applied_current' and (replay['pinned'] or replay['archived'] or not replay['muted']):
                        raise AssertionError('Replay borrowed the stale main-transaction preference snapshot')
                expected_revision = 1 if first_cancel else (3 if phase == 'rr_wait_applied_current' else 2)
                checked = postcheck(phase, expected_revision, 2 if expected_revision == 3 else 1,
                                    0 if first_cancel else (2 if expected_revision == 3 else 1), baseline)
                phase_output[phase] = {'transactions': records, 'advisory_wait': witness, 'postcheck': checked}
        return evidence
    finally:
        room_ids = [row['room_id'] for row in fixtures.values()]
        with registry.cursor() as cursor:
            cursor.execute('SELECT id,name FROM baseer_bchat_room WHERE id=ANY(%s)', [room_ids])
            if dict(cursor.fetchall()) != {row['room_id']: row['name'] for row in fixtures.values()}:
                raise RuntimeError('Refusing cancellation cleanup: exact room markers changed')
            cursor.execute('SELECT id,login FROM res_users WHERE id=ANY(%s)', [fixture_ids])
            if dict(cursor.fetchall()) != {user_id: 'bchat-cancel-race-%s-%s' % (label, marker)
                                           for user_id, label in zip(fixture_ids, ('owner', 'reader'))}:
                raise RuntimeError('Refusing cancellation cleanup: exact user markers changed')
            cursor.execute('DELETE FROM baseer_bchat_push_event WHERE recipient_id=ANY(%s)', [fixture_ids])
            cursor.execute('DELETE FROM baseer_bchat_social_operation WHERE actor_id=ANY(%s)', [fixture_ids])
            cursor.execute('''DELETE FROM baseer_bchat_membership_preference WHERE membership_id IN
                (SELECT id FROM baseer_bchat_membership WHERE room_id=ANY(%s))''', [room_ids])
            cursor.execute('DELETE FROM baseer_bchat_change WHERE user_id=ANY(%s) OR room_id=ANY(%s)', [fixture_ids, room_ids])
            cursor.execute('DELETE FROM baseer_bchat_group_event WHERE room_id=ANY(%s)', [room_ids])
            cursor.execute('DELETE FROM baseer_bchat_membership WHERE room_id=ANY(%s)', [room_ids])
            cursor.execute('DELETE FROM baseer_bchat_room WHERE id=ANY(%s)', [room_ids])
            cursor.execute('DELETE FROM baseer_bchat_change_cursor WHERE user_id=ANY(%s)', [fixture_ids])
            api.Environment(cursor, admin_id, {})['res.users'].sudo().browse(fixture_ids).unlink()
            cursor.execute('SELECT COUNT(*) FROM baseer_bchat_room WHERE id=ANY(%s)', [room_ids])
            remaining_rooms = cursor.fetchone()[0]
            cursor.execute('SELECT COUNT(*) FROM res_users WHERE id=ANY(%s)', [fixture_ids])
            remaining_users = cursor.fetchone()[0]
            if remaining_rooms or remaining_users:
                raise AssertionError('Cancellation fixture cleanup left owned rows behind')
            cursor.commit()
            evidence['cleanup'] = {'remaining_rooms': remaining_rooms, 'remaining_users': remaining_users}
