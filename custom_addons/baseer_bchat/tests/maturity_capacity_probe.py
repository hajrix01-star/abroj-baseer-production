"""Bounded Odoo-service capacity sample; never HTTP/device/SLA evidence.

Use only through the isolated Odoo-shell entrypoint. All measured services
run as ordinary synthetic users. Setup uses the same group/send services,
not bulk SQL message inserts. PostgreSQL/OS caches are uncontrolled/warm;
each measured attempt uses a new ORM environment and real transaction.
"""
from concurrent.futures import ThreadPoolExecutor
import json
from statistics import median
from threading import Barrier, Lock
from time import monotonic
from uuid import uuid4


DATABASE = 'bchat_maturity_test_20261017'
STATEMENT_TIMEOUT_MS = 10_000
LOCK_TIMEOUT_MS = 2_000
TOTAL_BUDGET_SECONDS = 300
SEQUENTIAL_SAMPLES = 10
CONCURRENT_ROUNDS = 10
MAX_ATTEMPTS = 6
TEXT = 'Synthetic maturity capacity message. رسالة قياس اصطناعية ثابتة.'


def _json_size(value):
    return len(json.dumps(value, ensure_ascii=False, default=str).encode('utf-8'))


def _safe_error(error):
    # Do not export exception messages, SQL, request text, names or UUIDs.
    return {'class': type(error).__name__, 'sqlstate': getattr(error, 'pgcode', None)}


def _aggregate(samples):
    result = {}
    for operation in sorted({item['operation'] for item in samples}):
        selected = [item for item in samples if item['operation'] == operation
                    and not item['warmup'] and item['result'] == 'ok']
        if selected:
            values = [item['elapsed_ms'] for item in selected]
            result[operation] = {
                'samples': len(selected), 'median_ms': round(median(values), 3),
                'max_ms': max(values),
                'row_count_min': min(item['row_count'] for item in selected),
                'row_count_max': max(item['row_count'] for item in selected),
                'response_utf8_bytes_max': max(item['response_utf8_bytes'] for item in selected),
            }
    return result


def run(env, emit=None):
    """Return evidence, including failed samples; caller must fail on status.

    The external runner must additionally enforce a five-minute hard timeout.
    The cooperative budget here cannot interrupt an OS/driver stall safely.
    """
    from psycopg2.errors import SerializationFailure
    from odoo import Command, api

    if env.cr.dbname != DATABASE:
        raise RuntimeError('Capacity probe requires the exact disposable maturity database')
    started = monotonic()
    registry = env.registry
    admin = env.ref('base.user_admin')
    admin_id, company_id = admin.id, admin.company_id.id
    marker = uuid4().hex
    user_ids, room_names, sent_intents = [], {}, []
    primary_id, owner_id, owner_membership_id = None, None, None
    emit = emit or (lambda _sample: None)
    sample_lock = Lock()
    result = {
        'schema_version': 1, 'status': 'failed',
        'scope': 'odoo_service_db_json_commit_not_http_or_device', 'database': DATABASE,
        'limits': {'statement_timeout_ms': STATEMENT_TIMEOUT_MS,
                   'lock_timeout_ms': LOCK_TIMEOUT_MS, 'total_budget_seconds': TOTAL_BUDGET_SECONDS},
        'fixture': {'users': 0, 'rooms': 0, 'primary_members': 0, 'seed_messages': 0,
                    'final_messages': 0, 'ordinary_actor_verified': False, 'marker_verified': False,
                    'text_profile': 'fixed_bilingual_small', 'text_utf8_bytes': len(TEXT.encode('utf-8'))},
        'sample_plan': {'warmups_per_operation': 1, 'sequential_per_operation': SEQUENTIAL_SAMPLES,
                        'concurrent_rounds': CONCURRENT_ROUNDS, 'workers_per_round': 2},
        'samples': [], 'summary': {}, 'invariants': {},
        'cleanup': {'completed': False, 'marker_verified': False}, 'error': None,
    }

    def budget():
        if monotonic() - started >= TOTAL_BUDGET_SECONDS:
            raise TimeoutError('The bounded capacity sample exceeded its execution budget')

    def deadlines(cursor):
        cursor.execute("SET LOCAL statement_timeout='10s'")
        cursor.execute("SET LOCAL lock_timeout='2s'")

    def ordinary_service(scoped, user_id):
        service = scoped['baseer.bchat.service'].with_user(user_id).with_context(
            allowed_company_ids=[company_id])
        if service.env.su or service.env.user.has_group('base.group_system'):
            raise AssertionError('Measured capacity calls must not run as an administrator')
        return service

    def record(sample):
        with sample_lock:
            result['samples'].append(sample)
            emit(sample)

    def measured(operation, sample_number, user_id, request, *, warmup=False,
                 round_number=None, worker=None, barrier=None):
        overall = monotonic()
        sample = {
            'operation': operation, 'sample': sample_number, 'warmup': warmup,
            'round': round_number, 'worker': worker,
            'page': {'history': 'latest', 'rooms': 'rooms100', 'search': 'search_hits'}.get(operation, 'write'),
            'request_utf8_bytes': _json_size(request), 'response_utf8_bytes': 0,
            'row_count': 0, 'result': 'error', 'elapsed_ms': 0,
            'attempt_count': 0, 'initial_backend_pid': None, 'final_backend_pid': None,
            'attempts': [], 'error': None,
        }
        for number in range(1, MAX_ATTEMPTS + 1):
            attempt_started = monotonic()
            attempt = {'number': number, 'backend_pid': None, 'isolation': None,
                       'elapsed_ms': 0, 'result': 'error', 'sqlstate': None}
            try:
                budget()
                with registry.cursor() as cursor:
                    deadlines(cursor)
                    cursor.execute('SHOW transaction_isolation')
                    attempt['isolation'] = cursor.fetchone()[0].strip().lower()
                    if attempt['isolation'] != 'repeatable read':
                        raise AssertionError('Capacity attempts require PostgreSQL REPEATABLE READ')
                    cursor.execute('SELECT pg_backend_pid()')
                    attempt['backend_pid'] = cursor.fetchone()[0]
                    if number == 1:
                        sample['initial_backend_pid'] = attempt['backend_pid']
                        if barrier is not None:
                            barrier.wait(timeout=10)
                    scoped = api.Environment(cursor, user_id, {'allowed_company_ids': [company_id]})
                    service = ordinary_service(scoped, user_id)
                    if operation in ('send', 'concurrent_send'):
                        response = service._v2_send(primary_id, request)
                        rows = 1
                    elif operation == 'history':
                        response = service._v2_history(primary_id)
                        rows = len(response['messages'])
                        if not 1 <= rows <= 30:
                            raise AssertionError('History exceeded the measured page bound')
                    elif operation == 'rooms':
                        response = service._v2_rooms()
                        rows = len(response['rooms'])
                        if rows != 100:
                            raise AssertionError('The synthetic account no longer has exactly 100 rooms')
                    elif operation == 'search':
                        response = service._v2_room_search(primary_id, request)
                        rows = len(response['messages'])
                        if not 1 <= rows <= 30:
                            raise AssertionError('Search exceeded the measured page bound')
                    else:
                        raise AssertionError('Unknown capacity operation')
                    size = _json_size(response)
                    if operation in ('history', 'search') and size > 131072:
                        raise AssertionError('The measured read page exceeded its JSON byte bound')
                    cursor.commit()  # Latency includes serialization and the actual commit.
                    budget()
                sample.update(response_utf8_bytes=size, row_count=rows, result='ok', error=None)
                attempt['result'] = 'ok'
            except SerializationFailure as error:
                attempt['sqlstate'] = error.pgcode
                if error.pgcode != '40001' or number == MAX_ATTEMPTS:
                    sample['error'] = _safe_error(error)
                else:
                    # Retry the same request object, UUID and membership epoch.
                    attempt['result'] = 'serialization_retry'
            except Exception as error:
                # In particular 40P01 and 55P03 are recorded failures, never retries.
                attempt['sqlstate'] = getattr(error, 'pgcode', None)
                sample['error'] = _safe_error(error)
            attempt['elapsed_ms'] = round((monotonic() - attempt_started) * 1000, 3)
            sample['attempts'].append(attempt)
            sample['attempt_count'] = number
            sample['final_backend_pid'] = attempt['backend_pid']
            if attempt['result'] != 'serialization_retry':
                break
        sample['elapsed_ms'] = round((monotonic() - overall) * 1000, 3)
        record(sample)
        return sample

    def require_success(samples):
        if any(item['result'] != 'ok' for item in samples):
            raise AssertionError('A measured capacity operation failed; raw samples are retained')

    def send_request(member_id):
        return {'api_version': 2, 'membership_id': member_id,
                'client_uuid': str(uuid4()), 'text': TEXT}

    def cleanup():
        env.cr.rollback()
        with registry.cursor() as cursor:
            deadlines(cursor)
            if user_ids:
                cursor.execute('SELECT id,login FROM res_users WHERE id=ANY(%s)', [user_ids])
                found = dict(cursor.fetchall())
                expected = {user_id: 'bchat-capacity-%s-%s' % (marker, index)
                            for index, user_id in enumerate(user_ids)}
                if found != expected:
                    raise RuntimeError('Refusing capacity cleanup: synthetic user ownership changed')
            if room_names:
                cursor.execute('SELECT id,name,group_creator_user_id FROM baseer_bchat_room WHERE id=ANY(%s)',
                               [list(room_names)])
                for room_id, name, creator_id in cursor.fetchall():
                    if name != room_names[room_id] or creator_id != owner_id:
                        raise RuntimeError('Refusing capacity cleanup: synthetic room ownership changed')
            result['cleanup']['marker_verified'] = True
            if room_names:
                rooms = list(room_names)
                cursor.execute('DELETE FROM baseer_bchat_change WHERE room_id=ANY(%s)', [rooms])
                cursor.execute('''DELETE FROM baseer_bchat_message_receipt WHERE message_id IN
                                  (SELECT id FROM baseer_bchat_message WHERE room_id=ANY(%s))''', [rooms])
                cursor.execute('DELETE FROM baseer_bchat_message WHERE room_id=ANY(%s)', [rooms])
                cursor.execute('DELETE FROM baseer_bchat_group_event WHERE room_id=ANY(%s)', [rooms])
                cursor.execute('DELETE FROM baseer_bchat_membership WHERE room_id=ANY(%s)', [rooms])
                cursor.execute('DELETE FROM baseer_bchat_room WHERE id=ANY(%s)', [rooms])
            if user_ids:
                cursor.execute('DELETE FROM baseer_bchat_change WHERE user_id=ANY(%s)', [user_ids])
                cursor.execute('DELETE FROM baseer_bchat_change_cursor WHERE user_id=ANY(%s)', [user_ids])
                scoped = api.Environment(cursor, admin_id, {'allowed_company_ids': [company_id]})
                scoped['res.users'].sudo().browse(user_ids).unlink()
                cursor.execute('SELECT COUNT(*) FROM res_users WHERE id=ANY(%s)', [user_ids])
                if cursor.fetchone()[0]:
                    raise AssertionError('Synthetic capacity users were not removed')
            cursor.commit()
            result['cleanup']['completed'] = True

    try:
        deadlines(env.cr)
        env.cr.execute('SELECT current_database(),(SELECT COUNT(*) FROM baseer_bchat_room),'
                       '(SELECT COUNT(*) FROM baseer_bchat_message)')
        database, rooms_before, messages_before = env.cr.fetchone()
        if database != DATABASE or rooms_before or messages_before:
            raise RuntimeError('Capacity setup requires empty BChat rooms/messages in the isolated database')
        users = env['res.users'].with_context(no_reset_password=True, mail_create_nosubscribe=True).create([{
            'name': 'BChat capacity %s %s' % (marker, index),
            'login': 'bchat-capacity-%s-%s' % (marker, index),
            'company_id': company_id, 'company_ids': [Command.set([company_id])],
            'group_ids': [Command.set([env.ref('base.group_user').id])],
        } for index in range(50)])
        user_ids[:] = users.ids
        owner_id = user_ids[0]
        env.cr.commit()
        result['fixture']['users'] = len(user_ids)
        for index in range(100):
            budget()
            deadlines(env.cr)
            service = ordinary_service(env, owner_id)
            name = 'BChat capacity %s %s' % (marker, index)
            created = service._v2_group_create({
                'api_version': 2, 'client_uuid': str(uuid4()), 'company_id': company_id,
                'name': name, 'member_user_ids': user_ids[1:] if index == 0 else [user_ids[1]],
            })
            room_names[created['room_id']] = name
            if index == 0:
                primary_id, owner_membership_id = created['room_id'], created['membership_id']
            env.cr.commit()
            result['fixture']['rooms'] = len(room_names)
        for index in range(500):
            budget()
            deadlines(env.cr)
            ordinary_service(env, owner_id)._v2_send(primary_id, send_request(owner_membership_id))
            if (index + 1) % 25 == 0:
                env.cr.commit()
                result['fixture']['seed_messages'] = index + 1
        deadlines(env.cr)
        env.cr.execute('SELECT COUNT(*) FROM baseer_bchat_membership WHERE room_id=%s AND active', [primary_id])
        primary_members = env.cr.fetchone()[0]
        env.cr.execute('SELECT COUNT(*) FROM baseer_bchat_message WHERE room_id=%s', [primary_id])
        seeded = env.cr.fetchone()[0]
        env.cr.execute('SELECT COUNT(*) FROM baseer_bchat_membership WHERE user_id=%s AND active', [owner_id])
        owner_rooms = env.cr.fetchone()[0]
        if (primary_members, seeded, owner_rooms) != (50, 500, 100):
            raise AssertionError('Capacity fixture does not match its declared bounds')
        env.cr.execute('SELECT id,name,group_creator_user_id FROM baseer_bchat_room WHERE id=ANY(%s)',
                       [list(room_names)])
        persisted_rooms = {room_id: name for room_id, name, creator in env.cr.fetchall()
                           if creator == owner_id}
        env.cr.execute('SELECT id,login FROM res_users WHERE id=ANY(%s)', [user_ids])
        persisted_users = dict(env.cr.fetchall())
        expected_users = {user_id: 'bchat-capacity-%s-%s' % (marker, index)
                          for index, user_id in enumerate(user_ids)}
        if persisted_rooms != room_names or persisted_users != expected_users:
            raise AssertionError('The capacity fixture marker differs from committed database rows')
        result['fixture'].update(primary_members=primary_members, ordinary_actor_verified=True, marker_verified=True)
        result['invariants']['seed_exact'] = True
        env.cr.rollback()

        for operation in ('send', 'history', 'rooms', 'search'):
            for sample_number in range(SEQUENTIAL_SAMPLES + 1):
                if operation == 'send':
                    request = send_request(owner_membership_id)
                    sent_intents.append((owner_id, request['client_uuid']))
                elif operation == 'search':
                    request = {'api_version': 2, 'membership_id': owner_membership_id,
                               'q': 'capacity', 'kind': 'text', 'before_id': None}
                else:
                    request = {} if operation == 'rooms' else {'room_id': primary_id, 'before_id': None}
                sample = measured(operation, sample_number, owner_id, request, warmup=sample_number == 0)
                require_success([sample])

        with registry.cursor() as cursor:
            deadlines(cursor)
            cursor.execute('''SELECT user_id,id FROM baseer_bchat_membership
                              WHERE room_id=%s AND user_id=ANY(%s) AND active''', [primary_id, user_ids[1:3]])
            worker_members = dict(cursor.fetchall())
        distinct_pids = True
        for round_number in range(1, CONCURRENT_ROUNDS + 1):
            budget()
            barrier = Barrier(2)
            requests = [(user_id, send_request(worker_members[user_id])) for user_id in user_ids[1:3]]
            sent_intents.extend((user_id, request['client_uuid']) for user_id, request in requests)
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(measured, 'concurrent_send', (round_number - 1) * 2 + worker,
                                       user_id, request, round_number=round_number, worker=worker, barrier=barrier)
                           for worker, (user_id, request) in enumerate(requests, 1)]
                samples = [future.result(timeout=35) for future in futures]
            require_success(samples)
            if len({item['initial_backend_pid'] for item in samples}) != 2:
                distinct_pids = False
                raise AssertionError('Concurrent capacity samples reused a single initial PostgreSQL backend')

        with registry.cursor() as cursor:
            deadlines(cursor)
            cursor.execute('''SELECT author_user_id,client_uuid,COUNT(*) FROM baseer_bchat_message
                              WHERE room_id=%s AND client_uuid=ANY(%s)
                              GROUP BY author_user_id,client_uuid''', [primary_id, [item[1] for item in sent_intents]])
            persisted = {(user_id, client_uuid): count for user_id, client_uuid, count in cursor.fetchall()}
            if set(persisted) != set(sent_intents) or any(count != 1 for count in persisted.values()):
                raise AssertionError('A measured send was lost or duplicated')
            cursor.execute('SELECT COUNT(*) FROM baseer_bchat_message WHERE room_id=%s', [primary_id])
            final_count = cursor.fetchone()[0]
            if final_count != 531:
                raise AssertionError('Capacity final message count differs from seed plus measured writes')
        result['fixture']['final_messages'] = final_count
        result['invariants'].update(each_send_once=True, concurrent_initial_pids_distinct=distinct_pids,
                                    history_page_bounded=True, room_list_exact=True, search_page_bounded=True)
        result['status'] = 'ok'
    except Exception as error:
        result['error'] = _safe_error(error)
    finally:
        try:
            cleanup()
        except Exception as error:
            result['status'] = 'failed'
            result['cleanup']['error'] = _safe_error(error)
            if result['error'] is None:
                result['error'] = _safe_error(error)
        result['summary'] = _aggregate(result['samples'])
        result['elapsed_ms'] = round((monotonic() - started) * 1000, 3)
    return result
