"""Prove full native purchase replay rollback after payment and reconciliation.

This rehearsal-only probe deliberately raises at the final run-commit point.
At that point ARZ March has created and posted both vendor bills, both payments
and both native reconciliations.  The enclosing writer savepoint must then
remove every record, including provenance and the planned run.  It never
commits and refuses a scope that was previously run.
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
        "stock_moves": env["stock.move"].sudo().search_count([]),
        "pickings": env["stock.picking"].sudo().search_count([]),
    }


before = counts()
if before["run"]:
    raise UserError("Post-reconcile rollback probe requires a never-run purchase scope: %s" % RUN_KEY)

observed = {"invoices": [], "payments": [], "reconciliations": []}
original_create_invoice = replay_writer._create_purchase_invoice
original_create_payment = replay_writer._create_purchase_payment
original_reconcile = replay_writer._reconcile_purchase_payment
original_commit_run = replay_writer._commit_run


def observe_invoice(*args, **kwargs):
    invoice = original_create_invoice(*args, **kwargs)
    observed["invoices"].append({
        "state": invoice.state,
        "total": invoice.amount_total,
    })
    return invoice


def observe_payment(*args, **kwargs):
    payment = original_create_payment(*args, **kwargs)
    observed["payments"].append({
        "state": payment.state,
        "move_state": payment.move_id.state,
        "amount": payment.amount,
    })
    return payment


def observe_reconciliation(*args, **kwargs):
    partial = original_reconcile(*args, **kwargs)
    invoice = args[-2]
    payment = args[-1]
    observed["reconciliations"].append({
        "amount": partial.amount,
        "invoice_paid": invoice.payment_state == "paid" and not invoice.amount_residual,
        "payment_reconciled": payment.is_reconciled,
    })
    return partial


def forced_failure(*args, **kwargs):
    if not (
        len(observed["invoices"]) == 2
        and len(observed["payments"]) == 2
        and len(observed["reconciliations"]) == 2
        and all(row["state"] == "posted" for row in observed["invoices"])
        and all(row["state"] == "paid" and row["move_state"] == "posted" for row in observed["payments"])
        and all(row["invoice_paid"] and row["payment_reconciled"] for row in observed["reconciliations"])
    ):
        raise UserError("Post-reconcile probe did not reach both native payments/reconciliations: %s" % observed)
    raise UserError("NOORIX_TEST_FORCED_FAILURE_AFTER_RECONCILIATION")


replay_writer._create_purchase_invoice = observe_invoice
replay_writer._create_purchase_payment = observe_payment
replay_writer._reconcile_purchase_payment = observe_reconciliation
replay_writer._commit_run = forced_failure
try:
    try:
        replay_writer.apply_purchase_month(env, SOURCE_COMPANY_ID, MONTH)
    except UserError as error:
        if "NOORIX_TEST_FORCED_FAILURE_AFTER_RECONCILIATION" not in str(error):
            raise
    else:
        raise UserError("Post-reconcile rollback probe did not force the expected failure")
finally:
    replay_writer._create_purchase_invoice = original_create_invoice
    replay_writer._create_purchase_payment = original_create_payment
    replay_writer._reconcile_purchase_payment = original_reconcile
    replay_writer._commit_run = original_commit_run

env.invalidate_all()
after = counts()
if before != after:
    raise UserError("Post-reconcile atomic rollback invariant failed: before=%s after=%s" % (before, after))

print(json.dumps({
    "status": "ok",
    "forced_failure": "after_payment_and_reconciliation",
    "observed_before_rollback": observed,
    "before": before,
    "after": after,
    "invariants": [
        "no_planned_run", "no_source_map", "no_product", "no_account_move",
        "no_payment", "no_partial_reconciliation", "no_stock_move", "no_picking",
    ],
}, sort_keys=True))
