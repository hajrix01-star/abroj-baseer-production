"""One-shot late-commit probe for the isolated BWork repair database only.

Run from an Odoo shell with ``run(env)``.  It is intentionally not imported by
tests/__init__.py: it commits two synthetic hints and then removes exactly
those hints and restores the private cursor.  Never run on an operational DB.
"""

from concurrent.futures import ThreadPoolExecutor
from secrets import randbelow
from threading import Event
from time import monotonic, sleep

from psycopg2.errors import SerializationFailure

from odoo import api


APPROVED_DB = 'bwork_repair_test_20261012'


def run(env):
    if env.cr.dbname != APPROVED_DB:
        raise RuntimeError('Refusing BWork feed probe outside the approved test DB')
    user = env.ref('base.user_admin')
    user_id = user.id
    registry = env.registry
    env.cr.execute('SELECT sequence FROM baseer_bwork_change_cursor WHERE user_id = %s',
                   [user_id])
    old_row = env.cr.fetchone()
    original = old_row[0] if old_row else 0
    env.cr.rollback()
    marker = 1_000_000_000 + randbelow(1_000_000_000)

    first_ready = Event()
    release_first = Event()
    second_started = Event()
    second_appended = Event()
    release_second = Event()

    def append_one(ready, release):
        with registry.cursor() as cursor:
            # Odoo's HTTP request retry wrapper restarts serializable
            # transactions.  Recreate the environment after each rollback.
            for attempt in range(5):
                try:
                    scoped = api.Environment(cursor, user_id, {})
                    result = scoped['baseer.bwork.service']._change_publish(
                        [user_id], 'revoked', room_id=None, order_id=marker,
                    )
                    break
                except SerializationFailure:
                    cursor.rollback()
                    if attempt == 4:
                        raise
            ready.set()
            if not release.wait(timeout=20):
                raise TimeoutError('Feed probe writer was not released')
            cursor.commit()
            return result[0][1:]

    def second_writer():
        second_started.set()
        return append_one(second_appended, release_second)

    def visible():
        with registry.cursor() as cursor:
            cursor.execute('''
                SELECT sequence FROM baseer_bwork_change
                WHERE user_id = %s AND sequence > %s ORDER BY sequence
            ''', [user_id, original])
            return [row[0] for row in cursor.fetchall()]

    started_at = monotonic()
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(append_one, first_ready, release_first)
            try:
                if not first_ready.wait(timeout=10):
                    raise TimeoutError('First writer did not append')
                second = pool.submit(second_writer)
                if not second_started.wait(timeout=10):
                    raise TimeoutError('Second writer did not start')
                sleep(0.2)
                assert not second_appended.is_set(), 'Second writer overtook locked first cursor'
                assert visible() == [], 'Uncommitted event became visible'

                release_first.set()
                first_seq, _first_id = first.result(timeout=15)
                assert first_seq == original + 1, (first_seq, original)
                if not second_appended.wait(timeout=15):
                    raise TimeoutError('Second writer did not append after first commit')
                assert visible() == [first_seq], 'Late second commit leaked early'

                release_second.set()
                second_seq, _second_id = second.result(timeout=15)
                assert second_seq == original + 2, (second_seq, original)
                assert visible() == [first_seq, second_seq], 'Committed feed has a sequence gap'
                return {'first_seq': first_seq, 'second_seq': second_seq,
                        'elapsed_ms': round((monotonic() - started_at) * 1000, 1)}
            finally:
                release_first.set()
                release_second.set()
    finally:
        # Only exact rows produced by this probe may be removed.  If an
        # unexpected writer touched the cursor, fail closed rather than
        # rewinding someone else's sequence.
        with registry.cursor() as cursor:
            cursor.execute('''
                SELECT id FROM baseer_bwork_change
                WHERE user_id = %s AND order_id = %s AND kind = 'revoked'
            ''', [user_id, marker])
            created = [row[0] for row in cursor.fetchall()]
            cursor.execute('SELECT sequence FROM baseer_bwork_change_cursor WHERE user_id = %s',
                           [user_id])
            current_row = cursor.fetchone()
            current = current_row[0] if current_row else 0
            if created and current != original + len(created):
                raise RuntimeError('Unexpected feed writer; manual isolated-DB cleanup required')
            if created:
                cursor.execute('DELETE FROM baseer_bwork_change WHERE id = ANY(%s)', [created])
                if cursor.rowcount != len(created):
                    raise RuntimeError('Probe row count mismatch; isolated DB needs inspection')
                if old_row:
                    cursor.execute('''
                        UPDATE baseer_bwork_change_cursor SET sequence = %s
                        WHERE user_id = %s AND sequence = %s
                    ''', [original, user_id, current])
                else:
                    cursor.execute('''
                        DELETE FROM baseer_bwork_change_cursor
                        WHERE user_id = %s AND sequence = %s
                    ''', [user_id, current])
                if cursor.rowcount != 1:
                    raise RuntimeError('Probe cursor cleanup mismatch')
            cursor.commit()
