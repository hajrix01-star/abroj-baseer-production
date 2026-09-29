"""Pure-Python validation for the pinned Noorix purchase replay contract.

This module deliberately has no Odoo import.  It is used both by the runtime
writer and by the offline dry-run command, so malformed source data is caught
before a database connection is considered.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path


SOURCE_ARCHIVE_SHA256 = "024606ADD82DCD78DC1835828A12D7B22C56E34924FF998ABF752134160E79E2"
SOURCE_MANIFEST_SHA256 = "84afbe3fa32dcb2ba89bb52451db032f3675baf50d97b243d63f4b31c9201fa6"
VAT_DIVISOR = Decimal("1.15")
MONEY_QUANTUM = Decimal("0.01")


class PurchaseContractError(ValueError):
    """The immutable decision contract cannot safely produce accounting rows."""


def decimal_value(value, label):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise PurchaseContractError("Invalid decimal for %s" % label) from error


def money(value):
    return decimal_value(value, "money").quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def stable_hash(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def settlement_hash(document, settlement):
    """A source-only evidence hash for allocation/ledger settlement rows.

    The manifest preserves the original invoice-row hash but not an independent
    raw-row digest for every allocation.  This deterministic digest binds the
    immutable invoice evidence to the exact source allocation and ledger tuple.
    """
    return stable_hash({
        "invoice_row_sha256": document["source_row_sha256"],
        "source_invoice_id": document["source_invoice_id"],
        "source_ledger_id": settlement["source_ledger_id"],
        "source_allocation_id": settlement["source_allocation_id"],
        "source_vault_id": settlement["source_vault_id"],
        "amount_raw": settlement["amount_raw"],
    })


def source_identity(row, *keys):
    parts = []
    for key in ("source_system", "source_tenant_id", "source_company_id") + keys:
        value = row.get(key)
        if value in (None, ""):
            raise PurchaseContractError("Missing %s in source identity" % key)
        parts.append(str(value))
    return ":".join(parts)


def _require(condition, message):
    if not condition:
        raise PurchaseContractError(message)


def _same_money(left, right):
    return money(left) == money(right)


def document_tax_policy(document):
    """Classify a purchase line by numeric source evidence, never supplier data.

    Historical Noorix rows occasionally leave ``source_tax_raw`` at zero while
    their authoritative price/gross relationship is plainly VAT inclusive.
    Conversely, small cash documents can be genuinely tax-free.  The approved
    selector is therefore exact numeric evidence: ``price * 1.15 == gross``
    for input VAT, or ``price == gross`` for no tax.  A positive raw tax is an
    additional consistency assertion, not a blanket inference rule.
    """
    source_tax = decimal_value(document["source_tax_raw"], "source_tax_raw")
    if source_tax < 0:
        raise PurchaseContractError("Negative source VAT is unsupported: %s" % document["canonical_key"])
    gross = money(document["source_total_raw"])
    price = decimal_value(document["price_unit"], "price_unit")
    inclusive = _same_money(price * VAT_DIVISOR, gross)
    no_tax = _same_money(price, gross)
    if inclusive == no_tax:
        raise PurchaseContractError("Cannot infer one purchase VAT policy: %s" % document["canonical_key"])
    if source_tax > 0 and not inclusive:
        raise PurchaseContractError("Positive source VAT conflicts with price/gross evidence: %s" % document["canonical_key"])
    return "vat15_inclusive" if inclusive else "no_tax"


def _validate_document_math(document):
    net = decimal_value(document["source_net_raw"], "source_net_raw")
    vat = decimal_value(document["source_tax_raw"], "source_tax_raw")
    gross = decimal_value(document["source_total_raw"], "source_total_raw")
    _require(net + vat == gross, "Source net + VAT differs from gross: %s" % document["canonical_key"])
    _require(money(gross) > 0, "Non-positive gross purchase document: %s" % document["canonical_key"])
    document_tax_policy(document)


def native_price_unit(document):
    """Return the source price only after ``document_tax_policy`` proved it."""
    document_tax_policy(document)
    return decimal_value(document["price_unit"], "price_unit")


def _normal_settlement(document):
    return {
        "source_allocation_id": document["source_allocation_id"],
        "source_ledger_id": document["source_ledger_id"],
        "source_vault_id": document["source_vault_id"],
        "amount_raw": document["source_total_raw"],
    }


def _special_category(invoice):
    return {
        "canonical_key": "special:%s" % invoice["canonical_key"],
        "source_mapping_key": "special:%s" % invoice["canonical_key"],
        "source_row_sha256": invoice["source_row_sha256"],
        "source_company_id": invoice["source_company_id"],
        "decision": "create_historical_service",
        "decision_account_code": invoice["decision_account_code"],
        "decision_product_code": invoice["decision_product_code"],
        "decision_product_name": invoice["decision_product_name"],
        "tax_policy": "no_tax",
    }


def build_purchase_contract(manifest):
    """Return source-only documents and category decisions after strict checks.

    Every returned document contains ``_category`` and ``_settlements``.  This
    format is intentionally independent from database identifiers, which keeps
    it usable by the writer and the offline dry-run command.
    """
    _require(manifest.get("source_archive_sha256") == SOURCE_ARCHIVE_SHA256,
             "Purchase contract archive pin differs")
    _require(isinstance(manifest.get("contracts"), list) and len(manifest["contracts"]) == 26,
             "Purchase contract count differs")

    categories = {}
    generic_payloads = []
    special_payloads = []
    general_purchase_policies = {
        "general_paid_vendor_bills_native_accounting_monthly_atomic",
        "karak_306_paid_vendor_bills_native_accounting_monthly_atomic",
    }
    for contract in manifest["contracts"]:
        payload = contract.get("payload", {})
        if payload.get("approved_policy") in general_purchase_policies:
            generic_payloads.append(payload)
            for decision in payload.get("category_decisions", []):
                key = decision.get("source_mapping_key")
                _require(key and decision.get("source_row_sha256"), "Category decision evidence is incomplete")
                previous = categories.setdefault(key, decision)
                _require(previous == decision, "Category decision identity differs: %s" % key)
        if payload.get("approved_policy") == "almoallem_single_rent_split_paid_vendor_bill_native_accounting":
            special_payloads.append(payload)

    _require(len(special_payloads) == 1, "Expected exactly one approved split settlement contract")
    documents = []
    vat_policy_counts = Counter()
    inferred_vat_raw_zero = []
    generic_counts = Counter()
    for payload in generic_payloads:
        report = payload.get("report", {})
        payload_docs = payload.get("documents", [])
        source_company_id = payload.get("company", {}).get("source_company_id")
        if not source_company_id:
            source_companies = {item.get("source_company_id") for item in payload_docs}
            _require(len(source_companies) == 1 and None not in source_companies,
                     "Generic purchase payload has no unambiguous source company")
            source_company_id = source_companies.pop()
        _require(len(payload_docs) == report.get("source_documents"), "Generic document count differs from report")
        report_months = report.get("months", {})
        actual_months = defaultdict(lambda: {"documents": 0, "gross": Decimal("0")})
        for source in payload_docs:
            document = dict(source)
            _require(document.get("decision") in {"create_paid_vendor_bill", "capitalize_cashier_computer"},
                     "Unsupported generic purchase decision")
            _require(document.get("source_company_id") == source_company_id, "Purchase company differs from payload")
            _require(document.get("source_archive_sha256") == SOURCE_ARCHIVE_SHA256, "Purchase archive pin differs")
            _require(document.get("category_mapping_key") in categories, "Unmapped purchase category")
            _require(document.get("month") and document.get("business_date", "").startswith(document["month"]),
                     "Purchase document month differs from business date")
            _require(document.get("source_row_sha256") and len(document["source_row_sha256"]) == 64,
                     "Purchase row hash is incomplete")
            source_identity(document, "source_invoice_id")
            source_identity(document, "source_supplier_id")
            source_identity(document, "source_vault_id")
            source_identity(document, "source_allocation_id")
            _validate_document_math(document)
            document["_vat_policy"] = document_tax_policy(document)
            vat_policy_counts[document["_vat_policy"]] += 1
            if document["_vat_policy"] == "vat15_inclusive" and decimal_value(document["source_tax_raw"], "source_tax_raw") == 0:
                inferred_vat_raw_zero.append(document["canonical_key"])
            document["_category"] = categories[document["category_mapping_key"]]
            document["_settlements"] = [_normal_settlement(document)]
            documents.append(document)
            generic_counts[(source_company_id, document["month"])] += 1
            actual_months[document["month"]]["documents"] += 1
            actual_months[document["month"]]["gross"] += money(document["source_total_raw"])
        _require(set(actual_months) == set(report_months), "Generic purchase months differ from report")
        for month, actual in actual_months.items():
            expected = report_months[month]
            _require(actual["documents"] == expected["documents"], "Generic month count differs: %s" % month)
            _require(actual["gross"] == money(expected["gross"]), "Generic month gross differs: %s" % month)

    special = special_payloads[0]
    invoice = dict(special.get("invoice") or {})
    settlements = special.get("settlements") or []
    _require(invoice and invoice.get("decision") == "create_split_paid_vendor_bill", "Split invoice is missing")
    _require(len(settlements) == 2, "Split invoice must have exactly two settlements")
    _require(invoice.get("source_archive_sha256") == SOURCE_ARCHIVE_SHA256, "Split invoice archive pin differs")
    _require(invoice.get("month") and invoice.get("business_date", "").startswith(invoice["month"]),
             "Split invoice month differs from business date")
    _validate_document_math(invoice)
    invoice["_vat_policy"] = document_tax_policy(invoice)
    vat_policy_counts[invoice["_vat_policy"]] += 1
    if invoice["_vat_policy"] == "vat15_inclusive" and decimal_value(invoice["source_tax_raw"], "source_tax_raw") == 0:
        inferred_vat_raw_zero.append(invoice["canonical_key"])
    normalized_settlements = []
    for settlement in settlements:
        normalized = dict(settlement)
        normalized["amount_raw"] = normalized.pop("source_allocation_raw")
        _require(decimal_value(normalized["amount_raw"], "split allocation") > 0, "Non-positive split allocation")
        source_identity({**invoice, **normalized}, "source_allocation_id")
        source_identity({**invoice, **normalized}, "source_vault_id")
        normalized_settlements.append(normalized)
    _require(sum((decimal_value(item["amount_raw"], "split allocation") for item in normalized_settlements), Decimal("0"))
             == decimal_value(invoice["source_total_raw"], "split gross"), "Split settlements do not equal invoice gross")
    invoice["_category"] = _special_category(invoice)
    invoice["_settlements"] = normalized_settlements
    documents.append(invoice)

    invoice_identities = [source_identity(document, "source_invoice_id") for document in documents]
    payment_identities = [
        source_identity({**document, **settlement}, "source_allocation_id")
        for document in documents for settlement in document["_settlements"]
    ]
    reconcile_identities = [
        source_identity({**document, **settlement}, "source_invoice_id", "source_ledger_id", "source_allocation_id")
        for document in documents for settlement in document["_settlements"]
    ]
    _require(len(invoice_identities) == len(set(invoice_identities)), "Duplicate source invoice identity")
    _require(len(payment_identities) == len(set(payment_identities)), "Duplicate source allocation identity")
    _require(len(reconcile_identities) == len(set(reconcile_identities)), "Duplicate source reconciliation identity")
    _require(len(documents) == 2962, "Purchase contract document count differs")

    by_wave = defaultdict(list)
    for document in documents:
        by_wave[(document["source_company_id"], document["month"])].append(document)
    return {
        "documents": documents,
        "categories": categories,
        "by_wave": {key: tuple(value) for key, value in by_wave.items()},
        "invoice_count": len(documents),
        "payment_count": len(payment_identities),
        "generic_wave_count": len(generic_counts),
        "vat_policy_counts": dict(vat_policy_counts),
        "vat_inferred_when_raw_zero": tuple(inferred_vat_raw_zero),
    }


def load_pinned_manifest(path):
    raw = Path(path).read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != SOURCE_MANIFEST_SHA256:
        raise PurchaseContractError("Source manifest SHA-256 differs")
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PurchaseContractError("Cannot decode source manifest") from error
    return manifest
