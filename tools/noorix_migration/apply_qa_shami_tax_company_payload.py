"""Create the approved SHAMI TAX company and link its exact-VAT supplier in QA only."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from odoo import Command, fields
from odoo.exceptions import UserError


PAYLOAD_PATH = Path("/mnt/noorix-payload/runs/20260913-shami-tax-company-master-qa-1/shami-tax-company-payload.json")
RUN_NAME = "20260913-shami-tax-company-master-qa-1"
EXPECTED_SHA256 = "30ec8f89c4e25a703e3b52d1fe06c110c47de11f5dd230687f3ad9a24db9ab35"
TARGET_DATABASE = "baseer_noorix_data_migration_qa_20260912"
WRITER_CONTEXT = "baseer_noorix_migration_writer"


def fail(message):
    raise UserError("Noorix QA SHAMI TAX company migration: %s" % message)


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
require(payload["run_name"] == RUN_NAME, "run identity mismatch")
require(payload["report"] == {"source_company_maps": 1, "new_companies": 1, "reused_global_suppliers": 1, "reused_existing_supplier_maps": 1}, "report differs from approved scope")
company_row = payload["company"]
supplier_row = payload["supplier"]
require(company_row["decision"] == "create_active_company" and company_row["target_company_name"] == "SHAMI TAX", "company decision differs")
require(supplier_row["decision"] == "existing_global_vat", "supplier decision differs")

Run = writer_model("baseer.noorix.migration.run")
CompanyMap = writer_model("baseer.noorix.company.map")
SupplierMap = writer_model("baseer.noorix.supplier.map")
Company = env["res.company"].sudo().with_context(active_test=False)
Partner = env["res.partner"].sudo().with_context(active_test=False)

env.cr.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ["%s:noorix-shami-tax-company" % env.cr.dbname])
existing = Run.search([("name", "=", RUN_NAME)], limit=1)
if existing:
    require(existing.payload_sha256 == payload_sha256 and existing.state in {"committed", "reconciled"}, "existing run conflicts")
    company_map = CompanyMap.search([("run_id", "=", existing.id)])
    supplier_map = SupplierMap.search([("source_system", "=", supplier_row["source_system"]), ("source_tenant_id", "=", supplier_row["source_tenant_id"]), ("source_company_id", "=", supplier_row["source_company_id"]), ("source_supplier_id", "=", supplier_row["source_supplier_id"])])
    require(len(company_map) == 1 and len(supplier_map) == 1, "committed map cardinality differs")
    company = company_map.company_id
    partner = supplier_map.partner_id
    require(company.active and company.country_id.code == "SA" and company.currency_id.name == "SAR", "committed company differs")
    # Noorix stores this identity in both language columns even though it is an
    # English-only label.  Preserve one bilingual identity in Odoo without
    # displaying the same text twice.
    if company.name != "SHAMI TAX":
        require(company.name == "SHAMI TAX | SHAMI TAX" and company.baseer_name_ar == "SHAMI TAX" and company.baseer_name_en == "SHAMI TAX", "committed company name differs")
        require(not env["account.move"].sudo().search_count([("company_id", "=", company.id)]) and not env["stock.move"].sudo().search_count([("company_id", "=", company.id)]), "cannot normalize an already-posted company identity")
        company.write({"baseer_name_ar": False, "baseer_name_en": "SHAMI TAX"})
        require(company.name == "SHAMI TAX", "company name normalization failed")
    require(partner.id == supplier_row["target_partner_id"] and partner.vat == supplier_row["target_vat"] and not partner.company_id and not partner.parent_id and partner.supplier_rank >= 1, "committed global supplier differs")
    print(json.dumps({"status": "already_committed", "run_id": existing.id, "company_id": company.id, "supplier_id": partner.id, "supplier_name": partner.name}, ensure_ascii=False, sort_keys=True))
    env.cr.commit()
else:
    require(not CompanyMap.search([("source_system", "=", company_row["source_system"]), ("source_tenant_id", "=", company_row["source_tenant_id"]), ("source_company_id", "=", company_row["source_company_id"])]), "source company is already mapped")
    supplier_map = SupplierMap.search([("source_system", "=", supplier_row["source_system"]), ("source_tenant_id", "=", supplier_row["source_tenant_id"]), ("source_company_id", "=", supplier_row["source_company_id"]), ("source_supplier_id", "=", supplier_row["source_supplier_id"])])
    require(len(supplier_map) == 1, "the existing source supplier mapping is missing or ambiguous")
    require(not Company.search([("name", "=", "SHAMI TAX")], limit=1), "SHAMI TAX already exists without approved provenance")
    country = env["res.country"].sudo().search([("code", "=", "SA")], limit=1)
    currency = env["res.currency"].sudo().search([("name", "=", "SAR")], limit=1)
    require(country and currency and country.currency_id == currency, "Saudi country/currency reference unavailable")
    partner = Partner.browse(supplier_row["target_partner_id"]).exists()
    require(partner and partner.vat == supplier_row["target_vat"] and not partner.company_id and not partner.parent_id and partner.active and partner.supplier_rank >= 1, "approved global supplier is no longer valid")
    require(supplier_map.partner_id == partner and supplier_map.source_archive_sha256 == payload["source_archive_sha256"] and supplier_map.canonical_key == supplier_row["canonical_key"] and supplier_map.decision == supplier_row["existing_mapping_decision"] and supplier_map.run_id.name == supplier_row["existing_mapping_run_name"] and supplier_map.run_id.state in {"committed", "reconciled"}, "existing supplier provenance does not match the approved exact-VAT link")
    before_moves = env["account.move"].sudo().search_count([])
    before_stock = env["stock.move"].sudo().search_count([])
    company = Company.create({"name": "SHAMI TAX", "baseer_name_ar": False, "baseer_name_en": "SHAMI TAX", "country_id": country.id, "currency_id": currency.id, "active": True})
    if company not in env.user.company_ids:
        env.user.sudo().write({"company_ids": [Command.link(company.id)]})
    company._baseer_prepare_accounting()
    require(company.chart_template == "sa", "Saudi chart was not initialized")
    require(env["account.move"].sudo().search_count([]) == before_moves, "company setup created accounting moves")
    require(env["stock.move"].sudo().search_count([]) == before_stock, "company setup created stock moves")
    run = Run.create({"name": RUN_NAME, "source_archive_sha256": payload["source_archive_sha256"], "source_tenant_id": company_row["source_tenant_id"], "payload_sha256": payload_sha256, "scope": "company_master", "state": "planned", "started_at": fields.Datetime.now(), "result_json": json.dumps({"stage": "preflight_passed", "report": payload["report"]}, ensure_ascii=False, sort_keys=True)})
    CompanyMap.create({"source_system": company_row["source_system"], "source_tenant_id": company_row["source_tenant_id"], "source_company_id": company_row["source_company_id"], "source_row_sha256": company_row["source_row_sha256"], "source_archive_sha256": company_row["source_archive_sha256"], "canonical_key": company_row["canonical_key"], "decision": company_row["decision"], "company_id": company.id, "run_id": run.id})
    require(CompanyMap.search_count([("run_id", "=", run.id)]) == 1, "post-write company map cardinality differs")
    run.write({"state": "committed", "finished_at": fields.Datetime.now(), "result_json": json.dumps({"status": "committed", "company_id": company.id, "supplier_id": partner.id, "supplier_name": partner.name, "report": payload["report"]}, ensure_ascii=False, sort_keys=True)})
    env.cr.commit()
    print(json.dumps({"status": "committed", "run_id": run.id, "company_id": company.id, "supplier_id": partner.id, "supplier_name": partner.name}, ensure_ascii=False, sort_keys=True))
