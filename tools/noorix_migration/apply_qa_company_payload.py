"""Apply the approved Noorix company crosswalk to isolated QA only."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from odoo import Command, fields
from odoo.exceptions import UserError


PAYLOAD_PATH = Path("/mnt/noorix-payload/runs/20260913-company-master-qa-1/company-payload.json")
RUN_NAME = "20260913-noorix-company-master-qa-1"
EXPECTED_SHA256 = "b0c94a368a2f369c09bfd9195a7f78f0c8715f5bd33d1addda617b64924d5128"
ARCHIVE_SHA256 = "024606ADD82DCD78DC1835828A12D7B22C56E34924FF998ABF752134160E79E2"
TARGET_DATABASE = "baseer_noorix_data_migration_qa_20260912"
WRITER_CONTEXT = "baseer_noorix_migration_writer"
KARAK_ACTIVE_SOURCE = "cmnvui7x70001etuf8p6xz3d0"
KARAK_ARCHIVED_SOURCE = "cmnf5zx10005ky8lml9hx2rpq"


def fail(message):
    raise UserError("Noorix QA company migration: %s" % message)


def require(condition, message):
    if not condition:
        fail(message)


def writer_model(name):
    return env[name].sudo().with_context(**{WRITER_CONTEXT: True})


payload_bytes = PAYLOAD_PATH.read_bytes()
payload_sha256 = hashlib.sha256(payload_bytes).hexdigest()
require(payload_sha256 == EXPECTED_SHA256, "payload SHA-256 differs from the approved artifact")
payload = json.loads(payload_bytes.decode("utf-8"))
require(env.cr.dbname == TARGET_DATABASE and payload["target_database"] == TARGET_DATABASE, "target database mismatch")
require(payload["source_archive_sha256"] == ARCHIVE_SHA256, "source archive mismatch")
require(payload["run_name"] == RUN_NAME, "run identity mismatch")
require(payload["report"] == {
    "source_company_maps": 5,
    "reused_existing_companies": 3,
    "created_historical_companies": 1,
    "archived_source_aliases": 1,
    "excluded_test_companies": 2,
    "deferred_shami_tax_companies": 1,
}, "company report differs from the approved scope")
rows = payload["companies"]
require(len(rows) == 5 and len({row["source_company_id"] for row in rows}) == 5, "company rows are invalid")
require({row["decision"] for row in rows} == {
    "reuse_existing_company", "create_historical_company", "alias_archived_company",
}, "company decisions are incomplete")

Run = writer_model("baseer.noorix.migration.run")
CompanyMap = writer_model("baseer.noorix.company.map")
Company = env["res.company"].sudo().with_context(active_test=False)

env.cr.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ["%s:noorix-company-master" % env.cr.dbname])
existing = Run.search([("name", "=", RUN_NAME)], limit=1)
if existing:
    require(existing.payload_sha256 == payload_sha256 and existing.state in {"committed", "reconciled"}, "existing run conflicts")
    maps = CompanyMap.search([("run_id", "=", existing.id)])
    require(len(maps) == 5 and len(set(maps.mapped("source_company_id"))) == 5, "committed company map cardinality differs")
    expected = {row["source_company_id"]: row for row in rows}
    for mapping in maps:
        row = expected[mapping.source_company_id]
        require(
            mapping.source_row_sha256 == row["source_row_sha256"]
            and mapping.source_archive_sha256 == ARCHIVE_SHA256
            and mapping.canonical_key == row["canonical_key"]
            and mapping.decision == row["decision"]
            and mapping.company_id.exists(),
            "committed company provenance differs from payload",
        )
    karak = maps.filtered(lambda item: item.source_company_id == KARAK_ACTIVE_SOURCE).company_id
    require(karak and karak.active and karak.currency_id.name == "SAR" and karak.country_id.code == "SA", "historical Karak company is not migration-ready")
    print(json.dumps({"status": "already_committed", "run_id": existing.id, "company_maps": 5, "karak_company_id": karak.id}, ensure_ascii=False, sort_keys=True))
    env.cr.commit()
else:
    require(CompanyMap.search_count([]) == 0, "company provenance table is not empty before first run")
    require(Company.search_count([]) == 3, "QA company baseline differs from three protected companies")
    expected_existing = {"ARZ": 1, "المعلم الشامي": 2, "دوحة المستهلك": 3}
    targets = {}
    for name, expected_id in expected_existing.items():
        company = Company.search([("name", "=", name)], limit=1)
        require(company and company.id == expected_id and company.active, "existing company crosswalk differs: %s" % name)
        targets[name] = company
    require(not Company.search([("name", "ilike", "وقت الكرك")], limit=1), "Karak already exists without approved provenance")

    country = env["res.country"].sudo().search([("code", "=", "SA")], limit=1)
    currency = env["res.currency"].sudo().search([("name", "=", "SAR")], limit=1)
    require(country and currency and country.currency_id == currency, "Saudi country/currency reference is unavailable")
    source = next(row["source"] for row in rows if row["source_company_id"] == KARAK_ACTIVE_SOURCE)
    values = {
        "name": "وقت الكرك | Karak",
        "baseer_name_ar": "وقت الكرك",
        "baseer_name_en": source["source_name_en"] or "Karak",
        "country_id": country.id,
        "currency_id": currency.id,
        "active": True,
    }
    if source["source_phone"]:
        values["phone"] = source["source_phone"]
    if source["source_email"]:
        values["email"] = source["source_email"]
    if source["source_address"]:
        values["street"] = source["source_address"]
    if source["source_tax_number"]:
        values["vat"] = source["source_tax_number"]

    before_moves = env["account.move"].sudo().search_count([])
    before_stock = env["stock.move"].sudo().search_count([])
    karak = Company.create(values)
    if karak not in env.user.company_ids:
        env.user.sudo().write({"company_ids": [Command.link(karak.id)]})
    # Execute the registered fill-only preparation now so verification occurs
    # inside this transaction; the native precommit callback is idempotent.
    karak._baseer_prepare_accounting()
    require(karak.chart_template == "sa", "Saudi chart was not initialized for Karak")
    config = env["pos.config"].sudo().with_context(active_test=False).search([
        ("company_id", "=", karak.id), ("baseer_summary_only", "=", True),
    ], limit=1)
    require(config and config.active and config.baseer_summary_product_id and config.baseer_summary_tax_id, "Karak sales-summary setup is incomplete")
    require(config.baseer_summary_tax_id.amount == 15 and config.baseer_summary_tax_id.type_tax_use == "sale", "Karak sales tax is not 15%")
    require(env["account.move"].sudo().search_count([]) == before_moves, "company setup created accounting moves")
    require(env["stock.move"].sudo().search_count([]) == before_stock, "company setup created stock moves")

    run = Run.create({
        "name": RUN_NAME,
        "source_archive_sha256": ARCHIVE_SHA256,
        "source_tenant_id": "all-companies",
        "payload_sha256": payload_sha256,
        "scope": "company_master",
        "state": "planned",
        "started_at": fields.Datetime.now(),
        "result_json": json.dumps({"stage": "preflight_passed", "report": payload["report"]}, ensure_ascii=False, sort_keys=True),
    })
    target_by_key = {
        "company:arz": targets["ARZ"],
        "company:almoallem": targets["المعلم الشامي"],
        "company:doha": targets["دوحة المستهلك"],
        "company:karak": karak,
    }
    CompanyMap.create([{
        "source_system": row["source_system"],
        "source_tenant_id": row["source_tenant_id"],
        "source_company_id": row["source_company_id"],
        "source_row_sha256": row["source_row_sha256"],
        "source_archive_sha256": row["source_archive_sha256"],
        "canonical_key": row["canonical_key"],
        "decision": row["decision"],
        "company_id": target_by_key[row["canonical_key"]].id,
        "run_id": run.id,
    } for row in rows])
    maps = CompanyMap.search([("run_id", "=", run.id)])
    require(len(maps) == 5 and len(maps.filtered(lambda item: item.company_id == karak)) == 2, "post-write company provenance differs")
    result = {
        "status": "committed",
        "company_maps": 5,
        "reused_existing_companies": 3,
        "created_historical_companies": 1,
        "karak_company_id": karak.id,
        "karak_active_during_migration": True,
        "archive_after_all_domains": True,
        "karak_accounts": env["account.account"].sudo().search_count([("company_ids", "in", karak.ids)]),
        "karak_journals": env["account.journal"].sudo().search_count([("company_id", "=", karak.id)]),
        "karak_products": env["product.template"].sudo().with_context(active_test=False).search_count([("company_id", "=", karak.id)]),
        "karak_summary_config_id": config.id,
        "report": payload["report"],
    }
    run.write({"state": "committed", "finished_at": fields.Datetime.now(), "result_json": json.dumps(result, ensure_ascii=False, sort_keys=True)})
    env.cr.commit()
    print(json.dumps({"run_id": run.id, **result}, ensure_ascii=False, sort_keys=True))
