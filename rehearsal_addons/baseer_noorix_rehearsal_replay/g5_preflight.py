"""Run with `odoo shell --shell-file` on the isolated 18084 rehearsal only."""

import json
from types import SimpleNamespace

from odoo.exceptions import UserError
from odoo.addons.baseer_noorix_rehearsal_replay import replay_writer, runtime_guard


def _business_counts():
    return {
        "companies": env["res.company"].sudo().with_context(active_test=False).search_count([("active", "=", True)]),
        "partners": env["res.partner"].sudo().with_context(active_test=False).search_count([("active", "=", True)]),
        "products": env["product.template"].sudo().with_context(active_test=False).search_count([("active", "=", True)]),
        "moves": env["account.move"].sudo().search_count([]),
        "payments": env["account.payment"].sudo().search_count([]),
        "stock_moves": env["stock.move"].sudo().search_count([]),
        "pickings": env["stock.picking"].sudo().search_count([]),
    }


before = _business_counts()
expected_active_baseline = {
    "companies": 3,
    "partners": 77,
    "products": 37,
    "moves": 2,
    "payments": 1,
    "stock_moves": 0,
    "pickings": 0,
}
if before != expected_active_baseline:
    raise UserError("G5 rehearsal active baseline differs: %s" % before)
plan = replay_writer.plan(env)
after = _business_counts()
if before != after or plan["orm_writes"] != 0:
    raise UserError("G5 preflight must not change business records")

for forbidden in (runtime_guard.PRODUCTION_DATABASE, runtime_guard.QA_DATABASE, "another_database"):
    try:
        runtime_guard.assert_rehearsal_database(SimpleNamespace(cr=SimpleNamespace(dbname=forbidden)))
    except UserError:
        continue
    raise UserError("G5 guard did not reject %s" % forbidden)

print(json.dumps({"status": "ok", "before": before, "after": after, "plan": plan}, ensure_ascii=False, sort_keys=True))
