"""Apply the approved Noorix latest purchase costs to isolated QA only."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from odoo import fields
from odoo.exceptions import UserError


PAYLOAD_PATH = Path("/mnt/noorix-payload/runs/20260912-product-cost-qa-1/product-cost-payload.json")
RUN_NAME = "20260912-noorix-product-cost-qa-1"
EXPECTED_SHA256 = "f9894e12c31cd3e5d0408cf6880e7892800a4fc3496beaaff581bc6d07168d7c"
ARCHIVE_SHA256 = "024606ADD82DCD78DC1835828A12D7B22C56E34924FF998ABF752134160E79E2"
WRITER_CONTEXT = "baseer_noorix_migration_writer"
EXECUTED_WRITER_SHA256 = "cc341d23dc34797a6c8a89c710309303a00e0d895f2831b3abc571b83514d92d"
EXECUTION_ARTIFACT_SHA256 = "9c7cbe50e00d1c346ae6654fded1c3e15e024433016543caa3d96871d348cd9d"
REPLAY_VERIFIER_SHA256 = "186475520827e7fba72f73de9274cbe4e5b57238b9b0ffb52824b008903c61e7"
REPLAY_VERIFIER_ARTIFACT_SHA256 = "d2f881826440a07086083ebcf11146db683ccafb0cf6391125afbde8261a0bb2"


def fail(message):
    raise UserError("Noorix QA product-cost migration: %s" % message)


def require(condition, message):
    if not condition:
        fail(message)


def writer_model(name):
    return env[name].sudo().with_context(**{WRITER_CONTEXT: True})


payload_bytes = PAYLOAD_PATH.read_bytes()
payload_sha256 = hashlib.sha256(payload_bytes).hexdigest()
require(payload_sha256 == EXPECTED_SHA256, "payload SHA-256 does not match approved cost payload")
payload = json.loads(payload_bytes.decode("utf-8"))
require(payload["target_database"] == env.cr.dbname and payload["source_archive_sha256"] == ARCHIVE_SHA256, "payload target/source mismatch")
require(payload["report"] == {
    "source_latest_received_purchase_costs": 279,
    "excluded_zero_costs": 1,
    "avocado_alias_resolved_by_latest_effective_cost": 1,
    "target_cost_updates": 277,
    "company_1_cost_updates": 193,
    "company_2_cost_updates": 84,
    "excluded_purchase_without_cost": 86,
    "excluded_sale_without_sales_price": 103,
}, "payload report differs from approved scope")
require(len(payload["costs"]) == 277 and all(row["source_cost"] > 0 for row in payload["costs"]), "cost rows are invalid")

Run = writer_model("baseer.noorix.migration.run")
CostMap = writer_model("baseer.noorix.product.cost.map")
ProductMap = writer_model("baseer.noorix.product.map")
Product = writer_model("product.product")

env.cr.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ["%s:noorix-product-cost" % env.cr.dbname])
existing = Run.search([("name", "=", RUN_NAME)], limit=1)
if existing:
    require(existing.payload_sha256 == payload_sha256 and existing.state in {"committed", "reconciled"}, "existing run conflicts or is non-final")
    maps = CostMap.search([("run_id", "=", existing.id)])
    require(len(maps) == 277 and len({mapping.product_id.id for mapping in maps}) == 277, "committed cost map cardinality differs")
    expected = {row["source_price_history_id"]: row for row in payload["costs"]}
    require(len(expected) == 277 and set(maps.mapped("source_price_history_id")) == set(expected), "committed source history identities differ from payload")
    for mapping in maps:
        row = expected.get(mapping.source_price_history_id)
        require(row is not None, "committed source history is absent from payload")
        require(
            mapping.source_system == row["source_system"]
            and mapping.source_tenant_id == row["source_tenant_id"]
            and mapping.source_company_id == row["source_company_id"]
            and mapping.source_product_id == row["source_product_id"]
            and mapping.source_row_sha256 == row["source_row_sha256"]
            and mapping.source_archive_sha256 == row["source_archive_sha256"]
            and mapping.canonical_key == row["canonical_key"]
            and mapping.decision == row["decision"]
            and mapping.source_cost == row["source_cost"]
            and fields.Datetime.to_string(mapping.effective_at) == row["effective_at"]
            and mapping.product_id.id == row["target_product_id"]
            and mapping.product_id.company_id.id == row["target_company_id"],
            "committed cost provenance differs from payload",
        )
        product = mapping.product_id.with_company(mapping.product_id.company_id)
        require(product.active and product.purchase_ok and not product.sale_ok and product.standard_price == row["source_cost"], "committed product target differs from payload")
    prior_result = json.loads(existing.result_json or "{}")
    receipt = {
        "kind": "full_provenance_replay",
        "payload_sha256": payload_sha256,
        "executed_writer_sha256": EXECUTED_WRITER_SHA256,
        "execution_artifact_sha256": EXECUTION_ARTIFACT_SHA256,
        "replay_verifier_sha256": REPLAY_VERIFIER_SHA256,
        "replay_verifier_artifact_sha256": REPLAY_VERIFIER_ARTIFACT_SHA256,
        "cost_maps": len(maps),
    }
    receipts = prior_result.get("replay_receipts", [])
    matching_receipt = next((existing_receipt for existing_receipt in receipts if existing_receipt.get("kind") == receipt["kind"] and existing_receipt.get("payload_sha256") == payload_sha256), None)
    if matching_receipt is None:
        receipt["verified_at"] = fields.Datetime.to_string(fields.Datetime.now())
        receipts.append(receipt)
        prior_result["replay_receipts"] = receipts
        existing.write({"state": "reconciled", "result_json": json.dumps(prior_result, ensure_ascii=False, sort_keys=True)})
    elif any(matching_receipt.get(key) != value for key, value in receipt.items()):
        matching_receipt.update(receipt)
        existing.write({"state": "reconciled", "result_json": json.dumps(prior_result, ensure_ascii=False, sort_keys=True)})
    print(json.dumps({"status": "already_committed", "run_id": existing.id, "cost_maps": len(maps), "full_provenance_replay": True}, ensure_ascii=False, sort_keys=True))
    env.cr.commit()
else:
    require(CostMap.search_count([]) == 0, "cost provenance table is not empty")
    require(ProductMap.search_count([]) == 468, "product provenance baseline differs")
    require("stock.valuation.layer" not in env.registry.models, "QA stock valuation layer is present; cost writer is blocked")
    Move = env["account.move"].sudo() if "account.move" in env.registry.models else None
    before_account_move_count = Move.search_count([]) if Move else None

    before_costs = {}
    targets = {}
    for row in payload["costs"]:
        product = Product.browse(row["target_product_id"]).exists()
        require(product and product.company_id.id == row["target_company_id"], "target product company differs from payload")
        product_map = ProductMap.search([("source_company_id", "=", row["source_company_id"]), ("source_product_id", "=", row["canonical_key"].rsplit(":", 1)[-1])], limit=1)
        require(product_map and product_map.product_tmpl_id.product_variant_id.id == product.id, "target product provenance differs")
        require(product.purchase_ok and not product.sale_ok and product.active, "target product is not a purchase-only active product")
        require(product.with_company(product.company_id).standard_price == 0, "target product already has a cost")
        before_costs[product.id] = 0
        targets[row["source_price_history_id"]] = product

    run = Run.create({
        "name": RUN_NAME,
        "source_archive_sha256": ARCHIVE_SHA256,
        "source_tenant_id": "all-companies",
        "payload_sha256": payload_sha256,
        "scope": "product_cost",
        "state": "planned",
        "started_at": fields.Datetime.now(),
        "result_json": json.dumps({"stage": "preflight_passed", "report": payload["report"]}, ensure_ascii=False, sort_keys=True),
    })
    CostMap.create([{
        key: value for key, value in row.items() if key not in {"target_product_id", "target_company_id"}
    } | {
        "product_id": targets[row["source_price_history_id"]].id,
        "run_id": run.id,
    } for row in payload["costs"]])
    for row in payload["costs"]:
        product = targets[row["source_price_history_id"]]
        product.with_company(product.company_id).write({"standard_price": row["source_cost"]})

    maps = CostMap.search([("run_id", "=", run.id)])
    require(len(maps) == 277 and len({mapping.product_id.id for mapping in maps}) == 277, "post-write cost-map mismatch")
    require(all(mapping.product_id.with_company(mapping.product_id.company_id).standard_price == mapping.source_cost > 0 for mapping in maps), "post-write cost mismatch")
    require(all(before_costs[mapping.product_id.id] == 0 for mapping in maps), "pre-write cost changed unexpectedly")
    env.flush_all()
    after_account_move_count = Move.search_count([]) if Move else None
    require(Move is None or after_account_move_count == before_account_move_count,
            "cost write changed accounting moves: before=%s after=%s" % (before_account_move_count, after_account_move_count))
    result = {"status": "committed", "cost_maps": 277, "company_1_cost_updates": 193, "company_2_cost_updates": 84, "report": payload["report"]}
    run.write({"state": "committed", "finished_at": fields.Datetime.now(), "result_json": json.dumps(result, ensure_ascii=False, sort_keys=True)})
    env.cr.commit()
    print(json.dumps({"run_id": run.id, **result}, ensure_ascii=False, sort_keys=True))
