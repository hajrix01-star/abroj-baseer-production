"""Forced-failure proof for one Noorix purchase replay wave.

Run only in a disposable/rehearsal Odoo shell after explicit test approval.
It deliberately raises immediately after the first native reconciliation, once
the writer has created its run, service product, vendor bill, payment, maps and
partial-reconciliation row.  The writer's own savepoint must roll every one of
those changes back even though this script catches the expected exception.

No commit is issued.  The probe refuses a wave that already has a run, so it
can never be used to overwrite or retest a committed financial wave.
"""

import json

from odoo.exceptions import UserError
from odoo.addons.baseer_noorix_rehearsal_replay import replay_writer


# ARZ March is the smallest chronological general-purchase wave.  Change both
# constants together only after a new approved source manifest and preflight.
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
    raise UserError("Rollback probe requires a never-run purchase scope: %s" % RUN_KEY)

original_reconcile = replay_writer._reconcile_purchase_payment
payment_after_reconciliation = {}


def forced_failure(env, company, document, settlement, invoice, payment):
    original_reconcile(env, company, document, settlement, invoice, payment)
    payment_after_reconciliation.update({
        "state": payment.state,
        "amount": payment.amount,
        "amount_signed": payment.amount_signed,
        "amount_company_currency_signed": payment.amount_company_currency_signed,
        "move_state": payment.move_id.state if payment.move_id else False,
        "is_reconciled": payment.is_reconciled,
        "invoice_payment_state": invoice.payment_state,
        "invoice_residual": invoice.amount_residual,
        "invoice_lines": [{
            "display_type": line.display_type,
            "product_id": line.product_id.id,
            "account_id": line.account_id.code,
            "price_unit": line.price_unit,
            "price_total": line.price_total,
        } for line in invoice.invoice_line_ids],
    })
    raise UserError("NOORIX_TEST_FORCED_FAILURE_AFTER_RECONCILIATION")


replay_writer._reconcile_purchase_payment = forced_failure
try:
    try:
        replay_writer.apply_purchase_month(env, SOURCE_COMPANY_ID, MONTH)
    except UserError as error:
        if "NOORIX_TEST_FORCED_FAILURE_AFTER_RECONCILIATION" not in str(error):
            raise
    else:
        raise UserError("Rollback probe did not force the expected failure")
finally:
    replay_writer._reconcile_purchase_payment = original_reconcile

env.invalidate_all()
after = counts()
if before != after:
    raise UserError("Atomic rollback invariant failed: before=%s after=%s" % (before, after))

print(json.dumps({
    "status": "ok",
    "forced_failure": "after_reconciliation",
    "before": before,
    "after": after,
    "payment_after_reconciliation": payment_after_reconciliation,
    "invariants": ["no_planned_run", "no_source_map", "no_product", "no_account_move", "no_payment", "no_partial_reconcile"],
}, sort_keys=True))
