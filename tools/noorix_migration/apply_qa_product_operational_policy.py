"""Apply the owner-approved Noorix product operating policy to isolated QA.

The SHA-pinned payload changes only mapped purchase goods from tracked goods to
non-storable goods and creates their internal default procurement options.  It
is advisory-locked, atomic and idempotent.  It never targets ``baseer_dev``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from odoo import fields
from odoo.exceptions import UserError


PAYLOAD_PATH = Path(
    "/mnt/noorix-payload/runs/20260912-product-operational-policy-qa-1/"
    "product-operational-policy-payload.json"
)
RUN_NAME = "20260912-noorix-product-operational-policy-qa-1"
EXPECTED_PAYLOAD_SHA256 = "7a9062e4a099b37ad79651b7bb035b7c14c61bd6d0dd3c44187a616a460e8374"
SOURCE_ARCHIVE_SHA256 = "024606ADD82DCD78DC1835828A12D7B22C56E34924FF998ABF752134160E79E2"
TARGET_DATABASE = "baseer_noorix_data_migration_qa_20260912"
WRITER_CONTEXT = "baseer_noorix_migration_writer"


def fail(message):
    raise UserError("Noorix QA product-policy migration: %s" % message)


def require(condition, message):
    if not condition:
        fail(message)


def writer_model(name):
    return env[name].sudo().with_context(**{WRITER_CONTEXT: True})


def default_option_for(row):
    return env["baseer.procurement.purchase.option"].sudo().search([
        ("company_id", "=", row["target_company_id"]),
        ("product_id", "=", row["target_product_id"]),
        ("uom_id", "=", row["uom_id"]),
        ("packaging_note", "in", [False, ""]),
        ("active", "=", True),
    ])


payload_bytes = PAYLOAD_PATH.read_bytes()
payload_sha256 = hashlib.sha256(payload_bytes).hexdigest()
require(env.cr.dbname == TARGET_DATABASE, "wrong target database")
require(payload_sha256 == EXPECTED_PAYLOAD_SHA256, "payload SHA-256 mismatch")
payload = json.loads(payload_bytes.decode("utf-8"))
require(payload["source_archive_sha256"] == SOURCE_ARCHIVE_SHA256, "source archive mismatch")
require(payload["target_database"] == TARGET_DATABASE, "payload targets another database")
require(payload["policy"] == "company_purchase_goods_non_storable_with_default_procurement_option", "policy differs")
require(payload["report"] == {
    "mapped_canonical_products": 467,
    "mapped_source_product_rows": 468,
    "purchase_goods_policy_updates": 364,
    "company_1_updates": 279,
    "company_2_updates": 85,
    "sale_only_products_unchanged": 103,
    "expected_default_purchase_options": 364,
}, "payload report differs")
rows = payload["products"]
require(len(rows) == 364, "policy row count differs")

Run = writer_model("baseer.noorix.migration.run")
ProductMap = writer_model("baseer.noorix.product.map")
Template = env["product.template"].sudo()
Product = env["product.product"].sudo()
Option = env["baseer.procurement.purchase.option"].sudo()

env.cr.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ["%s:noorix-product-operational-policy" % env.cr.dbname])
existing = Run.search([("name", "=", RUN_NAME)], limit=1)

expected_template_ids = {row["target_product_tmpl_id"] for row in rows}
expected_product_ids = {row["target_product_id"] for row in rows}
require(len(expected_template_ids) == len(expected_product_ids) == 364, "duplicate policy target")
require(ProductMap.search_count([]) == 468, "product provenance baseline differs")
mapped_template_ids = set(ProductMap.search([]).product_tmpl_id.ids)
require(expected_template_ids < mapped_template_ids, "policy targets are not the purchase subset of mapped products")

for row in rows:
    template = Template.browse(row["target_product_tmpl_id"]).exists()
    product = Product.browse(row["target_product_id"]).exists()
    require(template and product and product.product_tmpl_id == template, "target identity differs")
    require(template.company_id.id == row["target_company_id"] in {1, 2}, "target company differs")
    require(template.active and template.type == "consu" and template.purchase_ok and not template.sale_ok, "target is not an active purchase good")
    require(template.uom_id.id == row["uom_id"], "target inventory unit differs")
    source_maps = ProductMap.search([("product_tmpl_id", "=", template.id)])
    require(source_maps and set(source_maps.mapped("source_product_id")) == set(row["source_product_ids"]), "source product lineage differs")
    require(all(mapping.canonical_key == row["canonical_key"] for mapping in source_maps), "canonical lineage differs")

if existing:
    require(existing.payload_sha256 == payload_sha256 and existing.scope == "product_operational_policy", "existing run identity differs")
    require(existing.state in {"committed", "reconciled"}, "existing run is not final")
    require(not Template.browse(sorted(expected_template_ids)).filtered("is_storable"), "replayed policy flag differs")
    for row in rows:
        options = default_option_for(row)
        require(len(options) == 1, "replayed default option differs")
    print(json.dumps({"status": "already_reconciled", "run_id": existing.id, "policy_products": 364}, sort_keys=True))
    env.cr.commit()
else:
    templates = Template.browse(sorted(expected_template_ids))
    products = Product.browse(sorted(expected_product_ids))
    require(len(templates) == len(products) == 364, "target record count differs")
    require(not templates.filtered(lambda item: not item.is_storable), "a target was already non-storable")
    require(Option.search_count([("product_id", "in", products.ids)]) == 0, "a mapped purchase product already has a procurement option")
    require(env["baseer.procurement.request.line"].sudo().search_count([
        ("option_id.product_id", "in", products.ids),
    ]) == 0, "a mapped purchase product already has a procurement request")
    require(env["stock.quant"].sudo().search_count([("product_id", "in", products.ids)]) == 0, "a target has stock quants")
    require(env["stock.move"].sudo().search_count([("product_id", "in", products.ids)]) == 0, "a target has stock moves")

    Move = env["account.move"].sudo()
    ProductValue = env["product.value"].sudo() if "product.value" in env.registry.models else None
    before_account_moves = Move.search_count([])
    before_product_values = ProductValue.search_count([]) if ProductValue is not None else None
    before_product_value_ids = set(ProductValue.search([]).ids) if ProductValue is not None else set()
    before_stock_moves = env["stock.move"].sudo().search_count([])
    before_quants = env["stock.quant"].sudo().search_count([])

    run = Run.create({
        "name": RUN_NAME,
        "source_archive_sha256": SOURCE_ARCHIVE_SHA256,
        "source_tenant_id": "all-companies",
        "payload_sha256": payload_sha256,
        "scope": "product_operational_policy",
        "state": "planned",
        "started_at": fields.Datetime.now(),
        "result_json": json.dumps({"stage": "preflight_passed", "report": payload["report"]}, sort_keys=True),
    })

    templates.write({"is_storable": False})
    for company_id in (1, 2):
        company = env["res.company"].sudo().browse(company_id)
        company_products = products.filtered(lambda item: item.company_id == company)
        request_model = env["baseer.procurement.request"].sudo().with_company(company)
        request_model._default_options_for_products(company_products)

    env.flush_all()
    require(not templates.filtered("is_storable"), "post-write tracking flag differs")
    for row in rows:
        options = default_option_for(row)
        require(len(options) == 1, "default procurement option count differs")
        expected_opening_price = Product.browse(row["target_product_id"]).with_company(
            env["res.company"].browse(row["target_company_id"])
        ).standard_price
        require(options.last_price == expected_opening_price and not options.last_price_at, "default opening price differs")
    require(Move.search_count([]) == before_account_moves, "policy changed accounting moves")
    after_product_value_ids = set(ProductValue.search([]).ids) if ProductValue is not None else set()
    unexpected_product_values = ProductValue.browse(sorted(after_product_value_ids - before_product_value_ids)) if ProductValue is not None else None
    removed_product_value_ids = sorted(before_product_value_ids - after_product_value_ids)
    if (unexpected_product_values is not None and unexpected_product_values) or removed_product_value_ids:
        print(json.dumps({
            "unexpected_product_values": unexpected_product_values.read([
                "product_id", "company_id", "value", "description", "move_id", "lot_id",
            ])[:10],
            "product_value_before": before_product_values,
            "product_value_after": len(after_product_value_ids),
            "removed_product_value_count": len(removed_product_value_ids),
            "removed_product_value_sample_ids": removed_product_value_ids[:10],
        }, ensure_ascii=False, sort_keys=True, default=str))
    require(
        ProductValue is None or len(after_product_value_ids) == before_product_values,
        "policy changed product value history (%s -> %s; added %s; removed %s)" % (
            before_product_values,
            len(after_product_value_ids),
            len(unexpected_product_values),
            len(removed_product_value_ids),
        ),
    )
    require(env["stock.move"].sudo().search_count([]) == before_stock_moves, "policy changed stock moves")
    require(env["stock.quant"].sudo().search_count([]) == before_quants, "policy changed stock quants")

    result = {
        "status": "reconciled",
        "policy_products": 364,
        "company_1_updates": 279,
        "company_2_updates": 85,
        "default_options": 364,
        "account_move_delta": 0,
        "product_value_delta": 0,
        "stock_move_delta": 0,
        "stock_quant_delta": 0,
        "report": payload["report"],
    }
    run.write({
        "state": "reconciled",
        "finished_at": fields.Datetime.now(),
        "result_json": json.dumps(result, ensure_ascii=False, sort_keys=True),
    })
    env.cr.commit()
    print(json.dumps({"run_id": run.id, **result}, ensure_ascii=False, sort_keys=True))
