"""Append the approved SHAMI TAX source-bank provenance map in QA only.

Run exclusively through the isolated QA Odoo shell.  It creates no journal or
account: the frozen payload permits only reuse of the existing native BNK1.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from odoo import fields
from odoo.exceptions import UserError


PAYLOAD_PATH = Path("/mnt/noorix-payload/runs/20260913-shami-tax-liquidity-qa-1/shami-tax-liquidity-payload.json")
EXPECTED_SHA256 = "59bb8bf1aff9aae08c02a3dc4e15a69bf8f757cd21b7e69c3914255c6f3ab160"
TARGET_DATABASE = "baseer_noorix_data_migration_qa_20260912"
WRITER_CONTEXT = "baseer_noorix_migration_writer"


def fail(message):
    raise UserError("Noorix QA SHAMI TAX liquidity migration: %s" % message)


def require(condition, message):
    if not condition:
        fail(message)


def writer_model(name):
    return env[name].sudo().with_context(**{WRITER_CONTEXT: True})


if "env" not in globals():
    raise RuntimeError("Run this entrypoint through the approved QA Odoo shell")


payload_bytes = PAYLOAD_PATH.read_bytes()
payload_sha256 = hashlib.sha256(payload_bytes).hexdigest()
require(payload_sha256 == EXPECTED_SHA256, "payload SHA-256 differs from approved artifact")
payload = json.loads(payload_bytes.decode("utf-8"))
vault = payload.get("vault") or {}
require(env.cr.dbname == TARGET_DATABASE and payload.get("target_database") == TARGET_DATABASE, "target database differs")
require(payload.get("schema_version") == 1 and payload.get("run_name") == "20260913-noorix-shami-tax-liquidity-qa-1", "run identity differs")
require(payload.get("approved_policy") == "reuse_existing_native_company_bank_for_exact_active_source_bank_vault", "policy differs")
require(payload.get("report") == {"source_vaults": 1, "mapped_vaults": 1, "source_purchase_documents": 36, "source_purchase_gross": "275480.0000"}, "report differs")
for key in ("source_system", "source_tenant_id", "source_company_id", "source_vault_id", "source_vault_type", "source_vault_name", "source_row_sha256", "source_archive_sha256", "canonical_key", "decision", "target_company_id", "target_journal_id", "target_journal_code", "target_journal_type", "target_liquidity_account_code"):
    require(vault.get(key) not in (None, ""), "vault field is missing: %s" % key)
require(vault["source_system"] == "noorix" and vault["source_company_id"] == "cmr3fd0y3000hycziou1o2c47", "source company differs")
require(vault["source_vault_id"] == "cmr3fd0z9001lycziqkw21grp" and vault["source_vault_type"] == "bank" and vault["source_vault_name"] == "بنك", "source vault differs")
require(vault["decision"] == "reuse_existing_liquidity" and vault["target_company_id"] == 5 and vault["target_journal_id"] == 82 and vault["target_journal_code"] == "BNK1" and vault["target_journal_type"] == "bank" and vault["target_liquidity_account_code"] == "101001", "target journal contract differs")

Run = writer_model("baseer.noorix.migration.run")
VaultMap = writer_model("baseer.noorix.liquidity.vault.map")
CompanyMap = writer_model("baseer.noorix.company.map")
Company = env["res.company"].sudo().with_context(active_test=False)
Journal = env["account.journal"].sudo().with_context(active_test=False)

try:
    env.cr.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ["%s:noorix-shami-tax-liquidity" % env.cr.dbname])
    company_map = CompanyMap.search([("source_system", "=", vault["source_system"]), ("source_tenant_id", "=", vault["source_tenant_id"]), ("source_company_id", "=", vault["source_company_id"])], limit=2)
    require(len(company_map) == 1 and company_map.company_id.id == vault["target_company_id"] and company_map.source_archive_sha256 == payload["source_archive_sha256"], "company provenance differs")
    company = Company.browse(vault["target_company_id"]).exists()
    require(company and company.active and company.country_id.code == "SA" and company.currency_id.name == "SAR", "target company differs")
    journal = Journal.browse(vault["target_journal_id"]).exists()
    require(journal and journal.active and journal.company_id == company and journal.code == vault["target_journal_code"] and journal.type == vault["target_journal_type"] and journal.default_account_id.with_company(company).code == vault["target_liquidity_account_code"], "native bank journal differs")
    manual = journal.outbound_payment_method_line_ids.filtered(lambda line: line.payment_method_id.code == "manual" and line.payment_account_id == journal.default_account_id)
    require(len(manual) == 1, "native bank journal needs exactly one mapped manual outbound method")
    existing_map = VaultMap.search([("source_system", "=", vault["source_system"]), ("source_tenant_id", "=", vault["source_tenant_id"]), ("source_company_id", "=", vault["source_company_id"]), ("source_vault_id", "=", vault["source_vault_id"])], limit=2)
    run = Run.search([("name", "=", payload["run_name"])], limit=2)
    require(len(run) <= 1 and len(existing_map) <= 1, "existing run or vault map is ambiguous")
    if run or existing_map:
        require(run and existing_map and run.state in {"committed", "reconciled"} and run.payload_sha256 == payload_sha256 and run.scope == "liquidity_map", "existing run/map state differs")
        expected = {"source_row_sha256": vault["source_row_sha256"], "source_archive_sha256": vault["source_archive_sha256"], "canonical_key": vault["canonical_key"], "decision": vault["decision"]}
        require(existing_map.company_id == company and existing_map.journal_id == journal and existing_map.source_vault_type == vault["source_vault_type"] and existing_map.source_vault_name == vault["source_vault_name"] and all(existing_map[key] == value for key, value in expected.items()) and existing_map.run_id == run, "existing map evidence differs")
        result = {"status": "already_committed", "run_id": run.id, "company_id": company.id, "journal_id": journal.id, "journal_code": journal.code}
    else:
        run = Run.create({"name": payload["run_name"], "source_archive_sha256": payload["source_archive_sha256"], "source_tenant_id": vault["source_tenant_id"], "payload_sha256": payload_sha256, "scope": "liquidity_map", "state": "planned", "started_at": fields.Datetime.now(), "result_json": json.dumps({"stage": "preflight_passed", "report": payload["report"]}, sort_keys=True)})
        mapped = VaultMap.create({"source_system": vault["source_system"], "source_tenant_id": vault["source_tenant_id"], "source_company_id": vault["source_company_id"], "source_vault_id": vault["source_vault_id"], "source_vault_type": vault["source_vault_type"], "source_vault_name": vault["source_vault_name"], "source_row_sha256": vault["source_row_sha256"], "source_archive_sha256": vault["source_archive_sha256"], "canonical_key": vault["canonical_key"], "decision": vault["decision"], "company_id": company.id, "journal_id": journal.id, "run_id": run.id})
        require(mapped.company_id == company and mapped.journal_id == journal, "append-only vault map differs after create")
        result = {"status": "committed", "run_id": run.id, "company_id": company.id, "journal_id": journal.id, "journal_code": journal.code}
        run.write({"state": "committed", "finished_at": fields.Datetime.now(), "result_json": json.dumps({**result, "report": payload["report"]}, sort_keys=True)})
    env.cr.commit()
except Exception:
    env.cr.rollback()
    raise

print(json.dumps(result, ensure_ascii=False, sort_keys=True))
