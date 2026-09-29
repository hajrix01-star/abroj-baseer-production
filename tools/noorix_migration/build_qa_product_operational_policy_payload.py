"""Build the write-free QA payload for the Noorix product operating policy.

Run inside the isolated Noorix QA Odoo shell.  The script reads only immutable
product provenance and current target invariants, then writes a deterministic
JSON payload to ``/tmp`` for hashing and review before any policy write.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from odoo.exceptions import UserError


TARGET_DATABASE = "baseer_noorix_data_migration_qa_20260912"
SOURCE_ARCHIVE_SHA256 = "024606ADD82DCD78DC1835828A12D7B22C56E34924FF998ABF752134160E79E2"
OUTPUT_PATH = Path("/tmp/noorix-product-operational-policy.json")


def require(condition, message):
    if not condition:
        raise UserError("Noorix QA product-policy payload: %s" % message)


require(env.cr.dbname == TARGET_DATABASE, "wrong target database")
ProductMap = env["baseer.noorix.product.map"].sudo()
maps = ProductMap.search([])
require(len(maps) == 468, "product provenance baseline differs")

by_template = {}
for mapping in maps:
    by_template.setdefault(mapping.product_tmpl_id.id, []).append(mapping)
require(len(by_template) == 467, "canonical product target count differs")

rows = []
for template_id in sorted(by_template):
    template = env["product.template"].sudo().browse(template_id).exists()
    require(template and len(template.product_variant_ids) == 1, "mapped product variant invariant failed")
    if not template.purchase_ok:
        continue
    require(not template.sale_ok, "mapped purchase product is also sale-enabled")
    require(template.active and template.type == "consu", "mapped purchase product is not an active good")
    require(template.company_id.id in {1, 2}, "mapped purchase product has the wrong company")
    require(template.is_storable, "mapped purchase product is already non-storable before the policy run")
    source_maps = sorted(by_template[template_id], key=lambda row: (row.source_company_id, row.source_product_id))
    require(all(row.canonical_key == source_maps[0].canonical_key for row in source_maps), "canonical key differs inside one target")
    rows.append({
        "canonical_key": source_maps[0].canonical_key,
        "source_product_ids": [row.source_product_id for row in source_maps],
        "target_company_id": template.company_id.id,
        "target_product_tmpl_id": template.id,
        "target_product_id": template.product_variant_id.id,
        "previous_is_storable": True,
        "new_is_storable": False,
        "type": "consu",
        "purchase_ok": True,
        "sale_ok": False,
        "uom_id": template.uom_id.id,
    })

require(len(rows) == 364, "purchase product count differs")
report = {
    "mapped_canonical_products": 467,
    "mapped_source_product_rows": 468,
    "purchase_goods_policy_updates": len(rows),
    "company_1_updates": sum(row["target_company_id"] == 1 for row in rows),
    "company_2_updates": sum(row["target_company_id"] == 2 for row in rows),
    "sale_only_products_unchanged": 103,
    "expected_default_purchase_options": len(rows),
}
require(report["company_1_updates"] == 279 and report["company_2_updates"] == 85, "company split differs")

payload = {
    "schema_version": 1,
    "source_system": "noorix",
    "source_archive_sha256": SOURCE_ARCHIVE_SHA256,
    "target_database": TARGET_DATABASE,
    "policy": "company_purchase_goods_non_storable_with_default_procurement_option",
    "report": report,
    "products": rows,
}
payload_bytes = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
OUTPUT_PATH.write_bytes(payload_bytes)
print(json.dumps({
    "output": str(OUTPUT_PATH),
    "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
    "report": report,
}, ensure_ascii=False, sort_keys=True))
