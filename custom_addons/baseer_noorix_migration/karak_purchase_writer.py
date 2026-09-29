"""Apply one approved Karak purchase-history month to the isolated QA database.

The module is import-safe: importing it exposes validation helpers and never
writes.  Executing it through an Odoo shell (where ``env`` is present) applies
exactly the month selected by ``NOORIX_KARAK_MONTH``.  The surrounding shell
owns the transaction; this writer deliberately contains no commit or savepoint.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from odoo import Command, fields
from odoo.exceptions import UserError


PAYLOAD_PATH = Path(
    "/mnt/noorix-payload/runs/20260913-karak-purchase-history-qa-1/karak-purchase-payload.json"
)
TARGET_DATABASE = "baseer_noorix_data_migration_qa_20260912"
PRODUCTION_DATABASE = "baseer_dev"
ARCHIVE_SHA256 = "024606ADD82DCD78DC1835828A12D7B22C56E34924FF998ABF752134160E79E2"
SOURCE_TENANT_ID = "default-tenant-noorix-2024"
SOURCE_COMPANY_ID = "cmnvui7x70001etuf8p6xz3d0"
TARGET_COMPANY_ID = 4
WRITER_CONTEXT = "baseer_noorix_migration_writer"
RUN_PREFIX = "20260913-noorix-karak-purchase-history-qa"
APPROVED_POLICY = "karak_306_paid_vendor_bills_native_accounting_monthly_atomic"
CENT = Decimal("0.01")
SOURCE_SCALE = Decimal("0.0001")
VAT_RATE = Decimal("1.15")
RAW_DECIMAL_RE = re.compile(r"^(?:0|[1-9][0-9]*)\.[0-9]{4}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_REPORT = {
    "source_documents": 306,
    "taxable_documents": 228,
    "no_tax_documents": 78,
    "category_decisions": 15,
    "source_net": "56425.8068",
    "source_tax": "6686.4972",
    "source_gross": "63112.3040",
    "target_net": "56425.71",
    "target_tax": "6686.59",
    "target_gross": "63112.30",
    "months": {
        "2026-03": {"documents": 3, "gross": "2951.03"},
        "2026-04": {"documents": 144, "gross": "25771.75"},
        "2026-05": {"documents": 104, "gross": "21213.50"},
        "2026-06": {"documents": 53, "gross": "9851.44"},
        "2026-07": {"documents": 2, "gross": "3324.58"},
    },
}
EXPECTED_ALLOWLIST = {
    "target_company_id": 4,
    "purchase_journal": {"id": 58, "code": "BILL", "type": "purchase"},
    "payment_journals": {
        "bank": {"journal_id": 62, "journal_code": "BNK1", "journal_type": "bank", "liquidity_account_code": "101001"},
        "cash": {"journal_id": 67, "journal_code": "CSH1", "journal_type": "cash", "liquidity_account_code": "105001"},
    },
    "forbidden_journal_ids": [69, 70],
    "purchase_tax_id": 139,
}
ALLOWED_ACCOUNT_CODES = {
    "400018", "400020", "400047", "400019", "400042", "400015",
    "400072", "400050", "106003",
}
ALLOWED_DECISIONS = {
    "reuse_existing_service",
    "create_historical_service",
    "document_expense_override",
    "document_asset_override",
}
ALLOWED_DOCUMENT_DECISIONS = {"create_paid_vendor_bill", "capitalize_cashier_computer"}
FINITE_PRODUCT_POLICY = {
    "BASEER-SVC-ELECTRICITY": ("400018", "tax_when_source_positive", "reuse_existing_service", 1044),
    "BASEER-SVC-TELECOM": ("400020", "tax_when_source_positive", "reuse_existing_service", 1046),
    "NOORIX-HIST-KARAK-OTHER-FOOD": ("400047", "tax_when_source_positive", "create_historical_service", None),
    "NOORIX-HIST-KARAK-FRUIT-VEG": ("400047", "tax_when_source_positive", "create_historical_service", None),
    "NOORIX-HIST-KARAK-COOKING-GAS": ("400019", "no_tax", "create_historical_service", None),
    "NOORIX-HIST-KARAK-PLASTICS": ("400047", "tax_when_source_positive", "create_historical_service", None),
    "NOORIX-HIST-KARAK-CUPS": ("400047", "tax_when_source_positive", "create_historical_service", None),
    "NOORIX-HIST-KARAK-KITCHEN": ("400047", "tax_when_source_positive", "create_historical_service", None),
    "NOORIX-HIST-KARAK-SMALL-CASH": ("400047", "no_tax", "create_historical_service", None),
    "NOORIX-HIST-KARAK-REPAIRS": ("400042", "tax_when_source_positive", "create_historical_service", None),
    "NOORIX-HIST-KARAK-GOSI": ("400015", "no_tax", "create_historical_service", None),
    "NOORIX-HIST-KARAK-ZAKAT-FEES": ("400072", "no_tax", "create_historical_service", None),
    "NOORIX-HIST-KARAK-ELECTRONICS": ("400050", "tax_when_source_positive", "document_expense_override", None),
    "NOORIX-HIST-KARAK-CASHIER-COMPUTER": ("106003", "tax_when_source_positive", "document_asset_override", None),
}


def fail(message):
    raise UserError("Noorix QA Karak purchase migration: %s" % message)


def require(condition, message):
    if not condition:
        fail(message)


def source_decimal(value):
    """Parse one immutable four-decimal source value without float coercion."""
    text = str(value)
    if not RAW_DECIMAL_RE.fullmatch(text):
        raise ValueError("source value must be a non-negative four-decimal string")
    return Decimal(text)


def money(value):
    """Apply the approved commercial half-up SAR rounding."""
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def high_precision_price_unit(target_gross, taxable):
    """Return gross2/1.15 for taxable rows, without rounding the net input."""
    gross = money(target_gross)
    return gross / VAT_RATE if taxable else gross


def _sum_money(rows, field_name):
    return sum((money(row[field_name]) for row in rows), Decimal("0.00"))


def _sum_source(rows, field_name):
    return sum((source_decimal(row[field_name]) for row in rows), Decimal("0.0000"))


def validate_payload(payload):
    """Pure, strict G0-G3 validation; returns rows grouped by approved month."""
    require(isinstance(payload, dict), "payload root must be an object")
    require(payload.get("target_database") == TARGET_DATABASE, "payload target database differs")
    require(payload.get("source_archive_sha256") == ARCHIVE_SHA256, "source archive SHA-256 differs")
    require(payload.get("approved_policy") == APPROVED_POLICY, "approved purchase policy differs")
    report = payload.get("report") or {}
    require(report == EXPECTED_REPORT, "payload reconciliation report differs from the approved report")

    allowlist = payload.get("allowlist") or {}
    for key, value in EXPECTED_ALLOWLIST.items():
        require(allowlist.get(key) == value, "payload allowlist differs for %s" % key)
    vat_account_id = allowlist.get("vat_input_account_id")
    require(isinstance(vat_account_id, int) and vat_account_id > 0, "VAT input account allowlist is missing")

    categories = payload.get("category_decisions") or []
    documents = payload.get("documents") or []
    require(len(categories) == 15, "finite category/document map must contain exactly 15 decisions")
    require(len(documents) == 306, "purchase payload must contain exactly 306 documents")
    mapping_keys = [row.get("source_mapping_key") for row in categories]
    require(len(set(mapping_keys)) == 15 and all(mapping_keys), "category mapping keys must be unique and nonempty")
    category_by_key = {row["source_mapping_key"]: row for row in categories}
    product_codes = set()
    for row in categories:
        require(row.get("source_system") == "noorix", "category source system differs")
        require(row.get("source_tenant_id") == SOURCE_TENANT_ID, "category source tenant differs")
        require(row.get("source_company_id") == SOURCE_COMPANY_ID, "category source company differs")
        require(row.get("source_archive_sha256") == ARCHIVE_SHA256, "category archive evidence differs")
        require(SHA256_RE.fullmatch(str(row.get("source_row_sha256", ""))), "category row SHA-256 is invalid")
        require(row.get("decision") in ALLOWED_DECISIONS, "category decision is outside the finite map")
        require(row.get("tax_policy") in {"tax_when_source_positive", "no_tax"}, "category tax policy differs")
        require(row.get("target_account_code") in ALLOWED_ACCOUNT_CODES, "category account is outside the allowlist")
        require(isinstance(row.get("target_account_id"), int), "category target account ID is missing")
        require(row.get("target_product_code") and row.get("target_product_name"), "category service-product identity is missing")
        expected_policy = FINITE_PRODUCT_POLICY.get(row["target_product_code"])
        require(expected_policy is not None, "category service product is outside the finite product map")
        require(
            (row["target_account_code"], row["tax_policy"], row["decision"], row.get("target_product_id")) == expected_policy,
            "finite product/account/tax/decision policy differs for %s" % row["target_product_code"],
        )
        if row["decision"] == "reuse_existing_service":
            require(isinstance(row.get("target_product_id"), int), "reused service target ID is missing")
        else:
            require(row.get("target_product_id") is None, "new historical service must not preselect a product ID")
        product_codes.add(row["target_product_code"])
    require(len(product_codes) == 14, "finite map must resolve to exactly 14 service products")
    product_code_counts = Counter(row["target_product_code"] for row in categories)
    require(product_code_counts["NOORIX-HIST-KARAK-SMALL-CASH"] == 2, "NO NAME and uncategorized must share the small-cash service")
    require(all(count == 1 for code, count in product_code_counts.items() if code != "NOORIX-HIST-KARAK-SMALL-CASH"), "only the small-cash service may have two category decisions")

    source_ids = set()
    invoice_numbers = set()
    grouped = {month: [] for month in EXPECTED_REPORT["months"]}
    vault_counts = Counter()
    for row in documents:
        require(row.get("source_system") == "noorix", "document source system differs")
        require(row.get("source_tenant_id") == SOURCE_TENANT_ID, "document source tenant differs")
        require(row.get("source_company_id") == SOURCE_COMPANY_ID, "document source company differs")
        require(row.get("source_archive_sha256") == ARCHIVE_SHA256, "document archive evidence differs")
        require(row.get("target_company_id") == TARGET_COMPANY_ID, "document target company differs")
        require(row.get("source_document_kind") in {"purchase", "expense", "fixed_expense"}, "document kind is outside scope")
        require(row.get("decision") in ALLOWED_DOCUMENT_DECISIONS, "document decision is outside scope")
        require(SHA256_RE.fullmatch(str(row.get("source_row_sha256", ""))), "document row SHA-256 is invalid")
        source_id = row.get("source_invoice_id")
        require(source_id and source_id not in source_ids, "source invoice identity is missing or duplicated")
        source_ids.add(source_id)
        invoice_number = row.get("source_invoice_number")
        require(invoice_number and invoice_number not in invoice_numbers, "source invoice number is missing or duplicated")
        invoice_numbers.add(invoice_number)
        require(row.get("source_ledger_id") and row.get("source_allocation_id") and row.get("source_vault_id"), "source ledger/allocation/vault evidence is incomplete")
        require(row.get("source_supplier_id"), "source supplier identity is missing")
        try:
            source_net = source_decimal(row.get("source_net_raw"))
            source_tax = source_decimal(row.get("source_tax_raw"))
            source_total = source_decimal(row.get("source_total_raw"))
        except ValueError as exc:
            fail("invalid raw Decimal evidence for %s: %s" % (invoice_number, exc))
        require(source_net + source_tax == source_total, "source net plus tax differs from gross")
        target_net = money(row.get("target_net"))
        target_tax = money(row.get("target_tax"))
        target_total = money(row.get("target_total"))
        require(target_net + target_tax == target_total, "target net plus tax differs from gross")
        taxable = row.get("target_tax_id") == 139
        require((source_tax > 0) == taxable, "source/target tax partition differs")
        require(row.get("target_purchase_journal_id") == 58, "document purchase journal differs")
        require(row.get("target_payment_journal_id") in {62, 67}, "document payment journal differs")
        require(row.get("target_account_code") in ALLOWED_ACCOUNT_CODES, "document account is outside the allowlist")
        require(isinstance(row.get("target_account_id"), int), "document account ID is missing")
        require(isinstance(row.get("target_partner_id"), int), "document partner ID is missing")
        category = category_by_key.get(row.get("category_mapping_key"))
        require(category, "document category mapping is missing")
        require(row.get("target_product_code") == category["target_product_code"], "document/category product differs")
        require(row.get("target_product_id") == category.get("target_product_id"), "document/category product ID differs")
        require(row.get("target_product_name") == category["target_product_name"], "document/category product name differs")
        require(row.get("target_account_id") == category["target_account_id"], "document/category account differs")
        require(row.get("target_account_code") == category["target_account_code"], "document/category account code differs")
        require((row.get("source_category_id") or None) == (category.get("source_category_id") or None), "document/category source identity differs")
        require(taxable == (category["tax_policy"] == "tax_when_source_positive"), "document/category tax policy differs")
        if row["decision"] == "capitalize_cashier_computer":
            require(row.get("source_asset_id") and SHA256_RE.fullmatch(str(row.get("source_asset_row_sha256", ""))), "capitalized document lacks immutable asset evidence")
            require(row["target_account_code"] == "106003" and category["decision"] == "document_asset_override", "capitalized document must use the approved asset override")
        price_unit = Decimal(str(row.get("price_unit")))
        require(price_unit > 0, "document price unit must be positive")
        require(money(price_unit * (VAT_RATE if taxable else Decimal("1"))) == target_total, "high-precision price unit does not reproduce target gross")
        require(money(high_precision_price_unit(target_total, taxable) * (VAT_RATE if taxable else Decimal("1"))) == target_total, "approved gross-to-net formula failed")
        month = row.get("month")
        require(month in grouped and str(row.get("business_date", "")).startswith(month + "-"), "document is outside an approved month")
        grouped[month].append(row)
        vault_counts[row["target_payment_journal_id"]] += 1

    require(len({row["source_supplier_id"] for row in documents}) == 23, "exactly 23 mapped suppliers must be used")
    require(Counter(row["source_document_kind"] for row in documents) == Counter({"purchase": 293, "expense": 3, "fixed_expense": 10}), "purchase/expense/fixed-expense partition differs")
    require(sum(1 for row in documents if row["target_tax_id"] == 139) == 228, "taxable document count differs")
    require(sum(1 for row in documents if row["target_tax_id"] is None) == 78, "no-tax document count differs")
    require(vault_counts == Counter({67: 244, 62: 62}), "bank/cash document partition differs")
    require(_sum_source(documents, "source_net_raw") == Decimal(EXPECTED_REPORT["source_net"]), "source net total differs")
    require(_sum_source(documents, "source_tax_raw") == Decimal(EXPECTED_REPORT["source_tax"]), "source tax total differs")
    require(_sum_source(documents, "source_total_raw") == Decimal(EXPECTED_REPORT["source_gross"]), "source gross total differs")
    require(_sum_money(documents, "target_net") == Decimal(EXPECTED_REPORT["target_net"]), "target net total differs")
    require(_sum_money(documents, "target_tax") == Decimal(EXPECTED_REPORT["target_tax"]), "target tax total differs")
    require(_sum_money(documents, "target_total") == Decimal(EXPECTED_REPORT["target_gross"]), "target gross total differs")
    for month, expected in EXPECTED_REPORT["months"].items():
        require(len(grouped[month]) == expected["documents"], "monthly document count differs for %s" % month)
        require(_sum_money(grouped[month], "target_total") == money(expected["gross"]), "monthly gross differs for %s" % month)
    expense_cash = next((row for row in documents if row["source_invoice_number"] == "EXP-20260323-001"), None)
    expense_asset = next((row for row in documents if row["source_invoice_number"] == "EXP-20260323-002"), None)
    require(expense_cash and expense_cash["decision"] == "create_paid_vendor_bill" and expense_cash["target_account_code"] == "400050" and expense_cash["target_payment_journal_id"] == 67, "cash electronics override differs")
    require(not expense_cash.get("source_asset_id") and not expense_cash.get("source_asset_row_sha256"), "cash electronics document must not claim an asset")
    require(expense_asset and expense_asset["decision"] == "capitalize_cashier_computer" and expense_asset["target_account_code"] == "106003" and expense_asset["target_payment_journal_id"] == 62, "cashier-computer asset override differs")
    require(expense_asset.get("source_asset_id") and SHA256_RE.fullmatch(str(expense_asset.get("source_asset_row_sha256", ""))), "cashier-computer source asset evidence is missing")
    require(all(not row.get("source_asset_id") for row in documents if row is not expense_asset), "only the approved cashier-computer document may retain asset evidence")
    return grouped


def load_payload(path=PAYLOAD_PATH, expected_sha256=None):
    """Load the immutable artifact and require its separately supplied receipt."""
    expected = (expected_sha256 or os.environ.get("NOORIX_KARAK_PAYLOAD_SHA256", "")).strip().lower()
    require(SHA256_RE.fullmatch(expected), "NOORIX_KARAK_PAYLOAD_SHA256 must be the frozen 64-character SHA-256")
    payload_bytes = Path(path).read_bytes()
    actual = hashlib.sha256(payload_bytes).hexdigest()
    require(actual == expected, "payload SHA-256 differs from the frozen artifact")
    payload = json.loads(payload_bytes.decode("utf-8"))
    grouped = validate_payload(payload)
    return payload, grouped, actual


def _writer_model(env, name, company=None):
    model = env[name].sudo().with_context(**{WRITER_CONTEXT: True})
    if company:
        model = model.with_company(company).with_context(allowed_company_ids=[company.id])
    return model


def _account_code(account, company):
    return account.with_company(company).code or ""


def _validate_target_primitives(env, payload, rows, check_lock_dates=True):
    company = env["res.company"].sudo().with_context(active_test=False).browse(TARGET_COMPANY_ID).exists()
    require(company and company.active, "target company 4 is missing or inactive")
    require(company.country_id.code == "SA" and company.currency_id.name == "SAR", "target company is not Saudi/SAR")

    company_map = _writer_model(env, "baseer.noorix.company.map", company).search([
        ("source_system", "=", "noorix"),
        ("source_tenant_id", "=", SOURCE_TENANT_ID),
        ("source_company_id", "=", SOURCE_COMPANY_ID),
        ("company_id", "=", company.id),
    ], limit=2)
    require(
        len(company_map) == 1
        and company_map.source_archive_sha256 == ARCHIVE_SHA256
        and company_map.decision == "create_historical_company",
        "approved historical Karak company mapping is missing",
    )

    journals = env["account.journal"].sudo().with_context(active_test=False).browse([58, 62, 67, 69, 70]).exists()
    by_id = {journal.id: journal for journal in journals}
    purchase = by_id.get(58)
    require(purchase and purchase.company_id == company and purchase.code == "BILL" and purchase.type == "purchase", "BILL/58 differs")
    expected_payment = {62: ("BNK1", "101001"), 67: ("CSH1", "105001")}
    payment_methods = {}
    for journal_id, (code, liquidity_code) in expected_payment.items():
        journal = by_id.get(journal_id)
        require(journal and journal.company_id == company and journal.code == code and journal.type in {"bank", "cash"}, "%s/%s differs" % (code, journal_id))
        require(_account_code(journal.default_account_id, company) == liquidity_code, "%s liquidity account differs" % code)
        # Odoo 19 account.payment.method.line has no ``active`` field.  The
        # journal relation itself is the authoritative enabled outbound set.
        methods = journal.outbound_payment_method_line_ids.filtered(
            lambda line: line.code == "manual"
        )
        require(
            len(methods) == 1 and methods.journal_id == journal,
            "%s needs exactly one outbound manual payment method" % code,
        )
        payment_methods[journal_id] = methods
    require(by_id.get(69) and by_id[69].code == "PSBNK" and by_id.get(70) and by_id[70].code == "PSCSH", "forbidden POS journal identities differ")
    require(not ({row["target_purchase_journal_id"] for row in rows} | {row["target_payment_journal_id"] for row in rows}) & {69, 70}, "payload references a forbidden POS journal")

    tax = env["account.tax"].sudo().with_company(company).with_context(active_test=False, allowed_company_ids=[company.id]).browse(139).exists()
    require(tax and tax.company_id == company and tax.active and tax.type_tax_use == "purchase", "purchase tax 139 differs")
    require(Decimal(str(tax.amount)) == Decimal("15") and not tax.price_include, "purchase tax 139 must be 15% excluded")
    tax_accounts = tax.invoice_repartition_line_ids.filtered(lambda line: line.repartition_type == "tax").account_id
    require(len(tax_accounts) == 1 and tax_accounts.id == payload["allowlist"]["vat_input_account_id"] and _account_code(tax_accounts, company) == "104041", "purchase VAT input account differs")

    account_ids = {row["target_account_id"] for row in rows}
    accounts = env["account.account"].sudo().with_company(company).with_context(active_test=False, allowed_company_ids=[company.id]).browse(sorted(account_ids)).exists()
    require(set(accounts.ids) == account_ids, "one or more target accounts are missing")
    account_by_id = {account.id: account for account in accounts}
    for row in rows:
        account = account_by_id[row["target_account_id"]]
        require(account.active and _account_code(account, company) == row["target_account_code"], "target account identity differs")
        expected_type = "asset_fixed" if row["target_account_code"] == "106003" else "expense"
        require(account.account_type == expected_type, "target account type differs for %s" % row["target_account_code"])

    supplier_ids = {row["source_supplier_id"] for row in rows}
    supplier_maps = _writer_model(env, "baseer.noorix.supplier.map", company).search([
        ("source_system", "=", "noorix"),
        ("source_tenant_id", "=", SOURCE_TENANT_ID),
        ("source_company_id", "=", SOURCE_COMPANY_ID),
        ("source_supplier_id", "in", sorted(supplier_ids)),
    ])
    require(set(supplier_maps.mapped("source_supplier_id")) == supplier_ids, "supplier provenance is incomplete")
    partner_by_source = {mapping.source_supplier_id: mapping.partner_id for mapping in supplier_maps}
    for row in rows:
        partner = partner_by_source[row["source_supplier_id"]]
        require(partner.id == row["target_partner_id"], "payload supplier target differs from approved supplier map")
        require(not partner.company_id and not partner.commercial_partner_id.company_id and partner.supplier_rank > 0, "supplier must be a shared Odoo vendor")

    if check_lock_dates:
        for row in rows:
            business_date = fields.Date.to_date(row["business_date"])
            require(not company._get_violated_lock_dates(business_date, bool(row["target_tax_id"]), purchase), "invoice date is locked: %s" % row["business_date"])
            require(not company._get_violated_lock_dates(business_date, False, by_id[row["target_payment_journal_id"]]), "payment date is locked: %s" % row["business_date"])
    return company, purchase, by_id, payment_methods, tax, account_by_id, partner_by_source


def _service_product(env, company, decision, run, category_map_model, cache):
    code = decision["target_product_code"]
    product = cache.get(code)
    if product:
        return product
    Product = env["product.product"].sudo().with_company(company).with_context(active_test=False, allowed_company_ids=[company.id])
    if decision["decision"] == "reuse_existing_service":
        product = Product.browse(decision["target_product_id"]).exists()
        require(product and product.default_code == code, "approved existing service product differs")
    else:
        found = Product.search([("company_id", "=", company.id), ("default_code", "=", code)], limit=2)
        require(not found, "historical service code already exists without provenance: %s" % code)
        template = env["product.template"].sudo().with_company(company).with_context(allowed_company_ids=[company.id]).create({
            "name": decision["target_product_name"],
            "default_code": code,
            "company_id": company.id,
            "type": "service",
            "purchase_ok": True,
            "sale_ok": False,
            "active": True,
        })
        product = template.product_variant_id
    require(product.active and product.company_id == company and product.type == "service", "purchase history product must be an active company service")
    require(product.purchase_ok and not product.sale_ok, "purchase history product must be purchase-only")
    cache[code] = product
    return product


def _category_map(env, company, decision, run, product_cache):
    CategoryMap = _writer_model(env, "baseer.noorix.purchase.category.map", company)
    domain = [
        ("source_system", "=", "noorix"),
        ("source_tenant_id", "=", SOURCE_TENANT_ID),
        ("source_company_id", "=", SOURCE_COMPANY_ID),
        ("source_mapping_key", "=", decision["source_mapping_key"]),
    ]
    mapping = CategoryMap.search(domain, limit=2)
    if mapping:
        require(len(mapping) == 1, "category mapping is ambiguous")
        expected = {
            "source_category_id": decision["source_category_id"] or False,
            "source_category_name": decision["source_category_name"] or False,
            "source_row_sha256": decision["source_row_sha256"],
            "source_archive_sha256": ARCHIVE_SHA256,
            "canonical_key": decision["canonical_key"],
            "decision": decision["decision"],
            "tax_policy": decision["tax_policy"],
        }
        require(all(mapping[field_name] == value for field_name, value in expected.items()), "existing category evidence conflicts with payload")
        require(mapping.account_id.id == decision["target_account_id"] and _account_code(mapping.account_id, company) == decision["target_account_code"], "existing category account differs")
        require(mapping.product_id.default_code == decision["target_product_code"], "existing category product differs")
        product = _service_product(env, company, {**decision, "target_product_id": mapping.product_id.id, "decision": "reuse_existing_service"}, run, CategoryMap, product_cache)
        require(product == mapping.product_id, "two provenance rows disagree on the shared historical service")
        return mapping

    product = _service_product(env, company, decision, run, CategoryMap, product_cache)
    return CategoryMap.create({
        "source_system": "noorix",
        "source_tenant_id": SOURCE_TENANT_ID,
        "source_company_id": SOURCE_COMPANY_ID,
        "source_mapping_key": decision["source_mapping_key"],
        "source_category_id": decision["source_category_id"] or False,
        "source_category_name": decision["source_category_name"] or False,
        "source_row_sha256": decision["source_row_sha256"],
        "source_archive_sha256": ARCHIVE_SHA256,
        "canonical_key": decision["canonical_key"],
        "decision": decision["decision"],
        "tax_policy": decision["tax_policy"],
        "product_id": product.id,
        "account_id": decision["target_account_id"],
        "run_id": run.id,
    })


def _verify_invoice_mapping(mapping, row, company):
    direct_fields = (
        "source_system", "source_tenant_id", "source_company_id", "source_invoice_id",
        "source_ledger_id", "source_allocation_id", "source_vault_id", "source_supplier_id",
        "source_invoice_number", "source_supplier_invoice_number", "source_document_kind",
        "source_row_sha256", "source_archive_sha256", "canonical_key", "source_asset_id",
        "source_asset_row_sha256", "decision",
        "source_net_raw", "source_tax_raw", "source_total_raw",
    )
    for field_name in direct_fields:
        require((mapping[field_name] or False) == (row.get(field_name) or False), "invoice mapping evidence differs: %s" % field_name)
    require(mapping.business_date == fields.Date.to_date(row["business_date"]), "invoice mapping date differs")
    require(mapping.source_category_id == (row.get("source_category_id") or False), "invoice source category differs")
    require(mapping.company_id == company and mapping.partner_id.id == row["target_partner_id"], "invoice mapping target scope differs")
    require(mapping.purchase_journal_id.id == 58 and mapping.payment_journal_id.id == row["target_payment_journal_id"], "invoice mapping journal differs")
    require(mapping.tax_id.id == (row["target_tax_id"] or False), "invoice mapping tax differs")
    require(format(money(mapping.target_net), ".2f") == row["target_net"], "invoice mapping target net differs")
    require(format(money(mapping.target_tax), ".2f") == row["target_tax"], "invoice mapping target tax differs")
    require(format(money(mapping.target_total), ".2f") == row["target_total"], "invoice mapping target total differs")
    bill = mapping.bill_id
    payment = mapping.payment_id
    require(bill.company_id == company and bill.move_type == "in_invoice" and bill.state == "posted", "mapped vendor bill differs")
    require(bill.journal_id.id == 58 and bill.partner_id == mapping.partner_id, "mapped vendor bill journal/partner differs")
    require(bill.invoice_date == mapping.business_date and bill.date == mapping.business_date, "mapped vendor bill date differs")
    require(money(bill.amount_untaxed) == money(row["target_net"]), "mapped bill net differs")
    require(money(bill.amount_tax) == money(row["target_tax"]), "mapped bill tax differs")
    require(money(bill.amount_total) == money(row["target_total"]) and money(bill.amount_residual) == Decimal("0.00"), "mapped bill total/residual differs")
    require(payment.company_id == company and payment.journal_id.id == row["target_payment_journal_id"], "mapped payment scope differs")
    require(payment.move_id == mapping.payment_move_id and payment.move_id.state == "posted", "mapped native payment move differs")
    require(money(payment.amount) == money(row["target_total"]), "mapped payment amount differs")
    require(mapping.category_map_id.product_id in bill.invoice_line_ids.product_id, "mapped category service is absent from bill")
    product = mapping.category_map_id.product_id
    require(product.active and product.company_id == company and product.type == "service", "mapped purchase product is not an active company service")
    require(product.purchase_ok and not product.sale_ok, "mapped purchase product is not purchase-only")
    return bill, payment


def _replay(env, company, run, rows, category_decisions):
    InvoiceMap = _writer_model(env, "baseer.noorix.purchase.invoice.map", company)
    mappings = InvoiceMap.search([("run_id", "=", run.id)])
    require(len(mappings) == len(rows), "replay mapping count differs")
    by_source = {mapping.source_invoice_id: mapping for mapping in mappings}
    require(set(by_source) == {row["source_invoice_id"] for row in rows}, "replay source identities differ")
    bills = env["account.move"].browse()
    payments = env["account.payment"].browse()
    for row in rows:
        mapping = by_source[row["source_invoice_id"]]
        bill, payment = _verify_invoice_mapping(mapping, row, company)
        category = category_decisions[row["category_mapping_key"]]
        require(mapping.category_map_id.source_mapping_key == category["source_mapping_key"], "replay category mapping key differs")
        require(mapping.category_map_id.source_row_sha256 == category["source_row_sha256"], "replay category evidence differs")
        require(mapping.category_map_id.source_archive_sha256 == ARCHIVE_SHA256, "replay category archive differs")
        require(mapping.category_map_id.decision == category["decision"] and mapping.category_map_id.tax_policy == category["tax_policy"], "replay category decision differs")
        require(mapping.category_map_id.product_id.default_code == category["target_product_code"], "replay category product differs")
        require(mapping.category_map_id.account_id.id == category["target_account_id"], "replay category account differs")
        bills |= bill
        payments |= payment
    require(len(bills) == len(rows) and len(payments) == len(rows), "replay target cardinality differs")
    return {
        "status": "already_reconciled",
        "run_id": run.id,
        "month": rows[0]["month"],
        "documents": len(rows),
        "target_net": format(sum((money(bill.amount_untaxed) for bill in bills), Decimal("0.00")), ".2f"),
        "target_tax": format(sum((money(bill.amount_tax) for bill in bills), Decimal("0.00")), ".2f"),
        "target_gross": format(sum((money(bill.amount_total) for bill in bills), Decimal("0.00")), ".2f"),
    }


def apply_month(env, payload_path=PAYLOAD_PATH, expected_sha256=None, month=None):
    """Validate and apply one monthly transaction; never commits internally."""
    require(env.cr.dbname != PRODUCTION_DATABASE, "production baseer_dev is forbidden")
    require(env.cr.dbname == TARGET_DATABASE, "target database must be the isolated Noorix QA database")
    selected_month = (month or os.environ.get("NOORIX_KARAK_MONTH", "")).strip()
    require(selected_month in EXPECTED_REPORT["months"], "NOORIX_KARAK_MONTH must be one approved 2026 month")
    payload, grouped, payload_sha256 = load_payload(payload_path, expected_sha256)
    rows = sorted(grouped[selected_month], key=lambda row: (row["business_date"], row["source_invoice_number"], row["source_invoice_id"]))

    # This must precede every run/provenance replay lookup.  It is xact-scoped,
    # so success and failure are both owned by the caller's single transaction.
    env.cr.execute(
        "SELECT pg_advisory_xact_lock(hashtext(%s))",
        ["%s:noorix-karak-purchases:%s" % (env.cr.dbname, selected_month)],
    )
    run_name = "%s-%s-1" % (RUN_PREFIX, selected_month)
    Run = _writer_model(env, "baseer.noorix.migration.run")
    existing_run = Run.search([("name", "=", run_name)], limit=2)
    require(len(existing_run) <= 1, "monthly run identity is ambiguous")
    if existing_run:
        require(existing_run.payload_sha256 == payload_sha256 and existing_run.source_archive_sha256 == ARCHIVE_SHA256, "existing run belongs to different evidence")
        require(existing_run.scope == "purchase_history" and existing_run.state == "reconciled", "existing monthly run is incomplete or has the wrong scope")
        company, _purchase, _journals, _methods, _tax, _accounts, _partners = _validate_target_primitives(
            env, payload, rows, check_lock_dates=False,
        )
        category_decisions = {row["source_mapping_key"]: row for row in payload["category_decisions"]}
        return _replay(env, company, existing_run, rows, category_decisions)

    InvoiceMap = _writer_model(env, "baseer.noorix.purchase.invoice.map")
    require(not InvoiceMap.search([
        ("source_system", "=", "noorix"),
        ("source_tenant_id", "=", SOURCE_TENANT_ID),
        ("source_company_id", "=", SOURCE_COMPANY_ID),
        ("source_invoice_id", "in", [row["source_invoice_id"] for row in rows]),
    ], limit=1), "one or more source invoices are already mapped by another run")

    company, purchase_journal, journals, payment_methods, tax, accounts, partners = _validate_target_primitives(env, payload, rows)
    scoped = dict(allowed_company_ids=[company.id], active_test=False)
    Move = env["account.move"].sudo().with_company(company).with_context(**scoped)
    Payment = env["account.payment"].sudo().with_company(company).with_context(**scoped)
    StockMove = env["stock.move"].sudo().with_company(company).with_context(**scoped)
    Picking = env["stock.picking"].sudo().with_company(company).with_context(**scoped)
    PosOrder = env["pos.order"].sudo().with_company(company).with_context(**scoped)
    PosSession = env["pos.session"].sudo().with_company(company).with_context(**scoped)
    before = {
        "moves": Move.search_count([("company_id", "=", company.id)]),
        "payments": Payment.search_count([("company_id", "=", company.id)]),
        "stock_moves": StockMove.search_count([("company_id", "=", company.id)]),
        "pickings": Picking.search_count([("company_id", "=", company.id)]),
        "pos_orders": PosOrder.search_count([("company_id", "=", company.id)]),
        "pos_sessions": PosSession.search_count([("company_id", "=", company.id)]),
    }
    run = Run.create({
        "name": run_name,
        "source_archive_sha256": ARCHIVE_SHA256,
        "source_tenant_id": SOURCE_TENANT_ID,
        "payload_sha256": payload_sha256,
        "scope": "purchase_history",
        "state": "planned",
        "started_at": fields.Datetime.now(),
        "result_json": json.dumps({"stage": "preflight_passed", "month": selected_month}, sort_keys=True),
    })

    decision_by_key = {row["source_mapping_key"]: row for row in payload["category_decisions"]}
    product_cache = {}
    category_maps = {
        key: _category_map(env, company, decision_by_key[key], run, product_cache)
        for key in sorted({row["category_mapping_key"] for row in rows})
    }
    created_bills = Move.browse()
    created_payments = Payment.browse()
    map_values = []
    for row in rows:
        category_map = category_maps[row["category_mapping_key"]]
        business_date = fields.Date.to_date(row["business_date"])
        tax_command = Command.set([tax.id]) if row["target_tax_id"] else Command.clear()
        bill = Move.create({
            "move_type": "in_invoice",
            "company_id": company.id,
            "journal_id": purchase_journal.id,
            "partner_id": partners[row["source_supplier_id"]].id,
            "invoice_date": business_date,
            "date": business_date,
            "ref": "Noorix %s%s" % (row["source_invoice_number"], " / " + row["source_supplier_invoice_number"] if row["source_supplier_invoice_number"] else ""),
            "invoice_origin": "Noorix %s" % row["source_invoice_id"],
            "invoice_line_ids": [Command.create({
                "product_id": category_map.product_id.id,
                "name": row["target_product_name"],
                "quantity": 1.0,
                "price_unit": float(Decimal(row["price_unit"])),
                "account_id": accounts[row["target_account_id"]].id,
                "tax_ids": [tax_command],
            })],
        })
        require(not bill._get_violated_lock_dates(business_date, bool(row["target_tax_id"])), "native bill reports a locked date")
        require(money(bill.amount_untaxed) == money(row["target_net"]), "draft bill net differs from payload")
        require(money(bill.amount_tax) == money(row["target_tax"]), "draft bill tax differs from payload")
        require(money(bill.amount_total) == money(row["target_total"]), "draft bill gross differs from payload")
        bill.action_post()
        require(bill.state == "posted" and bill.date == business_date and bill.invoice_date == business_date, "native posting changed bill state/date")

        method = payment_methods[row["target_payment_journal_id"]]
        wizard = env["account.payment.register"].sudo().with_company(company).with_context(
            active_model="account.move", active_ids=bill.ids, allowed_company_ids=[company.id]
        ).create({
            "journal_id": journals[row["target_payment_journal_id"]].id,
            "payment_method_line_id": method.id,
            "amount": bill.amount_total,
            "payment_date": business_date,
            "installments_mode": "full",
            "payment_difference_handling": "open",
        })
        payment = wizard._create_payments()
        require(len(payment) == 1 and payment.move_id.state == "posted", "native payment was not posted exactly once")
        bill.invalidate_recordset()
        require(money(bill.amount_residual) == Decimal("0.00") and bill.payment_state in {"paid", "in_payment"}, "vendor bill was not fully reconciled")

        created_bills |= bill
        created_payments |= payment
        map_values.append({
            "source_system": "noorix",
            "source_tenant_id": SOURCE_TENANT_ID,
            "source_company_id": SOURCE_COMPANY_ID,
            "source_invoice_id": row["source_invoice_id"],
            "source_ledger_id": row["source_ledger_id"],
            "source_allocation_id": row["source_allocation_id"],
            "source_vault_id": row["source_vault_id"],
            "source_supplier_id": row["source_supplier_id"],
            "source_category_id": row["source_category_id"] or False,
            "source_invoice_number": row["source_invoice_number"],
            "source_supplier_invoice_number": row["source_supplier_invoice_number"] or False,
            "source_document_kind": row["source_document_kind"],
            "business_date": business_date,
            "source_net_raw": row["source_net_raw"],
            "source_tax_raw": row["source_tax_raw"],
            "source_total_raw": row["source_total_raw"],
            "source_row_sha256": row["source_row_sha256"],
            "source_archive_sha256": ARCHIVE_SHA256,
            "canonical_key": row["canonical_key"],
            "source_asset_id": row["source_asset_id"] or False,
            "source_asset_row_sha256": row["source_asset_row_sha256"] or False,
            "decision": row["decision"],
            "company_id": company.id,
            "category_map_id": category_map.id,
            "partner_id": partners[row["source_supplier_id"]].id,
            "tax_id": row["target_tax_id"] or False,
            "purchase_journal_id": purchase_journal.id,
            "payment_journal_id": journals[row["target_payment_journal_id"]].id,
            "bill_id": bill.id,
            "payment_id": payment.id,
            "payment_move_id": payment.move_id.id,
            "target_net": row["target_net"],
            "target_tax": row["target_tax"],
            "target_total": row["target_total"],
            "run_id": run.id,
        })

    mappings = InvoiceMap.create(map_values)
    require(len(mappings) == len(rows), "post-write invoice-map count differs")
    for row, mapping in zip(rows, mappings):
        _verify_invoice_mapping(mapping, row, company)

    after = {
        "moves": Move.search_count([("company_id", "=", company.id)]),
        "payments": Payment.search_count([("company_id", "=", company.id)]),
        "stock_moves": StockMove.search_count([("company_id", "=", company.id)]),
        "pickings": Picking.search_count([("company_id", "=", company.id)]),
        "pos_orders": PosOrder.search_count([("company_id", "=", company.id)]),
        "pos_sessions": PosSession.search_count([("company_id", "=", company.id)]),
    }
    require(after["moves"] - before["moves"] == len(rows) * 2, "writer created an unexpected extra/missing account move")
    require(after["payments"] - before["payments"] == len(rows), "native payment delta differs")
    for protected in ("stock_moves", "pickings", "pos_orders", "pos_sessions"):
        require(after[protected] == before[protected], "writer changed forbidden %s" % protected)
    require(len(created_bills) == len(rows) and len(created_payments) == len(rows), "created target cardinality differs")
    require(all(bill.journal_id.id == 58 for bill in created_bills), "a bill used a non-BILL journal")
    require(not (set(created_bills.mapped("journal_id").ids) | set(created_payments.mapped("journal_id").ids)) & {69, 70}, "writer used a forbidden POS journal")

    result = {
        "status": "reconciled",
        "month": selected_month,
        "company_id": company.id,
        "documents": len(rows),
        "vendor_bills": len(created_bills),
        "payments": len(created_payments),
        "target_net": format(_sum_money(rows, "target_net"), ".2f"),
        "target_tax": format(_sum_money(rows, "target_tax"), ".2f"),
        "target_gross": format(_sum_money(rows, "target_total"), ".2f"),
        "account_move_delta": after["moves"] - before["moves"],
        "stock_move_delta": 0,
        "picking_delta": 0,
        "pos_order_delta": 0,
        "pos_session_delta": 0,
    }
    run.write({
        "state": "reconciled",
        "finished_at": fields.Datetime.now(),
        "result_json": json.dumps(result, ensure_ascii=False, sort_keys=True),
    })
    return {"run_id": run.id, **result}
