"""Import-safe QA writer for the owner-declared Karak net-payroll settlement."""

from __future__ import annotations

import hashlib
import json
import os
import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from odoo import Command, fields
from odoo.exceptions import UserError


PAYLOAD_PATH = Path(
    "/mnt/noorix-payload/runs/20260913-karak-net-payroll-settlement-qa-1/"
    "karak-net-payroll-settlement-payload.json"
)
EXPECTED_PAYLOAD_SHA256 = "5657a4d93119a0a9faf1e35ebe80649ee390975ed61e3de0c3aade5eda0217df"
TARGET_DATABASE = "baseer_noorix_data_migration_qa_20260912"
PRODUCTION_DATABASE = "baseer_dev"
ARCHIVE_SHA256 = "024606ADD82DCD78DC1835828A12D7B22C56E34924FF998ABF752134160E79E2"
PURCHASE_PAYLOAD_SHA256 = "c6fc968d3b014213113b386ec1a53cc7e4f26930fc1bd828dd5c58b8df6d6785"
SOURCE_TENANT_ID = "default-tenant-noorix-2024"
SOURCE_COMPANY_ID = "cmnvui7x70001etuf8p6xz3d0"
SOURCE_PAYROLL_RUN_ID = "cmotzl3tn016i11ch29ycedtd"
SOURCE_RUN_NUMBER = "PR-2605-001"
TARGET_COMPANY_ID = 4
TARGET_BANK_JOURNAL_ID = 62
WRITER_CONTEXT = "baseer_noorix_migration_writer"
RUN_NAME = "20260913-noorix-karak-net-payroll-settlement-qa-1"
APPROVED_POLICY = "karak_owner_declared_net_payroll_paid_from_bank_one_native_move"
TARGET_REFERENCE = "Noorix PR-2605-001 — owner-declared historical net salary paid"
CENT = Decimal("0.01")
RAW_DECIMAL_RE = re.compile(r"^(?:0|[1-9][0-9]*)\.[0-9]{4}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PURCHASE_RUN_NAMES = tuple(
    "20260913-noorix-karak-purchase-history-qa-%s-1" % month
    for month in ("2026-03", "2026-04", "2026-05", "2026-06", "2026-07")
)
EXPECTED_REPORT = {
    "source_payroll_runs": 1,
    "source_items": 8,
    "source_accrual_rows": 5,
    "source_gross": "19266.6700",
    "source_advances": "9050.0000",
    "source_net": "10216.6700",
    "target_amount": "10216.67",
    "target_moves": 1,
    "target_move_lines": 2,
}
EXPECTED_ALLOWLIST = {
    "target_company_id": 4,
    "bank_journal": {"id": TARGET_BANK_JOURNAL_ID, "code": "BNK1", "type": "bank", "default_account_id": 792},
    "salary_expense_account": {"id": 708, "code": "400003", "type": "expense"},
    "bank_account": {"id": 792, "code": "101001", "type": "asset_cash"},
    "unchanged_accounts": [
        {"id": 801, "code": "201090", "type": "liability_payable"},
        {"id": 802, "code": "102090", "type": "asset_receivable"},
    ],
    "forbidden_journal_ids": [68, 69, 70],
}


def fail(message):
    raise UserError("Noorix QA Karak payroll settlement: %s" % message)


def require(condition, message):
    if not condition:
        fail(message)


def source_decimal(value):
    text = str(value)
    if not RAW_DECIMAL_RE.fullmatch(text):
        raise ValueError("source value must be a non-negative four-decimal string")
    return Decimal(text)


def money(value):
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def validate_payload(payload):
    """Pure strict validation of the one-run, one-move approved contract."""
    require(isinstance(payload, dict), "payload root must be an object")
    require(payload.get("target_database") == TARGET_DATABASE, "payload target database differs")
    require(payload.get("source_archive_sha256") == ARCHIVE_SHA256, "source archive SHA-256 differs")
    require(payload.get("approved_policy") == APPROVED_POLICY, "approved owner-declaration policy differs")
    require(payload.get("report") == EXPECTED_REPORT, "payload report differs from the approved payroll scope")
    require(payload.get("allowlist") == EXPECTED_ALLOWLIST, "payload accounting allowlist differs")
    row = payload.get("settlement")
    require(isinstance(row, dict), "payload must contain exactly one settlement object")
    exact = {
        "source_system": "noorix",
        "source_tenant_id": SOURCE_TENANT_ID,
        "source_company_id": SOURCE_COMPANY_ID,
        "source_payroll_run_id": SOURCE_PAYROLL_RUN_ID,
        "source_run_number": SOURCE_RUN_NUMBER,
        "source_archive_sha256": ARCHIVE_SHA256,
        "canonical_key": "payroll-settlement:%s:%s" % (SOURCE_COMPANY_ID, SOURCE_PAYROLL_RUN_ID),
        "source_accrual_count": 5,
        "source_gross_raw": EXPECTED_REPORT["source_gross"],
        "source_advances_raw": EXPECTED_REPORT["source_advances"],
        "source_net_raw": EXPECTED_REPORT["source_net"],
        "source_period": "2026-04-01",
        "source_completion_date": "2026-05-06",
        "target_posting_date": "2026-05-06",
        "date_basis": "owner_declaration_plus_source_completion",
        "owner_declaration": "treat_net_as_paid_from_bank",
        "decision": "create_owner_declared_bank_move",
        "target_company_id": 4,
        "target_journal_id": TARGET_BANK_JOURNAL_ID,
        "target_salary_expense_account_id": 708,
        "target_bank_account_id": 792,
        "target_amount": "10216.67",
        "target_reference": TARGET_REFERENCE,
    }
    for field_name, expected in exact.items():
        require(row.get(field_name) == expected, "settlement field differs: %s" % field_name)
    require(SHA256_RE.fullmatch(str(row.get("source_row_sha256", ""))), "source payroll row SHA-256 is invalid")
    require(SHA256_RE.fullmatch(str(row.get("source_accrual_rows_sha256", ""))), "source accrual rows SHA-256 is invalid")
    try:
        gross = source_decimal(row["source_gross_raw"])
        advances = source_decimal(row["source_advances_raw"])
        net = source_decimal(row["source_net_raw"])
    except ValueError as exc:
        fail("raw Decimal evidence is invalid: %s" % exc)
    require(gross - advances == net, "source gross less advances does not equal net")
    require(money(net) == money(row["target_amount"]), "target amount differs from source net")
    return row


def load_payload(path=PAYLOAD_PATH, expected_sha256=None):
    supplied = (expected_sha256 or os.environ.get("NOORIX_KARAK_PAYROLL_PAYLOAD_SHA256", "") or EXPECTED_PAYLOAD_SHA256).strip().lower()
    require(SHA256_RE.fullmatch(supplied), "payroll payload receipt must be a 64-character SHA-256")
    require(supplied == EXPECTED_PAYLOAD_SHA256, "payroll payload receipt differs from the frozen approved SHA-256")
    payload_bytes = Path(path).read_bytes()
    actual = hashlib.sha256(payload_bytes).hexdigest()
    require(actual == EXPECTED_PAYLOAD_SHA256, "payload SHA-256 differs from the frozen artifact")
    payload = json.loads(payload_bytes.decode("utf-8"))
    row = validate_payload(payload)
    return payload, row, actual


def _writer_model(env, name, company=None):
    model = env[name].sudo().with_context(**{WRITER_CONTEXT: True})
    if company:
        model = model.with_company(company).with_context(allowed_company_ids=[company.id])
    return model


def _account_code(account, company):
    return account.with_company(company).code or ""


def _account_effect(env, company, account):
    lines = env["account.move.line"].sudo().with_company(company).with_context(
        allowed_company_ids=[company.id]
    ).search([
        ("company_id", "=", company.id),
        ("account_id", "=", account.id),
        ("parent_state", "=", "posted"),
    ])
    return (
        len(lines),
        sum((money(line.debit) for line in lines), Decimal("0.00")),
        sum((money(line.credit) for line in lines), Decimal("0.00")),
        sum((money(line.balance) for line in lines), Decimal("0.00")),
    )


def _forbidden_snapshot(env, company):
    model_domains = {
        "res.partner": [],
        "account.payment": [("company_id", "=", company.id)],
        "vendor_bills": [
            ("company_id", "=", company.id),
            ("move_type", "in", ("in_invoice", "in_refund")),
        ],
        "stock.move": [("company_id", "=", company.id)],
        "stock.picking": [("company_id", "=", company.id)],
        "pos.order": [("company_id", "=", company.id)],
        "pos.session": [("company_id", "=", company.id)],
    }
    result = {}
    for key, domain in model_domains.items():
        model_name = "account.move" if key == "vendor_bills" else key
        result[key] = env[model_name].sudo().search_count(domain)
    for model_name in ("hr.employee", "hr.payslip", "hr.payslip.run", "baseer.payroll.run"):
        if model_name in env.registry.models:
            model = env[model_name].sudo()
            domain = [("company_id", "=", company.id)] if "company_id" in model._fields else []
            result[model_name] = model.search_count(domain)
    return result


def _validate_target(env, payload, row, check_lock_date=True):
    company = env["res.company"].sudo().with_context(active_test=False).browse(4).exists()
    require(company and company.active and company.country_id.code == "SA" and company.currency_id.name == "SAR", "target company 4 is not active Saudi/SAR")
    CompanyMap = _writer_model(env, "baseer.noorix.company.map", company)
    company_map = CompanyMap.search([
        ("source_system", "=", "noorix"),
        ("source_tenant_id", "=", SOURCE_TENANT_ID),
        ("source_company_id", "=", SOURCE_COMPANY_ID),
        ("company_id", "=", company.id),
    ], limit=2)
    require(len(company_map) == 1 and company_map.source_archive_sha256 == ARCHIVE_SHA256 and company_map.decision == "create_historical_company", "approved historical Karak company mapping is missing")

    Run = _writer_model(env, "baseer.noorix.migration.run", company)
    purchase_runs = Run.search([("name", "in", list(PURCHASE_RUN_NAMES))])
    require(set(purchase_runs.mapped("name")) == set(PURCHASE_RUN_NAMES), "all five Karak purchase months must reconcile before payroll settlement")
    require(all(run.scope == "purchase_history" and run.state == "reconciled" and run.payload_sha256 == PURCHASE_PAYLOAD_SHA256 and run.source_archive_sha256 == ARCHIVE_SHA256 for run in purchase_runs), "a prerequisite Karak purchase run differs")

    accounts = env["account.account"].sudo().with_company(company).with_context(
        active_test=False, allowed_company_ids=[company.id]
    ).browse([708, 792, 801, 802]).exists()
    require(set(accounts.ids) == {708, 792, 801, 802}, "finite payroll account allowlist is incomplete")
    account_by_id = {account.id: account for account in accounts}
    expected_accounts = {
        708: ("400003", "expense"), 792: ("101001", "asset_cash"),
        801: ("201090", "liability_payable"), 802: ("102090", "asset_receivable"),
    }
    for account_id, (code, account_type) in expected_accounts.items():
        account = account_by_id[account_id]
        require(account.active and _account_code(account, company) == code and account.account_type == account_type, "payroll account differs: %s" % account_id)

    journals = env["account.journal"].sudo().with_context(active_test=False).browse([TARGET_BANK_JOURNAL_ID, 68, 69, 70]).exists()
    journal_by_id = {journal.id: journal for journal in journals}
    bank_journal = journal_by_id.get(TARGET_BANK_JOURNAL_ID)
    require(bank_journal and bank_journal.active and bank_journal.company_id == company and bank_journal.code == "BNK1" and bank_journal.type == "bank" and bank_journal.default_account_id.id == 792, "BNK1/62 differs")
    require(journal_by_id.get(68) and journal_by_id[68].code == "BPAY", "forbidden BPAY/68 identity differs")
    require(journal_by_id.get(69) and journal_by_id[69].code == "PSBNK" and journal_by_id.get(70) and journal_by_id[70].code == "PSCSH", "forbidden POS journal identities differ")
    require(row["target_journal_id"] == TARGET_BANK_JOURNAL_ID and not ({row["target_journal_id"]} & set(payload["allowlist"]["forbidden_journal_ids"])), "payload selects a forbidden journal")
    posting_date = fields.Date.to_date(row["target_posting_date"])
    if check_lock_date:
        require(not company._get_violated_lock_dates(posting_date, False, bank_journal), "owner-declared posting date is locked")
    return company, bank_journal, account_by_id


def _verify_mapping(mapping, row, company):
    direct_fields = (
        "source_system", "source_tenant_id", "source_company_id", "source_payroll_run_id",
        "source_run_number", "source_row_sha256", "source_accrual_rows_sha256",
        "source_archive_sha256", "canonical_key", "source_gross_raw",
        "source_advances_raw", "source_net_raw", "date_basis", "owner_declaration", "decision",
    )
    for field_name in direct_fields:
        require(mapping[field_name] == row[field_name], "payroll mapping evidence differs: %s" % field_name)
    require(mapping.source_accrual_count == row["source_accrual_count"], "source accrual count differs")
    require(mapping.source_period == fields.Date.to_date(row["source_period"]), "source payroll period differs")
    require(mapping.source_completion_date == fields.Date.to_date(row["source_completion_date"]), "source completion date differs")
    require(mapping.target_posting_date == fields.Date.to_date(row["target_posting_date"]), "target posting date differs")
    require(mapping.company_id == company and mapping.journal_id.id == TARGET_BANK_JOURNAL_ID, "payroll mapping target company/journal differs")
    require(mapping.salary_expense_account_id.id == 708 and mapping.bank_account_id.id == 792, "payroll mapping target accounts differ")
    require(money(mapping.target_amount) == money(row["target_amount"]), "payroll mapping amount differs")
    move = mapping.move_id
    require(move.exists() and move.company_id == company and move.move_type == "entry" and move.state == "posted", "mapped payroll move differs")
    require(move.journal_id.id == TARGET_BANK_JOURNAL_ID and move.date == mapping.target_posting_date and move.ref == TARGET_REFERENCE, "mapped payroll move journal/date/reference differs")
    require(not move.partner_id and not move.line_ids.partner_id, "payroll settlement move must not have a partner")
    require(len(move.line_ids) == 2, "payroll settlement move must contain exactly two lines")
    debit = move.line_ids.filtered(lambda line: line.account_id.id == 708)
    credit = move.line_ids.filtered(lambda line: line.account_id.id == 792)
    require(len(debit) == len(credit) == 1, "payroll settlement move accounts differ")
    amount = money(row["target_amount"])
    require(money(debit.debit) == amount and money(debit.credit) == Decimal("0.00"), "salary-expense debit differs")
    require(money(credit.credit) == amount and money(credit.debit) == Decimal("0.00"), "bank credit differs")
    require(money(sum(move.line_ids.mapped("balance"))) == Decimal("0.00"), "payroll settlement move is unbalanced")
    require(not move.line_ids.filtered(lambda line: line.account_id.id in {801, 802} or line.account_id.account_type == "liability_payable"), "payroll settlement touched a forbidden payable/advance account")
    return move


def apply_settlement(env, payload_path=PAYLOAD_PATH, expected_sha256=None):
    """Apply the one-move settlement in the caller-owned transaction."""
    require(env.cr.dbname != PRODUCTION_DATABASE, "production baseer_dev is forbidden")
    require(env.cr.dbname == TARGET_DATABASE, "target database must be the isolated Noorix QA database")
    payload, row, payload_sha256 = load_payload(payload_path, expected_sha256)

    # This xact lock intentionally precedes every run or provenance replay lookup.
    env.cr.execute(
        "SELECT pg_advisory_xact_lock(hashtext(%s))",
        ["%s:noorix-karak-net-payroll" % env.cr.dbname],
    )
    Run = _writer_model(env, "baseer.noorix.migration.run")
    SettlementMap = _writer_model(env, "baseer.noorix.payroll.settlement.map")
    existing_run = Run.search([("name", "=", RUN_NAME)], limit=2)
    require(len(existing_run) <= 1, "payroll settlement run identity is ambiguous")
    if existing_run:
        require(existing_run.payload_sha256 == payload_sha256 and existing_run.source_archive_sha256 == ARCHIVE_SHA256, "existing run belongs to changed evidence")
        require(existing_run.scope == "payroll_settlement" and existing_run.state == "reconciled", "existing payroll settlement run is incomplete")
        company, _journal, _accounts = _validate_target(env, payload, row, check_lock_date=False)
        mappings = SettlementMap.search([("run_id", "=", existing_run.id)])
        require(len(mappings) == 1, "replay payroll settlement mapping count differs")
        move = _verify_mapping(mappings, row, company)
        return {"status": "already_reconciled", "run_id": existing_run.id, "mapping_id": mappings.id, "move_id": move.id, "amount": "10216.67"}

    require(not SettlementMap.search([
        ("source_system", "=", "noorix"),
        ("source_tenant_id", "=", SOURCE_TENANT_ID),
        ("source_company_id", "=", SOURCE_COMPANY_ID),
        ("source_payroll_run_id", "=", SOURCE_PAYROLL_RUN_ID),
    ], limit=1), "source payroll run is already mapped by another run")
    company, journal, accounts = _validate_target(env, payload, row)
    Move = env["account.move"].sudo().with_company(company).with_context(allowed_company_ids=[company.id])
    MoveLine = env["account.move.line"].sudo().with_company(company).with_context(allowed_company_ids=[company.id])
    before_move_count = Move.search_count([("company_id", "=", company.id)])
    before_line_count = MoveLine.search_count([("company_id", "=", company.id)])
    before_forbidden = _forbidden_snapshot(env, company)
    protected_effects = {account_id: _account_effect(env, company, accounts[account_id]) for account_id in (801, 802)}

    run = Run.create({
        "name": RUN_NAME,
        "source_archive_sha256": ARCHIVE_SHA256,
        "source_tenant_id": SOURCE_TENANT_ID,
        "payload_sha256": payload_sha256,
        "scope": "payroll_settlement",
        "state": "planned",
        "started_at": fields.Datetime.now(),
        "result_json": json.dumps({"stage": "preflight_passed", "source_run_number": SOURCE_RUN_NUMBER}, sort_keys=True),
    })
    posting_date = fields.Date.to_date(row["target_posting_date"])
    amount = money(row["target_amount"])
    move = Move.create({
        "move_type": "entry",
        "company_id": company.id,
        "journal_id": journal.id,
        "date": posting_date,
        "ref": TARGET_REFERENCE,
        "line_ids": [
            Command.create({
                "name": "Noorix PR-2605-001 — owner-declared historical net salary",
                "account_id": accounts[708].id,
                "partner_id": False,
                "debit": float(amount),
                "credit": 0.0,
            }),
            Command.create({
                "name": "Noorix PR-2605-001 — owner-declared bank payment",
                "account_id": accounts[792].id,
                "partner_id": False,
                "debit": 0.0,
                "credit": float(amount),
            }),
        ],
    })
    move.action_post()
    mapping = SettlementMap.create({
        "source_system": row["source_system"],
        "source_tenant_id": row["source_tenant_id"],
        "source_company_id": row["source_company_id"],
        "source_payroll_run_id": row["source_payroll_run_id"],
        "source_run_number": row["source_run_number"],
        "source_row_sha256": row["source_row_sha256"],
        "source_accrual_rows_sha256": row["source_accrual_rows_sha256"],
        "source_accrual_count": row["source_accrual_count"],
        "source_archive_sha256": row["source_archive_sha256"],
        "canonical_key": row["canonical_key"],
        "source_gross_raw": row["source_gross_raw"],
        "source_advances_raw": row["source_advances_raw"],
        "source_net_raw": row["source_net_raw"],
        "source_period": fields.Date.to_date(row["source_period"]),
        "source_completion_date": fields.Date.to_date(row["source_completion_date"]),
        "target_posting_date": posting_date,
        "date_basis": row["date_basis"],
        "owner_declaration": row["owner_declaration"],
        "decision": row["decision"],
        "company_id": company.id,
        "journal_id": journal.id,
        "salary_expense_account_id": accounts[708].id,
        "bank_account_id": accounts[792].id,
        "target_amount": row["target_amount"],
        "move_id": move.id,
        "run_id": run.id,
    })
    _verify_mapping(mapping, row, company)

    require(Move.search_count([("company_id", "=", company.id)]) == before_move_count + 1, "writer created an unexpected extra/missing move")
    require(MoveLine.search_count([("company_id", "=", company.id)]) == before_line_count + 2, "writer created an unexpected extra/missing move line")
    require(_forbidden_snapshot(env, company) == before_forbidden, "writer changed a forbidden payment/vendor/partner/payroll/stock/POS model")
    require(all(_account_effect(env, company, accounts[account_id]) == protected_effects[account_id] for account_id in (801, 802)), "salary-payable or employee-advance account changed")
    require(not move.line_ids.partner_id and journal.id == TARGET_BANK_JOURNAL_ID and journal.id not in {68, 69, 70}, "writer violated the partner/journal boundary")

    result = {
        "status": "reconciled", "company_id": company.id,
        "source_payroll_runs": 1, "move_id": move.id, "move_lines": 2,
        "amount": "10216.67", "salary_payable_effect": "0.00",
        "employee_advance_effect": "0.00", "payments_created": 0,
        "vendor_bills_created": 0, "stock_moves_created": 0,
    }
    run.write({
        "state": "reconciled", "finished_at": fields.Datetime.now(),
        "result_json": json.dumps(result, ensure_ascii=False, sort_keys=True),
    })
    return {"run_id": run.id, "mapping_id": mapping.id, **result}
