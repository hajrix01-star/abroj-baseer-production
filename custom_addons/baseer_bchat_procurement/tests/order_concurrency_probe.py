"""One-shot UUID race probe on bchat_orders_test_20261009 only.

This is deliberately not imported by tests/__init__.py.  It creates clearly
marked synthetic fixtures in the disposable isolated DB, then verifies that
two transactions with the same UUID leave exactly one internal request.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from odoo import Command, api
from odoo.service.model import retrying


def run(env):
    if env.cr.dbname != 'bchat_orders_test_20261009':
        raise RuntimeError('Refusing order race probe outside the isolated test DB')
    suffix = uuid4().hex[:8]
    company = env['res.company'].create({'name': '[LOCAL TEST] BChat order race ' + suffix})
    warehouse = env['stock.warehouse'].search([('company_id', '=', company.id)], limit=1)
    if not warehouse:
        warehouse = env['stock.warehouse'].create({
            'name': '[LOCAL TEST] BChat race warehouse', 'code': 'BR%s' % company.id,
            'company_id': company.id,
        })
    uom = env.ref('uom.product_uom_unit')
    product = env['product.product'].with_company(company).create({
        'name': '[LOCAL TEST] BChat race chicken', 'company_id': company.id,
        'uom_id': uom.id, 'purchase_ok': True, 'is_storable': True,
    })
    option = env['baseer.procurement.purchase.option'].with_company(company).create({
        'name': 'Piece', 'company_id': company.id,
        'product_id': product.id, 'uom_id': uom.id,
    })
    representative = env['res.partner'].create({'name': '[LOCAL TEST] BChat race buyer ' + suffix})
    representative.with_company(company).is_purchase_representative = True
    user = env['res.users'].with_context(no_reset_password=True).create({
        'name': '[LOCAL TEST] BChat race employee ' + suffix,
        'login': 'bchat-race-' + suffix,
        'company_id': company.id, 'company_ids': [Command.set(company.ids)],
        'group_ids': [Command.set([env.ref('base.group_user').id])],
    })
    token = str(uuid4())
    payload = {
        'api_version': 2, 'company_id': company.id,
        'warehouse_id': warehouse.id, 'representative_partner_id': None,
        'client_uuid': token,
        'lines': [{'option_id': option.id, 'quantity': '2.00'}],
    }
    env.cr.commit()  # Only the approved disposable test DB.
    barrier = Barrier(2)

    def submit(index):
        with env.registry.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '15s'")
            scoped = api.Environment(cursor, user.id, {'allowed_company_ids': [company.id]})
            barrier.wait(timeout=10)
            try:
                result = retrying(
                    lambda: scoped['baseer.bchat.service']._v2_order_create(payload), scoped,
                )
                cursor.commit()
                return {'worker': index, 'id': result['order']['id'],
                        'replayed': result['replayed']}
            except Exception as error:
                cursor.rollback()
                return {'worker': index, 'error': type(error).__name__}

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit, index) for index in (0, 1)]
        results = [future.result(timeout=40) for future in futures]
    with env.registry.cursor() as cursor:
        cursor.execute('''SELECT id, requester_id, representative_partner_id, state,
                                source_channel, whatsapp_sent_at
                           FROM baseer_procurement_request
                          WHERE company_id = %s AND client_token = %s''',
                       [company.id, token])
        rows = cursor.fetchall()
    assert len(rows) == 1, (results, rows)
    order_id, requester_id, rep_id, state, channel, whatsapp_at = rows[0]
    assert (requester_id, rep_id, state, channel, whatsapp_at) == (
        user.id, representative.id, 'sent', 'bchat', None,
    ), rows
    assert all(result.get('id') == order_id for result in results), results
    assert sorted(result['replayed'] for result in results) == [False, True], results
    return {'workers': results, 'request_count': len(rows), 'test_company_id': company.id}
