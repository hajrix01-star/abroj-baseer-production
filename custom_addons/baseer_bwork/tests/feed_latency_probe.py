"""Small backend-only feed timing probe for the isolated repair DB.

This does not measure WebSocket, Android rendering, or closed-app FCM.
Run ``run(env)`` from Odoo shell; the synthetic rows are removed afterward.
"""

from math import ceil
from secrets import randbelow
from time import monotonic

from odoo import api


def run(env, samples=20):
    if env.cr.dbname != 'bwork_repair_test_20261012' or samples != 20:
        raise RuntimeError('Refusing non-approved BWork timing probe')
    user_id = env.ref('base.user_admin').id
    registry = env.registry
    marker = 1_000_000_000 + randbelow(1_000_000_000)
    env.cr.execute('SELECT sequence FROM baseer_bwork_change_cursor WHERE user_id = %s',
                   [user_id])
    old_row = env.cr.fetchone()
    original = old_row[0] if old_row else 0
    env.cr.rollback()
    durations = []
    after = original
    try:
        for _index in range(samples):
            started = monotonic()
            with registry.cursor() as writer:
                service = api.Environment(writer, user_id, {})['baseer.bwork.service']
                service._change_publish([user_id], 'revoked', order_id=marker)
                writer.commit()
            with registry.cursor() as reader:
                service = api.Environment(reader, user_id, {})['baseer.bwork.service']
                page = service._v2_changes(after, 100)
                assert page['changes'] == [{'seq': after + 1, 'kind': 'revoked'}], page
                after = page['next_after']
            durations.append((monotonic() - started) * 1000)
        ordered = sorted(durations)
        return {'samples': samples, 'p95_ms': round(ordered[ceil(.95 * samples) - 1], 1),
                'max_ms': round(ordered[-1], 1), 'scope': 'backend commit + new cursor fetch'}
    finally:
        with registry.cursor() as cursor:
            cursor.execute('''
                SELECT id FROM baseer_bwork_change
                WHERE user_id = %s AND order_id = %s AND kind = 'revoked'
            ''', [user_id, marker])
            ids = [row[0] for row in cursor.fetchall()]
            cursor.execute('SELECT sequence FROM baseer_bwork_change_cursor WHERE user_id = %s',
                           [user_id])
            current_row = cursor.fetchone()
            current = current_row[0] if current_row else 0
            if current != original + len(ids):
                raise RuntimeError('Unexpected feed writer; inspect the isolated DB')
            if ids:
                cursor.execute('DELETE FROM baseer_bwork_change WHERE id = ANY(%s)', [ids])
                if cursor.rowcount != len(ids):
                    raise RuntimeError('Synthetic feed cleanup count mismatch')
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
                    raise RuntimeError('Synthetic cursor cleanup count mismatch')
            cursor.commit()
