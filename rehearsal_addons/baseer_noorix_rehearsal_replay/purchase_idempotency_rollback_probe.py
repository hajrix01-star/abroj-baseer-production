"""Transient first-apply + idempotent-replay proof for a Noorix purchase wave.

This is a rehearsal test only.  It performs the ARZ March writer call, calls
the same scope a second time to execute the full verifier, asserts the second
call creates no additional records, then raises a deliberate exception from
an outer savepoint.  The catch happens outside that savepoint, so no run, map,
invoice, payment or partial reconciliation survives.
"""

import json

from odoo.exceptions import UserError
from odoo.addons.baseer_noorix_rehearsal_replay import replay_writer


SOURCE_COMPANY_ID = "cmnf604ka009ay8lm556wgd9c"
MONTH = "2026-03"
RUN_KEY = "purchase:%s:%s" % (SOURCE_COMPANY_ID, MONTH)


def counts():
    return {
        "run": env["baseer.noorix.rehearsal.run"].sudo().search_count([("run_key", "=", RUN_KEY)]),
        "maps": env["baseer.noorix.rehearsal.source.map"].sudo().search_count([]),
        "products": env["product.template"].sudo().with_context(active_test=False).search_count([]),
        "moves": env["account.move"].sudo().search_count([]),
        "payments": env["account.payment"].sudo().search_count([]),
        "partials": env["account.partial.reconcile"].sudo().search_count([]),
    }


before = counts()
if before["run"]:
    raise UserError("Idempotency probe requires a never-run purchase scope: %s" % RUN_KEY)

first_result = second_result = between = after_second = None
try:
    with env.cr.savepoint():
        first_result = replay_writer.apply_purchase_month(env, SOURCE_COMPANY_ID, MONTH)
        between = counts()
        second_result = replay_writer.apply_purchase_month(env, SOURCE_COMPANY_ID, MONTH)
        after_second = counts()
        if between != after_second:
            raise UserError("Idempotent replay created records: first=%s second=%s" % (between, after_second))
        if first_result != second_result:
            raise UserError("Idempotent replay result differs")
        raise UserError("NOORIX_TEST_ROLLBACK_AFTER_IDEMPOTENT_REPLAY")
except UserError as error:
    if "NOORIX_TEST_ROLLBACK_AFTER_IDEMPOTENT_REPLAY" not in str(error):
        raise

env.invalidate_all()
after = counts()
if before != after:
    raise UserError("Idempotency rollback invariant failed: before=%s after=%s" % (before, after))

print(json.dumps({
    "status": "ok",
    "first_result": first_result,
    "second_result": second_result,
    "counts_after_first": between,
    "counts_after_replay": after_second,
    "before": before,
    "after_outer_rollback": after,
    "invariants": ["replay_no_new_records", "same_result", "outer_rollback_no_run_or_financial_rows"],
}, sort_keys=True))
