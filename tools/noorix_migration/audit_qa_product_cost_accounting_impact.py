import hashlib
import json
from pathlib import Path

from odoo import fields
from odoo.exceptions import UserError


PAYLOAD_PATH = Path("/mnt/noorix-payload/runs/20260912-product-cost-qa-1/product-cost-payload.json")
EXPECTED_SHA256 = "f9894e12c31cd3e5d0408cf6880e7892800a4fc3496beaaff581bc6d07168d7c"
WRITER_CONTEXT = "baseer_noorix_migration_writer"


class _RollbackProbe(Exception):
    pass


def require(condition, message):
    if not condition:
        raise UserError(f"Noorix QA product-cost accounting-impact audit: {message}")


raw = PAYLOAD_PATH.read_bytes()
require(hashlib.sha256(raw).hexdigest() == EXPECTED_SHA256, "payload checksum mismatch")
payload = json.loads(raw)
require(len(payload["costs"]) == 277, "approved-cost count mismatch")
require("account.move" in env.registry.models, "account.move is unavailable for the accounting-impact audit")

Move = env["account.move"].sudo()
Product = env["product.product"].sudo().with_context(**{WRITER_CONTEXT: True})
Run = env["baseer.noorix.migration.run"].sudo().with_context(**{WRITER_CONTEXT: True})
CostMap = env["baseer.noorix.product.cost.map"].sudo().with_context(**{WRITER_CONTEXT: True})
ProductMap = env["baseer.noorix.product.map"].sudo().with_context(**{WRITER_CONTEXT: True})
base_move_count = Move.search_count([])
results = []

for row in payload["costs"]:
    product = Product.browse(row["target_product_id"]).exists()
    require(product and product.company_id.id == row["target_company_id"], "target product differs from payload")
    company_product = product.with_company(product.company_id)
    before_move_count = Move.search_count([])
    before_cost = company_product.standard_price
    try:
        with env.cr.savepoint():
            company_product.write({"standard_price": row["source_cost"]})
            env.flush_all()
            move_delta = Move.search_count([]) - before_move_count
            raise _RollbackProbe()
    except _RollbackProbe:
        pass
    env.invalidate_all()
    product_after = Product.browse(row["target_product_id"]).exists().with_company(product.company_id)
    require(product_after.standard_price == before_cost, "savepoint failed to restore product cost")
    require(Move.search_count([]) == before_move_count, "savepoint failed to restore accounting moves")
    results.append({
        "source_price_history_id": row["source_price_history_id"],
        "target_product_id": row["target_product_id"],
        "company_id": row["target_company_id"],
        "name": product_after.name,
        "category": product_after.categ_id.name,
        "cost": row["source_cost"],
        "account_move_delta": move_delta,
    })

require(Move.search_count([]) == base_move_count, "audit changed the accounting-move baseline")
blocked = [result for result in results if result["account_move_delta"]]
safe = [result for result in results if not result["account_move_delta"]]
try:
    with env.cr.savepoint():
        for row in payload["costs"]:
            product = Product.browse(row["target_product_id"]).exists()
            product.with_company(product.company_id).write({"standard_price": row["source_cost"]})
        env.flush_all()
        batch_account_move_delta = Move.search_count([]) - base_move_count
        raise _RollbackProbe()
except _RollbackProbe:
    pass
env.invalidate_all()
require(Move.search_count([]) == base_move_count, "batch savepoint failed to restore accounting moves")
try:
    with env.cr.savepoint():
        run = Run.create({
            "name": "20260912-noorix-product-cost-probe",
            "source_archive_sha256": payload["source_archive_sha256"],
            "source_tenant_id": "all-companies",
            "payload_sha256": EXPECTED_SHA256,
            "scope": "product_cost",
            "state": "planned",
        })
        CostMap.create([{
            key: value for key, value in row.items() if key not in {"target_product_id", "target_company_id"}
        } | {
            "product_id": row["target_product_id"],
            "run_id": run.id,
        } for row in payload["costs"]])
        for row in payload["costs"]:
            product = Product.browse(row["target_product_id"]).exists()
            product.with_company(product.company_id).write({"standard_price": row["source_cost"]})
        env.flush_all()
        full_batch_account_move_delta = Move.search_count([]) - base_move_count
        raise _RollbackProbe()
except _RollbackProbe:
    pass
env.invalidate_all()
require(Move.search_count([]) == base_move_count, "full batch savepoint failed to restore accounting moves")
exact_targets = {}
for row in payload["costs"]:
    product = Product.browse(row["target_product_id"]).exists()
    product_map = ProductMap.search([("source_company_id", "=", row["source_company_id"]), ("source_product_id", "=", row["canonical_key"].rsplit(":", 1)[-1])], limit=1)
    require(product_map and product_map.product_tmpl_id.product_variant_id.id == product.id, "target product provenance differs")
    exact_targets[row["source_price_history_id"]] = product
try:
    with env.cr.savepoint():
        run = Run.create({
            "name": "20260912-noorix-product-cost-qa-1",
            "source_archive_sha256": payload["source_archive_sha256"],
            "source_tenant_id": "all-companies",
            "payload_sha256": EXPECTED_SHA256,
            "scope": "product_cost",
            "state": "planned",
            "started_at": fields.Datetime.now(),
            "result_json": json.dumps({"stage": "preflight_passed", "report": payload["report"]}, ensure_ascii=False, sort_keys=True),
        })
        CostMap.create([{
            key: value for key, value in row.items() if key not in {"target_product_id", "target_company_id"}
        } | {
            "product_id": exact_targets[row["source_price_history_id"]].id,
            "run_id": run.id,
        } for row in payload["costs"]])
        for row in payload["costs"]:
            product = exact_targets[row["source_price_history_id"]]
            product.with_company(product.company_id).write({"standard_price": row["source_cost"]})
        maps = CostMap.search([("run_id", "=", run.id)])
        require(len(maps) == 277 and len({mapping.product_id.id for mapping in maps}) == 277, "probe cost map mismatch")
        require(all(mapping.product_id.with_company(mapping.product_id.company_id).standard_price == mapping.source_cost > 0 for mapping in maps), "probe cost mismatch")
        env.flush_all()
        exact_writer_account_move_delta = Move.search_count([]) - base_move_count
        raise _RollbackProbe()
except _RollbackProbe:
    pass
env.invalidate_all()
require(Move.search_count([]) == base_move_count, "exact writer savepoint failed to restore accounting moves")
print(json.dumps({
    "status": "audited_without_commit",
    "base_account_move_count": base_move_count,
    "candidates": len(results),
    "safe_without_accounting_move": len(safe),
    "requires_accounting_move": len(blocked),
    "requires_accounting_move_rows": blocked,
    "batch_account_move_delta": batch_account_move_delta,
    "full_batch_account_move_delta": full_batch_account_move_delta,
    "exact_writer_account_move_delta": exact_writer_account_move_delta,
}, ensure_ascii=False, sort_keys=True))
env.cr.commit()
