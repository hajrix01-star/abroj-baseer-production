"""Post approved Noorix sales summaries to isolated QA, one company wave at a time."""

from __future__ import annotations

import hashlib
import json
import os
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from odoo import Command, fields
from odoo.exceptions import UserError


PAYLOAD_PATH = Path("/mnt/noorix-payload/runs/20260913-sales-summary-qa-1/sales-summary-payload.json")
EXPECTED_SHA256 = "37738a854ef99ee05d87173b70f55b3ceb7524edeefca71c68483f9fe3264853"
ARCHIVE_SHA256 = "024606ADD82DCD78DC1835828A12D7B22C56E34924FF998ABF752134160E79E2"
TARGET_DATABASE = "baseer_noorix_data_migration_qa_20260912"
COMPANY_RUN_NAME = "20260913-noorix-company-master-qa-1"
WRITER_CONTEXT = "baseer_noorix_migration_writer"
ALLOWED_WAVES = {"arz", "almoallem", "doha", "karak"}
RUN_PREFIX = "20260913-noorix-sales-summary-qa"
CENT = Decimal("0.01")


def money(value):
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def fail(message):
    raise UserError("Noorix QA sales-summary migration: %s" % message)


def require(condition, message):
    if not condition:
        fail(message)


def writer_model(name, company=None):
    model = env[name].sudo().with_context(**{WRITER_CONTEXT: True})
    return model.with_company(company).with_context(allowed_company_ids=[company.id]) if company else model


def summary_totals(records):
    return {
        "summaries": len(records),
        "gross": format(sum((money(row.amount_gross) for row in records), Decimal("0.00")), ".2f"),
        "net": format(sum((money(row.amount_net) for row in records), Decimal("0.00")), ".2f"),
        "tax": format(sum((money(row.amount_tax) for row in records), Decimal("0.00")), ".2f"),
        "customers": sum(records.mapped("customer_count")),
        "allocations": len(records.allocation_ids),
        "sessions": len(records.session_id),
        "orders": len(records.order_id),
    }


wave_key = os.environ.get("NOORIX_SALES_WAVE", "").strip().lower()
require(wave_key in ALLOWED_WAVES, "NOORIX_SALES_WAVE must be one of %s" % ", ".join(sorted(ALLOWED_WAVES)))
run_name = "%s-%s-1" % (RUN_PREFIX, wave_key)

payload_bytes = PAYLOAD_PATH.read_bytes()
payload_sha256 = hashlib.sha256(payload_bytes).hexdigest()
require(payload_sha256 == EXPECTED_SHA256, "payload SHA-256 differs from the approved artifact")
payload = json.loads(payload_bytes.decode("utf-8"))
dry_run = os.environ.get("NOORIX_MIGRATION_DRY_RUN") == "1"
if dry_run:
    require(env.cr.dbname.startswith("baseer_noorix_sales_dry_run_"), "dry run database name is not isolated")
else:
    require(env.cr.dbname == TARGET_DATABASE, "target database mismatch")
require(payload["target_database"] == TARGET_DATABASE, "payload target database mismatch")
require(payload["source_archive_sha256"] == ARCHIVE_SHA256, "source archive mismatch")
require(payload["approved_policy"] == "gross_includes_15_percent_vat_and_arz_20260526_sources_merge_into_one_all_day_summary", "owner-approved policy differs")
require(payload["owner_decision_at"] == "2026-09-13", "owner decision date differs")

expected_report = payload["report"]["waves"][wave_key]
rows = [row for row in payload["summaries"] if row["wave_key"] == wave_key]
require(len(rows) == expected_report["summaries"], "payload summary count differs")
require(sum(len(row["source_rows"]) for row in rows) == expected_report["sources"], "payload source-map count differs")
require(sum((money(row["amount_gross"]) for row in rows), Decimal("0.00")) == money(expected_report["gross"]), "payload gross differs")
require(sum(row["customer_count"] for row in rows) == expected_report["customers"], "payload customer count differs")
require(len({row["canonical_key"] for row in rows}) == len(rows), "payload canonical keys are not unique")
source_rows = [source for row in rows for source in row["source_rows"]]
require(len({row["source_summary_id"] for row in source_rows}) == len(source_rows), "payload source IDs are not unique")
require(all(row["source_archive_sha256"] == ARCHIVE_SHA256 for row in source_rows), "payload source provenance differs")

company_ids = {row["target_company_id"] for row in rows}
source_company_ids = {row["source_company_id"] for row in rows}
config_ids = {row["target_config_id"] for row in rows}
require(len(company_ids) == len(source_company_ids) == len(config_ids) == 1, "wave must contain exactly one source company, target company and POS config")
company = env["res.company"].sudo().with_context(active_test=False).browse(company_ids.pop()).exists()
require(company and company.active and company.country_id.code == "SA" and company.currency_id.name == "SAR", "target company is not active Saudi/SAR")
source_company_id = source_company_ids.pop()
config_id = config_ids.pop()

env.cr.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ["%s:noorix-sales:%s" % (env.cr.dbname, wave_key)])
Run = writer_model("baseer.noorix.migration.run", company)
SalesMap = writer_model("baseer.noorix.sales.summary.map", company)
Summary = env["baseer.pos.summary"].sudo().with_company(company).with_context(
    allowed_company_ids=[company.id], lang="en_US", tz="Asia/Riyadh"
)
CompanyMap = writer_model("baseer.noorix.company.map", company)

company_mapping = CompanyMap.search([
    ("source_company_id", "=", source_company_id),
    ("run_id.name", "=", COMPANY_RUN_NAME),
    ("company_id", "=", company.id),
], limit=1)
require(company_mapping and company_mapping.source_archive_sha256 == ARCHIVE_SHA256, "approved company crosswalk is missing")

config = env["pos.config"].sudo().with_company(company).with_context(active_test=False, allowed_company_ids=[company.id]).browse(config_id).exists()
require(config and config.active and config.company_id == company and config.baseer_summary_only, "target summary POS config differs")
require(config.baseer_summary_tax_id.active and config.baseer_summary_tax_id.amount == 15 and config.baseer_summary_tax_id.type_tax_use == "sale", "target sales tax is not active 15%")
require(config.baseer_summary_product_id.active and config.baseer_summary_product_id.type == "service", "target summary product must be an active service")
allowed_methods = set(config.payment_method_ids.filtered(lambda method: method.active).ids)
payload_methods = {allocation["target_payment_method_id"] for row in rows for allocation in row["allocations"]}
require(payload_methods <= allowed_methods, "payload contains a payment method outside the company summary POS")
require(all(sum((money(line["amount"]) for line in row["allocations"]), Decimal("0.00")) == money(row["amount_gross"]) for row in rows), "allocation totals differ from gross")

existing = Run.search([("name", "=", run_name)], limit=1)
if existing:
    require(existing.payload_sha256 == payload_sha256 and existing.state == "reconciled", "existing run conflicts or is incomplete")
    maps = SalesMap.search([("run_id", "=", existing.id)])
    require(len(maps) == expected_report["sources"], "replayed source-map count differs")
    summaries = maps.summary_id
    require(len(summaries) == expected_report["summaries"], "replayed summary count differs")
    expected_sources = {row["source_summary_id"]: row for row in source_rows}
    for mapping in maps:
        source = expected_sources.get(mapping.source_summary_id)
        require(source and mapping.source_row_sha256 == source["source_row_sha256"] and mapping.source_archive_sha256 == ARCHIVE_SHA256, "replayed source provenance differs")
        require(mapping.canonical_key == source["canonical_key"] and mapping.decision == source["decision"], "replayed mapping decision differs")
        require(money(mapping.source_gross) == money(source["source_gross"]) and mapping.source_customers == source["source_customers"], "replayed source values differ")
    totals = summary_totals(summaries)
    require(totals["gross"] == format(money(expected_report["gross"]), ".2f") and totals["customers"] == expected_report["customers"], "replayed financial totals differ")
    require(all(row.state == "approved" and row.session_id.state == "closed" and row.order_id.state == "done" for row in summaries), "replayed native POS documents differ")
    print(json.dumps({"status": "already_reconciled", "run_id": existing.id, "wave": wave_key, **totals}, ensure_ascii=False, sort_keys=True))
    env.cr.commit()
else:
    require(not SalesMap.search([("source_summary_id", "in", [row["source_summary_id"] for row in source_rows])], limit=1), "a source summary is already mapped by another run")
    require(not Summary.search([("company_id", "=", company.id), ("external_reference", "in", [row["external_reference"] for row in rows])], limit=1), "a payload reference already exists without provenance")

    before = {
        "summaries": Summary.search_count([("company_id", "=", company.id)]),
        "sessions": env["pos.session"].sudo().search_count([("company_id", "=", company.id)]),
        "orders": env["pos.order"].sudo().search_count([("company_id", "=", company.id)]),
        "stock_moves": env["stock.move"].sudo().search_count([("company_id", "=", company.id)]),
        "pickings": env["stock.picking"].sudo().search_count([("company_id", "=", company.id)]),
    }
    run = Run.create({
        "name": run_name,
        "source_archive_sha256": ARCHIVE_SHA256,
        "source_tenant_id": source_rows[0]["source_tenant_id"],
        "payload_sha256": payload_sha256,
        "scope": "sales_summary",
        "state": "planned",
        "started_at": fields.Datetime.now(),
        "result_json": json.dumps({"stage": "preflight_passed", "wave": wave_key, "expected": expected_report}, ensure_ascii=False, sort_keys=True),
    })

    created = Summary.browse()
    created_by_key = {}
    for row in rows:
        summary = Summary.create({
            "company_id": company.id,
            "config_id": config.id,
            "business_date": fields.Date.to_date(row["business_date"]),
            "period_scope": row["period_scope"],
            "day_schedule": row["day_schedule"],
            "customer_count": row["customer_count"],
            "external_reference": row["external_reference"],
            "notes": row["notes"],
            "allocation_ids": [Command.create({
                "payment_method_id": line["target_payment_method_id"],
                "amount": line["amount"],
            }) for line in row["allocations"]],
        })
        summary.action_approve()
        created |= summary
        created_by_key[row["canonical_key"]] = summary

    SalesMap.create([{
        "source_system": source["source_system"],
        "source_tenant_id": source["source_tenant_id"],
        "source_company_id": source["source_company_id"],
        "source_summary_id": source["source_summary_id"],
        "source_row_sha256": source["source_row_sha256"],
        "source_archive_sha256": source["source_archive_sha256"],
        "canonical_key": source["canonical_key"],
        "source_gross": source["source_gross"],
        "source_customers": source["source_customers"],
        "business_date": fields.Date.to_date(source["business_date"]),
        "shift": source["shift"],
        "decision": source["decision"],
        "summary_id": created_by_key[source["canonical_key"]].id,
        "run_id": run.id,
    } for source in source_rows])

    created.invalidate_recordset()
    maps = SalesMap.search([("run_id", "=", run.id)])
    totals = summary_totals(created)
    require(len(created) == expected_report["summaries"] and len(maps) == expected_report["sources"], "post-write cardinality differs")
    require(totals["gross"] == format(money(expected_report["gross"]), ".2f"), "post-write gross differs")
    require(totals["customers"] == expected_report["customers"], "post-write customer count differs")
    require(money(totals["gross"]) == money(totals["net"]) + money(totals["tax"]), "post-write net plus tax differs from gross")
    require(totals["sessions"] == totals["orders"] == expected_report["summaries"], "native POS document count differs")
    require(all(row.state == "approved" and row.session_id.state == "closed" and row.order_id.state == "done" and not row.order_id.picking_ids for row in created), "native POS state or no-stock policy differs")
    after_stock_moves = env["stock.move"].sudo().search_count([("company_id", "=", company.id)])
    after_pickings = env["stock.picking"].sudo().search_count([("company_id", "=", company.id)])
    require(after_stock_moves == before["stock_moves"] and after_pickings == before["pickings"], "sales summary wave created stock activity")
    require(Summary.search_count([("company_id", "=", company.id)]) == before["summaries"] + expected_report["summaries"], "company summary delta differs")
    require(env["pos.session"].sudo().search_count([("company_id", "=", company.id)]) == before["sessions"] + expected_report["summaries"], "company session delta differs")
    require(env["pos.order"].sudo().search_count([("company_id", "=", company.id)]) == before["orders"] + expected_report["summaries"], "company order delta differs")

    result = {
        "status": "reconciled",
        "wave": wave_key,
        "company_id": company.id,
        "source_maps": len(maps),
        **totals,
        "stock_moves_delta": after_stock_moves - before["stock_moves"],
        "pickings_delta": after_pickings - before["pickings"],
        "vat_policy": "15_percent_included_in_gross",
    }
    run.write({"state": "reconciled", "finished_at": fields.Datetime.now(), "result_json": json.dumps(result, ensure_ascii=False, sort_keys=True)})
    env.cr.commit()
    print(json.dumps({"run_id": run.id, **result}, ensure_ascii=False, sort_keys=True))
