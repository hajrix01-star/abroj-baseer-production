"""Build a deterministic, write-free Noorix supplier migration payload.

The input JSON is exported from a SHA-pinned Noorix PostgreSQL archive and the
target JSON is read from the isolated Odoo QA database.  The resulting payload
contains source lineage and reconciliation decisions but does not perform Odoo
writes.  It deliberately accepts a legal-identity match only when a valid Saudi
VAT belongs to exactly one global top-level Odoo partner.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SOURCE_SYSTEM = "noorix"
LEGAL_TOKENS = ("شركه", "مؤسسه", "company", "corporation", "establishment")
ANONYMOUS_CASH_NAME = "noname"
ANONYMOUS_CASH_PARTNER_NAME = "مورد نقدي غير مسمى"
ANONYMOUS_CASH_CATEGORY_NAME = "فواتير نقدية صغيرة"
APPROVED_CATEGORY_TARGETS = {
    "اتصالات": "مقدمو الاتصالات والإنترنت",
    "كهرباء": "مقدمو الكهرباء",
    "مياه": "مقدمو المياه",
    "رسوم منصات حكومية": "المنصات الحكومية",
    "منصة قوى": "المنصات الحكومية",
    "إقامات وجوازات": "الجهات الحكومية",
    "التأمينات الاجتماعية (GOSI)": "الجهات الحكومية",
    "رخصة بلدية": "الجهات الحكومية",
    "رخصة تجارية": "الجهات الحكومية",
    "ضرائب ورسوم أخرى": "الجهات الحكومية",
    "غرامات": "الجهات الحكومية",
    "إيجارات": "مقدمو الخدمات",
    "تأمين طبي": "مقدمو الخدمات",
    "تذاكر سفر الموظفين": "مقدمو الخدمات",
    "تسويق وهدايا": "مقدمو الخدمات",
    "رسوم إدارة حساب": "مقدمو الخدمات",
    "رسوم تطبيقات": "مقدمو الخدمات",
    "رواتب وأجور": "مقدمو الخدمات",
    "صيانة آلات": "مقدمو الخدمات",
    "صيانة سيارات": "مقدمو الخدمات",
    "صيانة وترميم": "مقدمو الخدمات",
    "صيانة وتشغيل": "مقدمو الخدمات",
    "فواتير نقدية صغيرة": "نقدي غير مسمى",
    "أثاث": "أثاث",
    "أجهزة وإلكترونيات": "أجهزة وإلكترونيات",
    "أصول ومعدات": "أصول ومعدات",
    "أكياس": "أكياس",
    "بضاعة تموينية": "بضاعة تموينية",
    "بلاستيكات": "بلاستيكات",
    "تعبئة وتغليف": "تعبئة وتغليف",
    "خامات": "خامات",
    "خضار وفواكه": "خضار وفواكه",
    "دجاج": "دواجن",
    "شحم": "شحوم",
    "شيشة": "شيشة",
    "علب وأكواب": "علب وأكواب",
    "غاز طبخ": "غاز طبخ",
    "غازيات": "مشروبات غازية",
    "فحم": "فحم",
    "قروض": "جهات تمويل",
    "قطع غيار": "قطع غيار",
    "قهوة بن": "قهوة وبن",
    "لحوم": "لحوم",
    "مستلزمات تشغيل مطبخ": "مستلزمات تشغيل مطبخ",
    "مشروبات": "مشروبات",
    "معدات مكتبية": "معدات مكتبية",
    "معسل": "معسل",
    "مواد غذائية": "مواد غذائية",
    "مواد غذائية أخرى": "مواد غذائية",
    "وقود ومواصلات": "وقود ومواصلات",
}
APPROVED_PARTNER_CROSSWALKS = {
    "هيئة الزكاة والدخل": "هيئة الزكاة والضريبة والجمارك | Zakat Tax and Customs Authority",
    "وزارة البلدية": "وزارة البلديات والإسكان | Ministry of Municipalities and Housing",
    "GOSI": "المؤسسة العامة للتأمينات الاجتماعية | General Organization for Social Insurance",
    "اقامات": "وزارة الموارد البشرية والتنمية الاجتماعية | Ministry of Human Resources and Social Development",
    "الشركة السعودية للكهرباء": "الشركة السعودية للطاقة | Saudi Energy",
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as source:
        return json.load(source)


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def digits(value: Any) -> str:
    return re.sub(r"[^0-9]", "", str(value or ""))


def valid_saudi_vat(value: Any) -> str | None:
    candidate = digits(value)
    if (
        len(candidate) == 15
        and candidate.startswith("3")
        and candidate.endswith("3")
        and len(set(candidate)) > 1
    ):
        return candidate
    return None


def normalized_name(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower().strip()
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه", "ـ": ""}))
    text = re.sub(r"[^\w\u0600-\u06ff]", "", text, flags=re.UNICODE)
    for token in LEGAL_TOKENS:
        text = text.replace(token, "")
    return text


def normalized_phone(value: Any) -> str:
    phone = digits(value)
    if phone.startswith("00966"):
        return "966" + phone[5:]
    if phone.startswith("966"):
        return phone
    if phone.startswith("0") and len(phone) == 10:
        return "966" + phone[1:]
    return phone


def target_tag_name(tag: dict[str, Any]) -> str:
    value = tag.get("name")
    if isinstance(value, dict):
        return str(value.get("ar_001") or value.get("ar") or value.get("en_US") or "")
    return str(value or "")


def choose_raw_name(rows: list[dict[str, Any]], field: str = "name_ar") -> str:
    active = [row for row in rows if not row.get("is_deleted") and str(row.get(field) or "").strip()]
    choices = active or [row for row in rows if str(row.get(field) or "").strip()]
    if not choices:
        return ""
    counts = Counter(str(row[field]).strip() for row in choices)
    first_id = {
        name: min(str(row["id"]) for row in choices if str(row[field]).strip() == name)
        for name in counts
    }
    return sorted(counts, key=lambda name: (-counts[name], -len(name), name, first_id[name]))[0]


def choose_phone(rows: list[dict[str, Any]]) -> str:
    active = [row for row in rows if not row.get("is_deleted") and str(row.get("phone") or "").strip()]
    normalized = {normalized_phone(row.get("phone")) for row in active}
    if len(normalized) != 1:
        return ""
    return sorted(str(row["phone"]).strip() for row in active)[0]


def source_identity(row: dict[str, Any]) -> str:
    return ":".join(
        (SOURCE_SYSTEM, str(row["tenant_id"]), str(row["company_id"]), str(row["id"]))
    )


def source_category_identity(row: dict[str, Any]) -> str:
    return ":".join(
        (SOURCE_SYSTEM, str(row["tenant_id"]), str(row["company_id"]), str(row["id"]))
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--archive-sha256", required=True)
    parser.add_argument("--cutoff", required=True)
    args = parser.parse_args()

    source = load_json(args.source)
    target = load_json(args.target)
    suppliers = sorted(source["suppliers"], key=lambda row: str(row["id"]))
    categories = {str(row["id"]): row for row in source["categories"]}
    target_partners = target["partners"]
    target_tags = target["tags"]
    approved_crosswalks_by_source_name = {
        normalized_name(source_name): target_name
        for source_name, target_name in APPROVED_PARTNER_CROSSWALKS.items()
    }

    targets_by_vat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    targets_by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for partner in target_partners:
        vat = valid_saudi_vat(partner.get("vat"))
        if vat:
            targets_by_vat[vat].append(partner)
        name_key = normalized_name(partner.get("name"))
        if name_key:
            targets_by_name[name_key].append(partner)

    partner_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for supplier in suppliers:
        vat = valid_saudi_vat(supplier.get("tax_number"))
        is_anonymous_cash = normalized_name(supplier.get("name_ar")) == ANONYMOUS_CASH_NAME and not vat
        key = "cash-anonymous:noorix" if is_anonymous_cash else (f"vat:{vat}" if vat else f"row:{supplier['id']}")
        partner_groups[key].append(supplier)

    canonical_partners: list[dict[str, Any]] = []
    supplier_maps: list[dict[str, Any]] = []
    blocked_supplier_groups = 0
    for key in sorted(partner_groups):
        rows = partner_groups[key]
        vat = valid_saudi_vat(rows[0].get("tax_number")) if key.startswith("vat:") else None
        is_anonymous_cash = key == "cash-anonymous:noorix"
        decision = "cash_anonymous" if is_anonymous_cash else ("automatic_valid_vat" if vat else "kept_separate")
        target_partner_id: int | None = None
        source_name = ANONYMOUS_CASH_PARTNER_NAME if is_anonymous_cash else choose_raw_name(rows)
        approved_target_name = approved_crosswalks_by_source_name.get(normalized_name(source_name))
        if approved_target_name:
            candidates = targets_by_name.get(normalized_name(approved_target_name), [])
            if (
                len(candidates) == 1
                and candidates[0].get("company_id") is None
                and candidates[0].get("parent_id") is None
            ):
                decision = "existing_approved_crosswalk"
                target_partner_id = candidates[0]["id"]
            else:
                decision = "blocked_conflict"
                blocked_supplier_groups += 1
        elif vat:
            candidates = targets_by_vat.get(vat, [])
            if candidates:
                if (
                    len(candidates) == 1
                    and candidates[0].get("company_id") is None
                    and candidates[0].get("parent_id") is None
                ):
                    decision = "existing_global_vat"
                    target_partner_id = candidates[0]["id"]
                else:
                    decision = "blocked_conflict"
                    blocked_supplier_groups += 1
        canonical = {
            "canonical_key": key,
            "decision": decision,
            "target_partner_id": target_partner_id,
            "name": source_name,
            "vat": vat,
            "phone": choose_phone(rows),
            "active": any(not row.get("is_deleted") for row in rows),
            "source_ids": [source_identity(row) for row in rows],
        }
        canonical_partners.append(canonical)
        for row in rows:
            supplier_maps.append(
                {
                    "source_system": SOURCE_SYSTEM,
                    "source_tenant_id": row["tenant_id"],
                    "source_company_id": row["company_id"],
                    "source_supplier_id": row["id"],
                    "source_row_sha256": digest(row),
                    "source_archive_sha256": args.archive_sha256,
                    "canonical_key": key,
                    "decision": decision,
                    "target_partner_id": target_partner_id,
                }
            )

    category_source_rows = [
        categories[str(row["supplier_category_id"])]
        for row in suppliers
        if row.get("supplier_category_id") and str(row["supplier_category_id"]) in categories
    ]
    unique_category_sources = {str(row["id"]): row for row in category_source_rows}
    category_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for category in unique_category_sources.values():
        key = normalized_name(category.get("name_ar"))
        if key:
            canonical_key = "tag:small-cash-invoices" if key == ANONYMOUS_CASH_NAME else f"tag:{key}"
            category_groups[canonical_key].append(category)

    target_tags_by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for tag in target_tags:
        key = normalized_name(target_tag_name(tag))
        if key:
            target_tags_by_name[key].append(tag)

    canonical_categories: list[dict[str, Any]] = []
    category_maps: list[dict[str, Any]] = []
    category_key_by_source_id: dict[str, str] = {}
    for key in sorted(category_groups):
        rows = category_groups[key]
        is_anonymous_cash = key == "tag:small-cash-invoices"
        normalized = ANONYMOUS_CASH_NAME if is_anonymous_cash else key.removeprefix("tag:")
        approved_target_name = APPROVED_CATEGORY_TARGETS.get(
            ANONYMOUS_CASH_CATEGORY_NAME if is_anonymous_cash else choose_raw_name(rows)
        )
        candidates = target_tags_by_name.get(
            normalized_name(approved_target_name) if approved_target_name else normalized,
            [],
        )
        if approved_target_name and len(candidates) == 1:
            decision, target_tag_id = "existing_approved_semantic", candidates[0]["id"]
        elif len(candidates) == 1:
            decision, target_tag_id = "existing_exact_name", candidates[0]["id"]
        elif len(candidates) > 1:
            decision, target_tag_id = "ambiguous_existing_name", None
        else:
            decision, target_tag_id = "create_new", None
        canonical_categories.append(
            {
                "canonical_key": key,
                "decision": decision,
                "target_tag_id": target_tag_id,
                "name": ANONYMOUS_CASH_CATEGORY_NAME if is_anonymous_cash else choose_raw_name(rows),
                "source_category_ids": [source_category_identity(row) for row in rows],
                "source_types": sorted({str(row.get("type") or "") for row in rows}),
            }
        )
        for row in rows:
            category_key_by_source_id[str(row["id"])] = key
            category_maps.append(
                {
                    "source_system": SOURCE_SYSTEM,
                    "source_tenant_id": row["tenant_id"],
                    "source_company_id": row["company_id"],
                    "source_category_id": row["id"],
                    "source_row_sha256": digest(row),
                    "source_archive_sha256": args.archive_sha256,
                    "canonical_key": key,
                    "target_tag_id": target_tag_id,
                    "decision": decision,
                }
            )

    category_key_by_supplier_source = {
        source_identity(row): category_key_by_source_id.get(str(row.get("supplier_category_id")))
        for row in suppliers
    }
    canonical_key_by_source = {
        source_identity(row): (
            "cash-anonymous:noorix"
            if normalized_name(row.get("name_ar")) == ANONYMOUS_CASH_NAME and not valid_saudi_vat(row.get("tax_number"))
            else (f"vat:{valid_saudi_vat(row.get('tax_number'))}" if valid_saudi_vat(row.get("tax_number")) else f"row:{row['id']}")
        )
        for row in suppliers
    }
    memberships = sorted(
        {
            (canonical_key_by_source[source_id], category_key)
            for source_id, category_key in category_key_by_supplier_source.items()
            if category_key
        }
    )
    report = {
        "archive_sha256": args.archive_sha256,
        "cutoff": args.cutoff,
        "source_supplier_rows": len(suppliers),
        "valid_vat_rows": sum(bool(valid_saudi_vat(row.get("tax_number"))) for row in suppliers),
        "canonical_supplier_groups": len(canonical_partners),
        "existing_global_vat_groups": sum(row["decision"] == "existing_global_vat" for row in canonical_partners),
        "existing_approved_crosswalk_groups": sum(row["decision"] == "existing_approved_crosswalk" for row in canonical_partners),
        "existing_global_partner_groups": sum(row["decision"] in {"existing_global_vat", "existing_approved_crosswalk"} for row in canonical_partners),
        "new_supplier_groups": sum(row["decision"] in {"automatic_valid_vat", "kept_separate", "cash_anonymous"} for row in canonical_partners),
        "anonymous_cash_source_rows": sum(row["canonical_key"] == "cash-anonymous:noorix" for row in supplier_maps),
        "blocked_supplier_groups": blocked_supplier_groups,
        "source_category_ids": len(unique_category_sources),
        "canonical_category_tags": len(canonical_categories),
        "reused_category_tags": sum(row["decision"] in {"existing_exact_name", "existing_approved_semantic"} for row in canonical_categories),
        "new_category_tags": sum(row["decision"] in {"create_new", "ambiguous_existing_name"} for row in canonical_categories),
        "canonical_supplier_tag_memberships": len(memberships),
        "source_supplier_maps": len(supplier_maps),
        "source_category_maps": len(category_maps),
    }
    payload = {
        "schema_version": 1,
        "source_system": SOURCE_SYSTEM,
        "source_archive_sha256": args.archive_sha256,
        "cutoff": args.cutoff,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "report": report,
        "canonical_partners": canonical_partners,
        "supplier_maps": supplier_maps,
        "canonical_categories": canonical_categories,
        "category_maps": category_maps,
        "memberships": [
            {"canonical_partner_key": partner_key, "canonical_category_key": category_key}
            for partner_key, category_key in memberships
        ],
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    payload_path = args.output_dir / "supplier-payload.json"
    payload_path.write_text(stable_json(payload) + "\n", encoding="utf-8")
    payload_sha256 = hashlib.sha256(payload_path.read_bytes()).hexdigest()
    report_lines = [
        "# Noorix supplier migration — read-only reconciliation",
        "",
        f"- Archive SHA-256: `{args.archive_sha256}`",
        f"- Historical cutoff: `{args.cutoff}`",
        f"- Payload SHA-256: `{payload_sha256}`",
        "",
        "| Measure | Count |",
        "| --- | ---: |",
    ]
    labels = {
        "source_supplier_rows": "In-scope source supplier rows",
        "valid_vat_rows": "Rows with a valid Saudi VAT",
        "canonical_supplier_groups": "Canonical supplier groups",
        "existing_global_vat_groups": "Groups mapped to an existing global partner by valid VAT",
        "existing_approved_crosswalk_groups": "Groups mapped through an owner-approved partner crosswalk",
        "existing_global_partner_groups": "Total groups mapped to an existing Odoo global partner",
        "new_supplier_groups": "Groups eligible to create in QA",
        "anonymous_cash_source_rows": "Anonymous cash source rows grouped into one partner",
        "blocked_supplier_groups": "Blocked supplier groups",
        "source_category_ids": "Referenced source category IDs",
        "canonical_category_tags": "Canonical Noorix supplier-category groups",
        "reused_category_tags": "Noorix category groups resolved to existing QA tags",
        "new_category_tags": "QA tags still required to create",
        "canonical_supplier_tag_memberships": "Canonical supplier/tag memberships",
        "source_supplier_maps": "Supplier source mappings",
        "source_category_maps": "Category source mappings",
    }
    report_lines.extend(f"| {labels[key]} | {report[key]} |" for key in labels)
    report_lines.extend(
        [
            "",
            "Policy: only one exact valid Saudi VAT mapped to one global top-level Odoo partner is reused. ",
            "Name and phone similarity do not create a merge, link, or rename.",
        ]
    )
    (args.output_dir / "supplier-reconciliation.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    print(payload_sha256)


if __name__ == "__main__":
    main()
