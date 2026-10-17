"""Two real C13 witnesses; run(env) ONLY on the exact disposable maturity DB.

Late-commit writers use declared protected synthetic message/receipt seeds,
without feed-hint writers. This is NOT a normal-send concurrency claim. Reads
and two-device ACKs call the real service as an ordinary recipient. No database,
receipt callback, lock, time or service is mocked. Not imported as a TransactionCase.
"""
import hashlib
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from time import monotonic
from uuid import uuid4

from psycopg2.errors import SerializationFailure
from odoo import Command, api, fields

from ..models.message import _SERVICE_TOKEN
from ..models.message_receipt import _RECEIPT_TOKEN


APPROVED_DB = 'bchat_maturity_test_20261017'


def run(env):
    if env.cr.dbname != APPROVED_DB:
        raise RuntimeError('Receipt witnesses require the exact disposable maturity database')
    registry = env.registry
    admin_id, company_id = env.ref('base.user_admin').id, env.company.id
    marker = uuid4().hex
    logins = {'bchat-receipt-delivery-%s-%s' % (marker, label) for label in ('owner', 'reader')}
    room_name = 'Receipt delivery probe ' + marker
    room_id, user_ids, committed, proof = None, [], False, None

    def transaction(cursor):
        cursor.execute("SET LOCAL statement_timeout='10s'")
        cursor.execute("SET LOCAL lock_timeout='2s'")
        cursor.execute('SHOW transaction_isolation')
        isolation = cursor.fetchone()[0].strip().lower()
        if isolation != 'repeatable read':
            raise AssertionError('Receipt witnesses require genuine PostgreSQL REPEATABLE READ')
        cursor.execute('SELECT pg_backend_pid(),txid_current()')
        pid, txid = cursor.fetchone()
        return {'backend_pid': pid, 'isolation': isolation, 'transaction_id': txid}

    def ordinary(cursor, user_id):
        scoped = api.Environment(cursor, user_id, {'allowed_company_ids': [company_id]})
        if scoped.su or scoped.user.has_group('base.group_system') or not scoped.user._is_internal():
            raise AssertionError('C13 read/ACK witness must use an ordinary internal account')
        return scoped

    def seed(scoped, label):
        # Intentionally bypass only feed/push publication for deterministic commit order.
        # No normal send, feed serialization or provider behavior is asserted here.
        message = scoped['baseer.bchat.message']._create_verified({
            'room_id': room_id, 'company_id': company_id, 'membership_id': owner_member,
            'author_user_id': owner_id, 'client_uuid': str(uuid4()),
            'payload_digest': hashlib.sha256((marker + label).encode()).hexdigest(),
            'text': 'Synthetic receipt witness ' + label,
        }, _SERVICE_TOKEN)
        receipt = scoped['baseer.bchat.message.receipt']._create_verified([{
            'message_id': message.id, 'membership_id': reader_member,
            'recipient_user_id': reader_id, 'company_id': company_id,
        }], _RECEIPT_TOKEN)
        scoped.flush_all()
        return message.id, receipt.id

    try:
        transaction(env.cr)
        users = env['res.users'].with_context(no_reset_password=True, mail_create_nosubscribe=True).create([{
            'name': 'Receipt probe %s %s' % (marker, label),
            'login': 'bchat-receipt-delivery-%s-%s' % (marker, label),
            'company_id': company_id, 'company_ids': [Command.set([company_id])],
            'group_ids': [Command.set([env.ref('base.group_user').id])],
        } for label in ('owner', 'reader')])
        owner, reader = users
        owner_id, reader_id = owner.id, reader.id
        user_ids = users.ids
        created = env['baseer.bchat.service'].with_user(owner)._v2_group_create({
            'api_version': 2, 'company_id': company_id, 'client_uuid': str(uuid4()),
            'name': room_name, 'member_user_ids': [reader_id]})
        room_id = created['room_id']
        memberships = env['baseer.bchat.membership'].sudo().search([
            ('room_id', '=', room_id), ('active', '=', True)])
        by_user = {row.user_id.id: row.id for row in memberships}
        owner_member, reader_member = by_user[owner_id], by_user[reader_id]
        baseline_message, baseline_receipt = seed(env, 'baseline-unchanged')
        ack_message, ack_receipt = seed(env, 'two-device-ack')
        env.cr.execute('SELECT id,delivered_at,read_at FROM baseer_bchat_message_receipt WHERE id=%s', [baseline_receipt])
        original_receipts = env.cr.fetchall()
        if original_receipts != [(baseline_receipt, None, None)]:
            raise AssertionError('Baseline receipt seed is not pristine')
        env.cr.commit()
        committed = True

        reads = []
        canonical_epochs = []

        def pending(after, writers):
            # A new cursor/TX for each read is essential: reusing an RR snapshot
            # could hide the late commit and incorrectly blame the reset algorithm.
            with registry.cursor() as cursor:
                meta = transaction(cursor)
                if meta['backend_pid'] in writers:
                    raise AssertionError('Reader reused a still-held writer connection')
                scoped = ordinary(cursor, reader_id)
                service = scoped['baseer.bchat.service']
                response = service._v2_pending_receipts(after)
                ids = [row['receipt_id'] for row in response['refs']]
                if ids != sorted(set(ids)) or len(ids) > 30 or any(row <= 0 for row in ids):
                    raise AssertionError('Pending read did not preserve its bounded receipt ordering')
                for reference in response['refs']:
                    canonical = service._v2_message(reference['room_id'], reference['message_id'])
                    pinned = (reference['room_id'] == room_id
                              and reference['membership_id'] == reader_member
                              and canonical['room_id'] == room_id
                              and canonical['membership_id'] == reader_member
                              and canonical['message']['id'] == reference['message_id'])
                    canonical_epochs.append(pinned)
                    if not pinned:
                        raise AssertionError('Canonical read did not echo the current recipient epoch')
                reads.append({**meta, 'after_id': after, 'receipt_ids': ids,
                              'next_after_id': response['next_after_id']})
                return ids

        # Keep both writer connections checked out through all three reader TXs.
        # That proves reader PID independence even with a PostgreSQL connection pool.
        with registry.cursor() as first, registry.cursor() as second:
            first_meta = transaction(first)
            low_message, low_receipt = seed(ordinary(first, owner_id), 'low-uncommitted')
            second_meta = transaction(second)
            high_message, high_receipt = seed(ordinary(second, owner_id), 'high-committed-first')
            writer_pids = [first_meta['backend_pid'], second_meta['backend_pid']]
            if len(set(writer_pids)) != 2 or low_receipt >= high_receipt:
                raise AssertionError('Late-commit witnesses lack distinct writers or low/high ordering')
            second.commit()
            first_page = pending(0, writer_pids)
            first_only_high = high_receipt in first_page and low_receipt not in first_page
            if not first_only_high:
                raise AssertionError('An uncommitted low receipt leaked or committed higher receipt disappeared')
            first.commit()
            continuation = pending(high_receipt, writer_pids)
            excludes_late = low_receipt not in continuation
            reset_page = pending(0, writer_pids)
            reset_finds = low_receipt in reset_page
            if not excludes_late or not reset_finds:
                raise AssertionError('Reset pass failed to recover the late lower receipt')
            if len({row['transaction_id'] for row in reads}) != 3:
                raise AssertionError('Reader did not establish three fresh RR transactions')
        if not canonical_epochs or not all(canonical_epochs):
            raise AssertionError('No verified canonical epoch was observed')

        start = Barrier(2)
        deadline = monotonic() + 40

        def acknowledge():
            initial_pid, initial_isolation = None, None
            for attempt in range(1, 7):
                if monotonic() >= deadline:
                    raise TimeoutError('Two-device ACK witness exceeded its bounded retry deadline')
                try:
                    with registry.cursor() as cursor:
                        meta = transaction(cursor)
                        if attempt == 1:
                            initial_pid, initial_isolation = meta['backend_pid'], meta['isolation']
                            # Establish both real RR snapshots BEFORE either ACK can commit.
                            cursor.execute('SELECT COUNT(*) FROM baseer_bchat_message_receipt WHERE id=%s', [ack_receipt])
                            if cursor.fetchone()[0] != 1:
                                raise AssertionError('ACK receipt fixture is unavailable')
                            start.wait(timeout=10)
                        scoped = ordinary(cursor, reader_id)
                        service = scoped['baseer.bchat.service']
                        canonical = service._v2_message(room_id, ack_message)
                        if (canonical['room_id'], canonical['membership_id'], canonical['message']['id']) != (
                                room_id, reader_member, ack_message):
                            raise AssertionError('ACK request did not pin the canonical recipient epoch')
                        result = service._v2_receipt_ack(room_id, ack_message, 'delivered',
                                                         membership_id=reader_member)
                        cursor.commit()
                        return {'state': 'ok', 'attempts': attempt, 'initial_backend_pid': initial_pid,
                                'isolation': initial_isolation, 'result': result}
                except SerializationFailure as error:
                    if error.pgcode != '40001' or attempt == 6:
                        raise
                    # Exactly the same room/message/kind/membership on a fresh TX.
                    # Deadlock40P01 / lock-timeout55P03 are deliberately not caught.

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(acknowledge) for _number in range(2)]
            devices = [future.result(timeout=45) for future in futures]
        if len({row['initial_backend_pid'] for row in devices}) != 2:
            raise AssertionError('Two-device ACKs did not use independent initial PostgreSQL backends')
        results = [row['result'] for row in devices]
        if (any(row['message_id'] != ack_message for row in results)
                or sorted(row['replayed'] for row in results) != [False, True]
                or results[0]['unread_count'] != results[1]['unread_count']
                or results[0]['last_message_id'] != results[1]['last_message_id']):
            raise AssertionError('Identical ACK did not apply once and replay once')
        stable = bool(results[0]['delivered_at'] and results[0]['delivered_at'] == results[1]['delivered_at'])
        no_read = all(row['read_at'] is None for row in results)
        if not stable or not no_read:
            raise AssertionError('Concurrent delivery ACK changed its timestamp or fabricated a read')

        with registry.cursor() as cursor:
            transaction(cursor)
            cursor.execute('''SELECT delivered_at,read_at FROM baseer_bchat_message_receipt
                WHERE message_id=%s AND membership_id=%s AND recipient_user_id=%s''',
                [ack_message, reader_member, reader_id])
            rows = cursor.fetchall()
            if len(rows) != 1 or fields.Datetime.to_string(rows[0][0]) != results[0]['delivered_at'] or rows[0][1] is not None:
                raise AssertionError('Stored ACK receipt is not one stable delivery without a read')
            cursor.execute('SELECT id,delivered_at,read_at FROM baseer_bchat_message_receipt WHERE id=%s', [baseline_receipt])
            unchanged = cursor.fetchall() == original_receipts
            if not unchanged:
                raise AssertionError('C13 witnesses changed the excluded baseline receipt')
            cursor.execute('SELECT COUNT(*) FROM baseer_bchat_message_receipt WHERE id=ANY(%s) AND (delivered_at IS NOT NULL OR read_at IS NOT NULL)',
                           [[low_receipt, high_receipt]])
            if cursor.fetchone()[0]:
                raise AssertionError('GET discovery or canonical read acknowledged one of the late-commit seeds')
        proof = {'database': env.cr.dbname,
                 'late_commit': {'writer_pids': writer_pids,
                     'writer_isolations': [first_meta['isolation'], second_meta['isolation']],
                     'low_receipt_id': low_receipt, 'high_receipt_id': high_receipt,
                     'first_page_only_high': first_only_high,
                     'continuation_excludes_late_low': excludes_late, 'reset_finds_late_low': reset_finds,
                     'canonical_has_current_epoch': all(canonical_epochs),
                     'writer_fixture': 'protected_seed_no_feed_send_claim', 'reads': reads},
                 'ack_two_devices': devices, 'receipt_rows': len(rows),
                 'stable_delivered_timestamp': stable, 'read_not_fabricated': no_read,
                 'original_receipts_unchanged': unchanged, 'cleanup_completed': False}
    finally:
        # Release the caller's own setup locks on failure before any cleanup cursor.
        env.cr.rollback()
        if committed:
            with registry.cursor() as cursor:
                transaction(cursor)
                cursor.execute('SELECT name,group_creator_user_id FROM baseer_bchat_room WHERE id=%s', [room_id])
                if cursor.fetchone() != (room_name, owner_id):
                    raise RuntimeError('Refusing receipt cleanup: synthetic room ownership changed')
                cursor.execute('SELECT login FROM res_users WHERE id=ANY(%s)', [user_ids])
                if {row[0] for row in cursor.fetchall()} != logins:
                    raise RuntimeError('Refusing receipt cleanup: synthetic account markers changed')
                cursor.execute('SELECT COUNT(*) FROM baseer_bchat_membership WHERE room_id=%s AND NOT(user_id=ANY(%s))', [room_id, user_ids])
                if cursor.fetchone()[0]:
                    raise RuntimeError('Refusing receipt cleanup: unexpected room participant')
                cursor.execute('SELECT COUNT(*) FROM baseer_bchat_message WHERE room_id=%s AND NOT(author_user_id=ANY(%s))', [room_id, user_ids])
                if cursor.fetchone()[0]:
                    raise RuntimeError('Refusing receipt cleanup: unexpected message author')
                cursor.execute('SELECT COUNT(*) FROM baseer_bchat_push_device WHERE user_id=ANY(%s)', [user_ids])
                if cursor.fetchone()[0]:
                    raise RuntimeError('Refusing receipt cleanup: unexpected push installation')
                counts = {}
                for table, where, values in (
                        ('baseer_bchat_change', 'room_id=%s OR user_id=ANY(%s)', [room_id, user_ids]),
                        ('baseer_bchat_message_receipt', 'message_id IN (SELECT id FROM baseer_bchat_message WHERE room_id=%s)', [room_id]),
                        ('baseer_bchat_message', 'room_id=%s', [room_id]),
                        ('baseer_bchat_group_event', 'room_id=%s', [room_id]),
                        ('baseer_bchat_membership', 'room_id=%s', [room_id]),
                        ('baseer_bchat_room', 'id=%s', [room_id]),
                        ('baseer_bchat_social_operation', 'actor_id=ANY(%s)', [user_ids]),
                        ('baseer_bchat_change_cursor', 'user_id=ANY(%s)', [user_ids])):
                    # Table/predicate strings are fixed literals above, never external input.
                    cursor.execute('DELETE FROM ' + table + ' WHERE ' + where, values)
                    counts[table] = cursor.rowcount
                owned_users = api.Environment(cursor, admin_id, {})['res.users'].sudo().browse(user_ids)
                counts['res_users'] = len(owned_users.exists())
                owned_users.unlink()
                cursor.execute('''SELECT (SELECT COUNT(*) FROM res_users WHERE id=ANY(%s))
                    +(SELECT COUNT(*) FROM baseer_bchat_room WHERE id=%s)
                    +(SELECT COUNT(*) FROM baseer_bchat_membership WHERE room_id=%s)
                    +(SELECT COUNT(*) FROM baseer_bchat_message WHERE room_id=%s)
                    +(SELECT COUNT(*) FROM baseer_bchat_change_cursor WHERE user_id=ANY(%s))''',
                    [user_ids, room_id, room_id, room_id, user_ids])
                counts['remaining_owned'] = cursor.fetchone()[0]
                if counts['remaining_owned'] != 0:
                    raise AssertionError('Receipt probe cleanup left owned fixture rows')
                cursor.commit()
            if proof is not None:
                proof['cleanup_completed'] = True
                proof['cleanup_counts'] = counts
    return proof
