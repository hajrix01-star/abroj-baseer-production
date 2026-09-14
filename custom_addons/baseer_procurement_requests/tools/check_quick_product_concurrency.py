"""Disposable two-session acceptance probe for PRC-CATALOG-QUICK1."""

import json
import threading
import time
from uuid import uuid4

from psycopg2 import errors as pg_errors
from odoo import api
from odoo.exceptions import ConcurrencyError
from odoo.modules.registry import Registry


database = env.cr.dbname
company = env.company
cashier_group = env.ref('baseer_procurement_requests.group_procurement_cashier')
env.user.group_ids |= cashier_group
category_values = {'name': 'PRC quick concurrency standard'}
if 'property_cost_method' in env['product.category']._fields:
    category_values['property_cost_method'] = 'standard'
if 'property_valuation' in env['product.category']._fields:
    category_values['property_valuation'] = 'periodic'
category = env['product.category'].create(category_values)
name = 'PRC concurrency %s' % uuid4().hex
user_id = env.user.id
company_id = company.id
category_id = category.id
env.cr.commit()

snapshot_ready = threading.Event()
first_committed = threading.Event()
results = []
errors = []
result_lock = threading.Lock()


def create_first_product():
    try:
        if not snapshot_ready.wait(timeout=10):
            raise RuntimeError('Stale-snapshot setup timed out.')
        with Registry(database).cursor() as cursor:
            thread_env = api.Environment(cursor, user_id, {'allowed_company_ids': [company_id]})
            result = thread_env['baseer.procurement.request'].create_quick_catalog_product(
                name, '11.25', category_id,
            )
            cursor.commit()
            results.append(result)
        first_committed.set()
    except Exception as error:  # pragma: no cover - standalone acceptance output
        with result_lock:
            errors.append('first: %r' % error)


def create_from_stale_snapshot():
    try:
        with Registry(database).cursor() as cursor:
            thread_env = api.Environment(cursor, user_id, {'allowed_company_ids': [company_id]})
            cursor.execute('SELECT count(*) FROM product_product')
            cursor.fetchone()
            snapshot_ready.set()
            if not first_committed.wait(timeout=10):
                raise RuntimeError('First product commit timed out.')
            try:
                thread_env['baseer.procurement.request'].create_quick_catalog_product(
                    '  %s  ' % name.upper(), '11.25', category_id,
                )
            except ConcurrencyError:
                cursor.rollback()
            else:
                raise AssertionError('Stale snapshot did not trigger a concurrency retry.')
        for attempt in range(5):
            try:
                with Registry(database).cursor() as cursor:
                    retry_env = api.Environment(cursor, user_id, {'allowed_company_ids': [company_id]})
                    result = retry_env['baseer.procurement.request'].create_quick_catalog_product(
                        '  %s  ' % name.upper(), '11.25', category_id,
                    )
                    cursor.commit()
                    results.append(result)
                    return
            except ConcurrencyError:
                time.sleep(0.05 * (attempt + 1))
        raise RuntimeError('Product concurrency retry budget exhausted.')
    except Exception as error:  # pragma: no cover - standalone acceptance output
        with result_lock:
            errors.append('stale: %r' % error)


threads = [threading.Thread(target=create_first_product), threading.Thread(target=create_from_stale_snapshot)]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join(timeout=30)
if any(thread.is_alive() for thread in threads):
    raise RuntimeError('Concurrency probe timed out.')
if errors:
    raise RuntimeError('; '.join(errors))

with Registry(database).cursor() as cursor:
    check_env = api.Environment(cursor, user_id, {'allowed_company_ids': [company_id]})
    products = check_env['product.product'].with_context(active_test=False).search([
        ('company_id', '=', company_id), ('name', '=ilike', name),
    ])
    options = check_env['baseer.procurement.purchase.option'].search([
        ('company_id', '=', company_id), ('product_id', 'in', products.ids),
    ])
    payload = {
        'results': sorted(result['created'] for result in results),
        'product_ids': sorted(set(result['product_id'] for result in results)),
        'product_count': len(products),
        'option_count': len(options),
    }
    if payload != {
        'results': [False, True],
        'product_ids': [products.id] if len(products) == 1 else payload['product_ids'],
        'product_count': 1,
        'option_count': 1,
    }:
        raise AssertionError(payload)
    concurrent_product_id = products.id

favorite_snapshot_ready = threading.Event()
favorite_first_committed = threading.Event()
favorite_errors = []


def set_first_favorite():
    try:
        if not favorite_snapshot_ready.wait(timeout=10):
            raise RuntimeError('Favorite stale-snapshot setup timed out.')
        with Registry(database).cursor() as cursor:
            thread_env = api.Environment(cursor, user_id, {'allowed_company_ids': [company_id]})
            thread_env['baseer.procurement.request'].set_catalog_favorite(
                concurrent_product_id, True,
            )
            cursor.commit()
        favorite_first_committed.set()
    except Exception as error:  # pragma: no cover - standalone acceptance output
        with result_lock:
            favorite_errors.append(repr(error))


def set_favorite_from_stale_snapshot():
    try:
        with Registry(database).cursor() as cursor:
            thread_env = api.Environment(cursor, user_id, {'allowed_company_ids': [company_id]})
            cursor.execute('SELECT count(*) FROM baseer_procurement_product_favorite')
            cursor.fetchone()
            favorite_snapshot_ready.set()
            if not favorite_first_committed.wait(timeout=10):
                raise RuntimeError('First favorite commit timed out.')
            try:
                thread_env['baseer.procurement.request'].set_catalog_favorite(
                    concurrent_product_id, True,
                )
            except ConcurrencyError:
                cursor.rollback()
            else:
                raise AssertionError('Stale favorite snapshot did not trigger a concurrency retry.')
        with Registry(database).cursor() as cursor:
            retry_env = api.Environment(cursor, user_id, {'allowed_company_ids': [company_id]})
            retry_env['baseer.procurement.request'].set_catalog_favorite(
                concurrent_product_id, True,
            )
            cursor.commit()
    except Exception as error:  # pragma: no cover - standalone acceptance output
        with result_lock:
            favorite_errors.append(repr(error))


favorite_threads = [
    threading.Thread(target=set_first_favorite),
    threading.Thread(target=set_favorite_from_stale_snapshot),
]
for thread in favorite_threads:
    thread.start()
for thread in favorite_threads:
    thread.join(timeout=30)
if any(thread.is_alive() for thread in favorite_threads):
    raise RuntimeError('Favorite concurrency probe timed out.')
if favorite_errors:
    raise RuntimeError('; '.join(favorite_errors))
with Registry(database).cursor() as cursor:
    check_env = api.Environment(cursor, user_id, {'allowed_company_ids': [company_id]})
    favorite_count = check_env['baseer.procurement.product.favorite'].sudo().search_count([
        ('user_id', '=', user_id), ('company_id', '=', company_id),
        ('product_id', '=', concurrent_product_id), ('is_favorite', '=', True),
    ])
    if favorite_count != 1:
        raise AssertionError({'favorite_count': favorite_count})
    payload['favorite_count'] = favorite_count


def exercise_opposite_state_race(initial_state, winner_state, stale_desired, label):
    with Registry(database).cursor() as cursor:
        setup_env = api.Environment(cursor, user_id, {'allowed_company_ids': [company_id]})
        setup_env['baseer.procurement.request'].set_catalog_favorite(
            concurrent_product_id, initial_state,
        )
        cursor.commit()

    snapshot_event = threading.Event()
    winner_event = threading.Event()
    race_errors = []

    def winner():
        try:
            if not snapshot_event.wait(timeout=10):
                raise RuntimeError('%s winner setup timed out.' % label)
            with Registry(database).cursor() as cursor:
                winner_env = api.Environment(cursor, user_id, {'allowed_company_ids': [company_id]})
                winner_env['baseer.procurement.request'].set_catalog_favorite(
                    concurrent_product_id, winner_state,
                )
                cursor.commit()
            winner_event.set()
        except Exception as error:  # pragma: no cover - standalone acceptance output
            race_errors.append('winner: %r' % error)

    def stale_writer():
        try:
            with Registry(database).cursor() as cursor:
                stale_env = api.Environment(cursor, user_id, {'allowed_company_ids': [company_id]})
                cursor.execute(
                    'SELECT is_favorite FROM baseer_procurement_product_favorite '
                    'WHERE user_id=%s AND company_id=%s AND product_id=%s',
                    [user_id, company_id, concurrent_product_id],
                )
                cursor.fetchone()
                snapshot_event.set()
                if not winner_event.wait(timeout=10):
                    raise RuntimeError('%s winner commit timed out.' % label)
                try:
                    stale_env['baseer.procurement.request'].set_catalog_favorite(
                        concurrent_product_id, stale_desired,
                    )
                except (ConcurrencyError, pg_errors.SerializationFailure):
                    cursor.rollback()
                else:
                    raise AssertionError('%s stale write did not request a retry.' % label)
            with Registry(database).cursor() as cursor:
                retry_env = api.Environment(cursor, user_id, {'allowed_company_ids': [company_id]})
                retry_env['baseer.procurement.request'].set_catalog_favorite(
                    concurrent_product_id, stale_desired,
                )
                cursor.commit()
        except Exception as error:  # pragma: no cover - standalone acceptance output
            race_errors.append('stale: %r' % error)

    race_threads = [threading.Thread(target=winner), threading.Thread(target=stale_writer)]
    for thread in race_threads:
        thread.start()
    for thread in race_threads:
        thread.join(timeout=30)
    if any(thread.is_alive() for thread in race_threads):
        raise RuntimeError('%s race timed out.' % label)
    if race_errors:
        raise RuntimeError('%s: %s' % (label, '; '.join(race_errors)))
    with Registry(database).cursor() as cursor:
        verify_env = api.Environment(cursor, user_id, {'allowed_company_ids': [company_id]})
        state_row = verify_env['baseer.procurement.product.favorite'].sudo().search([
            ('user_id', '=', user_id), ('company_id', '=', company_id),
            ('product_id', '=', concurrent_product_id),
        ], limit=1)
        if not state_row or state_row.is_favorite is not stale_desired:
            raise AssertionError({label: state_row.is_favorite if state_row else None})


exercise_opposite_state_race(False, True, False, 'true-to-false')
exercise_opposite_state_race(True, False, True, 'false-to-true')
payload['opposite_state_races'] = 2

print('PRC_QUICK_CONCURRENCY_OK ' + json.dumps(payload, sort_keys=True))
