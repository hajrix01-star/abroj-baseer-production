"""Read-only plan for the remaining Noorix HR and payroll rehearsal waves.

The planner is read-only.  Its companion wave API is deliberately narrow: it
can create and post only the approved ``account.move`` records for one
independently locked rehearsal wave at a time.  It cannot create employees,
payroll records, payments, payslips, stock, POS records, or cash recovery /
disbursement documents.

The plan is deliberately source-first:

* every source identity comes from the pinned Noorix manifest or the sealed,
  SHA-pinned Noorix HR/payroll source snapshot;
* companies and liquidity journals resolve only through the existing immutable
  rehearsal source maps;
* employees, journals and accounts use exact, same-company semantic matches;
* no QA database identity or target id is embedded in this file.

The two ``SAL-PR-2609-001`` records are August 2026 settlements paid from
their source vaults.  They are not September unpaid payroll.  The obsolete
unpaid-correction artifact is checked and reported as excluded, never planned.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from odoo import Command, fields
from odoo.exceptions import UserError

from . import runtime_guard
from .models.evidence import WRITER_CONTEXT


PLAN_VERSION = "hr-payroll-rehearsal-plan-v1"
MONEY_QUANTUM = Decimal("0.01")
EXPECTED_ATOMIC_WAVE_COUNT = 37

# This is both an accounting contract and a writer allow-list.  A manifest or
# snapshot change cannot make this executor write another business process.
_EXECUTABLE_SCOPE_KINDS = {
    "payroll_opening_advance": {"opening_employee_advance"},
    "payroll_paid_august": {"paid_historical_salary"},
    "payroll_historical_core": {"paid_historical_salary"},
    "payroll_arz_daily_salary": {"paid_historical_daily_salary"},
    "payroll_arz_daily_overtime": {"paid_historical_daily_overtime"},
    "payroll_almoallem_historical": {"salary", "overtime"},
    "payroll_doha_overtime": {"historical_payroll"},
    "payroll_karak_settlement": {"paid_historical_salary"},
    "hr_paid_service": {"paid_employee_service"},
}

_FORBIDDEN_EFFECT_MODELS = (
    "hr.payslip",
    "hr.payslip.run",
    "hr.payroll.run",
    "account.payment",
    "stock.move",
    "stock.picking",
    "stock.quant",
    "stock.valuation.layer",
    "pos.order",
    "pos.session",
    "baseer.pos.summary",
)

# These are immutable source-contract hashes from the pinned manifest, rather
# than QA artifacts or target identifiers.  They prevent a future arbitrary
# manifest entry from being silently interpreted as a payroll instruction.
ADVANCE_AND_AUGUST_PAYROLL_ARTIFACT = (
    "c238e53660196377ba770579d1365bdf088b22614697699e9ad973c58b2efeae"
)
ALMOALLEM_PAYROLL_ARTIFACT = (
    "82bf234cf38b2b8e1240cf6d55c6846a6557caa64f68e33fcf67e488d050c2ee"
)
DOHA_OVERTIME_ARTIFACT = (
    "cba6d6b534a179d4141e66894cef379b603ef5cef5c7ee860947ebcf64de41f0"
)
HR_EXPENSES_ARTIFACT = (
    "2512d01769cf7fe0c602e1f3dea00f08e11eb02ddf25734fdb6492ce965998ed"
)
KARAK_PAYROLL_ARTIFACT = (
    "5657a4d93119a0a9faf1e35ebe80649ee390975ed61e3de0c3aade5eda0217df"
)
SUPERSEDED_UNPAID_CORRECTION_ARTIFACT = (
    "873c773b3aae05f92a85b8f4a67eb8c1d6cb7601ea97aa82add273aa8bf5c032"
)


# A service maps to one approved same-company expense account code.  This is
# an allow-list, not a keyword inference.  New source service labels stop the
# planning wave until they receive an explicit source decision.
_HR_SERVICE_ACCOUNT = {
    "تجديداقامه": "400093",
    "نقلكفاله": "400093",
    "تاشيرهخروجوعوده": "400093",
    "شهادهصحيه": "400075",
    "تذكرهسفر": "400006",
    "تامينطبي": "400009",
}

# The paid August source settles one ARZ invoice from bank and one Almoallem
# invoice from bank plus Keeta.  The raw manifest proves the settlement
# identities; this immutable amount table is checked against each invoice
# total, so a split cannot be lost or reshaped later.
_AUGUST_SETTLEMENT_AMOUNT = {
    "cmtptodvf000910d6w6c6usqb": "17749.97",
    "cmtpttvip000k10d6ay7fmzxo": "6565.00",
    "cmtpttviv000o10d6xeixk7uc": "22798.10",
}

# Core payroll, daily-wage, and HR row facts are loaded exclusively from the
# sealed source snapshot at plan time; no archive-derived row or amount is
# embedded in this planner.

def _money(value, label):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite():
            raise InvalidOperation
        return amount.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError) as error:
        raise UserError("Noorix HR/payroll plan has invalid %s" % label) from error


def _normal(value):
    value = (value or "").strip().casefold()
    value = value.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه"}))
    return re.sub(r"[\s\-_.،,()]+", "", value)


def _stable_hash(value):
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def _one(records, label):
    if len(records) != 1:
        raise UserError("Noorix HR/payroll plan requires one %s; found %s" % (label, len(records)))
    # Odoo recordsets are already the one desired record.  Plain manifest
    # collections need their sole item unwrapped.
    return records[0] if isinstance(records, (list, tuple)) else records


def _source_identity(row, terminal_key):
    keys = ("source_system", "source_tenant_id", "source_company_id", terminal_key)
    values = []
    for key in keys:
        value = row.get(key)
        if value in (None, ""):
            raise UserError("Noorix HR/payroll source identity lacks %s" % key)
        values.append(str(value))
    return ":".join(values)


def _contract(manifest, *, artifact, label):
    matches = [item for item in manifest["contracts"] if item.get("artifact_sha256") == artifact]
    contract = _one(matches, label)
    payload = contract.get("payload")
    if not isinstance(payload, dict) or payload.get("source_archive_sha256") != runtime_guard.SOURCE_ARCHIVE_SHA256:
        raise UserError("Noorix HR/payroll %s source archive pin differs" % label)
    return payload


def _company_for_source(env, source_company_id):
    identity = "noorix:%s:%s" % ("default-tenant-noorix-2024", source_company_id)
    Map = env["baseer.noorix.rehearsal.source.map"].sudo()
    mapping = _one(Map.search([
        ("scope", "=", "company"), ("source_identity", "=", identity),
    ]), "company source map")
    if (
        mapping.source_archive_sha256 != runtime_guard.SOURCE_ARCHIVE_SHA256
        or mapping.target_model != "res.company"
    ):
        raise UserError("Noorix HR/payroll company evidence differs for %s" % source_company_id)
    company = env["res.company"].sudo().with_context(active_test=False).browse(mapping.target_res_id).exists()
    if not company or not company.active:
        raise UserError("Noorix HR/payroll source company has no active rehearsal target")
    return company


def _company_model(env, model, company):
    return env[model].sudo().with_company(company).with_context(
        active_test=False, allowed_company_ids=[company.id]
    )


def _semantic_account(env, company, code, expected_types):
    Account = _company_model(env, "account.account", company)
    company_field = "company_ids" if "company_ids" in Account._fields else "company_id"
    account = _one(Account.search([
        (company_field, "in", [company.id]), ("code", "=", code),
    ]), "same-company account %s" % code)
    if account.account_type not in set(expected_types):
        raise UserError("Noorix HR/payroll account %s has an unexpected type" % code)
    return account


def _semantic_journal(env, company, code, journal_type):
    journal = _one(_company_model(env, "account.journal", company).search([
        ("company_id", "=", company.id), ("code", "=", code), ("type", "=", journal_type),
    ]), "same-company journal %s" % code)
    if not journal.active:
        raise UserError("Noorix HR/payroll journal %s is archived" % code)
    return journal


def _vault_journal(env, company, row):
    identity = _source_identity(row, "source_vault_id")
    Map = env["baseer.noorix.rehearsal.source.map"].sudo()
    mapping = _one(Map.search([
        ("scope", "=", "vault"), ("source_identity", "=", identity),
    ]), "vault source map")
    if (
        mapping.source_archive_sha256 != runtime_guard.SOURCE_ARCHIVE_SHA256
        or mapping.target_model != "account.journal"
    ):
        raise UserError("Noorix HR/payroll vault evidence differs for %s" % identity)
    journal = _company_model(env, "account.journal", company).browse(mapping.target_res_id).exists()
    if not journal or journal.company_id != company or journal.type not in {"bank", "cash"}:
        raise UserError("Noorix HR/payroll vault has no same-company liquidity journal")
    if not journal.active or not journal.default_account_id:
        raise UserError("Noorix HR/payroll liquidity journal is not operational")
    return journal


def _employee(env, company, source_name):
    matches = _company_model(env, "hr.employee", company).search([
        ("company_id", "=", company.id),
    ]).filtered(lambda employee: _normal(employee.name) == _normal(source_name))
    employee = _one(matches, "same-company employee %s" % source_name)
    if not employee.work_contact_id:
        raise UserError("Noorix HR/payroll employee has no work contact: %s" % source_name)
    return employee


def _existing_provenance(env, scope, identity, source_hash, canonical_key):
    Map = env["baseer.noorix.rehearsal.source.map"].sudo()
    mappings = Map.search([("scope", "=", scope), ("source_identity", "=", identity)])
    if not mappings:
        return {"state": "planned", "existing_target_id": False}
    mapping = _one(mappings, "existing HR/payroll provenance")
    if (
        mapping.source_archive_sha256 != runtime_guard.SOURCE_ARCHIVE_SHA256
        or mapping.source_row_sha256 != source_hash
        or mapping.canonical_key != canonical_key
        or mapping.target_model != "account.move"
    ):
        raise UserError("Noorix HR/payroll provenance conflicts for %s" % identity)
    target = env["account.move"].sudo().with_context(active_test=False).browse(mapping.target_res_id).exists()
    if not target or target.state != "posted":
        raise UserError("Noorix HR/payroll provenance target is not a posted move")
    return {"state": "already_mapped", "existing_target_id": target.id}


def _binding(record):
    return {
        "company": {"id": record["company"].id, "name": record["company"].name},
        "journal": {"id": record["journal"].id, "code": record["journal"].code},
        "debit_account": {"id": record["debit_account"].id, "code": record["debit_account"].code},
        "credit_account": (
            {"id": record["credit_account"].id, "code": record["credit_account"].code}
            if record.get("credit_account") else False
        ),
        "credit_splits": [
            {
                "amount": str(_money(item["amount"], "credit split")),
                "journal": {"id": item["journal"].id, "code": item["journal"].code},
                "account": {"id": item["account"].id, "code": item["account"].code},
            }
            for item in record.get("credit_splits", [])
        ],
        "employee": (
            {"id": record["employee"].id, "name": record["employee"].name,
             "partner_id": record["employee"].work_contact_id.id}
            if record.get("employee") else False
        ),
        "liquidity_journal": (
            {"id": record["liquidity_journal"].id, "code": record["liquidity_journal"].code}
            if record.get("liquidity_journal") else False
        ),
    }


def _plan_record(env, *, scope, row, canonical_key, amount, date, move_kind,
                 company, journal, debit_account, credit_account, employee=None,
                 liquidity_journal=None, reference, identity_terminal="source_invoice_id",
                 credit_splits=None):
    source_hash = _stable_hash({
        "plan_version": PLAN_VERSION,
        "scope": scope,
        "canonical_key": canonical_key,
        "source_archive_sha256": runtime_guard.SOURCE_ARCHIVE_SHA256,
        "source": row,
        "amount": str(_money(amount, canonical_key)),
        "date": date,
        "move_kind": move_kind,
    })
    terminal = identity_terminal if row.get(identity_terminal) else "source_payroll_run_id"
    identity = _source_identity(row, terminal)
    state = _existing_provenance(env, scope, identity, source_hash, canonical_key)
    record = {
        "scope": scope,
        "source_identity": identity,
        "canonical_key": canonical_key,
        "source_evidence_sha256": source_hash,
        "amount": str(_money(amount, canonical_key)),
        "date": date,
        "move_kind": move_kind,
        "company": company,
        "journal": journal,
        "debit_account": debit_account,
        "credit_account": credit_account,
        "credit_splits": credit_splits or [],
        "employee": employee,
        "liquidity_journal": liquidity_journal,
        "reference": reference,
        **state,
    }
    record["bindings"] = _binding(record)
    return {key: value for key, value in record.items() if key not in {
        "company", "journal", "debit_account", "credit_account", "employee", "liquidity_journal",
        "credit_splits",
    }}


def _advance_records(env, payload):
    rows = payload.get("opening_advance_records")
    if not isinstance(rows, list) or len(rows) != 12:
        raise UserError("Noorix opening-advance source count differs")
    planned = []
    total = Decimal("0")
    for row in rows:
        if row.get("decision") != "opening_outstanding_only_invoice_settled_amount_authoritative":
            raise UserError("Noorix opening advance has an unsupported decision")
        amount = _money(row.get("source_opening_residual_raw"), "opening advance")
        if amount <= 0:
            raise UserError("Noorix opening advance is not a positive residual")
        company = _company_for_source(env, row["source_company_id"])
        employee = _employee(env, company, row["source_employee_name"])
        planned.append(_plan_record(
            env, scope="payroll_opening_advance", row=row, canonical_key=row["canonical_key"],
            amount=amount, date=row["source_as_of_date"], move_kind="opening_employee_advance",
            company=company, journal=_semantic_journal(env, company, "MISC", "general"),
            debit_account=_semantic_account(env, company, "102090", {"asset_receivable"}),
            credit_account=_semantic_account(env, company, "999999", {"equity_unaffected"}),
            employee=employee, reference="Noorix %s — opening employee advance" % row["source_invoice_number"],
        ))
        total += amount
    if total != _money(payload.get("preflight", {}).get("source_opening_total"), "opening advance total"):
        raise UserError("Noorix opening advance total differs from its source preflight")
    return planned, total


def _paid_payroll_records(env, payload):
    rows = payload.get("september_net_payroll_records")
    if not isinstance(rows, list) or len(rows) != 2:
        raise UserError("Noorix August paid-payroll source count differs")
    planned = []
    total = Decimal("0")
    for row in rows:
        if (
            row.get("decision") != "historical_net_payroll_only_no_payslip_no_employee_no_advance_recovery"
            or row.get("source_date") != "2026-08-31"
        ):
            raise UserError("Noorix paid payroll is not the approved August settlement")
        settlements = row.get("settlements")
        if not isinstance(settlements, list) or not settlements:
            raise UserError("Noorix paid payroll lacks settlement evidence")
        amount = _money(row.get("source_total_raw"), "August paid payroll")
        split_total = Decimal("0")
        for settlement in settlements:
            allocation_id = settlement.get("source_allocation_id")
            split_total += _money(_AUGUST_SETTLEMENT_AMOUNT.get(allocation_id), "August settlement allocation")
        if split_total != amount:
            raise UserError("Noorix August settlement allocations do not equal the salary invoice")
        company = _company_for_source(env, row["source_company_id"])
        # One move per invoice keeps the source invoice auditable while the
        # credit side preserves each original liquidity split.
        debit = _semantic_account(env, company, "400003", {"expense"})
        payroll_journal = _semantic_journal(env, company, "BPAY", "general")
        credit_splits = []
        for settlement in settlements:
            allocation_id = settlement["source_allocation_id"]
            allocation_amount = _money(_AUGUST_SETTLEMENT_AMOUNT[allocation_id], "August settlement allocation")
            settlement_row = dict(row)
            settlement_row.update(settlement)
            liquidity = _vault_journal(env, company, settlement_row)
            credit_splits.append({
                "amount": allocation_amount, "journal": liquidity,
                "account": liquidity.default_account_id,
                "source_allocation_id": allocation_id,
                "source_ledger_id": settlement["source_ledger_id"],
                "source_vault_id": settlement["source_vault_id"],
            })
        source_row = dict(row)
        source_row["settlement_amounts"] = [
            {key: item[key] for key in ("source_allocation_id", "source_ledger_id", "source_vault_id")}
            | {"amount_raw": str(_money(item["amount"], "August settlement allocation"))}
            for item in credit_splits
        ]
        planned.append(_plan_record(
            env, scope="payroll_paid_august", row=source_row, canonical_key=row["canonical_key"],
            amount=amount, date=row["source_date"], move_kind="paid_historical_salary",
            company=company, journal=payroll_journal, debit_account=debit, credit_account=None,
            credit_splits=credit_splits,
            reference="Noorix %s — August historical salary settlement" % row["source_invoice_number"],
        ))
        total += amount
    return planned, total


def _snapshot_group(snapshot, key, classifications):
    """Validate a sealed row-level evidence group before planning from it."""
    group = _one([item for item in snapshot["groups"] if item.get("key") == key], key)
    records = group.get("records")
    if not isinstance(records, list) or len(records) != group.get("expected_record_count"):
        raise UserError("Noorix %s snapshot record count differs" % key)
    if not records or not isinstance(group.get("source_table_paths"), list):
        raise UserError("Noorix %s snapshot source tables differ" % key)
    identities = set()
    company_totals = defaultdict(lambda: {"record_count": 0, "amount": Decimal("0")})
    total = Decimal("0")
    for record in records:
        evidence = record.get("source_evidence")
        if not isinstance(evidence, dict) or not isinstance(evidence.get("invoice"), dict):
            raise UserError("Noorix %s snapshot row has no invoice evidence" % key)
        if _stable_hash(evidence) != str(record.get("source_row_sha256", "")).lower():
            raise UserError("Noorix %s snapshot row hash differs" % key)
        invoice = evidence["invoice"]
        identity = record.get("source_invoice_id")
        company_id = record.get("source_company_id")
        if (
            not identity or identity in identities or not company_id
            or invoice.get("source_invoice_id") != identity
            or invoice.get("source_company", {}).get("id") != company_id
            or invoice.get("source_tenant_id") != snapshot["source_tenant_id"]
            or record.get("source_business_date") != invoice.get("source_transaction_date")
            or invoice.get("source_status") != "active"
            or record.get("classification") not in classifications
        ):
            raise UserError("Noorix %s snapshot row identity differs" % key)
        amount = _money(record.get("source_amount_raw"), "%s snapshot amount" % key)
        if amount <= 0 or amount != _money(invoice.get("source_total_raw"), "%s invoice total" % key):
            raise UserError("Noorix %s snapshot row amount differs" % key)
        identities.add(identity)
        company_totals[company_id]["record_count"] += 1
        company_totals[company_id]["amount"] += amount
        total += amount
    if total != _money(group.get("amount_total_raw"), "%s snapshot total" % key):
        raise UserError("Noorix %s snapshot group total differs" % key)
    declared_companies = group.get("totals_by_company")
    if not isinstance(declared_companies, list) or len(declared_companies) != len(company_totals):
        raise UserError("Noorix %s snapshot company totals differ" % key)
    declared = {
        item.get("source_company_id"): (item.get("record_count"), _money(item.get("amount_total_raw"), "%s company total" % key))
        for item in declared_companies
    }
    observed = {
        company_id: (values["record_count"], values["amount"])
        for company_id, values in company_totals.items()
    }
    if declared != observed:
        raise UserError("Noorix %s snapshot company reconciliation differs" % key)
    group_hash = _stable_hash({
        "key": key,
        "source_table_paths": group["source_table_paths"],
        "expected_record_count": group["expected_record_count"],
        "amount_total_raw": str(_money(group["amount_total_raw"], "%s group amount" % key)),
        "rows": [
            {"source_invoice_id": row["source_invoice_id"], "source_row_sha256": row["source_row_sha256"]}
            for row in records
        ],
    })
    return group, group_hash


def _snapshot_settlement_splits(record, expected_reference_type):
    """Match each sealed source allocation to its active source ledger row."""
    evidence = record["source_evidence"]
    allocations = evidence.get("source_allocations")
    ledgers = evidence.get("source_ledger_entries")
    if not isinstance(allocations, list) or not isinstance(ledgers, list) or not allocations or not ledgers:
        raise UserError("Noorix snapshot row has no settlement evidence")
    if len({item.get("source_allocation_id") for item in allocations}) != len(allocations):
        raise UserError("Noorix snapshot allocation identities differ")
    if len({item.get("source_ledger_id") for item in ledgers}) != len(ledgers):
        raise UserError("Noorix snapshot ledger identities differ")
    expected_amount = _money(record["source_amount_raw"], "snapshot settlement amount")
    ledger_buckets = defaultdict(list)
    ledger_total = Decimal("0")
    for ledger in ledgers:
        amount = _money(ledger.get("source_amount_raw"), "snapshot ledger amount")
        wallet_id = ledger.get("source_wallet", {}).get("id")
        if (
            amount <= 0 or not wallet_id or ledger.get("source_status") != "active"
            or ledger.get("source_reference_type") != expected_reference_type
            or ledger.get("source_transaction_date") != record["source_business_date"]
        ):
            raise UserError("Noorix snapshot ledger evidence differs")
        ledger_buckets[(wallet_id, amount)].append(ledger)
        ledger_total += amount
    if ledger_total != expected_amount:
        raise UserError("Noorix snapshot ledger settlement total differs")
    splits = []
    allocation_total = Decimal("0")
    for allocation in allocations:
        amount = _money(allocation.get("source_amount_raw"), "snapshot allocation amount")
        wallet_id = allocation.get("source_wallet", {}).get("id")
        bucket = ledger_buckets[(wallet_id, amount)]
        if amount <= 0 or not wallet_id or not bucket:
            raise UserError("Noorix snapshot allocation cannot match its ledger")
        ledger = bucket.pop(0)
        splits.append({
            "source_allocation_id": allocation["source_allocation_id"],
            "source_ledger_id": ledger["source_ledger_id"],
            "source_vault_id": wallet_id,
            "source_amount_raw": str(amount),
        })
        allocation_total += amount
    if allocation_total != expected_amount or any(ledger_buckets.values()):
        raise UserError("Noorix snapshot allocation settlement total differs")
    source_wallet_id = record.get("source_wallet_id")
    if source_wallet_id and (len(splits) != 1 or splits[0]["source_vault_id"] != source_wallet_id):
        raise UserError("Noorix snapshot direct wallet evidence differs")
    return splits


def _snapshot_source_row(snapshot, record, group_hash, expected_document_kind):
    """Flatten verified sealed evidence into a source-only planner row."""
    invoice = record["source_evidence"]["invoice"]
    if invoice.get("source_document_kind") != expected_document_kind:
        raise UserError("Noorix snapshot document kind differs")
    row = {
        "source_system": snapshot["source_system"],
        "source_tenant_id": snapshot["source_tenant_id"],
        "source_company_id": record["source_company_id"],
        "source_invoice_id": record["source_invoice_id"],
        "source_invoice_number": invoice.get("source_invoice_number"),
        "source_vault_id": record.get("source_wallet_id"),
        "source_amount_raw": str(_money(record["source_amount_raw"], "snapshot source amount")),
        "source_business_date": record["source_business_date"],
        "source_document_kind": expected_document_kind,
        "source_snapshot_row_sha256": record["source_row_sha256"],
        "source_snapshot_group_sha256": group_hash,
    }
    if not row["source_invoice_number"]:
        raise UserError("Noorix snapshot source invoice number is missing")
    row["source_settlement_splits"] = _snapshot_settlement_splits(record, "salary" if expected_document_kind == "salary" else "invoice")
    return row


def _historical_core_payroll_records(env, snapshot):
    """Plan only the 20 source-proven, paid historical salary documents."""
    group, group_hash = _snapshot_group(
        snapshot, "historical_core_payroll", {"historical_core_paid_salary"}
    )
    facts = group["records"]

    planned = []
    total = Decimal("0")
    for fact in facts:
        row = _snapshot_source_row(snapshot, fact, group_hash, "salary")
        amount = _money(row["source_amount_raw"], "historical core payroll")
        if amount <= 0 or fact["classification"] != "historical_core_paid_salary":
            raise UserError("Noorix historical core-payroll source status differs")
        company = _company_for_source(env, row["source_company_id"])
        debit = _semantic_account(env, company, "400003", {"expense"})
        payroll_journal = _semantic_journal(env, company, "BPAY", "general")
        splits = row.get("source_settlement_splits", ())
        if len(splits) > 1:
            if len({item["source_allocation_id"] for item in splits}) != len(splits):
                raise UserError("Noorix historical core-payroll settlement evidence differs")
            credit_splits = []
            split_total = Decimal("0")
            for split in splits:
                split_amount = _money(split["source_amount_raw"], "historical core-payroll settlement")
                if split_amount <= 0 or not split.get("source_ledger_id"):
                    raise UserError("Noorix historical core-payroll settlement is incomplete")
                settlement_row = dict(row)
                settlement_row["source_vault_id"] = split["source_vault_id"]
                liquidity = _vault_journal(env, company, settlement_row)
                credit_splits.append({
                    "amount": split_amount,
                    "journal": liquidity,
                    "account": liquidity.default_account_id,
                    "source_allocation_id": split["source_allocation_id"],
                    "source_ledger_id": split["source_ledger_id"],
                    "source_vault_id": split["source_vault_id"],
                })
                split_total += split_amount
            if split_total != amount:
                raise UserError("Noorix historical core-payroll settlement total differs")
            planned.append(_plan_record(
                env, scope="payroll_historical_core", row=row,
                canonical_key="historical-salary:%s:%s" % (
                    row["source_company_id"], row["source_invoice_id"]
                ), amount=amount, date=row["source_business_date"], move_kind="paid_historical_salary",
                company=company, journal=payroll_journal, debit_account=debit,
                credit_account=None, credit_splits=credit_splits,
                reference="Noorix %s — pinned historical salary settlement" % row["source_invoice_number"],
            ))
        else:
            row["source_vault_id"] = splits[0]["source_vault_id"]
            liquidity = _vault_journal(env, company, row)
            planned.append(_plan_record(
                env, scope="payroll_historical_core", row=row,
                canonical_key="historical-salary:%s:%s" % (
                    row["source_company_id"], row["source_invoice_id"]
                ), amount=amount, date=row["source_business_date"], move_kind="paid_historical_salary",
                company=company, journal=payroll_journal, debit_account=debit,
                credit_account=liquidity.default_account_id, liquidity_journal=liquidity,
                reference="Noorix %s — pinned historical salary settlement" % row["source_invoice_number"],
            ))
        total += amount
    if total != _money(group["amount_total_raw"], "historical core-payroll group total"):
        raise UserError("Noorix historical core-payroll total differs from pinned archive")
    return planned, total


def _arz_daily_wage_records(env, snapshot):
    """Plan the 23 source-classified ARZ daily salary/overtime payments."""
    group, group_hash = _snapshot_group(
        snapshot, "arz_daily_wages_overtime", {"arz_daily_salary", "arz_daily_overtime"}
    )
    facts = group["records"]

    planned = []
    total = Decimal("0")
    for fact in facts:
        row = _snapshot_source_row(snapshot, fact, group_hash, "expense")
        amount = _money(row["source_amount_raw"], "ARZ daily wage")
        kind = fact["classification"].removeprefix("arz_daily_")
        if amount <= 0 or kind not in {"salary", "overtime"}:
            raise UserError("Noorix ARZ daily-wage source evidence differs")
        if row["source_company_id"] != fact["source_evidence"]["invoice"]["source_company"]["id"]:
            raise UserError("Noorix daily wage source company evidence differs")
        row["source_vault_id"] = row["source_settlement_splits"][0]["source_vault_id"]
        company = _company_for_source(env, row["source_company_id"])
        liquidity = _vault_journal(env, company, row)
        scope = "payroll_arz_daily_%s" % kind
        planned.append(_plan_record(
            env, scope=scope, row=row,
            canonical_key="historical-arz-daily-%s:%s" % (kind, row["source_invoice_id"]),
            amount=amount, date=row["source_business_date"],
            move_kind="paid_historical_daily_%s" % kind,
            company=company, journal=_semantic_journal(env, company, "BPAY", "general"),
            debit_account=_semantic_account(env, company, "400003", {"expense"}),
            credit_account=liquidity.default_account_id, liquidity_journal=liquidity,
            reference="Noorix %s — historical daily %s" % (row["source_invoice_number"], kind),
        ))
        total += amount
    if total != _money(group["amount_total_raw"], "ARZ daily-wage group total"):
        raise UserError("Noorix ARZ daily-wage total differs from pinned archive")
    return planned, total


def _owner_payroll_records(env, payload, *, expected_count, expected_total, scope, expected_decision):
    rows = payload.get("records")
    if not isinstance(rows, list) or len(rows) != expected_count:
        raise UserError("Noorix %s source count differs" % scope)
    planned = []
    total = Decimal("0")
    for row in rows:
        if row.get("decision") != expected_decision:
            raise UserError("Noorix %s contains an unsupported decision" % scope)
        amount = _money(row.get("source_total_raw"), scope)
        if amount <= 0 or _money(row.get("source_net_raw"), scope) != amount or _money(row.get("source_tax_raw"), scope) != 0:
            raise UserError("Noorix %s source financial evidence differs" % scope)
        company = _company_for_source(env, row["source_company_id"])
        liquidity = _vault_journal(env, company, row)
        planned.append(_plan_record(
            env, scope=scope, row=row, canonical_key=row["canonical_key"], amount=amount,
            date=row["business_date"], move_kind=row.get("settlement_kind", "historical_payroll"),
            company=company, journal=_semantic_journal(env, company, "BPAY", "general"),
            debit_account=_semantic_account(env, company, "400003", {"expense"}),
            credit_account=liquidity.default_account_id, liquidity_journal=liquidity,
            reference="Noorix %s — historical %s settlement" % (
                row["source_invoice_number"], row.get("settlement_kind", "payroll")
            ),
        ))
        total += amount
    if total != _money(expected_total, "%s total" % scope):
        raise UserError("Noorix %s total differs from its approved contract" % scope)
    return planned, total


def _hr_expense_records(env, payload, snapshot):
    rows = payload.get("records")
    if not isinstance(rows, list) or len(rows) != 19:
        raise UserError("Noorix HR-expense source count differs")
    group, group_hash = _snapshot_group(
        snapshot, "hr_paid_service_expenses", {"historical_paid_employee_service"}
    )
    snapshot_rows = {row.get("source_invoice_id"): row for row in group["records"]}
    if len(snapshot_rows) != len(rows) or set(snapshot_rows) != {row.get("source_invoice_id") for row in rows}:
        raise UserError("Noorix HR-expense source identities differ")
    if payload.get("source_tenant_id") != snapshot["source_tenant_id"]:
        raise UserError("Noorix HR-expense source tenant differs")
    planned = []
    total = Decimal("0")
    for row in rows:
        fact = snapshot_rows[row["source_invoice_id"]]
        source_row = _snapshot_source_row(snapshot, fact, group_hash, "hr_expense")
        contract_reference = fact["source_evidence"].get("contract_reference")
        if not isinstance(contract_reference, dict) or contract_reference.get("source_contract_artifact_sha256") != HR_EXPENSES_ARTIFACT:
            raise UserError("Noorix HR-expense contract evidence differs")
        contract_fields = (
            "source_employee_name", "source_allocation_id", "source_ledger_id",
            "source_vault_id",
        )
        if (
            fact["source_company_id"] != row.get("source_company_id")
            or any(contract_reference.get(key) != row.get(key) for key in contract_fields)
            or contract_reference.get("service") != row.get("service")
            or contract_reference.get("source_business_date") != row.get("business_date")
            or _money(contract_reference.get("source_amount_raw"), "HR contract amount")
            != _money(source_row["source_amount_raw"], "HR snapshot amount")
        ):
            raise UserError("Noorix HR-expense contract row differs from sealed evidence")
        service_key = _normal(row.get("service"))
        account_code = _HR_SERVICE_ACCOUNT.get(service_key)
        if not account_code:
            raise UserError("Noorix HR-expense service lacks an approved account: %s" % row.get("service"))
        amount = _money(source_row["source_amount_raw"], "HR expense")
        company = _company_for_source(env, row["source_company_id"])
        employee = _employee(env, company, row["source_employee_name"])
        if len(source_row["source_settlement_splits"]) != 1:
            raise UserError("Noorix HR-expense has a non-atomic source settlement")
        source_row["source_vault_id"] = source_row["source_settlement_splits"][0]["source_vault_id"]
        source_row["expense_account_code"] = account_code
        source_row["source_employee_name"] = row["source_employee_name"]
        source_row["service"] = row["service"]
        liquidity = _vault_journal(env, company, source_row)
        planned.append(_plan_record(
            env, scope="hr_paid_service", row=source_row,
            canonical_key="historical-hr-service:%s:%s" % (row["source_company_id"], row["source_invoice_id"]),
            amount=amount, date=source_row["source_business_date"], move_kind="paid_employee_service",
            company=company, journal=_semantic_journal(env, company, "MISC", "general"),
            debit_account=_semantic_account(env, company, account_code, {"expense"}),
            credit_account=liquidity.default_account_id, employee=employee, liquidity_journal=liquidity,
            reference="Noorix %s — %s" % (source_row["source_invoice_number"], row["service"]),
        ))
        total += amount
    if (
        total != _money(group["amount_total_raw"], "HR-expense snapshot total")
        or total != _money(payload.get("report", {}).get("total"), "HR expense contract total")
    ):
        raise UserError("Noorix HR-expense total differs from its approved contract")
    return planned, total


def _karak_record(env, payload):
    row = payload.get("settlement")
    if not isinstance(row, dict) or row.get("decision") != "create_owner_declared_bank_move":
        raise UserError("Noorix Karak payroll settlement differs")
    amount = _money(row.get("source_net_raw"), "Karak payroll settlement")
    if amount != _money(payload.get("report", {}).get("source_net"), "Karak source net"):
        raise UserError("Noorix Karak settlement total differs from report")
    company = _company_for_source(env, row["source_company_id"])
    bank = _semantic_journal(env, company, "BNK1", "bank")
    if not bank.default_account_id:
        raise UserError("Noorix Karak bank journal lacks a liquidity account")
    planned = _plan_record(
        env, scope="payroll_karak_settlement", row=row, canonical_key=row["canonical_key"],
        amount=amount, date=row["source_completion_date"], move_kind="paid_historical_salary",
        company=company, journal=_semantic_journal(env, company, "BPAY", "general"),
        debit_account=_semantic_account(env, company, "400003", {"expense"}),
        credit_account=bank.default_account_id, liquidity_journal=bank,
        reference="Noorix %s — owner-declared historical net salary paid" % row["source_run_number"],
    )
    return [planned], amount


def _wave_key(operation):
    company_source = operation["source_identity"].split(":")[2]
    if operation["scope"] == "payroll_opening_advance":
        return "opening-advance:%s" % company_source
    if operation["scope"] == "hr_paid_service":
        return "hr-expense:%s:%s" % (company_source, operation["date"][:7])
    if operation["scope"] == "payroll_karak_settlement":
        return "payroll-karak:%s" % company_source
    return "%s:%s:%s" % (operation["scope"], company_source, operation["date"][:7])


def _atomic_waves(operations):
    grouped = defaultdict(list)
    for operation in operations:
        grouped[_wave_key(operation)].append(operation)
    waves = []
    for key in sorted(grouped):
        rows = grouped[key]
        waves.append({
            "run_scope": "payroll_month",
            "run_key": "hr-payroll:%s" % key,
            "atomic": True,
            "operation_count": len(rows),
            "amount": str(sum((_money(row["amount"], "planned operation") for row in rows), Decimal("0"))),
            "source_identities": sorted(row["source_identity"] for row in rows),
            "required_write_protocol": [
                "take a transaction-scoped advisory lock for this run key",
                "create or verify one rehearsal run evidence row",
                "create every account.move and source map in this wave, or roll back all of them",
                "post every move before marking the run committed",
            ],
        })
    return waves


def plan_hr_payroll_replay(env, path=None):
    """Return a read-only, semantically rebound HR/payroll replay plan.

    Calling this function is safe in an Odoo shell: it performs no create,
    write, unlink, posting, lock, or commit.  The narrowly approved
    ``apply_hr_payroll_replay_wave`` API below always rebuilds this plan under
    its advisory lock; no returned operation is executable by itself.
    """
    runtime_guard.assert_rehearsal_database(env)
    manifest = runtime_guard.load_source_manifest(path or runtime_guard.DEFAULT_MANIFEST_PATH)
    snapshot = runtime_guard.load_hr_payroll_source_snapshot()
    if (
        snapshot.get("source_system") != "noorix"
        or not snapshot.get("source_tenant_id")
        or not isinstance(snapshot.get("grand_total"), dict)
        or snapshot["grand_total"].get("record_count") != 62
    ):
        raise UserError("Noorix sealed HR/payroll source snapshot root differs")

    advances_payload = _contract(
        manifest, artifact=ADVANCE_AND_AUGUST_PAYROLL_ARTIFACT,
        label="opening advances and August paid payroll",
    )
    almo_payload = _contract(manifest, artifact=ALMOALLEM_PAYROLL_ARTIFACT, label="Almoallem payroll")
    doha_payload = _contract(manifest, artifact=DOHA_OVERTIME_ARTIFACT, label="Doha overtime")
    hr_payload = _contract(manifest, artifact=HR_EXPENSES_ARTIFACT, label="HR expenses")
    karak_payload = _contract(manifest, artifact=KARAK_PAYROLL_ARTIFACT, label="Karak payroll")
    superseded = _contract(
        manifest, artifact=SUPERSEDED_UNPAID_CORRECTION_ARTIFACT, label="superseded unpaid correction",
    )
    if len(superseded.get("records", [])) != 2:
        raise UserError("Noorix superseded unpaid correction evidence differs")

    advances, advances_total = _advance_records(env, advances_payload)
    august_paid, august_paid_total = _paid_payroll_records(env, advances_payload)
    historical_core, historical_core_total = _historical_core_payroll_records(env, snapshot)
    arz_daily_wages, arz_daily_wages_total = _arz_daily_wage_records(env, snapshot)
    almo_payroll, almo_payroll_total = _owner_payroll_records(
        env, almo_payload, expected_count=4, expected_total="2965.00",
        scope="payroll_almoallem_historical", expected_decision="create_owner_declared_historical_payroll_move",
    )
    doha_overtime, doha_overtime_total = _owner_payroll_records(
        env, doha_payload, expected_count=4, expected_total="1100.00",
        scope="payroll_doha_overtime", expected_decision="create_owner_declared_overtime_cash_move",
    )
    hr_expenses, hr_expenses_total = _hr_expense_records(env, hr_payload, snapshot)
    karak_payroll, karak_total = _karak_record(env, karak_payload)
    snapshot_group_hashes = {
        "historical_core_payroll": _snapshot_group(
            snapshot, "historical_core_payroll", {"historical_core_paid_salary"}
        )[1],
        "arz_daily_wages_overtime": _snapshot_group(
            snapshot, "arz_daily_wages_overtime", {"arz_daily_salary", "arz_daily_overtime"}
        )[1],
        "hr_paid_service_expenses": _snapshot_group(
            snapshot, "hr_paid_service_expenses", {"historical_paid_employee_service"}
        )[1],
    }
    snapshot_record_count = len(historical_core) + len(arz_daily_wages) + len(hr_expenses)
    snapshot_total = historical_core_total + arz_daily_wages_total + hr_expenses_total
    if (
        snapshot_record_count != snapshot["grand_total"].get("record_count")
        or snapshot_total != _money(snapshot["grand_total"].get("amount_total_raw"), "HR/payroll snapshot grand total")
    ):
        raise UserError("Noorix sealed HR/payroll source snapshot grand total differs")

    operations = (
        advances + august_paid + historical_core + arz_daily_wages + almo_payroll
        + doha_overtime + hr_expenses + karak_payroll
    )
    identities = [(row["scope"], row["source_identity"]) for row in operations]
    if len(identities) != len(set(identities)):
        raise UserError("Noorix HR/payroll plan has duplicate provenance identities")
    totals_by_scope = Counter()
    counts_by_scope = Counter()
    for row in operations:
        counts_by_scope[row["scope"]] += 1
        totals_by_scope[row["scope"]] += _money(row["amount"], row["scope"])

    return {
        "writer": "baseer_noorix_rehearsal_replay.hr_payroll_replay",
        "plan_version": PLAN_VERSION,
        "mode": "read_only_plan",
        "target_database": env.cr.dbname,
        "source_archive_sha256": runtime_guard.SOURCE_ARCHIVE_SHA256,
        "manifest_sha256": runtime_guard.SOURCE_MANIFEST_SHA256,
        "hr_payroll_source_snapshot_sha256": runtime_guard.HR_PAYROLL_SOURCE_SNAPSHOT_SHA256,
        "hr_payroll_source_snapshot_group_hashes": snapshot_group_hashes,
        "source_contracts": {
            "opening_advances_and_august_paid": ADVANCE_AND_AUGUST_PAYROLL_ARTIFACT,
            "almoallem_historical_payroll": ALMOALLEM_PAYROLL_ARTIFACT,
            "doha_historical_overtime": DOHA_OVERTIME_ARTIFACT,
            "hr_paid_services": HR_EXPENSES_ARTIFACT,
            "karak_paid_payroll": KARAK_PAYROLL_ARTIFACT,
            "sealed_hr_payroll_source_snapshot": runtime_guard.HR_PAYROLL_SOURCE_SNAPSHOT_SHA256,
        },
        "superseded_not_planned": [{
            "artifact_sha256": SUPERSEDED_UNPAID_CORRECTION_ARTIFACT,
            "reason": "source-ledger review classifies both 2026-08-31 records as paid August settlements",
            "source_records": len(superseded["records"]),
        }],
        "prohibitions": [
            "no employee creation", "no supplier creation", "no payslip creation",
            "no payroll-run creation", "no payment creation", "no stock or POS effect",
            "no historic advance cash/bank disbursement or recovery replay",
        ],
        "counts_by_scope": dict(sorted(counts_by_scope.items())),
        "totals_by_scope": {key: str(value) for key, value in sorted(totals_by_scope.items())},
        "control_totals": {
            "opening_advance_residual": str(advances_total),
            "august_paid_payroll": str(august_paid_total),
            "historical_core_payroll": str(historical_core_total),
            "arz_daily_wages": str(arz_daily_wages_total),
            "almoallem_historical_payroll": str(almo_payroll_total),
            "doha_historical_overtime": str(doha_overtime_total),
            "hr_paid_services": str(hr_expenses_total),
            "karak_paid_payroll": str(karak_total),
        },
        "atomic_waves": _atomic_waves(operations),
        "operations": operations,
    }


# ---------------------------------------------------------------------------
# Narrow, rehearsal-only wave executor
# ---------------------------------------------------------------------------
#
# There deliberately is no "apply all" helper.  The caller must select one
# run key, invoke this function in its own database transaction, and decide
# whether to commit that transaction only after independent reconciliation.
# Keeping that boundary in the API makes the 37 waves independently atomic.


def _writer_model(env, model):
    """Return the only model wrapper allowed to append rehearsal evidence."""
    return env[model].sudo().with_context(**{WRITER_CONTEXT: True})


def _wave_lock(env, run_key):
    """Serialize one, and only one, immutable payroll wave in this transaction."""
    env.cr.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [
        "%s:noorix-hr-payroll:%s" % (env.cr.dbname, run_key),
    ])


def _positive_money(value, label):
    amount = _money(value, label)
    if amount <= 0:
        raise UserError("Noorix HR/payroll executor requires a positive %s" % label)
    return amount


def _forbidden_effect_snapshot(env):
    """Hash models the payroll writer must never touch.

    The snapshot is intentionally taken before and after each wave.  If a
    future customization makes account posting write a payslip, payment,
    inventory, or POS record, the savepoint rolls the whole wave back.
    """
    snapshot = {}
    for model_name in _FORBIDDEN_EFFECT_MODELS:
        if model_name not in env.registry.models:
            continue
        Model = env[model_name].sudo().with_context(active_test=False)
        field_names = ["id"]
        field_names.extend(name for name in ("create_date", "write_date") if name in Model._fields)
        rows = Model.search([], order="id").read(field_names)
        snapshot[model_name] = {
            "count": len(rows),
            "sha256": _stable_hash([
                {key: str(value) if value not in (False, None) else False for key, value in row.items()}
                for row in rows
            ]),
        }
    return snapshot


def _assert_forbidden_effects_unchanged(before, after):
    if before != after:
        changed = sorted(set(before) | set(after))
        changed = [name for name in changed if before.get(name) != after.get(name)]
        raise UserError(
            "Noorix HR/payroll executor touched a forbidden model: %s" % ", ".join(changed)
        )


def _exact_waves(plan):
    """Prove that execution still addresses the sealed 37-wave contract."""
    waves = plan.get("atomic_waves")
    operations = plan.get("operations")
    if not isinstance(waves, list) or not isinstance(operations, list):
        raise UserError("Noorix HR/payroll execution plan has no waves")
    if len(waves) != EXPECTED_ATOMIC_WAVE_COUNT:
        raise UserError(
            "Noorix HR/payroll execution requires exactly %s atomic waves; found %s"
            % (EXPECTED_ATOMIC_WAVE_COUNT, len(waves))
        )
    seen_keys = set()
    seen_identities = set()
    by_identity = {row.get("source_identity"): row for row in operations}
    if len(by_identity) != len(operations) or None in by_identity:
        raise UserError("Noorix HR/payroll execution plan has duplicate source identities")
    for wave in waves:
        key = wave.get("run_key")
        identities = wave.get("source_identities")
        if (
            not isinstance(key, str) or not key.startswith("hr-payroll:")
            or key in seen_keys or wave.get("run_scope") != "payroll_month"
            or wave.get("atomic") is not True or not isinstance(identities, list)
            or not identities or identities != sorted(set(identities))
        ):
            raise UserError("Noorix HR/payroll execution wave contract differs")
        if len(identities) != wave.get("operation_count"):
            raise UserError("Noorix HR/payroll execution wave count differs")
        rows = [by_identity.get(identity) for identity in identities]
        if any(row is None for row in rows):
            raise UserError("Noorix HR/payroll execution wave source identity differs")
        amount = sum((_positive_money(row["amount"], "planned operation") for row in rows), Decimal("0"))
        if amount != _positive_money(wave.get("amount"), "wave total"):
            raise UserError("Noorix HR/payroll execution wave total differs")
        seen_keys.add(key)
        seen_identities.update(identities)
    if seen_identities != set(by_identity):
        raise UserError("Noorix HR/payroll execution waves do not cover every operation")
    return {wave["run_key"]: [by_identity[identity] for identity in wave["source_identities"]] for wave in waves}


def list_hr_payroll_replay_waves(env, path=None):
    """Read-only execution preview, including the exact 37 eligible waves."""
    runtime_guard.assert_rehearsal_database(env)
    plan = plan_hr_payroll_replay(env, path=path)
    wave_rows = _exact_waves(plan)
    return {
        "mode": "read_only_wave_preview",
        "target_database": plan["target_database"],
        "source_archive_sha256": plan["source_archive_sha256"],
        "manifest_sha256": plan["manifest_sha256"],
        "hr_payroll_source_snapshot_sha256": plan["hr_payroll_source_snapshot_sha256"],
        "hr_payroll_source_snapshot_group_hashes": plan["hr_payroll_source_snapshot_group_hashes"],
        "wave_count": len(wave_rows),
        "atomic_waves": plan["atomic_waves"],
    }


def _same_company_account(env, company, binding, label):
    """Rebind one account by exact target id and immutable semantic code."""
    if not isinstance(binding, dict) or not binding.get("id") or not binding.get("code"):
        raise UserError("Noorix HR/payroll %s account binding is missing" % label)
    account = _company_model(env, "account.account", company).browse(binding["id"]).exists()
    if not account or account.code != binding["code"]:
        raise UserError("Noorix HR/payroll %s account binding differs" % label)
    if "company_ids" in account._fields:
        in_company = company.id in account.company_ids.ids
    else:
        in_company = account.company_id == company
    if not in_company:
        raise UserError("Noorix HR/payroll %s account is not in the source company" % label)
    if "deprecated" in account._fields and account.deprecated:
        raise UserError("Noorix HR/payroll %s account is deprecated" % label)
    return account


def _same_company_journal(env, company, binding, label, allowed_types):
    """Rebind an operational journal without accepting a target-id fallback."""
    if not isinstance(binding, dict) or not binding.get("id") or not binding.get("code"):
        raise UserError("Noorix HR/payroll %s journal binding is missing" % label)
    journal = _company_model(env, "account.journal", company).browse(binding["id"]).exists()
    if (
        not journal or journal.company_id != company or journal.code != binding["code"]
        or journal.type not in set(allowed_types) or not journal.active
    ):
        raise UserError("Noorix HR/payroll %s journal binding differs" % label)
    return journal


def _assert_period_unlocked(company, operation_date):
    """Fail before every creation when the company explicitly locks the date."""
    date_value = fields.Date.to_date(operation_date)
    if not date_value:
        raise UserError("Noorix HR/payroll operation date is invalid")
    # Field availability varies slightly across supported Odoo editions.  Each
    # one is checked explicitly if installed; Odoo posting performs its own
    # lock validation again as the final guard.
    for field_name in (
        "fiscalyear_lock_date", "tax_lock_date", "hard_lock_date", "period_lock_date",
    ):
        if field_name not in company._fields:
            continue
        locked_through = company[field_name]
        if locked_through and date_value <= fields.Date.to_date(locked_through):
            raise UserError(
                "Noorix HR/payroll period %s is locked through %s for %s"
                % (date_value, locked_through, company.display_name)
            )
    return date_value


def _operation_targets(env, operation):
    """Rebind every planned target in the current transaction.

    ``plan_hr_payroll_replay`` already proves semantic source-map resolution;
    this second binding pass pins the chosen target ids, types, codes and
    company memberships immediately before writing.
    """
    scope = operation.get("scope")
    kind = operation.get("move_kind")
    if kind not in _EXECUTABLE_SCOPE_KINDS.get(scope, set()):
        raise UserError("Noorix HR/payroll operation is outside the executor allow-list")
    if any(token in " ".join(str(operation.get(key, "")).casefold() for key in (
        "scope", "move_kind", "canonical_key", "reference",
    )) for token in ("cash recovery", "cash disbursement", "advance recovery", "advance disbursement")):
        raise UserError("Noorix HR/payroll executor cannot replay cash recovery or disbursement")

    binding = operation.get("bindings")
    if not isinstance(binding, dict):
        raise UserError("Noorix HR/payroll operation binding is missing")
    company_binding = binding.get("company")
    if not isinstance(company_binding, dict) or not company_binding.get("id"):
        raise UserError("Noorix HR/payroll company binding is missing")
    company = env["res.company"].sudo().with_context(active_test=False).browse(company_binding["id"]).exists()
    if not company or not company.active or company.name != company_binding.get("name"):
        raise UserError("Noorix HR/payroll company binding differs")

    journal = _same_company_journal(env, company, binding.get("journal"), "posting", {"general"})
    # Also prove the semantic selection remains unique in this transaction.
    semantic_journal = _semantic_journal(env, company, journal.code, "general")
    if semantic_journal != journal:
        raise UserError("Noorix HR/payroll posting journal semantic binding differs")

    debit = _same_company_account(env, company, binding.get("debit_account"), "debit")
    advance = scope == "payroll_opening_advance"
    if advance:
        if debit.code != "102090" or debit.account_type != "asset_receivable":
            raise UserError("Noorix opening advance must debit account 102090")
        if _semantic_account(env, company, "102090", {"asset_receivable"}) != debit:
            raise UserError("Noorix opening advance debit semantic binding differs")
    elif debit.code == "102090" or debit.account_type != "expense":
        raise UserError("Noorix historical payroll/HR debit account differs")
    elif _semantic_account(env, company, debit.code, {"expense"}) != debit:
        raise UserError("Noorix historical payroll/HR debit semantic binding differs")

    employee = False
    employee_binding = binding.get("employee")
    if employee_binding:
        employee = _employee(env, company, employee_binding.get("name"))
        if (
            employee.id != employee_binding.get("id")
            or employee.work_contact_id.id != employee_binding.get("partner_id")
        ):
            raise UserError("Noorix HR/payroll employee semantic binding differs")
    if advance and not employee:
        raise UserError("Noorix opening advance has no mapped employee")

    split_bindings = binding.get("credit_splits") or []
    credit_binding = binding.get("credit_account")
    liquidity_binding = binding.get("liquidity_journal")
    if advance:
        if split_bindings or liquidity_binding or not credit_binding:
            raise UserError("Noorix opening advance may not use a liquidity credit")
        credit = _same_company_account(env, company, credit_binding, "opening advance credit")
        if credit.code != "999999" or credit.account_type != "equity_unaffected":
            raise UserError("Noorix opening advance must credit account 999999")
        credits = [(credit, _positive_money(operation.get("amount"), "opening advance amount"))]
    elif split_bindings:
        if credit_binding or liquidity_binding:
            raise UserError("Noorix split historical settlement has conflicting liquidity bindings")
        credits = []
        for index, split in enumerate(split_bindings, start=1):
            liquidity = _same_company_journal(
                env, company, split.get("journal"), "settlement split %s" % index, {"bank", "cash"},
            )
            credit = _same_company_account(env, company, split.get("account"), "settlement split %s" % index)
            if liquidity.default_account_id != credit:
                raise UserError("Noorix settlement split does not use its mapped liquidity account")
            credits.append((credit, _positive_money(split.get("amount"), "settlement split %s" % index)))
    else:
        if not credit_binding or not liquidity_binding:
            raise UserError("Noorix historical settlement has no mapped liquidity credit")
        liquidity = _same_company_journal(env, company, liquidity_binding, "settlement", {"bank", "cash"})
        credit = _same_company_account(env, company, credit_binding, "settlement")
        if liquidity.default_account_id != credit:
            raise UserError("Noorix settlement does not use its mapped liquidity account")
        credits = [(credit, _positive_money(operation.get("amount"), "historical settlement amount"))]

    amount = _positive_money(operation.get("amount"), "operation amount")
    if sum((value for _account, value in credits), Decimal("0")) != amount:
        raise UserError("Noorix HR/payroll credit splits do not balance the source amount")
    return {
        "company": company,
        "journal": journal,
        "debit": debit,
        "credits": credits,
        "employee": employee,
        "amount": amount,
    }


def _assert_move_matches_operation(move, operation, targets, *, posted):
    """Check exact double-entry shape before and after posting."""
    if (
        not move or move.move_type != "entry" or move.company_id != targets["company"]
        or move.journal_id != targets["journal"] or move.date != fields.Date.to_date(operation["date"])
        or move.ref != operation["reference"]
    ):
        raise UserError("Noorix HR/payroll account move header differs from its plan")
    if posted and move.state != "posted":
        raise UserError("Noorix HR/payroll account move was not posted")
    if not posted and move.state != "draft":
        raise UserError("Noorix HR/payroll account move is not a draft before posting")

    lines = move.line_ids
    expected_credit_count = len(targets["credits"])
    if len(lines) != expected_credit_count + 1:
        raise UserError("Noorix HR/payroll account move has unexpected lines")
    debit_lines = lines.filtered(lambda line: _money(line.debit, "move debit") > 0)
    credit_lines = lines.filtered(lambda line: _money(line.credit, "move credit") > 0)
    if len(debit_lines) != 1 or len(credit_lines) != expected_credit_count:
        raise UserError("Noorix HR/payroll account move is not a simple balanced entry")
    debit_line = debit_lines[0]
    if (
        debit_line.account_id != targets["debit"]
        or _money(debit_line.debit, "move debit") != targets["amount"]
        or _money(debit_line.credit, "move debit credit") != Decimal("0.00")
    ):
        raise UserError("Noorix HR/payroll debit line differs from its plan")
    expected_partner_id = (
        targets["employee"].work_contact_id.id
        if operation["scope"] == "payroll_opening_advance" else False
    )
    if debit_line.partner_id.id != expected_partner_id:
        raise UserError("Noorix HR/payroll debit partner differs from its plan")
    if any(line.partner_id for line in credit_lines):
        raise UserError("Noorix HR/payroll credit line unexpectedly has a partner")

    observed_credits = Counter(
        (line.account_id.id, str(_money(line.credit, "move credit"))) for line in credit_lines
    )
    expected_credits = Counter(
        (account.id, str(amount)) for account, amount in targets["credits"]
    )
    if observed_credits != expected_credits:
        raise UserError("Noorix HR/payroll credit lines differ from their plan")
    debit_total = sum((_money(line.debit, "move debit") for line in lines), Decimal("0"))
    credit_total = sum((_money(line.credit, "move credit") for line in lines), Decimal("0"))
    if debit_total != targets["amount"] or credit_total != targets["amount"]:
        raise UserError("Noorix HR/payroll account move is not balanced at 0.01 precision")


def _create_posted_move(env, operation, targets):
    """Create exactly one balanced journal entry, then post and re-verify it."""
    _assert_period_unlocked(targets["company"], operation["date"])
    partner_id = targets["employee"].work_contact_id.id if operation["scope"] == "payroll_opening_advance" else False
    line_vals = [Command.create({
        "name": operation["reference"],
        "account_id": targets["debit"].id,
        "debit": float(targets["amount"]),
        "credit": 0.0,
        "partner_id": partner_id,
    })]
    for credit_account, amount in targets["credits"]:
        line_vals.append(Command.create({
            "name": operation["reference"],
            "account_id": credit_account.id,
            "debit": 0.0,
            "credit": float(amount),
        }))
    Move = env["account.move"].sudo().with_company(targets["company"]).with_context(
        allowed_company_ids=[targets["company"].id], check_move_validity=True,
    )
    move = Move.create({
        "move_type": "entry",
        "company_id": targets["company"].id,
        "journal_id": targets["journal"].id,
        "date": operation["date"],
        "ref": operation["reference"],
        "line_ids": line_vals,
    })
    _assert_move_matches_operation(move, operation, targets, posted=False)
    move.action_post()
    _assert_move_matches_operation(move, operation, targets, posted=True)
    return move


def _create_source_map(env, operation, move, run):
    """Append one immutable source map; pre-existing maps are never reused here."""
    Map = _writer_model(env, "baseer.noorix.rehearsal.source.map")
    existing = Map.search([
        ("scope", "=", operation["scope"]),
        ("source_identity", "=", operation["source_identity"]),
    ])
    if existing:
        raise UserError("Noorix HR/payroll source map already exists for a fresh replay wave")
    return Map.create({
        "scope": operation["scope"],
        "source_identity": operation["source_identity"],
        "source_row_sha256": operation["source_evidence_sha256"],
        "source_archive_sha256": runtime_guard.SOURCE_ARCHIVE_SHA256,
        "canonical_key": operation["canonical_key"],
        "target_model": "account.move",
        "target_res_id": move.id,
        "run_id": run.id,
    })


def _validate_committed_wave(env, run, run_key, operations, plan):
    """Verify a completed wave without writing a row, map, or move."""
    if run.scope != "payroll_month" or run.run_key != run_key:
        raise UserError("Noorix HR/payroll committed run identity differs")
    if (
        run.source_archive_sha256 != runtime_guard.SOURCE_ARCHIVE_SHA256
        or run.manifest_sha256 != runtime_guard.SOURCE_MANIFEST_SHA256
    ):
        raise UserError("Noorix HR/payroll committed run source pins differ")
    if run.state not in {"committed", "reconciled"}:
        raise UserError("Noorix HR/payroll existing run is not committed")
    try:
        result = json.loads(run.result_json or "")
    except (TypeError, ValueError) as error:
        raise UserError("Noorix HR/payroll committed run has invalid evidence") from error
    if (
        not isinstance(result, dict)
        or result.get("run_key") != run_key
        or result.get("hr_payroll_source_snapshot_sha256")
        != runtime_guard.HR_PAYROLL_SOURCE_SNAPSHOT_SHA256
        or result.get("snapshot_group_hashes") != plan["hr_payroll_source_snapshot_group_hashes"]
        or result.get("operation_count") != len(operations)
        or _money(result.get("amount"), "committed wave amount")
        != sum((_positive_money(item["amount"], "committed operation") for item in operations), Decimal("0"))
    ):
        raise UserError("Noorix HR/payroll committed run evidence differs")

    Map = env["baseer.noorix.rehearsal.source.map"].sudo().with_context(active_test=False)
    mappings = Map.search([("run_id", "=", run.id)], order="id")
    expected = {(item["scope"], item["source_identity"]): item for item in operations}
    observed = {(item.scope, item.source_identity): item for item in mappings}
    if len(mappings) != len(expected) or set(observed) != set(expected):
        raise UserError("Noorix HR/payroll committed source maps differ")
    target_ids = set()
    for key, operation in expected.items():
        mapping = observed[key]
        if (
            mapping.source_row_sha256 != operation["source_evidence_sha256"]
            or mapping.source_archive_sha256 != runtime_guard.SOURCE_ARCHIVE_SHA256
            or mapping.canonical_key != operation["canonical_key"]
            or mapping.target_model != "account.move" or not mapping.target_res_id
            or mapping.run_id != run
        ):
            raise UserError("Noorix HR/payroll committed source map differs")
        if mapping.target_res_id in target_ids:
            raise UserError("Noorix HR/payroll committed wave reuses an account move")
        target_ids.add(mapping.target_res_id)
        move = env["account.move"].sudo().with_context(active_test=False).browse(mapping.target_res_id).exists()
        targets = _operation_targets(env, operation)
        _assert_move_matches_operation(move, operation, targets, posted=True)
    return result


def _start_run(env, run_key):
    return _writer_model(env, "baseer.noorix.rehearsal.run").create({
        "run_key": run_key,
        "scope": "payroll_month",
        "source_archive_sha256": runtime_guard.SOURCE_ARCHIVE_SHA256,
        "manifest_sha256": runtime_guard.SOURCE_MANIFEST_SHA256,
        "state": "planned",
    })


def apply_hr_payroll_replay_wave(env, run_key, path=None):
    """Apply one planned payroll/HR wave inside the caller's transaction.

    This is intentionally the sole mutation API in this module.  It never
    calls ``commit`` and it has no bulk/apply-all variant.  On any error its
    savepoint rolls back the account moves, source maps and run evidence for
    the selected wave together.  A committed/reconciled run is verified
    read-only and returned unchanged.
    """
    runtime_guard.assert_rehearsal_database(env)
    if not isinstance(run_key, str) or not run_key:
        raise UserError("Noorix HR/payroll replay requires one non-empty run key")

    # The lock is acquired before re-planning.  Every source map, target, and
    # snapshot hash is therefore rebound under the same transaction lock that
    # protects the selected one of the 37 waves.
    _wave_lock(env, run_key)
    plan = plan_hr_payroll_replay(env, path=path)
    waves = _exact_waves(plan)
    operations = waves.get(run_key)
    if operations is None:
        raise UserError("Noorix HR/payroll replay run key is not an approved atomic wave")

    forbidden_before = _forbidden_effect_snapshot(env)
    Run = _writer_model(env, "baseer.noorix.rehearsal.run")
    existing = Run.search([("run_key", "=", run_key)])
    if existing:
        existing = _one(existing, "HR/payroll replay run")
        result = _validate_committed_wave(env, existing, run_key, operations, plan)
        _assert_forbidden_effects_unchanged(forbidden_before, _forbidden_effect_snapshot(env))
        return result
    if any(item.get("state") != "planned" for item in operations):
        raise UserError("Noorix HR/payroll replay cannot create a run with existing provenance")

    with env.cr.savepoint():
        # Every target is rebound once more immediately before writes.  This
        # avoids applying a plan made under a stale employee/account/journal
        # binding even if a caller held the transaction open.
        bound_operations = [(item, _operation_targets(env, item)) for item in operations]
        run = _start_run(env, run_key)
        written = []
        for operation, targets in bound_operations:
            move = _create_posted_move(env, operation, targets)
            mapping = _create_source_map(env, operation, move, run)
            written.append({
                "scope": operation["scope"],
                "source_identity": operation["source_identity"],
                "source_evidence_sha256": operation["source_evidence_sha256"],
                "canonical_key": operation["canonical_key"],
                "move_id": move.id,
                "source_map_id": mapping.id,
                "amount": str(targets["amount"]),
            })
        result = {
            "writer": "baseer_noorix_rehearsal_replay.hr_payroll_replay",
            "mode": "rehearsal_wave",
            "run_key": run_key,
            "target_database": env.cr.dbname,
            "source_archive_sha256": runtime_guard.SOURCE_ARCHIVE_SHA256,
            "manifest_sha256": runtime_guard.SOURCE_MANIFEST_SHA256,
            "hr_payroll_source_snapshot_sha256": runtime_guard.HR_PAYROLL_SOURCE_SNAPSHOT_SHA256,
            "snapshot_group_hashes": plan["hr_payroll_source_snapshot_group_hashes"],
            "operation_count": len(written),
            "amount": str(sum((_money(item["amount"], "written operation") for item in written), Decimal("0"))),
            "operations": written,
        }
        _assert_forbidden_effects_unchanged(forbidden_before, _forbidden_effect_snapshot(env))
        run.with_context(**{WRITER_CONTEXT: True}).write({
            "state": "committed",
            "result_json": json.dumps(result, ensure_ascii=False, sort_keys=True),
        })
    return result
