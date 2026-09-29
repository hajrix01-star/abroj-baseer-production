"""Read-only rebind capacity plan for the Noorix MAIN rehearsal.

This intentionally plans references only.  It never creates, updates or posts
an Odoo record; a later writer may proceed only when this plan has no
ambiguities and its planned master-data actions have been accepted.
"""

from __future__ import annotations

import re

from . import replay_guard


def _normal(value):
    value = (value or "").strip().casefold()
    value = value.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه"}))
    return re.sub(r"[\s\-_.،,()]+", "", value)


def _company_specs(payloads):
    specs = {}
    for payload in payloads:
        candidates = payload.get("companies", [])
        if isinstance(payload.get("company"), dict) and payload["company"].get("canonical_key"):
            candidates = candidates + [payload["company"]]
        for row in candidates:
            source = row.get("source", {})
            source_id = row.get("source_company_id")
            name = source.get("source_name_ar") or source.get("nameAr")
            canonical = row.get("canonical_key")
            if source_id and name and canonical:
                specs[source_id] = {"canonical_key": canonical, "name": name, "decision": row.get("decision")}
    return specs


def _one(records):
    return records if len(records) == 1 else False


def plan(env, path):
    """Return an all-read-only capacity/rebind plan; fail only on bad manifest."""
    replay_guard.assert_rehearsal_database(env)
    manifest = replay_guard.load_source_manifest(path)
    payloads = [contract["payload"] for contract in manifest["contracts"]]
    companies = _company_specs(payloads)
    Company = env["res.company"].sudo()
    company_plan, company_by_source = [], {}
    by_canonical = {}
    for source_id, spec in companies.items():
        by_canonical.setdefault(spec["canonical_key"], []).append((source_id, spec))
    for canonical, source_rows in sorted(by_canonical.items()):
        sample = source_rows[0][1]
        matches = Company.search([]).filtered(
            lambda row: _normal(row.name) == _normal(sample["name"])
            and row.active
            and row.currency_id.name == "SAR"
            and row.country_id.code == "SA"
        )
        status = "reuse" if len(matches) == 1 else "create" if not matches else "ambiguous"
        company_plan.append({"canonical_key": canonical, "name": sample["name"], "status": status, "matches": len(matches)})
        if len(matches) == 1:
            for source_id, _spec in source_rows:
                company_by_source[source_id] = matches

    supplier_payload = next((p for p in payloads if "canonical_partners" in p), {})
    partners = env["res.partner"].sudo().search([("company_id", "=", False)])
    supplier_counts = {"reuse_vat": 0, "reuse_name_phone": 0, "create": 0, "ambiguous": 0}
    for supplier in supplier_payload.get("canonical_partners", []):
        vat = (supplier.get("vat") or "").strip()
        vat_matches = partners.filtered(lambda row: vat and (row.vat or "").strip() == vat)
        if len(vat_matches) == 1:
            supplier_counts["reuse_vat"] += 1
            continue
        if len(vat_matches) > 1:
            supplier_counts["ambiguous"] += 1
            continue
        phone = supplier.get("phone") or ""
        email = supplier.get("email") or ""
        name_matches = partners.filtered(
            lambda row: _normal(row.name) == _normal(supplier["name"])
            and (
                (bool(phone) and _normal(row.phone) == _normal(phone))
                or (bool(email) and _normal(row.email) == _normal(email))
                or (not phone and not email)
            )
        )
        if len(name_matches) == 1:
            supplier_counts["reuse_name_phone"] += 1
        elif not name_matches:
            supplier_counts["create"] += 1
        else:
            supplier_counts["ambiguous"] += 1

    historical_categories = [
        row for payload in payloads for row in payload.get("category_decisions", [])
    ]
    account_counts = {"resolved": 0, "deferred_new_company": 0, "missing_or_ambiguous": 0}
    for category in historical_categories:
        company = company_by_source.get(category["source_company_id"])
        if not company:
            account_counts["deferred_new_company"] += 1
            continue
        matches = env["account.account"].sudo().with_company(company).with_context(
            allowed_company_ids=[company.id]
        ).search([
            ("company_ids", "in", company.ids),
            ("code", "=", category["decision_account_code"]),
        ])
        if len(matches) == 1 and (not category.get("decision_account_type") or matches.account_type == category["decision_account_type"]):
            account_counts["resolved"] += 1
        else:
            account_counts["missing_or_ambiguous"] += 1

    vault_counts = {"resolved": 0, "create": 0, "deferred_new_company": 0, "ambiguous": 0}
    for vault in [row for payload in payloads for row in payload.get("vault_decisions", [])]:
        company = company_by_source.get(vault["source_company_id"])
        if not company:
            vault_counts["deferred_new_company"] += 1
            continue
        matches = env["account.journal"].sudo().with_company(company).with_context(
            allowed_company_ids=[company.id]
        ).search([
            ("company_id", "=", company.id),
            ("code", "=", vault["decision_journal_code"]),
            ("type", "=", vault["decision_journal_type"]),
        ])
        if len(matches) == 1:
            vault_counts["resolved"] += 1
        elif not matches:
            vault_counts["create"] += 1
        else:
            vault_counts["ambiguous"] += 1

    return {
        "database": env.cr.dbname,
        "manifest_sha256": replay_guard.SOURCE_MANIFEST_SHA256,
        "orm_writes": 0,
        "companies": company_plan,
        "suppliers": supplier_counts,
        "historical_category_accounts": account_counts,
        "vaults": vault_counts,
        "documents": sum(len(payload.get("documents", [])) for payload in payloads),
        "split_purchase_invoices": sum(
            1 for payload in payloads if isinstance(payload.get("invoice"), dict) and payload.get("settlements")
        ),
        "purchase_invoices_total": sum(len(payload.get("documents", [])) for payload in payloads)
        + sum(1 for payload in payloads if isinstance(payload.get("invoice"), dict) and payload.get("settlements")),
        "sales_summaries": sum(len(payload.get("summaries", [])) for payload in payloads),
    }
