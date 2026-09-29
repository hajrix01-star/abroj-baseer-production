"""Karak March full-wave rollback and verifier proof.

Run only in the isolated rehearsal Odoo shell after an approved read-only
preflight.  The probe applies the three approved Karak March vendor bills,
runs the same scope again to exercise the no-write verifier, and then rolls
the outer savepoint back deliberately.  It never commits.

The scope includes the approved cashier-computer document asset override.  It
must remain a service product posting to account 106003 (``asset_fixed``),
without stock movement or an asset/depreciation lifecycle.
"""

import json

from odoo.exceptions import UserError
from odoo.addons.baseer_noorix_rehearsal_replay import replay_writer


SOURCE_COMPANY_ID = "cmnvui7x70001etuf8p6xz3d0"
MONTH = "2026-03"
RUN_KEY = "purchase:%s:%s" % (SOURCE_COMPANY_ID, MONTH)


def _optional_count(model):
    Model = env.get(model)
    return Model.sudo().search_count([]) if Model else None


def counts():
    return {
        "run": env["baseer.noorix.rehearsal.run"].sudo().search_count([("run_key", "=", RUN_KEY)]),
        "maps": env["baseer.noorix.rehearsal.source.map"].sudo().search_count([]),
        "products": env["product.template"].sudo().with_context(active_test=False).search_count([]),
        "moves": env["account.move"].sudo().search_count([]),
        "payments": env["account.payment"].sudo().search_count([]),
        "partials": env["account.partial.reconcile"].sudo().search_count([]),
        "stock_moves": _optional_count("stock.move"),
        "account_assets": _optional_count("account.asset"),
        "eh_assets": _optional_count("eh.asset"),
    }


def product_context_diagnostic():
    """Expose the company-property difference behind the Karak verifier test."""
    manifest = replay_writer.runtime_guard.load_source_manifest()
    contract = replay_writer._purchase_contract(manifest)
    document = next(
        row for row in contract["by_wave"][(SOURCE_COMPANY_ID, MONTH)]
        if row["_category"]["decision_product_code"] == "NOORIX-HIST-KARAK-REPAIRS"
    )
    company = replay_writer._company_by_source(env, SOURCE_COMPANY_ID)
    ambient_product = replay_writer._mapped_target(
        env, "purchase_category", replay_writer._category_identity(document),
        document["_category"]["source_row_sha256"], "product.template", "purchase category",
        document["_category"]["canonical_key"],
    )
    karak_product = replay_writer._mapped_target(
        env, "purchase_category", replay_writer._category_identity(document),
        document["_category"]["source_row_sha256"], "product.template", "purchase category",
        document["_category"]["canonical_key"], company=company,
    )
    expected_account = replay_writer._historical_service_account(env, company, document)

    def values(product):
        account = product.property_account_expense_id
        return {
            "product_id": product.id,
            "product_company_id": product.company_id.id,
            "type": product.type,
            "purchase_ok": product.purchase_ok,
            "sale_ok": product.sale_ok,
            "property_account_id": account.id,
            "property_account_code": account.code,
        }

    return {
        "shell_company_id": env.company.id,
        "karak_company_id": company.id,
        "expected_account_id": expected_account.id,
        "expected_account_code": expected_account.code,
        "ambient_product": values(ambient_product),
        "karak_product": values(karak_product),
    }


before = counts()
if before["run"]:
    raise UserError("Karak rollback probe requires a never-run scope: %s" % RUN_KEY)

first_result = second_result = between = after_second = context_diagnostic = None
try:
    with env.cr.savepoint():
        first_result = replay_writer.apply_purchase_month(env, SOURCE_COMPANY_ID, MONTH)
        expected_result = {"vendor_bills": 3, "payments": 3, "reconciliations": 3, "zero_residual": True}
        if any(first_result.get(key) != expected for key, expected in expected_result.items()):
            raise UserError("Karak March result differs: %s" % first_result)
        between = counts()
        expected_delta = {"run": 1, "maps": 12, "moves": 6, "payments": 3, "partials": 3}
        for key, expected in expected_delta.items():
            if between[key] - before[key] != expected:
                raise UserError("Karak March count delta differs for %s" % key)
        for key in ("stock_moves", "account_assets", "eh_assets"):
            if before[key] is not None and between[key] != before[key]:
                raise UserError("Karak cashier computer unexpectedly created %s" % key)
        context_diagnostic = product_context_diagnostic()
        if context_diagnostic["karak_product"]["property_account_id"] != context_diagnostic["expected_account_id"]:
            raise UserError("Karak product context invariant differs: %s" % context_diagnostic)
        second_result = replay_writer.apply_purchase_month(env, SOURCE_COMPANY_ID, MONTH)
        after_second = counts()
        if between != after_second:
            raise UserError("Karak idempotent replay created records: first=%s second=%s" % (between, after_second))
        if first_result != second_result:
            raise UserError("Karak idempotent replay result differs")
        raise UserError("NOORIX_TEST_ROLLBACK_KARAK_MARCH")
except UserError as error:
    if "NOORIX_TEST_ROLLBACK_KARAK_MARCH" not in str(error):
        raise

env.invalidate_all()
after = counts()
if before != after:
    raise UserError("Karak rollback invariant failed: before=%s after=%s" % (before, after))

print(json.dumps({
    "status": "ok",
    "first_result": first_result,
    "second_result": second_result,
    "counts_after_first": between,
    "counts_after_replay": after_second,
    "product_context_diagnostic": context_diagnostic,
    "before": before,
    "after_outer_rollback": after,
    "invariants": [
        "three_bills_three_payments_three_reconciliations",
        "cashier_computer_service_to_106003_asset_fixed",
        "no_stock_or_asset_lifecycle",
        "replay_no_new_records",
        "outer_rollback_no_run_or_financial_rows",
    ],
}, sort_keys=True))
