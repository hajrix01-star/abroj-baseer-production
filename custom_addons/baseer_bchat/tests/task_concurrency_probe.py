"""One-shot two-cursor task probe for bchat_text_test_20261009 only.

Creates four clearly marked test tasks, commits them so separate cursors can
race, and removes precisely those four tasks plus their audit events in finally.
Never import this module from tests/__init__.py or run it on a working DB.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from psycopg2.errors import SerializationFailure

from odoo import api
from odoo.service.model import retrying


def run(env):
    if env.cr.dbname != 'bchat_text_test_20261009':
        raise RuntimeError('Refusing task race probe outside the approved isolated DB')
    user = env.ref('base.user_admin')
    company = user.company_id
    if not user.active or not user._is_internal() or company not in user.company_ids:
        raise RuntimeError('The isolated test admin is not an eligible BChat user')
    titles = ['[LOCAL TEST] BChat task race %s %s' % (number, uuid4().hex[:8])
              for number in range(4)]
    ids = []
    committed = False
    try:
        service = env['baseer.bchat.service'].with_user(user).with_company(company)
        for title in titles:
            result = service._v2_task_create({
                'api_version': 2, 'company_id': company.id, 'room_id': None,
                'client_uuid': str(uuid4()), 'title': title, 'description': '',
                'due_at': None, 'assignee_id': user.id,
            })
            ids.append(result['task']['id'])
        env.cr.commit()  # Only this approved isolated test DB.
        committed = True

        def race(targets, uuids):
            barrier = Barrier(2)

            def worker(index):
                with env.registry.cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = '15s'")
                    scoped = api.Environment(cursor, user.id,
                                             {'allowed_company_ids': [company.id]})
                    barrier.wait(timeout=10)
                    try:
                        result = retrying(lambda: scoped['baseer.bchat.service']._v2_task_transition(
                            targets[index], {
                                'api_version': 2, 'client_uuid': uuids[index],
                                'expected_revision': 1, 'action': 'start',
                                'assignee_id': None, 'reason': None,
                            }), scoped)
                        return ('ok', result['replayed'], result['operation_revision'])
                    except Exception as error:
                        cursor.rollback()
                        return ('error', type(error).__name__, getattr(error, 'code', ''))

            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(worker, index) for index in (0, 1)]
                return [future.result(timeout=35) for future in futures]

        shared = str(uuid4())
        same = race((ids[0], ids[0]), (shared, shared))
        assert sorted(item[0] for item in same) == ['ok', 'ok'], same
        assert sorted(item[1] for item in same) == [False, True], same
        assert all(item[2] == 2 for item in same), same

        distinct = race((ids[1], ids[1]), (str(uuid4()), str(uuid4())))
        assert sorted(item[0] for item in distinct) == ['error', 'ok'], distinct
        assert next(item for item in distinct if item[0] == 'error')[1:] == (
            'ProtocolError', 'revision_conflict'), distinct

        crossed = race((ids[2], ids[3]), (str(uuid4()),) * 2)
        assert sorted(item[0] for item in crossed) == ['error', 'ok'], crossed
        assert next(item for item in crossed if item[0] == 'error')[1:] == (
            'ProtocolError', 'idempotency_conflict'), crossed

        with env.registry.cursor() as cursor:
            cursor.execute('SELECT id,revision FROM baseer_bchat_task WHERE id = ANY(%s) ORDER BY id', [ids])
            revisions = dict(cursor.fetchall())
            assert revisions[ids[0]] == 2 and revisions[ids[1]] == 2, revisions
            assert sorted((revisions[ids[2]], revisions[ids[3]])) == [1, 2], revisions
            cursor.execute('SELECT task_id,COUNT(*) FROM baseer_bchat_task_event '
                           'WHERE task_id = ANY(%s) GROUP BY task_id', [ids])
            events = dict(cursor.fetchall())
            assert events[ids[0]] == 1 and events[ids[1]] == 1, events
            assert sum(events.get(value, 0) for value in ids[2:]) == 1, events
        return {'same_uuid': same, 'distinct_uuid': distinct,
                'cross_task_uuid': crossed, 'no_double_transition': True}
    finally:
        if not committed:
            env.cr.rollback()
        if committed and ids:
            with env.registry.cursor() as cursor:
                for task_id, title in zip(ids, titles):
                    cursor.execute('SELECT creator_id,title FROM baseer_bchat_task WHERE id = %s', [task_id])
                    row = cursor.fetchone()
                    if row != (user.id, title):
                        raise RuntimeError('Refusing cleanup: task ownership/title changed')
                cursor.execute('DELETE FROM baseer_bchat_task_event WHERE task_id = ANY(%s)', [ids])
                for task_id, title in zip(ids, titles):
                    cursor.execute('DELETE FROM baseer_bchat_task '
                                   'WHERE id = %s AND creator_id = %s AND title = %s',
                                   [task_id, user.id, title])
                    if cursor.rowcount != 1:
                        raise RuntimeError('Expected exactly one local test task to clean')
                cursor.commit()


def run_list_reassignment(env):
    """Prove an old assignee cannot receive a stale independent-task page."""
    if env.cr.dbname != 'bchat_text_test_20261009':
        raise RuntimeError('Refusing task list race probe outside the approved isolated DB')
    reader = env.ref('base.user_admin')
    company = reader.company_id
    candidates = env['baseer.bchat.service'].with_user(reader)._v2_task_options(company.id)['assignees']
    creator_id = next((item['id'] for item in candidates if item['id'] != reader.id), None)
    if not creator_id:
        raise RuntimeError('An existing second internal user is required; no fixture user will be created')
    creator = env['res.users'].browse(creator_id)
    title = '[LOCAL TEST] BChat list race %s' % uuid4().hex[:8]
    task_id = None
    committed = False
    try:
        created = env['baseer.bchat.service'].with_user(creator).with_company(company)._v2_task_create({
            'api_version': 2, 'company_id': company.id, 'room_id': None,
            'client_uuid': str(uuid4()), 'title': title, 'description': '',
            'due_at': None, 'assignee_id': reader.id,
        })
        task_id = created['task']['id']
        env.cr.commit()  # Only the approved isolated test database.
        committed = True
        with env.registry.cursor() as stale_cr:
            stale_cr.execute('SELECT id FROM baseer_bchat_task WHERE id = %s', [task_id])
            assert stale_cr.fetchone() == (task_id,)
            with env.registry.cursor() as writer_cr:
                writer = api.Environment(writer_cr, creator.id,
                                         {'allowed_company_ids': [company.id]})
                writer['baseer.bchat.service']._v2_task_transition(task_id, {
                    'api_version': 2, 'client_uuid': str(uuid4()),
                    'expected_revision': 1, 'action': 'reassign',
                    'assignee_id': creator.id, 'reason': None,
                })
                writer_cr.commit()
            stale = api.Environment(stale_cr, reader.id,
                                    {'allowed_company_ids': [company.id]})
            try:
                stale['baseer.bchat.service']._v2_tasks()
            except SerializationFailure:
                stale_cr.rollback()
            else:
                raise AssertionError('A stale assignee list did not trigger a full-request retry')
        with env.registry.cursor() as fresh_cr:
            fresh = api.Environment(fresh_cr, reader.id,
                                    {'allowed_company_ids': [company.id]})
            task_ids = [item['id'] for item in fresh['baseer.bchat.service']._v2_tasks()['tasks']]
            assert task_id not in task_ids, task_ids
        return {'stale_reader': 'serialization_retry', 'fresh_reader': 'task_hidden'}
    finally:
        if not committed:
            env.cr.rollback()
        if committed and task_id:
            with env.registry.cursor() as cleanup_cr:
                cleanup_cr.execute('SELECT creator_id,title FROM baseer_bchat_task WHERE id = %s',
                                   [task_id])
                if cleanup_cr.fetchone() != (creator.id, title):
                    raise RuntimeError('Refusing cleanup: task ownership/title changed')
                cleanup_cr.execute('DELETE FROM baseer_bchat_task_event WHERE task_id = %s', [task_id])
                cleanup_cr.execute('DELETE FROM baseer_bchat_task '
                                   'WHERE id = %s AND creator_id = %s AND title = %s',
                                   [task_id, creator.id, title])
                if cleanup_cr.rowcount != 1:
                    raise RuntimeError('Expected exactly one local test task to clean')
                cleanup_cr.commit()
