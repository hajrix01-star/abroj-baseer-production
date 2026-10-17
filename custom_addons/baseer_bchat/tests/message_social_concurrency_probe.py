"""Four real same-room C32 races, on the exact disposable maturity database.

The additional fresh-replay witness calls the real read-only helper directly;
it does NOT force the UniqueViolation branch or manufacture SQL collisions.
No provider, ORM, lock, source write, or receipt timestamp is mocked.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from psycopg2.errors import SerializationFailure
from odoo import Command, api

from .. import v2_contracts
from ..contracts import ProtocolError


def run(env):
    if env.cr.dbname != 'bchat_maturity_test_20261017':
        raise RuntimeError('C32 races require the exact disposable maturity database')
    registry = env.registry
    admin_id, company_id = env.ref('base.user_admin').id, env.company.id
    marker = uuid4().hex
    users = env['res.users'].with_context(no_reset_password=True, mail_create_nosubscribe=True).create([{
        'name': 'Message social race %s %s' % (marker, label),
        'login': 'bchat-message-social-%s-%s' % (marker, label),
        'company_id': company_id, 'company_ids': [Command.set([company_id])],
        'group_ids': [Command.set([env.ref('base.group_user').id])],
    } for label in ('owner', 'reader', 'other')])
    owner, reader, other = users
    ids = users.ids
    created = env['baseer.bchat.service'].with_user(owner)._v2_group_create({
        'api_version': 2, 'company_id': company_id, 'client_uuid': str(uuid4()),
        'name': 'Message social race ' + marker, 'member_user_ids': [reader.id, other.id]})
    room_id = created['room_id']
    memberships = env['baseer.bchat.membership'].sudo().search([('room_id', '=', room_id), ('active', '=', True)])
    member_by_user = {row.user_id.id: row.id for row in memberships}
    owner_id, reader_id, other_id = owner.id, reader.id, other.id
    base_message = env['baseer.bchat.service'].with_user(owner)._v2_send(room_id, {
        'api_version': 2, 'membership_id': member_by_user[owner_id], 'client_uuid': str(uuid4()),
        'text': 'Immutable C32 race fixture'})['message_id']
    env.cr.execute('''SELECT id,delivered_at,read_at FROM baseer_bchat_message_receipt
                      WHERE message_id=%s ORDER BY id''', [base_message])
    original_receipts = env.cr.fetchall()
    env.cr.commit()
    phases, backend_pids = {}, set()
    proof = None

    def race(actions):
        start = Barrier(2)

        def execute(user_id, action):
            initial_pid, isolation = None, None
            for number in range(1, 7):
                try:
                    with registry.cursor() as cursor:
                        cursor.execute("SET LOCAL statement_timeout='10s'")
                        cursor.execute("SET LOCAL lock_timeout='2s'")
                        if number == 1:
                            cursor.execute('SHOW transaction_isolation')
                            isolation = cursor.fetchone()[0].strip().lower()
                            if isolation != 'repeatable read':
                                raise AssertionError('C32 races require actual PostgreSQL REPEATABLE READ')
                        cursor.execute('SELECT pg_backend_pid()')
                        pid = cursor.fetchone()[0]
                        backend_pids.add(pid)
                        if number == 1:
                            initial_pid = pid
                            # Establish each real RR snapshot before either
                            # contender writes. A retry is not this witness.
                            cursor.execute('SELECT COUNT(*) FROM baseer_bchat_message WHERE room_id=%s', [room_id])
                            cursor.fetchone()
                            start.wait(timeout=10)
                        scoped = api.Environment(cursor, user_id, {'allowed_company_ids': [company_id]})
                        service = scoped['baseer.bchat.service']
                        if scoped.su or scoped.user.has_group('base.group_system'):
                            raise AssertionError('C32 race services must use ordinary accounts')
                        try:
                            response = action(service)
                        except ProtocolError as error:
                            if error.code != 'revision_conflict' or error.status != 409:
                                raise
                            cursor.rollback()
                            return {'state': 'revision_conflict', 'status': 409, 'result': None,
                                    'attempts': number, 'initial_backend_pid': initial_pid, 'isolation': isolation}
                        cursor.commit()
                        return {'state': 'ok', 'result': response, 'attempts': number,
                                'initial_backend_pid': initial_pid, 'isolation': isolation}
                except SerializationFailure as error:
                    if error.pgcode != '40001' or number == 6:
                        raise
                    # The closure retains the exact UUID/raw intent. A 40P01
                    # or 55P03 is not caught or converted into success here.

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(execute, user_id, action) for user_id, action in actions]
            results = [future.result(timeout=40) for future in futures]
        if len({row['initial_backend_pid'] for row in results}) != 2:
            raise AssertionError('C32 contenders did not use two independent initial backends')
        return results

    try:
        reactions = [{'api_version': 2, 'membership_id': member_by_user[reader_id],
                      'client_uuid': str(uuid4()), 'expected_revision': 0, 'emoji': emoji}
                     for emoji in ('👍', '❤️')]
        phases['reaction_absent_cas'] = race([(reader_id, lambda service, payload=payload:
            service._v2_message_reaction(room_id, base_message, payload)) for payload in reactions])
        if sorted(row['state'] for row in phases['reaction_absent_cas']) != ['ok', 'revision_conflict']:
            raise AssertionError('Absent reaction CAS must have exactly one winner')
        save = {'api_version': 2, 'membership_id': member_by_user[reader_id],
                'client_uuid': str(uuid4()), 'expected_revision': 0, 'saved': True}
        phases['saved_same_uuid'] = race([(reader_id, lambda service: service._v2_message_saved(
            room_id, base_message, save)) for _index in range(2)])
        if (any(row['state'] != 'ok' or row['result']['operation_revision'] != 1
                for row in phases['saved_same_uuid'])
                or sorted(row['result']['replayed'] for row in phases['saved_same_uuid']) != [False, True]):
            raise AssertionError('Identical saved intent did not persist once and replay once')
        plain = {'api_version': 2, 'membership_id': member_by_user[owner_id],
                 'client_uuid': str(uuid4()), 'text': 'Same legacy and social intent'}
        phases['legacy_social_empty_mentions'] = race([
            (owner_id, lambda service: service._v2_send(room_id, plain)),
            (owner_id, lambda service: service._v2_social_send(room_id, {**plain, 'mention_user_ids': []})),
        ])
        explicit = {'api_version': 2, 'membership_id': member_by_user[owner_id],
                    'client_uuid': str(uuid4()), 'text': 'Explicit same-room intent', 'mention_user_ids': [reader_id]}
        phases['explicit_mentions_same_uuid'] = race([(owner_id, lambda service:
            service._v2_social_send(room_id, explicit)) for _index in range(2)])
        for name in ('legacy_social_empty_mentions', 'explicit_mentions_same_uuid'):
            if any(row['state'] != 'ok' for row in phases[name]) or len({
                    row['result']['message_id'] for row in phases[name]}) != 1:
                raise AssertionError('C32 same-room sends duplicated or lost their immutable message')
        with registry.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout='10s'")
            cursor.execute("SET LOCAL lock_timeout='2s'")
            scoped = api.Environment(cursor, owner_id, {'allowed_company_ids': [company_id]})
            normalized = v2_contracts.normalize_social_send(explicit)
            fresh = scoped['baseer.bchat.service']._v2_fresh_replay(
                room_id, member_by_user[owner_id], normalized, v2_contracts.digest(room_id, normalized))
            if fresh != phases['explicit_mentions_same_uuid'][0]['result']:
                raise AssertionError('The real fresh replay helper lost the explicit-mention digest')
            changed = {**normalized, 'mention_user_ids': [other_id]}
            try:
                scoped['baseer.bchat.service']._v2_fresh_replay(
                    room_id, member_by_user[owner_id], changed, v2_contracts.digest(room_id, changed))
            except ProtocolError as error:
                if error.code != 'idempotency_conflict' or error.status != 409:
                    raise
            else:
                raise AssertionError('Fresh replay accepted a changed mention intent')
            cursor.execute('SELECT revision FROM baseer_bchat_message_reaction WHERE message_id=%s', [base_message])
            if cursor.fetchall() != [(1,)]:
                raise AssertionError('Reaction CAS duplicated state or lost its first revision')
            cursor.execute('SELECT revision FROM baseer_bchat_message_saved WHERE message_id=%s', [base_message])
            if cursor.fetchall() != [(1,)]:
                raise AssertionError('Saved idempotence duplicated state or lost its first revision')
            counts = []
            for payload in (plain, explicit):
                cursor.execute('SELECT COUNT(*) FROM baseer_bchat_message WHERE room_id=%s AND author_user_id=%s AND client_uuid=%s',
                               [room_id, owner_id, payload['client_uuid']])
                counts.append(cursor.fetchone()[0])
            if counts != [1, 1]:
                raise AssertionError('A C32 message UUID was lost or duplicated')
            cursor.execute('''SELECT message_id,recipient_user_id,recipient_membership_id
                              FROM baseer_bchat_message_mention WHERE room_id=%s''', [room_id])
            explicit_id = phases['explicit_mentions_same_uuid'][0]['result']['message_id']
            if cursor.fetchall() != [(explicit_id, reader_id, member_by_user[reader_id])]:
                raise AssertionError('Explicit mention creation was not atomic/idempotent')
            cursor.execute('''SELECT id,delivered_at,read_at FROM baseer_bchat_message_receipt
                              WHERE message_id=%s ORDER BY id''', [base_message])
            if cursor.fetchall() != original_receipts:
                raise AssertionError('A C32 projection changed existing receipt timestamps')
            cursor.execute('SELECT action,COUNT(*) FROM baseer_bchat_social_operation WHERE actor_id=ANY(%s) GROUP BY action', [ids])
            if dict(cursor.fetchall()) != {'message_reaction': 1, 'message_saved': 1}:
                raise AssertionError('C32 retries duplicated their immutable social audit')
            cursor.execute('''SELECT COUNT(*) FROM baseer_bchat_message_receipt r
                              JOIN baseer_bchat_message m ON m.id=r.message_id
                              WHERE m.room_id=%s AND (r.read_at IS NOT NULL OR r.delivered_at IS NOT NULL)''', [room_id])
            if cursor.fetchone()[0]:
                raise AssertionError('Social metadata changed message receipt timestamps')
        proof = {'database': env.cr.dbname, 'independent_backends': len(backend_pids), 'phases': phases,
                 'reaction_rows': 1, 'reaction_revision': 1, 'saved_rows': 1, 'saved_revision': 1,
                 'legacy_social_message_count': 1, 'explicit_message_count': 1, 'mention_rows': 1,
                 'operation_receipts': 2,
                 'receipt_timestamps_unchanged': True, 'fresh_mention_replay_verified': True,
                 'fresh_mention_digest_conflict_rejected': True,
                 'fresh_replay_witness': 'direct_read_only_helper_not_forced_unique_violation',
                 'cleanup_completed': False}
    finally:
        with registry.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout='10s'")
            cursor.execute("SET LOCAL lock_timeout='2s'")
            cursor.execute('SELECT name,group_creator_user_id FROM baseer_bchat_room WHERE id=%s', [room_id])
            if cursor.fetchone() != ('Message social race ' + marker, owner_id):
                raise RuntimeError('Refusing C32 cleanup: synthetic room ownership changed')
            cursor.execute('SELECT login FROM res_users WHERE id=ANY(%s)', [ids])
            if {row[0] for row in cursor.fetchall()} != {
                    'bchat-message-social-%s-%s' % (marker, label) for label in ('owner', 'reader', 'other')}:
                raise RuntimeError('Refusing C32 cleanup: synthetic account ownership changed')
            cursor.execute('DELETE FROM baseer_bchat_message_reaction WHERE room_id=%s', [room_id])
            cursor.execute('DELETE FROM baseer_bchat_message_saved WHERE room_id=%s', [room_id])
            cursor.execute('DELETE FROM baseer_bchat_message_mention WHERE room_id=%s', [room_id])
            cursor.execute('DELETE FROM baseer_bchat_social_operation WHERE actor_id=ANY(%s)', [ids])
            cursor.execute('DELETE FROM baseer_bchat_change WHERE room_id=%s OR user_id=ANY(%s)', [room_id, ids])
            cursor.execute('''DELETE FROM baseer_bchat_message_receipt WHERE message_id IN
                              (SELECT id FROM baseer_bchat_message WHERE room_id=%s)''', [room_id])
            cursor.execute('DELETE FROM baseer_bchat_message WHERE room_id=%s', [room_id])
            cursor.execute('DELETE FROM baseer_bchat_group_event WHERE room_id=%s', [room_id])
            cursor.execute('DELETE FROM baseer_bchat_membership WHERE room_id=%s', [room_id])
            cursor.execute('DELETE FROM baseer_bchat_room WHERE id=%s', [room_id])
            cursor.execute('DELETE FROM baseer_bchat_change_cursor WHERE user_id=ANY(%s)', [ids])
            api.Environment(cursor, admin_id, {})['res.users'].sudo().browse(ids).unlink()
            cursor.commit()
        if proof is not None:
            proof['cleanup_completed'] = True
    return proof
