"""Real PostgreSQL lock-order probe, ONLY on bchat_maturity_test_* databases.

Correction contract: every composite publisher (permissions, membership
batches, remove/leave, room batches, task reassignment) reserves its full
recipient union in ascending user_id BEFORE its first hint. Sorting each
separate append does not prevent B -> A versus A -> B deadlocks.

This is not an imported TransactionCase: it intentionally commits disposable
fixtures so independent PostgreSQL connections can contend on real rows.
It pauses after genuine writes; it never mocks the database, cursor locks,
user.write, message send, or hint persistence. Call run(env) from Odoo shell.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, local
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from psycopg2.errors import SerializationFailure

from odoo import Command, api

from ..models.push import _PUSH_TOKEN


def run(env):
    if not env.cr.dbname.startswith('bchat_maturity_test_'):
        raise RuntimeError('Refusing permission-hint race outside a disposable bchat_maturity_test_* database')
    registry = env.registry
    admin = env.ref('base.user_admin')
    manager_group = env.ref('baseer_bchat.group_bchat_manager')
    if manager_group not in admin.group_ids:
        raise RuntimeError('The isolated runner admin must have the BChat manager test role')
    company = admin.company_id
    marker = uuid4().hex
    users = env['res.users'].with_context(no_reset_password=True, mail_create_nosubscribe=True)
    fixture_users = users.create([{
        'name': 'BChat cursor race %s %s' % (label, marker),
        'login': 'bchat-cursor-race-%s-%s' % (label, marker),
        'company_id': company.id, 'company_ids': [Command.set(company.ids)],
        'group_ids': [Command.set([env.ref('base.group_user').id])],
    } for label in ('a', 'b', 'sender')])
    a, b, sender = fixture_users
    created = env['baseer.bchat.service'].with_user(a)._v2_group_create({
        'api_version': 2, 'client_uuid': str(uuid4()), 'company_id': company.id,
        'name': 'Cursor race ' + marker, 'member_user_ids': [b.id, sender.id],
    })
    room_id = created['room_id']
    task_title = 'Cursor race task ' + marker
    task_id = env['baseer.bchat.service'].with_user(sender)._v2_task_create({
        'api_version': 2, 'company_id': company.id, 'room_id': None,
        'client_uuid': str(uuid4()), 'title': task_title,
        'description': '', 'due_at': None, 'assignee_id': a.id,
    })['task']['id']
    skip_installation = str(uuid4())
    skip_token = 'synthetic-skip-locked-' + marker + 'x' * 40
    registration = env['baseer.bchat.service'].with_user(a)._v2_push_register({
        'api_version': 2, 'installation_id': skip_installation, 'fcm_token': skip_token})
    skip_device = env['baseer.bchat.push.device'].sudo().search([
        ('account_key', '=', registration['account_key'])], limit=1)
    skip_event = env['baseer.bchat.push.event']._queue_verified([{
        'recipient_id': a.id, 'device_id': skip_device.id, 'task_id': task_id,
        'company_id': company.id, 'event_kind': 'assigned', 'task_revision': 1,
        'state': 'pending',
    }], _PUSH_TOKEN)
    skip_device_id, skip_event_id = skip_device.id, skip_event.id
    revoke_member_id = env['baseer.bchat.membership'].sudo().search([
        ('room_id', '=', room_id), ('user_id', '=', b.id), ('active', '=', True)]).id
    sender_member = env['baseer.bchat.membership'].sudo().search([
        ('room_id', '=', room_id), ('user_id', '=', sender.id), ('active', '=', True)])
    fixture_ids = fixture_users.ids
    sender_id, sender_member_id, admin_id, company_id = sender.id, sender_member.id, admin.id, company.id
    env.cr.commit()  # The strict database-name gate makes this fixture commit explicit.
    service_class = type(env['baseer.bchat.service'])
    original_publish = service_class._change_publish
    thread_state = local()
    observed = {}
    backend_pids = set()
    phases = []

    def remove_skip_fixture(cursor):
        cursor.execute('''SELECT user_id,installation_id,fcm_token FROM baseer_bchat_push_device
                          WHERE id=%s''', [skip_device_id])
        device = cursor.fetchone()
        if device and device != (a.id, skip_installation, skip_token):
            raise RuntimeError('Refusing cleanup: skip-locked device ownership changed')
        cursor.execute('SELECT recipient_id,device_id,task_id FROM baseer_bchat_push_event WHERE id=%s', [skip_event_id])
        event = cursor.fetchone()
        if event and event != (a.id, skip_device_id, task_id):
            raise RuntimeError('Refusing cleanup: skip-locked event ownership changed')
        cursor.execute('DELETE FROM baseer_bchat_push_event WHERE id=%s', [skip_event_id])
        cursor.execute('DELETE FROM baseer_bchat_push_device WHERE id=%s', [skip_device_id])

    def skip_locked_dispatch_witness():
        """Committed synthetic queue row, real dispatch SQL, two real workers.

        Only FCM configuration/OAuth/HTTP are stubbed. The claimed row, locks,
        authorization, state write, cursor isolation and deadlines are real.
        """
        pids, isolations = [], []
        event_class = type(env['baseer.bchat.push.event'])
        with registry.cursor() as first_worker, registry.cursor() as second_worker:
            for worker in (first_worker, second_worker):
                worker.execute("SET LOCAL statement_timeout='3s'")
                worker.execute("SET LOCAL lock_timeout='2s'")
                worker.execute('SHOW transaction_isolation')
                isolation = worker.fetchone()[0].strip().lower()
                if isolation != 'repeatable read':
                    raise AssertionError('SKIP LOCKED witness requires PostgreSQL REPEATABLE READ')
                isolations.append(isolation)
                worker.execute('SELECT pg_backend_pid()')
                pids.append(worker.fetchone()[0])
            if pids[0] == pids[1]:
                raise AssertionError('SKIP LOCKED witness requires two independent workers')
            first_worker.execute('SELECT id FROM baseer_bchat_push_event WHERE id=%s FOR UPDATE', [skip_event_id])
            if first_worker.fetchall() != [(skip_event_id,)]:
                raise AssertionError('The committed synthetic queue row was not visible to the first worker')
            second_env = api.Environment(second_worker, admin_id, {'allowed_company_ids': [company_id]})
            dispatcher = second_env['baseer.bchat.push.event']
            with patch.object(event_class, '_fcm_config', return_value={'project_id': 'synthetic-project'}), \
                    patch.object(event_class, '_fcm_access_token', return_value='synthetic-access-token'), \
                    patch('requests.post', return_value=SimpleNamespace(status_code=200)) as provider:
                dispatcher._dispatch_event_ids([skip_event_id])
                locked_calls = provider.call_count
                locked_state = dispatcher.sudo().browse(skip_event_id).state
                if locked_calls or locked_state != 'pending':
                    raise AssertionError('A locked queue row reached the second dispatcher worker')
                first_worker.rollback()  # Release its real lock, not a mocked claim result.
                dispatcher._dispatch_event_ids([skip_event_id])
                final_state = dispatcher.sudo().browse(skip_event_id).state
                if provider.call_count != 1 or final_state != 'sent':
                    raise AssertionError('The same dispatcher could not claim the row after release')
                second_worker.commit()
        with registry.cursor() as cleanup:
            # Remove this event and device before the permission races, so
            # they cannot introduce post-commit FCM scheduling into those cases.
            remove_skip_fixture(cleanup)
            cleanup.commit()
        return {'initial_backend_pids': pids, 'isolations': isolations,
                'statement_timeout_ms': 3000, 'lock_timeout_ms': 2000,
                'locked_excluded': locked_calls == 0 and locked_state == 'pending',
                'claimed_after_release': final_state == 'sent',
                'provider_calls_while_locked': locked_calls, 'provider_calls_after_release': 1,
                'final_state': final_state, 'synthetic_fixture_removed_before_races': True}

    def publish_with_window(service, user_ids, kind, **kwargs):
        result = original_publish(service, user_ids, kind, **kwargs)
        phase = getattr(thread_state, 'phase', None)
        role = getattr(thread_state, 'role', None)
        first = not getattr(thread_state, 'paused', False)
        wanted = {'send': 'message', 'reassign': 'task',
                  'revoke': 'revoked', 'leave': 'revoked'}.get(role, 'permissions')
        if phase and role and first and kind == wanted:
            thread_state.paused = True
            observed[role].set()
            for other_role, checkpoint in observed.items():
                if other_role != role:
                    # With the correction the competing publisher may block
                    # before its first hint, so this is a bounded window,
                    # not a barrier that falsely requires both to own locks.
                    checkpoint.wait(timeout=0.35)
        return result

    def execute(role, start, action):
        thread_state.role = role
        thread_state.phase = True
        thread_state.paused = False
        initial_backend_pid, isolation = None, None
        for attempt in range(6):
            try:
                with registry.cursor() as cursor:
                    cursor.execute("SET LOCAL statement_timeout = '8s'")
                    cursor.execute("SET LOCAL lock_timeout = '5s'")
                    if attempt == 0:
                        cursor.execute('SHOW transaction_isolation')
                        isolation = cursor.fetchone()[0].strip().lower()
                        if isolation != 'repeatable read':
                            raise AssertionError('Permission race requires actual PostgreSQL REPEATABLE READ isolation')
                    cursor.execute('SELECT pg_backend_pid()')
                    backend_pid = cursor.fetchone()[0]
                    backend_pids.add(backend_pid)
                    if attempt == 0:
                        initial_backend_pid = backend_pid
                        # Both transactions are already open with a real RR
                        # snapshot; a later 40001 retry is not the proof.
                        start.wait(timeout=10)
                    scoped = api.Environment(cursor, admin_id, {'allowed_company_ids': [company_id]})
                    result = action(scoped)
                    cursor.commit()
                    return {'attempts': attempt + 1, 'initial_backend_pid': initial_backend_pid,
                            'isolation': isolation, 'result': result}
            except SerializationFailure:
                # Odoo's repeatable-read request wrapper retries 40001.
                # DeadlockDetected (40P01) is deliberately NOT swallowed.
                if attempt == 5:
                    raise

    def phase(roles):
        nonlocal observed
        observed = {role: Event() for role, _action in roles}
        start = Barrier(len(roles))
        with ThreadPoolExecutor(max_workers=len(roles)) as pool:
            futures = {role: pool.submit(execute, role, start, action) for role, action in roles}
            results = {role: future.result(timeout=30) for role, future in futures.items()}
        if len({result['initial_backend_pid'] for result in results.values()}) != len(roles):
            raise AssertionError('The probe did not use independent PostgreSQL backends')
        return results

    service_class._change_publish = publish_with_window
    try:
        skip_locked_exclusion = skip_locked_dispatch_witness()
        phases.append(phase([
            ('a', lambda scoped: scoped['res.users'].browse(a.id).write({'bchat_media_download': False})),
            ('b', lambda scoped: scoped['res.users'].browse(b.id).write({'bchat_media_download': False})),
        ]))
        message_uuid = str(uuid4())
        phases.append(phase([
            ('write', lambda scoped: scoped['res.users'].browse(b.id).write({'bchat_media_download': True})),
            ('send', lambda scoped: scoped['baseer.bchat.service'].with_user(sender_id)._v2_send(room_id, {
                'api_version': 2, 'membership_id': sender_member_id,
                'client_uuid': message_uuid, 'text': 'Synthetic lock-order journey',
            })),
        ]))
        reassign_uuid = str(uuid4())
        phases.append(phase([
            ('write', lambda scoped: scoped['res.users'].browse(a.id).write({'bchat_media_download': True})),
            ('reassign', lambda scoped: scoped['baseer.bchat.service'].with_user(sender_id)._v2_task_transition(
                task_id, {'api_version': 2, 'client_uuid': reassign_uuid,
                          'expected_revision': 1, 'action': 'reassign',
                          'assignee_id': b.id, 'reason': 'Synthetic lock-order journey'})),
        ]))
        phases.append(phase([
            ('write', lambda scoped: scoped['res.users'].browse(b.id).write({'bchat_media_download': False})),
            ('revoke', lambda scoped: scoped['baseer.bchat.membership'].browse(revoke_member_id).action_revoke()),
        ]))
        phases.append(phase([
            ('write', lambda scoped: scoped['res.users'].browse(sender_id).write({'bchat_media_download': False})),
            ('leave', lambda scoped: scoped['baseer.bchat.service'].with_user(sender_id)._v2_group_change(
                room_id, {'api_version': 2, 'action': 'leave'})),
        ]))
        with registry.cursor() as cursor:
            cursor.execute('''
                SELECT COUNT(*) FROM baseer_bchat_message
                WHERE room_id = %s AND author_user_id = %s AND client_uuid = %s
            ''', [room_id, sender_id, message_uuid])
            if cursor.fetchone()[0] != 1:
                raise AssertionError('The race lost or duplicated the verified message')
            cursor.execute('SELECT assignee_id, revision FROM baseer_bchat_task WHERE id = %s', [task_id])
            if cursor.fetchone() != (b.id, 2):
                raise AssertionError('The verified reassignment was lost or duplicated')
            cursor.execute('''SELECT COUNT(*) FROM baseer_bchat_task_event
                              WHERE task_id = %s AND client_uuid = %s''', [task_id, reassign_uuid])
            if cursor.fetchone()[0] != 1:
                raise AssertionError('The immutable reassignment audit was lost or duplicated')
            cursor.execute('''SELECT user_id FROM baseer_bchat_membership
                              WHERE room_id = %s AND active''', [room_id])
            if cursor.fetchall() != [(a.id,)]:
                raise AssertionError('Revoke/leave did not preserve the remaining administrator')
            cursor.execute('''
                SELECT user_id, MIN(sequence), MAX(sequence), COUNT(*)
                FROM baseer_bchat_change WHERE user_id = ANY(%s)
                GROUP BY user_id
            ''', [fixture_ids])
            sequences = cursor.fetchall()
            if len(sequences) != 3 or any(high - low + 1 != total for _user, low, high, total in sequences):
                raise AssertionError('Committed per-user change sequences contain a gap')
        return {'independent_backends': len(backend_pids), 'phases': phases,
                'message_count': 1, 'task_revision': 2, 'sequence_continuity': True,
                'skip_locked_exclusion': skip_locked_exclusion}
    finally:
        service_class._change_publish = original_publish
        # Exact synthetic ownership is checked before removing fixtures. No
        # arbitrary table cleanup or operational database is accepted here.
        with registry.cursor() as cursor:
            cursor.execute('SELECT name FROM baseer_bchat_room WHERE id = %s', [room_id])
            if cursor.fetchone() != ('Cursor race ' + marker,):
                raise RuntimeError('Refusing cleanup: room ownership marker changed')
            cursor.execute('SELECT title FROM baseer_bchat_task WHERE id = %s', [task_id])
            if cursor.fetchone() != (task_title,):
                raise RuntimeError('Refusing cleanup: task ownership marker changed')
            cursor.execute('SELECT login FROM res_users WHERE id = ANY(%s)', [fixture_ids])
            logins = {row[0] for row in cursor.fetchall()}
            if logins != {'bchat-cursor-race-%s-%s' % (label, marker)
                          for label in ('a', 'b', 'sender')}:
                raise RuntimeError('Refusing cleanup: synthetic users changed')
            remove_skip_fixture(cursor)
            cursor.execute('''DELETE FROM baseer_bchat_push_event WHERE message_id IN
                              (SELECT id FROM baseer_bchat_message WHERE room_id = %s)''', [room_id])
            cursor.execute('DELETE FROM baseer_bchat_push_event WHERE task_id = %s', [task_id])
            cursor.execute('DELETE FROM baseer_bchat_task_event WHERE task_id = %s', [task_id])
            cursor.execute('''DELETE FROM baseer_bchat_message_receipt WHERE message_id IN
                              (SELECT id FROM baseer_bchat_message WHERE room_id = %s)''', [room_id])
            cursor.execute('DELETE FROM baseer_bchat_change WHERE user_id = ANY(%s) OR room_id = %s',
                           [fixture_ids, room_id])
            cursor.execute('DELETE FROM baseer_bchat_message WHERE room_id = %s', [room_id])
            cursor.execute('DELETE FROM baseer_bchat_task WHERE id = %s', [task_id])
            cursor.execute('DELETE FROM baseer_bchat_group_event WHERE room_id = %s', [room_id])
            cursor.execute('DELETE FROM baseer_bchat_membership WHERE room_id = %s', [room_id])
            cursor.execute('DELETE FROM baseer_bchat_room WHERE id = %s', [room_id])
            cursor.execute('DELETE FROM baseer_bchat_change_cursor WHERE user_id = ANY(%s)', [fixture_ids])
            cleanup = api.Environment(cursor, admin_id, {})
            cleanup['res.users'].sudo().browse(fixture_ids).unlink()
            cursor.commit()
