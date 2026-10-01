"""Run with Odoo shell against the explicitly isolated QA test database only.

Real independent transactions mutate a payment while the protected command
waits for its row lock. These fixtures remain exclusively in the test clone.
"""
import threading
import time

from odoo import api
from odoo.exceptions import AccessError
from odoo.addons.baseer_pos_product_substitution.tests.test_substitution import TestBaseerPosProductSubstitution

assert env.cr.dbname == 'baseer_prc_latest_qa_test_20261001', 'Test clone only'
env.cr.rollback()
registry = env.registry
actor = TestBaseerPosProductSubstitution('test_cashier_can_edit_draft_with_provisional_payment')
actor.env = env

for label, mutation in [('confirmation', {'payment_status': 'done'}), ('amount', {'amount': 12})]:
    _config, order, _replacement, action, payment = actor._manual_draft_payment_fixture()
    order_id, payment_id = order.id, payment.id
    revision = order._baseer_revision()
    source_uuid = action['source_line_uuid']
    env.cr.commit()
    ready = threading.Event()
    proceed = threading.Event()
    result = {}

    def edit_worker():
        with registry.cursor() as edit_cr:
            editing = api.Environment(edit_cr, env.uid, dict(env.context))
            record = editing['pos.order'].browse(order_id)
            # Establish the transaction snapshot before the concurrent write.
            assert record.payment_ids.amount == 10
            edit_cr.execute('SELECT pg_backend_pid()')
            result['pid'] = edit_cr.fetchone()[0]
            ready.set()
            assert proceed.wait(8)
            try:
                record.baseer_apply_protected_action('edit', action, revision)
                result['outcome'] = 'unexpected_success'
            except Exception as error:
                result['outcome'] = type(error).__name__
                result['sqlstate'] = getattr(error, 'pgcode', None)
            finally:
                edit_cr.rollback()

    worker = threading.Thread(target=edit_worker, daemon=True)
    worker.start()
    assert ready.wait(8)
    with registry.cursor() as writer_cr:
        writer = api.Environment(writer_cr, env.uid, dict(env.context))
        writer['pos.payment'].browse(payment_id).write(mutation)
        proceed.set()
        waiting = False
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with registry.cursor() as observer_cr:
                observer_cr.execute(
                    "SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s",
                    [result['pid']])
                observed = observer_cr.fetchone()
                if observed and observed[0] == 'Lock':
                    waiting = True
                    break
            time.sleep(0.05)
        assert waiting, (label, result)
        writer_cr.commit()
    worker.join(8)
    assert not worker.is_alive()
    assert result['outcome'] == 'SerializationFailure' and result['sqlstate'] == '40001', result
    env.cr.rollback()
    env.invalidate_all()
    preserved = env['pos.payment'].browse(payment_id)
    assert preserved.exists()
    assert all(preserved[key] == value for key, value in mutation.items())
    unchanged = env['pos.order'].browse(order_id)
    assert unchanged.lines.uuid == source_uuid
    assert not env['baseer.pos.substitution'].search_count([('action_uuid', '=', action['action_uuid'])])
    try:
        unchanged.baseer_apply_protected_action('edit', action, revision)
    except AccessError:
        pass
    else:
        raise AssertionError('A fresh retry must preserve the modified payment')
    env.cr.rollback()
    print('RACE_PASS', label, 'lock wait -> serialization rollback -> guarded fresh retry; payment and source retained')
print('RACE_ALL_PASS=2')

