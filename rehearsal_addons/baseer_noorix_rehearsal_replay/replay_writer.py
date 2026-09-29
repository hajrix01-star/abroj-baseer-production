"""Source-only master replay for the isolated 18084 Noorix rehearsal.

The writer has no UI entry point.  It may be run only through a controlled
Odoo shell after the runtime guard has proved the target and source pins.
Financial document writers intentionally belong to later waves.
"""

from __future__ import annotations

import hashlib
import json
import re

from odoo.exceptions import UserError

from . import purchase_contract, runtime_guard
from .models.evidence import WRITER_CONTEXT


# This is intentionally a closed allow-list.  A future source manifest cannot
# turn a generic document override into an approved product/account target:
# every override below binds one immutable source document to its exact
# category provenance.  No source or target lookup falls back to a name.
_HISTORICAL_DOCUMENT_SERVICE_OVERRIDES = {
    "document_expense_override": {
        "decision_fields": {
            "source_mapping_key": "document:cmnylglul000avtjyzo1u3z7b",
            "canonical_key": "karak-purchase:NOORIX-HIST-KARAK-ELECTRONICS",
            "decision_product_code": "NOORIX-HIST-KARAK-ELECTRONICS",
            "decision_product_name": "تاريخي - أجهزة وإلكترونيات",
            "decision_account_code": "400050",
            "source_row_sha256": "6b03a1e5035f78526610bdead02b264f1bd75e1a87d8f9a9aefc7088c199bfcb",
        },
        "document_fields": {
            "source_invoice_id": "cmnylglul000avtjyzo1u3z7b",
            "decision": "create_paid_vendor_bill",
        },
    },
    "document_asset_override": {
        "decision_fields": {
            "source_mapping_key": "document:cmnyo8tox000f9abseyg43zdg",
            "canonical_key": "karak-purchase:NOORIX-HIST-KARAK-CASHIER-COMPUTER",
            "decision_product_code": "NOORIX-HIST-KARAK-CASHIER-COMPUTER",
            "decision_product_name": "تاريخي - كمبيوتر الكاشير",
            "decision_account_code": "106003",
            "source_row_sha256": "17ec6bea7b1c7356326cc9cf2adaa00d7b4f8a673b6620c0649cdee4efe14ca2",
        },
        "document_fields": {
            "source_invoice_id": "cmnyo8tox000f9abseyg43zdg",
            "decision": "capitalize_cashier_computer",
            "source_asset_id": "cmnyo9oxs000p9absv3j8y3dm",
            "source_asset_row_sha256": "9b1e369f36ff670708015ef9f5bdbd03d6dade56e6661e3c39befecfc5dffadc",
        },
        "account_type": "asset_fixed",
    },
}


def _normal(value):
    value = (value or "").strip().casefold()
    value = value.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه"}))
    return re.sub(r"[\s\-_.،,()]+", "", value)


def _payloads(manifest):
    return [contract["payload"] for contract in manifest["contracts"]]


def _company_rows(payloads):
    rows = []
    for payload in payloads:
        rows.extend(payload.get("companies", []))
        company = payload.get("company")
        if isinstance(company, dict) and company.get("canonical_key"):
            rows.append(company)
    return rows


def _source_identity(row):
    return ":".join(str(row.get(key, "")) for key in (
        "source_system", "source_tenant_id", "source_company_id", "source_supplier_id",
    ))


def _company_name(source):
    return source.get("source_name_ar") or source.get("nameAr") or ""


def _hash_code(prefix, canonical_key):
    return "%s-%s" % (prefix, hashlib.sha256(canonical_key.encode("utf-8")).hexdigest()[:16].upper())


def _writer_model(env, model):
    return env[model].sudo().with_context(**{WRITER_CONTEXT: True})


def _lock(env, scope_key):
    env.cr.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [
        "%s:noorix-rehearsal:%s" % (env.cr.dbname, scope_key),
    ])


def _one(recordset, label):
    if len(recordset) != 1:
        raise UserError("Noorix rehearsal rebind requires one %s; found %s" % (label, len(recordset)))
    return recordset


def _get_or_start_run(env, scope, run_key):
    Run = _writer_model(env, "baseer.noorix.rehearsal.run")
    run = Run.search([("run_key", "=", run_key)])
    if run:
        _one(run, "replay run")
        if (
            run.scope != scope
            or run.source_archive_sha256 != runtime_guard.SOURCE_ARCHIVE_SHA256
            or run.manifest_sha256 != runtime_guard.SOURCE_MANIFEST_SHA256
        ):
            raise UserError("Noorix rehearsal run identity differs for %s" % run_key)
        if run.state not in {"committed", "reconciled"}:
            raise UserError("Noorix rehearsal run %s is not safely resumable" % run_key)
        return run, False
    return Run.create({
        "run_key": run_key,
        "scope": scope,
        "source_archive_sha256": runtime_guard.SOURCE_ARCHIVE_SHA256,
        "manifest_sha256": runtime_guard.SOURCE_MANIFEST_SHA256,
        "state": "planned",
    }), True


def _commit_run(run, result):
    run.with_context(**{WRITER_CONTEXT: True}).write({
        "state": "committed",
        "result_json": json.dumps(result, ensure_ascii=False, sort_keys=True),
    })


def _ensure_map(env, *, scope, source_identity, source_row_sha256, canonical_key, target, run):
    Map = _writer_model(env, "baseer.noorix.rehearsal.source.map")
    existing = Map.search([("scope", "=", scope), ("source_identity", "=", source_identity)])
    if existing:
        _one(existing, "source mapping")
        if (
            existing.source_row_sha256 != source_row_sha256
            or existing.source_archive_sha256 != runtime_guard.SOURCE_ARCHIVE_SHA256
            or existing.canonical_key != canonical_key
            or existing.target_model != target._name
            or existing.target_res_id != target.id
        ):
            raise UserError("Noorix source mapping differs for %s" % source_identity)
        return existing
    return Map.create({
        "scope": scope,
        "source_identity": source_identity,
        "source_row_sha256": source_row_sha256,
        "source_archive_sha256": runtime_guard.SOURCE_ARCHIVE_SHA256,
        "canonical_key": canonical_key,
        "target_model": target._name,
        "target_res_id": target.id,
        "run_id": run.id,
    })


def _source_key(row, terminal_key):
    parts = [str(row.get(key, "")) for key in (
        "source_system", "source_tenant_id", "source_company_id",
    )]
    # A company map is already uniquely identified by its source-company id.
    # Appending that id again only obscures the evidence record.
    if terminal_key != "source_company_id":
        parts.append(str(row.get(terminal_key, "")))
    return ":".join(parts)


def _country_sa(env):
    return _one(env["res.country"].sudo().search([("code", "=", "SA")]), "Saudi Arabia country")


def _currency_sar(env):
    return _one(env["res.currency"].sudo().search([("name", "=", "SAR")]), "SAR currency")


def _canonical_company_specs(payloads):
    by_canonical = {}
    for row in _company_rows(payloads):
        by_canonical.setdefault(row["canonical_key"], []).append(row)
    return by_canonical


def _company_by_source(env, source_company_id):
    mappings = _writer_model(env, "baseer.noorix.rehearsal.source.map").search([
        ("scope", "=", "company"),
    ]).filtered(lambda mapping: mapping.source_identity.rsplit(":", 1)[-1] == source_company_id)
    mapping = _one(mappings, "company source mapping")
    if mapping.target_model != "res.company":
        raise UserError("Company source mapping has an invalid target model")
    return env["res.company"].sudo().with_context(active_test=False).browse(mapping.target_res_id).exists()


def _company_target(env, row):
    source = row["source"]
    Company = env["res.company"].sudo().with_context(active_test=False)
    matches = Company.search([]).filtered(
        lambda company: not company.parent_id
        and company.active
        and company.country_id.code == "SA"
        and company.currency_id.name == "SAR"
        and _normal(company.name) == _normal(_company_name(source))
    )
    if row["decision"] == "reuse_existing_company":
        return _one(matches, "existing root company")
    if row["decision"] not in {"create_historical_company", "create_active_company"}:
        raise UserError("Unsupported company decision %s" % row["decision"])
    if matches:
        raise UserError("Historical company %s unexpectedly already exists" % _company_name(source))
    return Company.create({
        "name": _company_name(source),
        "country_id": _country_sa(env).id,
        "currency_id": _currency_sar(env).id,
        # Karak remains active during its historical posting waves, then the
        # final reconciliation wave archives it as approved by the owner.
        "active": True,
    })


def apply_company_master(env, path=None):
    """Create/rebind exactly the five legal companies and six source aliases."""
    runtime_guard.assert_rehearsal_database(env)
    manifest = runtime_guard.load_source_manifest(path or runtime_guard.DEFAULT_MANIFEST_PATH)
    _lock(env, "master-company")
    run, fresh = _get_or_start_run(env, "master_company", "master-company:all")
    if not fresh:
        return json.loads(run.result_json)

    payloads = _payloads(manifest)
    targets = {}
    source_rows = 0
    for canonical_key, rows in _canonical_company_specs(payloads).items():
        primary = next((item for item in rows if item["decision"] != "alias_archived_company"), rows[0])
        target = _company_target(env, primary)
        targets[canonical_key] = target
        for row in rows:
            _ensure_map(
                env,
                scope="company",
                source_identity=_source_key(row, "source_company_id"),
                source_row_sha256=row["source_row_sha256"],
                canonical_key=canonical_key,
                target=target,
                run=run,
            )
            source_rows += 1
    result = {"canonical_companies": len(targets), "source_company_ids": source_rows, "company_ids": sorted(target.id for target in targets.values())}
    _commit_run(run, result)
    return result


def _partner_target(env, supplier):
    Partner = env["res.partner"].sudo().with_context(active_test=False)
    partners = Partner.search([("company_id", "=", False)])
    vat = (supplier.get("vat") or "").strip()
    if vat:
        matches = partners.filtered(lambda partner: (partner.vat or "").strip() == vat)
        if matches:
            return _one(matches, "supplier VAT")
    phone, email = _normal(supplier.get("phone")), _normal(supplier.get("email"))
    if phone or email:
        matches = partners.filtered(
            lambda partner: _normal(partner.name) == _normal(supplier["name"])
            and ((phone and _normal(partner.phone) == phone) or (email and _normal(partner.email) == email))
        )
        if matches:
            return _one(matches, "supplier name and contact")
    return Partner.create({
        "name": supplier["name"],
        "vat": vat or False,
        "phone": supplier.get("phone") or False,
        "email": supplier.get("email") or False,
        "supplier_rank": 1,
        "company_type": "company",
        "country_id": _country_sa(env).id,
        "active": bool(supplier.get("active", True)),
    })


def _tag_target(env, spec):
    Tag = env["res.partner.category"].sudo()
    matches = Tag.search([("name", "=", spec["name"])])
    if matches:
        return _one(matches, "supplier tag")
    return Tag.create({"name": spec["name"]})


def apply_supplier_master(env, path=None):
    """Create/rebind global suppliers, supplier tags and every source alias."""
    runtime_guard.assert_rehearsal_database(env)
    manifest = runtime_guard.load_source_manifest(path or runtime_guard.DEFAULT_MANIFEST_PATH)
    _lock(env, "suppliers-global")
    run, fresh = _get_or_start_run(env, "suppliers_global", "suppliers-global:all")
    if not fresh:
        return json.loads(run.result_json)

    payload = next(item for item in _payloads(manifest) if "canonical_partners" in item)
    partners, tags = {}, {}
    for supplier in payload["canonical_partners"]:
        partners[supplier["canonical_key"]] = _partner_target(env, supplier)
    for category in payload["canonical_categories"]:
        tags[category["canonical_key"]] = _tag_target(env, category)
    for membership in payload["memberships"]:
        partner = partners[membership["canonical_partner_key"]]
        tag = tags[membership["canonical_category_key"]]
        if tag not in partner.category_id:
            partner.write({"category_id": [(4, tag.id)]})
    for row in payload["supplier_maps"]:
        _ensure_map(
            env,
            scope="supplier",
            source_identity=_source_key(row, "source_supplier_id"),
            source_row_sha256=row["source_row_sha256"],
            canonical_key=row["canonical_key"],
            target=partners[row["canonical_key"]],
            run=run,
        )
    for row in payload["category_maps"]:
        _ensure_map(
            env,
            scope="supplier_tag",
            source_identity=_source_key(row, "source_category_id"),
            source_row_sha256=row["source_row_sha256"],
            canonical_key=row["canonical_key"],
            target=tags[row["canonical_key"]],
            run=run,
        )
    result = {
        "canonical_suppliers": len(partners), "source_supplier_ids": len(payload["supplier_maps"]),
        "supplier_tags": len(tags), "source_supplier_category_ids": len(payload["category_maps"]),
    }
    _commit_run(run, result)
    return result


def _supplier_consolidation_groups(env):
    """Return only exact duplicate Noorix supplier contacts and their primary."""
    Map = _writer_model(env, "baseer.noorix.rehearsal.source.map")
    supplier_maps = Map.search([("scope", "=", "supplier")])
    targets = env["res.partner"].sudo().with_context(active_test=False).browse(
        sorted(set(supplier_maps.mapped("target_res_id")))
    ).exists()
    by_name = {}
    for partner in targets:
        # Company-bound addresses and non-suppliers are never consolidation candidates.
        if partner.company_id or partner.supplier_rank < 1:
            continue
        by_name.setdefault(_normal(partner.name), []).append(partner)

    groups = []
    for normalized_name, partners in by_name.items():
        if len(partners) < 2:
            continue
        partners = env["res.partner"].browse(sorted(partner.id for partner in partners))
        vat_partners = partners.filtered(lambda partner: bool((partner.vat or "").strip()))
        if len(vat_partners) > 1:
            raise UserError("Supplier duplicate group has more than one VAT identity: %s" % partners.mapped("name"))
        primary = vat_partners or partners[:1]
        duplicates = partners - primary
        maps = supplier_maps.filtered(lambda mapping: mapping.target_res_id in partners.ids)
        if not maps:
            raise UserError("Supplier duplicate group has no Noorix source mapping")
        groups.append({
            "normalized_name": normalized_name,
            "primary": primary,
            "duplicates": duplicates,
            "maps": maps,
        })
    return groups


def apply_supplier_consolidation(env):
    """Permanently delete exact duplicate supplier contacts after source redirects.

    Existing source maps remain immutable evidence.  A new consolidation map
    redirects every affected source identity to the selected shared supplier,
    so future financial writers never dereference a deleted contact.
    """
    runtime_guard.assert_rehearsal_database(env)
    _lock(env, "suppliers-consolidation")
    run, fresh = _get_or_start_run(env, "supplier_consolidation", "supplier-consolidation:exact-name-v1")
    if not fresh:
        return json.loads(run.result_json)

    groups = _supplier_consolidation_groups(env)
    redirected = deleted = 0
    for group in groups:
        primary = group["primary"]
        duplicates = group["duplicates"]
        # Preserve all supplier classifications on the surviving shared record.
        all_tags = (primary | duplicates).mapped("category_id")
        primary.write({
            "category_id": [(6, 0, all_tags.ids)],
            "supplier_rank": max((primary | duplicates).mapped("supplier_rank")),
            "country_id": _country_sa(env).id,
        })
        for source_map in group["maps"]:
            _ensure_map(
                env,
                scope="supplier_consolidation",
                source_identity=source_map.source_identity,
                source_row_sha256=source_map.source_row_sha256,
                canonical_key="supplier-name:%s" % group["normalized_name"],
                target=primary,
                run=run,
            )
            redirected += 1
        # Native unlink is deliberately used only after all source redirects
        # exist; any foreign-key or business-document reference aborts the
        # complete scope transaction.
        deleted += len(duplicates)
        duplicates.unlink()
    result = {
        "duplicate_groups": len(groups),
        "deleted_duplicate_contacts": deleted,
        "redirected_source_supplier_ids": redirected,
        "surviving_shared_suppliers": len(groups),
    }
    _commit_run(run, result)
    return result


def _product_category_target(env, spec, roots):
    Category = env["product.category"].sudo()
    root = roots.get(spec["root"])
    if not root:
        root_matches = Category.search([("name", "=", spec["root"]), ("parent_id", "=", False)])
        root = _one(root_matches, "product category root") if root_matches else Category.create({"name": spec["root"]})
        roots[spec["root"]] = root
    matches = Category.search([("name", "=", spec["name_ar"]), ("parent_id", "=", root.id)])
    return _one(matches, "product category") if matches else Category.create({"name": spec["name_ar"], "parent_id": root.id})


def _uom_by_name(env, name):
    Uom = env["uom.uom"].sudo().with_context(active_test=False)
    matches = Uom.browse()
    for language in (False, "ar_001", "en_US"):
        matches |= Uom.with_context(lang=language).search([("name", "=", name)])
    return _one(matches, "existing unit of measure")


def _uom_target(env, spec):
    if spec["decision"] == "reuse_existing_uom":
        return _uom_by_name(env, spec["expected_name"])
    if spec["decision"] != "create_package_root_uom":
        raise UserError("Unsupported UoM decision %s" % spec["decision"])
    Uom = env["uom.uom"].sudo().with_context(active_test=False)
    matches = Uom.search([("name", "=", spec["name"]), ("relative_uom_id", "=", False)])
    return _one(matches, "package root UoM") if matches else Uom.create({
        "name": spec["name"], "relative_uom_id": False, "relative_factor": 1.0, "rounding": 0.01,
    })


def _product_category_for_key(key, categories, roots):
    if key in categories:
        return categories[key]
    if key.startswith("root:"):
        expected_root = key.split(":", 1)[1]
        matches = [record for name, record in roots.items() if _normal(name) == _normal(expected_root)]
        if len(matches) == 1:
            return matches[0]
    raise UserError("No product category mapping for %s" % key)


def apply_product_master(env, path=None):
    """Create company-owned non-stock products, categories and source UoM maps."""
    runtime_guard.assert_rehearsal_database(env)
    manifest = runtime_guard.load_source_manifest(path or runtime_guard.DEFAULT_MANIFEST_PATH)
    _lock(env, "product-company")
    run, fresh = _get_or_start_run(env, "product_company", "product-company:all")
    if not fresh:
        return json.loads(run.result_json)

    payload = next(item for item in _payloads(manifest) if "canonical_products" in item)
    roots, categories, uoms, products = {}, {}, {}, {}
    for spec in payload["canonical_categories"]:
        categories[spec["canonical_key"]] = _product_category_target(env, spec, roots)
    for spec in payload["canonical_uoms"]:
        uoms[spec["canonical_key"]] = _uom_target(env, spec)
    for spec in payload["canonical_products"]:
        company = _company_by_source(env, spec["source_company_id"])
        if not company:
            raise UserError("No company mapping for product %s" % spec["canonical_key"])
        code = _hash_code("NOORIX", spec["canonical_key"])
        Template = env["product.template"].sudo().with_company(company).with_context(
            allowed_company_ids=[company.id], active_test=False
        )
        matches = Template.search([("company_id", "=", company.id), ("default_code", "=", code)])
        if matches:
            product = _one(matches, "company product default code")
        else:
            product = Template.create({
                "name": spec["name_ar"], "default_code": code, "company_id": company.id,
                "categ_id": _product_category_for_key(spec["category_key"], categories, roots).id,
                "uom_id": uoms[spec["uom_key"]].id,
                "purchase_ok": bool(spec["purchase_ok"]), "sale_ok": bool(spec["sale_ok"]),
                "type": spec["type"], "is_storable": False, "active": bool(spec["active"]),
            })
        products[spec["canonical_key"]] = product
    for row in payload["category_maps"]:
        _ensure_map(env, scope="product_category", source_identity=_source_key(row, "source_category_id"),
            source_row_sha256=row["source_row_sha256"], canonical_key=row["canonical_key"], target=categories[row["canonical_key"]], run=run)
    for row in payload["uom_maps"]:
        _ensure_map(env, scope="product_uom", source_identity=_source_key(row, "source_uom_id"),
            source_row_sha256=row["source_row_sha256"], canonical_key=row["canonical_key"], target=uoms[row["canonical_key"]], run=run)
    for row in payload["product_maps"]:
        _ensure_map(env, scope="product", source_identity=_source_key(row, "source_product_id"),
            source_row_sha256=row["source_row_sha256"], canonical_key=row["canonical_key"], target=products[row["canonical_key"]], run=run)
    result = {
        "canonical_products": len(products), "source_product_ids": len(payload["product_maps"]),
        "product_categories": len(categories), "source_category_ids": len(payload["category_maps"]),
        "canonical_uoms": len(uoms), "source_uom_ids": len(payload["uom_maps"]),
    }
    _commit_run(run, result)
    return result


def _vault_decisions(manifest, snapshot):
    payload = next(item for item in _payloads(manifest) if "vault_decisions" in item)
    decisions = payload["vault_decisions"]
    source_rows = {
        (row["source_company_id"], row["source_vault_id"]): row
        for row in snapshot["vault_source_rows"]
    }
    decision_keys = {(row["source_company_id"], row["source_vault_id"]) for row in decisions}
    if decision_keys != set(source_rows) or len(decisions) != 14:
        raise UserError("Vault decisions do not exactly match the source vault snapshot")
    return decisions, source_rows


def _vault_target(env, decision, company):
    Journal = env["account.journal"].sudo().with_context(
        active_test=False, allowed_company_ids=[company.id]
    ).with_company(company)
    matches = Journal.search([
        ("company_id", "=", company.id),
        ("code", "=", decision["decision_journal_code"]),
        ("type", "=", decision["decision_journal_type"]),
    ])
    if decision["decision"] == "reuse_existing_liquidity":
        journal = _one(matches, "existing liquidity journal")
        if not journal.active:
            raise UserError("Approved liquidity journal is archived: %s" % journal.code)
        return journal
    if decision["decision"] != "create_historical_wallet":
        raise UserError("Unsupported vault decision %s" % decision["decision"])
    if matches:
        raise UserError("Historical liquidity journal unexpectedly already exists: %s" % decision["decision_journal_code"])
    journal = Journal.create({
        "name": decision["decision_journal_name"],
        "code": decision["decision_journal_code"],
        "type": decision["decision_journal_type"],
        "company_id": company.id,
    })
    if not journal.active or not journal.default_account_id:
        raise UserError("Native liquidity journal setup is incomplete: %s" % journal.code)
    return journal


def apply_vault_master(env, path=None, snapshot_path=None):
    """Create/rebind the 14 approved liquidity journals without financial moves."""
    runtime_guard.assert_rehearsal_database(env)
    manifest = runtime_guard.load_source_manifest(path or runtime_guard.DEFAULT_MANIFEST_PATH)
    snapshot = runtime_guard.load_vault_snapshot(snapshot_path or runtime_guard.DEFAULT_VAULT_SNAPSHOT_PATH)
    _lock(env, "vault-company")
    run, fresh = _get_or_start_run(env, "vault_company", "vault-company:all")
    if not fresh:
        return json.loads(run.result_json)

    decisions, source_rows = _vault_decisions(manifest, snapshot)
    targets = {}
    reused = created = 0
    for decision in decisions:
        key = (decision["source_company_id"], decision["source_vault_id"])
        source = source_rows[key]
        if not source["source_active"] or source["source_archived"]:
            raise UserError("Approved vault is not active source liquidity: %s" % source["source_vault_id"])
        company = _company_by_source(env, source["source_company_id"])
        if not company or not company.active:
            raise UserError("No active company mapping for vault %s" % source["source_vault_id"])
        journal = _vault_target(env, decision, company)
        targets[key] = journal
        if decision["decision"] == "reuse_existing_liquidity":
            reused += 1
        else:
            created += 1
        _ensure_map(
            env,
            scope="vault",
            source_identity=_source_key(source, "source_vault_id"),
            source_row_sha256=source["source_row_sha256"],
            canonical_key="vault:%s:%s" % key,
            target=journal,
            run=run,
        )
    result = {
        "source_vault_ids": len(targets), "reused_liquidity_journals": reused,
        "created_historical_wallets": created, "journal_ids": sorted(journal.id for journal in targets.values()),
    }
    _commit_run(run, result)
    return result


def _company_env(env, model, company):
    """Return an explicitly single-company environment for every finance ORM call."""
    return env[model].sudo().with_company(company).with_context(
        allowed_company_ids=[company.id], active_test=False,
    )


def _mapped_target(
    env, scope, source_identity, source_row_sha256, target_model, label, canonical_key=None, company=None,
):
    """Resolve immutable evidence, in the target company when one is required.

    Product properties are company-dependent in Odoo.  A mapped company product
    must therefore never be browsed in the shell's ambient company (which can
    differ from the invoice company during an idempotent replay).
    """
    Map = _writer_model(env, "baseer.noorix.rehearsal.source.map")
    mapping = _one(Map.search([
        ("scope", "=", scope), ("source_identity", "=", source_identity),
    ]), label)
    if (
        mapping.source_row_sha256 != source_row_sha256
        or mapping.source_archive_sha256 != runtime_guard.SOURCE_ARCHIVE_SHA256
        or mapping.target_model != target_model
        or (canonical_key is not None and mapping.canonical_key != canonical_key)
    ):
        raise UserError("Noorix %s evidence differs for %s" % (label, source_identity))
    Target = _company_env(env, target_model, company) if company else env[target_model].sudo().with_context(
        active_test=False,
    )
    target = Target.browse(mapping.target_res_id).exists()
    if not target:
        raise UserError("Noorix %s target no longer exists for %s" % (label, source_identity))
    return target


def _supplier_for_purchase(env, document):
    identity = purchase_contract.source_identity(document, "source_supplier_id")
    # Consolidation redirects are later, immutable source evidence and always
    # take precedence over the original supplier map.  Neither route uses a
    # partner-name fallback.
    Map = _writer_model(env, "baseer.noorix.rehearsal.source.map")
    redirected = Map.search([("scope", "=", "supplier_consolidation"), ("source_identity", "=", identity)])
    if redirected:
        return _mapped_target(
            env, "supplier_consolidation", identity, redirected.source_row_sha256,
            "res.partner", "supplier consolidation",
        )
    source_map = _one(Map.search([("scope", "=", "supplier"), ("source_identity", "=", identity)]), "supplier")
    return _mapped_target(env, "supplier", identity, source_map.source_row_sha256, "res.partner", "supplier")


def _vault_for_purchase(env, company, document, settlement):
    source = dict(document)
    source.update(settlement)
    identity = purchase_contract.source_identity(source, "source_vault_id")
    # Vault maps store the original raw-vault digest, not a financial-document
    # hash.  It is intentionally checked by identity and target company here.
    Map = _writer_model(env, "baseer.noorix.rehearsal.source.map")
    mapping = _one(Map.search([("scope", "=", "vault"), ("source_identity", "=", identity)]), "source vault")
    if (
        mapping.source_archive_sha256 != runtime_guard.SOURCE_ARCHIVE_SHA256
        or mapping.target_model != "account.journal"
    ):
        raise UserError("Noorix source vault evidence differs for %s" % identity)
    journal = _company_env(env, "account.journal", company).browse(mapping.target_res_id).exists()
    if not journal or journal.company_id != company or journal.type not in {"bank", "cash"}:
        raise UserError("Noorix source vault is not a same-company bank/cash journal: %s" % identity)
    if not journal.default_account_id:
        raise UserError("Noorix source vault lacks a liquidity account: %s" % journal.code)
    return journal


def _purchase_journal(env, company):
    journal = _one(_company_env(env, "account.journal", company).search([
        ("company_id", "=", company.id), ("code", "=", "BILL"), ("type", "=", "purchase"),
    ]), "purchase journal BILL")
    if not journal.active:
        raise UserError("Noorix purchase journal BILL is archived")
    return journal


def _expense_account(env, company, decision):
    Account = _company_env(env, "account.account", company)
    company_field = "company_ids" if "company_ids" in Account._fields else "company_id"
    account = _one(Account.search([
        (company_field, "in", [company.id]), ("code", "=", decision["decision_account_code"]),
    ]), "same-company expense/asset account %s" % decision["decision_account_code"])
    expected_type = decision.get("decision_account_type")
    allowed_types = {"expense", "expense_direct_cost", "asset_fixed"}
    if expected_type and account.account_type != expected_type:
        raise UserError("Noorix account type differs for %s" % account.code)
    if not expected_type and account.account_type not in allowed_types:
        raise UserError("Noorix account type is not an approved purchase target for %s" % account.code)
    return account


def _purchase_tax_15(env, company):
    """Select ordinary purchase VAT only; reverse-charge/withholding never qualify."""
    Tax = _company_env(env, "account.tax", company)
    candidates = Tax.search([
        ("company_id", "=", company.id), ("type_tax_use", "=", "purchase"),
        ("amount_type", "=", "percent"), ("amount", "=", 15.0), ("price_include", "=", False),
    ]).filtered(lambda tax: tax.active and "104041" in tax.invoice_repartition_line_ids.mapped("account_id.code"))
    tax = _one(candidates, "ordinary 15% purchase VAT with input account 104041")
    tax_accounts = set(tax.invoice_repartition_line_ids.mapped("account_id.code"))
    if "104041" not in tax_accounts or "104043" in tax_accounts or "201017" in tax_accounts:
        raise UserError("Noorix selected an RC/withholding or invalid purchase tax")
    return tax


def _category_identity(document):
    decision = document["_category"]
    source = dict(document)
    source.update(decision)
    return purchase_contract.source_identity(source, "source_mapping_key")


def _historical_service_policy(document):
    """Return the closed override policy, or reject an unapproved category."""
    decision = document["_category"]
    decision_name = decision.get("decision")
    if decision_name == "create_historical_service":
        return {}
    if decision_name == "reuse_existing_service":
        # This is not a creation policy.  The exact company/default-code
        # rebind and the common product/account invariant are enforced by
        # _historical_service(); a missing or ambiguous product is unsafe.
        return {"reuse_existing": True}
    policy = _HISTORICAL_DOCUMENT_SERVICE_OVERRIDES.get(decision_name)
    if not policy:
        raise UserError("Unsupported purchase category decision %s" % decision_name)
    for field, expected in policy["decision_fields"].items():
        if decision.get(field) != expected:
            raise UserError("Noorix approved category override differs: %s" % field)
    for field, expected in policy["document_fields"].items():
        if document.get(field) != expected:
            raise UserError("Noorix approved document override differs: %s" % field)
    return policy


def _historical_service_account(env, company, document):
    """Resolve the approved account, including a fixed-asset type assertion."""
    policy = _historical_service_policy(document)
    account = _expense_account(env, company, document["_category"])
    expected_type = policy.get("account_type")
    if expected_type and account.account_type != expected_type:
        raise UserError("Noorix override account type differs for %s" % account.code)
    return account


def _assert_historical_service_product(product, company, account):
    """Keep creation and idempotent verification on the exact same invariant."""
    if (
        product.company_id != company or product.type != "service" or not product.purchase_ok
        or product.sale_ok or product.property_account_expense_id != account
    ):
        raise UserError("Noorix historical service invariant differs for %s" % product.default_code)


def _historical_service(env, company, document, run):
    """Create the exact approved service product for an allowed category decision."""
    decision = document["_category"]
    # The cashier-computer override intentionally remains a service product
    # whose invoice line posts to 106003.  The writer never creates stock or
    # invokes an asset/depreciation lifecycle; the source asset is provenance
    # evidence only and is asserted by _historical_service_policy().
    account = _historical_service_account(env, company, document)
    Product = _company_env(env, "product.template", company)
    product = Product.search([
        ("company_id", "=", company.id), ("default_code", "=", decision["decision_product_code"]),
    ])
    if product:
        product = _one(product, "historical service product")
    elif _historical_service_policy(document).get("reuse_existing"):
        raise UserError(
            "Noorix approved reusable service is missing for company %s: %s" % (
                company.id, decision["decision_product_code"],
            )
        )
    else:
        product = Product.create({
            "name": decision["decision_product_name"],
            "default_code": decision["decision_product_code"],
            "company_id": company.id,
            "type": "service",
            "purchase_ok": True,
            "sale_ok": False,
            "property_account_expense_id": account.id,
        })
    _assert_historical_service_product(product, company, account)
    _ensure_map(
        env, scope="purchase_category", source_identity=_category_identity(document),
        source_row_sha256=decision["source_row_sha256"], canonical_key=decision["canonical_key"],
        target=product, run=run,
    )
    return product, account


def _source_reference(document):
    return "NOORIX:%s | %s" % (document["source_invoice_id"], document.get("source_invoice_number") or "-")


def _invoice_identity(document):
    return purchase_contract.source_identity(document, "source_invoice_id")


def _payment_identity(document, settlement):
    source = dict(document)
    source.update(settlement)
    return purchase_contract.source_identity(source, "source_allocation_id")


def _reconciliation_identity(document, settlement):
    source = dict(document)
    source.update(settlement)
    return purchase_contract.source_identity(source, "source_invoice_id", "source_ledger_id", "source_allocation_id")


def _map_hash_for_settlement(document, settlement):
    return purchase_contract.settlement_hash(document, settlement)


def _assert_unmapped(env, scope, source_identity):
    if _writer_model(env, "baseer.noorix.rehearsal.source.map").search_count([
        ("scope", "=", scope), ("source_identity", "=", source_identity),
    ]):
        raise UserError("Noorix %s already has immutable evidence: %s" % (scope, source_identity))


def _create_purchase_invoice(env, company, document, product, account, journal, tax):
    identity = _invoice_identity(document)
    _assert_unmapped(env, "purchase_invoice", identity)
    Move = _company_env(env, "account.move", company)
    ref = _source_reference(document)
    if Move.search_count([
        ("company_id", "=", company.id), ("move_type", "=", "in_invoice"), ("ref", "=", ref),
    ]):
        raise UserError("Noorix vendor bill reference exists without provenance: %s" % ref)
    taxes = [(6, 0, tax.ids)] if document["_vat_policy"] == "vat15_inclusive" else [(5, 0, 0)]
    invoice = Move.create({
        "move_type": "in_invoice",
        "company_id": company.id,
        "journal_id": journal.id,
        "partner_id": _supplier_for_purchase(env, document).id,
        "invoice_date": document["business_date"],
        "date": document["business_date"],
        "ref": ref,
        "invoice_line_ids": [(0, 0, {
            "name": document["decision_product_name"],
            "product_id": product.product_variant_id.id,
            "account_id": account.id,
            "quantity": 1.0,
            "price_unit": float(purchase_contract.native_price_unit(document)),
            "tax_ids": taxes,
        })],
    })
    invoice.action_post()
    expected_total = float(purchase_contract.money(document["source_total_raw"]))
    if invoice.state != "posted" or abs(invoice.amount_total - expected_total) > 0.00001:
        raise UserError("Noorix vendor bill total/state differs for %s" % document["canonical_key"])
    return invoice


def _manual_outbound_method(journal):
    methods = journal.outbound_payment_method_line_ids.filtered(
        lambda line: line.payment_method_id.code == "manual"
    )
    return _one(methods, "manual outbound payment method")


def _create_purchase_payment(env, company, document, settlement, invoice, journal):
    identity = _payment_identity(document, settlement)
    _assert_unmapped(env, "purchase_payment", identity)
    Payment = _company_env(env, "account.payment", company)
    payment = Payment.create({
        "payment_type": "outbound",
        "partner_type": "supplier",
        "partner_id": invoice.partner_id.id,
        "amount": float(purchase_contract.money(settlement["amount_raw"])),
        "currency_id": company.currency_id.id,
        "date": document["business_date"],
        "journal_id": journal.id,
        "payment_method_line_id": _manual_outbound_method(journal).id,
        # Odoo 19's native payment memo is the persisted payment reference;
        # account.payment has no writable ``ref`` field.
        "memo": "NOORIX:%s" % settlement["source_allocation_id"],
    })
    payment.action_post()
    # Odoo 19 payment states are draft/in_process/paid (not ``posted``).  The
    # accounting post invariant belongs to the native move; a payment is valid
    # here only once that move is posted and Odoo has advanced its own state.
    if (
        payment.state not in {"in_process", "paid"} or not payment.move_id
        or payment.move_id.state != "posted"
        or abs(payment.amount - float(purchase_contract.money(settlement["amount_raw"]))) > 0.00001
    ):
        raise UserError(
            "Noorix payment total/state differs for %s (state=%s, move_state=%s, amount=%s, amount_company_signed=%s)"
            % (identity, payment.state, payment.move_id.state if payment.move_id else False,
               payment.amount, payment.amount_company_currency_signed)
        )
    return payment


def _payable_pair(invoice, payment):
    invoice_lines = invoice.line_ids.filtered(
        lambda line: line.account_id.account_type == "liability_payable" and line.partner_id == invoice.partner_id
    )
    payment_lines = payment.move_id.line_ids.filtered(
        lambda line: line.account_id.account_type == "liability_payable" and line.partner_id == invoice.partner_id
    )
    invoice_line = _one(invoice_lines, "vendor-bill payable line")
    payment_line = _one(payment_lines, "payment payable line")
    if invoice_line.account_id != payment_line.account_id:
        raise UserError("Noorix invoice/payment payable accounts differ")
    return invoice_line, payment_line


def _reconcile_purchase_payment(env, company, document, settlement, invoice, payment):
    identity = _reconciliation_identity(document, settlement)
    _assert_unmapped(env, "purchase_reconciliation", identity)
    invoice_line, payment_line = _payable_pair(invoice, payment)
    if invoice_line.reconciled or payment_line.reconciled:
        raise UserError("Noorix payment lines were unexpectedly reconciled before provenance")
    (invoice_line | payment_line).reconcile()
    partials = (invoice_line.matched_debit_ids | invoice_line.matched_credit_ids).filtered(
        lambda partial: {
            partial.debit_move_id.id, partial.credit_move_id.id,
        } == {invoice_line.id, payment_line.id}
    )
    partial = _one(partials, "native payment reconciliation")
    if abs(partial.amount - float(purchase_contract.money(settlement["amount_raw"]))) > 0.00001:
        raise UserError("Noorix native reconciliation amount differs for %s" % identity)
    return partial


def _invoice_canonical_key(document):
    # The tax decision is evidence, not just a line-construction detail.  A
    # changed VAT inference can therefore never silently replay the same bill.
    return "%s|vat_policy:%s" % (document["canonical_key"], document["_vat_policy"])


def _same_amount(actual, expected):
    return abs(actual - float(purchase_contract.money(expected))) <= 0.00001


def _verify_purchase_document(env, company, document):
    """Validate all target invariants without creating or modifying anything."""
    invoice = _mapped_target(
        env, "purchase_invoice", _invoice_identity(document), document["source_row_sha256"],
        "account.move", "purchase invoice", _invoice_canonical_key(document), company=company,
    )
    if (
        invoice.company_id != company or invoice.move_type != "in_invoice" or invoice.state != "posted"
        or invoice.ref != _source_reference(document) or not _same_amount(invoice.amount_total, document["source_total_raw"])
    ):
        raise UserError("Noorix vendor-bill invariant differs for %s" % document["canonical_key"])
    supplier = _supplier_for_purchase(env, document)
    if invoice.partner_id != supplier:
        raise UserError("Noorix vendor-bill supplier differs for %s" % document["canonical_key"])
    account = _historical_service_account(env, company, document)
    product = _mapped_target(
        env, "purchase_category", _category_identity(document), document["_category"]["source_row_sha256"],
        "product.template", "purchase category", document["_category"]["canonical_key"], company=company,
    )
    _assert_historical_service_product(product, company, account)
    # Odoo 19 labels ordinary invoice items explicitly as ``product`` rather
    # than leaving display_type false.  Section/note/tax display rows must
    # never satisfy the immutable product/account/tax verification below.
    invoice_lines = invoice.invoice_line_ids.filtered(lambda line: line.display_type == "product")
    line = _one(invoice_lines, "vendor-bill product line")
    if line.product_id.product_tmpl_id != product or line.account_id != account:
        raise UserError("Noorix vendor-bill line target differs for %s" % document["canonical_key"])
    expected_price = float(purchase_contract.native_price_unit(document))
    if abs(line.price_unit - expected_price) > 0.00001:
        raise UserError("Noorix vendor-bill line price differs for %s" % document["canonical_key"])
    expected_tax = _purchase_tax_15(env, company) if document["_vat_policy"] == "vat15_inclusive" else False
    if (expected_tax and line.tax_ids != expected_tax) or (not expected_tax and line.tax_ids):
        raise UserError("Noorix vendor-bill VAT policy differs for %s" % document["canonical_key"])

    for settlement in document["_settlements"]:
        settlement_hash = _map_hash_for_settlement(document, settlement)
        payment = _mapped_target(
            env, "purchase_payment", _payment_identity(document, settlement), settlement_hash,
            "account.payment", "purchase payment",
            "%s|payment:%s" % (document["canonical_key"], settlement["source_allocation_id"]), company=company,
        )
        journal = _vault_for_purchase(env, company, document, settlement)
        if (
            payment.company_id != company or payment.state != "paid" or not payment.move_id
            or payment.move_id.state != "posted" or not payment.is_reconciled or payment.partner_id != invoice.partner_id
            or payment.journal_id != journal or payment.memo != "NOORIX:%s" % settlement["source_allocation_id"]
            or not _same_amount(payment.amount, settlement["amount_raw"])
        ):
            raise UserError("Noorix payment invariant differs for %s" % _payment_identity(document, settlement))
        partial = _mapped_target(
            env, "purchase_reconciliation", _reconciliation_identity(document, settlement), settlement_hash,
            "account.partial.reconcile", "purchase reconciliation",
            "%s|reconciliation:%s" % (document["canonical_key"], settlement["source_allocation_id"]), company=company,
        )
        invoice_line, payment_line = _payable_pair(invoice, payment)
        if (
            {partial.debit_move_id.id, partial.credit_move_id.id} != {invoice_line.id, payment_line.id}
            or not _same_amount(partial.amount, settlement["amount_raw"])
        ):
            raise UserError("Noorix reconciliation invariant differs for %s" % _reconciliation_identity(document, settlement))
    if abs(invoice.amount_residual) > 0.00001 or invoice.payment_state != "paid":
        raise UserError("Noorix vendor bill is not fully paid for %s" % document["canonical_key"])
    return invoice


def _purchase_result(documents):
    totals = {
        "source_net": sum((purchase_contract.decimal_value(doc["source_net_raw"], "source_net_raw") for doc in documents), 0),
        "source_tax": sum((purchase_contract.decimal_value(doc["source_tax_raw"], "source_tax_raw") for doc in documents), 0),
        "source_gross": sum((purchase_contract.decimal_value(doc["source_total_raw"], "source_total_raw") for doc in documents), 0),
    }
    vat_counts = {"vat15_inclusive": 0, "no_tax": 0}
    for document in documents:
        vat_counts[document["_vat_policy"]] += 1
    return {
        "vendor_bills": len(documents),
        "payments": sum(len(document["_settlements"]) for document in documents),
        "reconciliations": sum(len(document["_settlements"]) for document in documents),
        "source_net": str(totals["source_net"]),
        "source_tax": str(totals["source_tax"]),
        "source_gross": str(totals["source_gross"]),
        "vat_policy_counts": vat_counts,
        "zero_residual": True,
    }


def _purchase_contract(manifest):
    try:
        return purchase_contract.build_purchase_contract(manifest)
    except purchase_contract.PurchaseContractError as error:
        raise UserError("Noorix purchase source contract is unsafe: %s" % error) from error


def plan_purchase_month(env, source_company_id, month, path=None):
    """Read-only G7 preflight for one exact company/month financial scope."""
    runtime_guard.assert_rehearsal_database(env)
    manifest = runtime_guard.load_source_manifest(path or runtime_guard.DEFAULT_MANIFEST_PATH)
    contract = _purchase_contract(manifest)
    documents = contract["by_wave"].get((source_company_id, month), ())
    if not documents:
        raise UserError("No approved Noorix purchase documents for %s / %s" % (source_company_id, month))
    company = _company_by_source(env, source_company_id)
    if not company or not company.active:
        raise UserError("No active target company mapping for purchase wave")
    missing = {"supplier": 0, "vault": 0, "account": 0, "purchase_journal": 0, "vat_tax": 0}
    try:
        _purchase_journal(env, company)
    except UserError:
        missing["purchase_journal"] += 1
    if any(document["_vat_policy"] == "vat15_inclusive" for document in documents):
        try:
            _purchase_tax_15(env, company)
        except UserError:
            missing["vat_tax"] += 1
    for document in documents:
        try:
            _supplier_for_purchase(env, document)
        except UserError:
            missing["supplier"] += 1
        try:
            _historical_service_account(env, company, document)
        except UserError:
            missing["account"] += 1
        for settlement in document["_settlements"]:
            try:
                _vault_for_purchase(env, company, document, settlement)
            except UserError:
                missing["vault"] += 1
    result = _purchase_result(documents)
    result.update({
        "database": env.cr.dbname,
        "source_company_id": source_company_id,
        "month": month,
        "target_company_id": company.id,
        "missing_or_ambiguous": missing,
        "orm_writes": 0,
    })
    return result


def apply_purchase_month(env, source_company_id, month, path=None):
    """Atomically create/replay one approved company-month bill/payment wave.

    Invoke one company-month per controlled Odoo-shell transaction.  The
    function itself never opens a later month and uses a transaction advisory
    lock plus immutable source maps for category, invoice, payment and native
    reconciliation independently.
    """
    runtime_guard.assert_rehearsal_database(env)
    manifest = runtime_guard.load_source_manifest(path or runtime_guard.DEFAULT_MANIFEST_PATH)
    contract = _purchase_contract(manifest)
    documents = contract["by_wave"].get((source_company_id, month), ())
    if not documents:
        raise UserError("No approved Noorix purchase documents for %s / %s" % (source_company_id, month))
    company = _company_by_source(env, source_company_id)
    if not company or not company.active:
        raise UserError("No active target company mapping for purchase wave")
    _lock(env, "purchase:%s:%s" % (source_company_id, month))
    run_key = "purchase:%s:%s" % (source_company_id, month)
    # A shell caller may hold a wider transaction; this savepoint contains the
    # run creation itself as well as every map and financial write.  Thus a
    # caller which catches UserError cannot accidentally retain a ``planned``
    # run that would block a safe retry of the same company/month.
    with env.cr.savepoint():
        run, fresh = _get_or_start_run(env, "purchase_month", run_key)
        if not fresh:
            for document in documents:
                _verify_purchase_document(env, company, document)
            return json.loads(run.result_json)
        journal = _purchase_journal(env, company)
        for document in documents:
            product, account = _historical_service(env, company, document, run)
            tax = _purchase_tax_15(env, company) if document["_vat_policy"] == "vat15_inclusive" else False
            invoice = _create_purchase_invoice(env, company, document, product, account, journal, tax)
            _ensure_map(
                env, scope="purchase_invoice", source_identity=_invoice_identity(document),
                source_row_sha256=document["source_row_sha256"], canonical_key=_invoice_canonical_key(document),
                target=invoice, run=run,
            )
            for settlement in document["_settlements"]:
                payment_journal = _vault_for_purchase(env, company, document, settlement)
                payment = _create_purchase_payment(env, company, document, settlement, invoice, payment_journal)
                settlement_hash = _map_hash_for_settlement(document, settlement)
                _ensure_map(
                    env, scope="purchase_payment", source_identity=_payment_identity(document, settlement),
                    source_row_sha256=settlement_hash,
                    canonical_key="%s|payment:%s" % (document["canonical_key"], settlement["source_allocation_id"]),
                    target=payment, run=run,
                )
                reconciliation = _reconcile_purchase_payment(
                    env, company, document, settlement, invoice, payment,
                )
                _ensure_map(
                    env, scope="purchase_reconciliation", source_identity=_reconciliation_identity(document, settlement),
                    source_row_sha256=settlement_hash,
                    canonical_key="%s|reconciliation:%s" % (document["canonical_key"], settlement["source_allocation_id"]),
                    target=reconciliation, run=run,
                )
            if abs(invoice.amount_residual) > 0.00001 or invoice.payment_state != "paid":
                raise UserError("Noorix invoice is not fully reconciled: %s" % document["canonical_key"])
        result = _purchase_result(documents)
        result.update({"source_company_id": source_company_id, "month": month})
        _commit_run(run, result)
    return result

def apply_master_data(env, path=None):
    """Run each approved master scope once; financial records remain untouched."""
    return {
        "companies": apply_company_master(env, path),
        "suppliers": apply_supplier_master(env, path),
        "products": apply_product_master(env, path),
    }


def plan(env, path=None):
    """Validate source-only input and report unambiguous target rebind capacity.

    The function performs no create/write/unlink/post operation and returns the
    exact counts expected by G5.  A later writer must consume this plan rather
    than applying any name-only matching.
    """
    runtime_guard.assert_rehearsal_database(env)
    manifest = runtime_guard.load_source_manifest(path or runtime_guard.DEFAULT_MANIFEST_PATH)
    payloads = _payloads(manifest)

    company_plan = []
    Company = env["res.company"].sudo()
    by_canonical = {}
    for row in _company_rows(payloads):
        by_canonical.setdefault(row["canonical_key"], []).append(row)
    for canonical_key, rows in by_canonical.items():
        row = next((item for item in rows if item["decision"] != "alias_archived_company"), rows[0])
        source = row["source"]
        matches = Company.search([]).filtered(
            lambda company: not company.parent_id
            and company.active
            and company.country_id.code == "SA"
            and company.currency_id.name == "SAR"
            and _normal(company.name) == _normal(_company_name(source))
        )
        company_plan.append({
            "source_company_ids": sorted(item["source_company_id"] for item in rows),
            "canonical_key": canonical_key,
            "decision": row["decision"],
            "matches": len(matches),
            "action": "reuse" if len(matches) == 1 else "create" if not matches else "defer",
        })

    supplier_payload = next(payload for payload in payloads if "canonical_partners" in payload)
    partners = env["res.partner"].sudo().search([("company_id", "=", False)])
    supplier_counts = {"reuse_vat": 0, "reuse_name_contact": 0, "create": 0, "defer": 0}
    for supplier in supplier_payload["canonical_partners"]:
        vat = (supplier.get("vat") or "").strip()
        vat_matches = partners.filtered(lambda partner: vat and (partner.vat or "").strip() == vat)
        if len(vat_matches) == 1:
            supplier_counts["reuse_vat"] += 1
            continue
        if len(vat_matches) > 1:
            supplier_counts["defer"] += 1
            continue
        name = _normal(supplier["name"])
        phone = _normal(supplier.get("phone"))
        email = _normal(supplier.get("email"))
        if not (phone or email):
            supplier_counts["create"] += 1
            continue
        matches = partners.filtered(
            lambda partner: _normal(partner.name) == name
            and ((phone and _normal(partner.phone) == phone) or (email and _normal(partner.email) == email))
        )
        if len(matches) == 1:
            supplier_counts["reuse_name_contact"] += 1
        elif not matches:
            supplier_counts["create"] += 1
        else:
            supplier_counts["defer"] += 1

    product_payload = next(payload for payload in payloads if "canonical_products" in payload)
    products = env["product.template"].sudo().search([])
    product_plan = {"create": 0, "defer": 0}
    for product in product_payload["canonical_products"]:
        # The source contract has no trusted default_code for this first run;
        # existing records may only be selected by a writer once a code exists.
        # This read-only result prevents a name-based product merge.
        if products.filtered(lambda template: template.company_id and template.company_id.id == -1):
            product_plan["defer"] += 1
        else:
            product_plan["create"] += 1

    return {
        "database": env.cr.dbname,
        "source_archive_sha256": runtime_guard.SOURCE_ARCHIVE_SHA256,
        "manifest_sha256": runtime_guard.SOURCE_MANIFEST_SHA256,
        "contracts": len(manifest["contracts"]),
        "expected": {
            "source_company_ids": 6,
            "canonical_companies": 5,
            "canonical_suppliers": 286,
            "supplier_tags": 50,
            "canonical_products": 467,
            # Keep canonical entities separate from source aliases: the
            # contract intentionally normalises some category and UoM names.
            "canonical_product_categories": len(product_payload["canonical_categories"]),
            "source_product_category_ids": len(product_payload["category_maps"]),
            "canonical_uoms": len(product_payload["canonical_uoms"]),
            "source_product_uom_ids": len(product_payload["uom_maps"]),
            "vaults": 14,
            "purchase_documents": 2962,
            "sales_summaries": 669,
        },
        "company_plan": company_plan,
        "supplier_plan": supplier_counts,
        "product_plan": product_plan,
        "orm_writes": 0,
    }
