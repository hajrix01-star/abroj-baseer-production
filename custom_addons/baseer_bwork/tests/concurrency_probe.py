"""Manual two-cursor probe for a DISPOSABLE Odoo database only.

Run with an Odoo shell whose ``env`` is already loaded. This is deliberately
not imported by tests/__init__.py: it commits test fixtures so independent
cursors can race, and therefore must never run in a shared or live database.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from time import sleep
from uuid import uuid4

from odoo import Command, api
from odoo.service.model import retrying


def run(env):
    if not env.cr.dbname.startswith('bwork_text_test_'):
        raise RuntimeError('Refusing concurrency probe outside a bwork_text_test_ disposable DB')
    company = env.company
    suffix = uuid4().hex
    users = env['res.users'].with_context(no_reset_password=True)
    manager = users.create({
        'name': 'BWork concurrency manager %s' % suffix,
        'login': 'bwork-race-manager-%s' % suffix,
        'company_id': company.id,
        'company_ids': [Command.set(company.ids)],
        'group_ids': [Command.set([env.ref('baseer_bwork.group_bwork_manager').id])],
    })
    member = users.create({
        'name': 'BWork concurrency member %s' % suffix,
        'login': 'bwork-race-member-%s' % suffix,
        'company_id': company.id,
        'company_ids': [Command.set(company.ids)],
        'group_ids': [Command.set([env.ref('base.group_user').id])],
    })
    rooms = env['baseer.bwork.room'].with_user(manager).with_company(company)
    first_room = rooms.create({'name': 'BWork race A %s' % suffix, 'company_id': company.id})
    second_room = rooms.create({'name': 'BWork race B %s' % suffix, 'company_id': company.id})
    membership_model = env['baseer.bwork.membership'].with_user(manager).with_company(company)
    first_membership = membership_model.create({'room_id': first_room.id, 'user_id': manager.id})
    second_membership = membership_model.create({'room_id': second_room.id, 'user_id': manager.id})
    ids = (manager.id, member.id, company.id, first_room.id, second_room.id,
           first_membership.id, second_membership.id)
    env.cr.commit()  # Explicit fixture commit is safe only on this disposable DB.

    manager_id, member_id, company_id, room_a, room_b, membership_a, membership_b = ids
    registry = env.registry

    def race(work):
        barrier = Barrier(2)

        def worker():
            with registry.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '15s'")
                scoped = api.Environment(cursor, manager_id, {'allowed_company_ids': [company_id]})
                barrier.wait(timeout=10)
                try:
                    value = retrying(lambda: work(scoped), scoped)
                    return ('ok', value)
                except Exception as error:
                    cursor.rollback()
                    return ('error', type(error).__name__, str(error))

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker) for _ in range(2)]
            return [future.result(timeout=35) for future in futures]

    join = race(lambda scoped: scoped['baseer.bwork.membership'].create({
        'room_id': room_a, 'user_id': member_id,
    }).id)
    assert sorted(item[0] for item in join) == ['error', 'ok'], join
    assert next(item for item in join if item[0] == 'error')[1] == 'AccessError', join

    same_uuid = str(uuid4())
    send = race(lambda scoped: scoped['baseer.bwork.service']._v2_send(room_a, {
        'api_version': 2, 'membership_id': membership_a,
        'client_uuid': same_uuid, 'text': 'same two-cursor payload',
    }))
    assert all(item[0] == 'ok' for item in send), send
    assert send[0][1]['message_id'] == send[1][1]['message_id'], send

    cross_uuid = str(uuid4())
    target_rooms = [room_a, room_b]
    target_memberships = [membership_a, membership_b]
    # Different locks, same author/UUID: the DB unique constraint must decide.
    barrier = Barrier(2)

    def cross_worker(index):
        with registry.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '15s'")
            scoped = api.Environment(cursor, manager_id, {'allowed_company_ids': [company_id]})
            barrier.wait(timeout=10)
            try:
                result = retrying(lambda: scoped['baseer.bwork.service']._v2_send(target_rooms[index], {
                    'api_version': 2, 'membership_id': target_memberships[index],
                    'client_uuid': cross_uuid, 'text': 'cross-room conflict',
                }), scoped)
                return ('ok', result)
            except Exception as error:
                cursor.rollback()
                return ('error', type(error).__name__, str(error))

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(cross_worker, index) for index in (0, 1)]
        cross = [future.result(timeout=35) for future in futures]
    assert sorted(item[0] for item in cross) == ['error', 'ok'], cross
    assert next(item for item in cross if item[0] == 'error')[1] == 'ProtocolError', cross

    with registry.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) FROM baseer_bwork_membership WHERE room_id = %s AND user_id = %s AND active',
                       [room_a, member_id])
        assert cursor.fetchone()[0] == 1
        for value in (same_uuid, cross_uuid):
            cursor.execute('SELECT COUNT(*) FROM baseer_bwork_message WHERE author_user_id = %s AND client_uuid = %s',
                           [manager_id, value])
            assert cursor.fetchone()[0] == 1

    # Deterministic stale-snapshot interleavings: writer holds the room lock
    # while reader establishes a REPEATABLE READ snapshot, then reader tries
    # the same room before writer commits. Odoo must retry the entire reader.
    def interleave(room_id, writer_work, reader_uid, reader_work):
        writer_ready = Event()
        reader_ready = Event()

        def writer():
            with registry.cursor() as cursor:
                scoped = api.Environment(cursor, manager_id, {'allowed_company_ids': [company_id]})
                result = writer_work(scoped)
                writer_ready.set()
                assert reader_ready.wait(timeout=10)
                sleep(0.25)  # Give reader time to block on the held row lock.
                cursor.commit()
                return result

        def reader():
            assert writer_ready.wait(timeout=10)
            with registry.cursor() as cursor:
                cursor.execute('SELECT revision FROM baseer_bwork_room WHERE id = %s', [room_id])
                cursor.fetchone()  # Establish an old REPEATABLE READ snapshot.
                scoped = api.Environment(cursor, reader_uid, {'allowed_company_ids': [company_id]})
                reader_ready.set()
                try:
                    return ('ok', retrying(lambda: reader_work(scoped), scoped))
                except Exception as error:
                    cursor.rollback()
                    return ('error', type(error).__name__, str(error))

        with ThreadPoolExecutor(max_workers=2) as pool:
            write_future = pool.submit(writer)
            read_future = pool.submit(reader)
            return write_future.result(timeout=35), read_future.result(timeout=35)

    # A message committed before a join must become the new join floor.
    with registry.cursor() as cursor:
        scoped = api.Environment(cursor, manager_id, {'allowed_company_ids': [company_id]})
        join_room = scoped['baseer.bwork.room'].create({
            'name': 'BWork race join floor %s' % suffix, 'company_id': company_id,
        })
        join_manager = scoped['baseer.bwork.membership'].create({
            'room_id': join_room.id, 'user_id': manager_id,
        })
        join_room_id, join_manager_id = join_room.id, join_manager.id
        cursor.commit()
    join_send_uuid = str(uuid4())
    prior_send, later_join = interleave(
        join_room_id,
        lambda scoped: scoped['baseer.bwork.service']._v2_send(join_room_id, {
            'api_version': 2, 'membership_id': join_manager_id,
            'client_uuid': join_send_uuid, 'text': 'before concurrent join',
        }),
        manager_id,
        lambda scoped: scoped['baseer.bwork.membership'].create({
            'room_id': join_room_id, 'user_id': member_id,
        }).id,
    )
    assert later_join[0] == 'ok', later_join
    with registry.cursor() as cursor:
        scoped = api.Environment(cursor, member_id, {'allowed_company_ids': [company_id]})
        membership = scoped['baseer.bwork.membership'].sudo().browse(later_join[1])
        assert membership.joined_after_message_id == prior_send['message_id']
        assert scoped['baseer.bwork.service']._v2_history(join_room_id)['messages'] == []

    # A concurrent leave must deny an in-flight send from that member.
    with registry.cursor() as cursor:
        scoped = api.Environment(cursor, manager_id, {'allowed_company_ids': [company_id]})
        leave_member_id = scoped['baseer.bwork.membership'].create({
            'room_id': room_b, 'user_id': member_id,
        }).id
        cursor.commit()
    denied_uuid = str(uuid4())
    _, denied_send = interleave(
        room_b,
        lambda scoped: scoped['baseer.bwork.membership'].browse(leave_member_id).action_revoke(),
        member_id,
        lambda scoped: scoped['baseer.bwork.service']._v2_send(room_b, {
            'api_version': 2, 'membership_id': leave_member_id,
            'client_uuid': denied_uuid, 'text': 'must not persist',
        }),
    )
    assert denied_send[0:2] == ('error', 'AccessError'), denied_send
    with registry.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) FROM baseer_bwork_message WHERE author_user_id = %s AND client_uuid = %s',
                       [member_id, denied_uuid])
        assert cursor.fetchone()[0] == 0

    # A history request racing leave cannot return an older visible page.
    active_first = next(item for item in join if item[0] == 'ok')[1]
    _, denied_history = interleave(
        room_a,
        lambda scoped: scoped['baseer.bwork.membership'].browse(active_first).action_revoke(),
        member_id,
        lambda scoped: scoped['baseer.bwork.service']._v2_history(room_a),
    )
    assert denied_history[0:2] == ('error', 'AccessError'), denied_history

    return {'join': join, 'same_room_send': send, 'cross_room_send': cross,
            'send_before_join': later_join, 'send_after_leave': denied_send,
            'history_after_leave': denied_history,
            'fixture_room_ids': [room_a, room_b], 'fixture_persists_in_disposable_db': True}


if __name__ == '__main__':
    print(run(env))  # noqa: F821 - Odoo shell injects env.
