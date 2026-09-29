"""Apply one SHA-pinned Noorix supplier payload to the isolated Odoo QA DB.

Run only from ``odoo shell`` with the migration addon loaded.  The script is
deliberately idempotent: a committed run with the same immutable payload is a
verified no-op, while any identity mismatch fails before changing partners.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

from odoo import fields
from odoo.exceptions import UserError


PAYLOAD_PATH = Path("/mnt/noorix-payload/runs/20260912-supplier-final-category-review-1/supplier-payload.json")
RUN_NAME = "20260912-noorix-supplier-master-qa-1"
EXPECTED_PAYLOAD_SHA256 = "f13b0a33b788f7bb405d49efeefcc9ef8d7aaa9c2ae4507cfa99aef6c2d88556"
WRITER_CONTEXT = "baseer_noorix_migration_writer"


def fail(message):
    raise UserError("Noorix QA supplier migration: %s" % message)


def require(condition, message):
    if not condition:
        fail(message)


payload_bytes = PAYLOAD_PATH.read_bytes()
payload_sha256 = hashlib.sha256(payload_bytes).hexdigest()
require(payload_sha256 == EXPECTED_PAYLOAD_SHA256, "payload SHA-256 does not match the approved payload")
payload = json.loads(payload_bytes.decode("utf-8"))
report = payload["report"]
require(report["blocked_supplier_groups"] == 0, "payload contains blocked supplier groups")
require(report["new_category_tags"] == 0, "payload requires unapproved category creation")

def writer_model(name):
    return env[name].sudo().with_context(**{WRITER_CONTEXT: True})


Run = writer_model("baseer.noorix.migration.run")
SupplierMap = writer_model("baseer.noorix.supplier.map")
CategoryMap = writer_model("baseer.noorix.supplier.category.map")
Partner = writer_model("res.partner")
Tag = writer_model("res.partner.category")

existing_run = Run.search([("name", "=", RUN_NAME)], limit=1)
if existing_run:
    require(existing_run.payload_sha256 == payload_sha256, "existing run name belongs to a different payload")
    if existing_run.state in {"committed", "reconciled"}:
        print(json.dumps({
            "status": "already_committed",
            "run_id": existing_run.id,
            "state": existing_run.state,
            "supplier_maps": SupplierMap.search_count([("run_id", "=", existing_run.id)]),
            "category_maps": CategoryMap.search_count([("run_id", "=", existing_run.id)]),
        }, ensure_ascii=False, sort_keys=True))
        env.cr.commit()
    else:
        fail("a non-final run with this name already exists")
else:
    canonical_partners = payload["canonical_partners"]
    supplier_maps = payload["supplier_maps"]
    category_maps = payload["category_maps"]
    memberships = payload["memberships"]
    require(len(canonical_partners) == report["canonical_supplier_groups"], "canonical supplier count mismatch")
    require(len(supplier_maps) == report["source_supplier_maps"], "supplier mapping count mismatch")
    require(len(category_maps) == report["source_category_maps"], "category mapping count mismatch")
    require(len(memberships) == report["canonical_supplier_tag_memberships"], "membership count mismatch")

    category_target_by_key = {}
    for category in payload["canonical_categories"]:
        target_id = category["target_tag_id"]
        require(target_id, "a category has no approved target tag")
        target = Tag.browse(target_id).exists()
        require(target and target.name, "an approved target tag is missing from QA")
        category_target_by_key[category["canonical_key"]] = target.id
    require(len(category_target_by_key) == report["canonical_category_tags"], "canonical category count mismatch")

    member_tags_by_partner_key = defaultdict(set)
    for membership in memberships:
        partner_key = membership["canonical_partner_key"]
        category_key = membership["canonical_category_key"]
        require(category_key in category_target_by_key, "membership references an unresolved category")
        member_tags_by_partner_key[partner_key].add(category_target_by_key[category_key])
    effective_membership_count = sum(len(tag_ids) for tag_ids in member_tags_by_partner_key.values())

    # Snapshot the only existing records that may receive a controlled write.
    existing_targets = {}
    for canonical in canonical_partners:
        if canonical["decision"] in {"existing_global_vat", "existing_approved_crosswalk"}:
            partner = Partner.browse(canonical["target_partner_id"]).exists()
            require(partner, "an approved existing partner target is missing from QA")
            require(not partner.company_id and not partner.parent_id, "an approved target is no longer global/top-level")
            existing_targets[canonical["canonical_key"]] = partner
    require(len(existing_targets) == report["existing_global_partner_groups"], "existing target count mismatch")

    run = Run.create({
        "name": RUN_NAME,
        "source_archive_sha256": payload["source_archive_sha256"],
        "source_tenant_id": "all-companies",
        "payload_sha256": payload_sha256,
        "scope": "supplier_master",
        "state": "planned",
        "started_at": fields.Datetime.now(),
        "result_json": json.dumps({"stage": "preflight_passed", "report": report}, ensure_ascii=False, sort_keys=True),
    })

    partner_by_key = {}
    created_count = 0
    reused_count = 0
    for canonical in canonical_partners:
        key = canonical["canonical_key"]
        decision = canonical["decision"]
        tag_ids = sorted(member_tags_by_partner_key.get(key, set()))
        if decision in {"existing_global_vat", "existing_approved_crosswalk"}:
            partner = existing_targets[key]
            controlled_values = {}
            if partner.supplier_rank < 1:
                controlled_values["supplier_rank"] = 1
            if tag_ids:
                controlled_values["category_id"] = [(4, tag_id) for tag_id in tag_ids if tag_id not in partner.category_id.ids]
            if controlled_values:
                partner.write(controlled_values)
            reused_count += 1
        elif decision in {"automatic_valid_vat", "kept_separate", "cash_anonymous"}:
            values = {
                "name": canonical["name"],
                "company_id": False,
                "supplier_rank": 1,
                "active": bool(canonical["active"]),
                "category_id": [(6, 0, tag_ids)],
            }
            if decision == "automatic_valid_vat":
                require(canonical["vat"], "valid-VAT decision has no VAT")
                values["vat"] = canonical["vat"]
            if canonical.get("phone"):
                values["phone"] = canonical["phone"]
            partner = Partner.create(values)
            created_count += 1
        else:
            fail("unapproved partner decision: %s" % decision)
        partner_by_key[key] = partner

    require(created_count == report["new_supplier_groups"], "new partner count mismatch")
    require(reused_count == report["existing_global_partner_groups"], "reused partner count mismatch")

    SupplierMap.create([
        {
            "source_system": row["source_system"],
            "source_tenant_id": str(row["source_tenant_id"]),
            "source_company_id": str(row["source_company_id"]),
            "source_supplier_id": str(row["source_supplier_id"]),
            "source_row_sha256": row["source_row_sha256"],
            "source_archive_sha256": row["source_archive_sha256"],
            "canonical_key": row["canonical_key"],
            "decision": row["decision"],
            "partner_id": partner_by_key[row["canonical_key"]].id,
            "run_id": run.id,
        }
        for row in supplier_maps
    ])
    CategoryMap.create([
        {
            "source_system": row["source_system"],
            "source_tenant_id": str(row["source_tenant_id"]),
            "source_company_id": str(row["source_company_id"]),
            "source_category_id": str(row["source_category_id"]),
            "source_row_sha256": row["source_row_sha256"],
            "source_archive_sha256": row["source_archive_sha256"],
            "canonical_key": row["canonical_key"],
            "category_id": row["target_tag_id"],
            "run_id": run.id,
        }
        for row in category_maps
    ])

    # Reconciliation is performed before the only explicit commit.
    mapped_partner_ids = {
        row.partner_id.id
        for row in SupplierMap.with_context(active_test=False).search([("run_id", "=", run.id)])
    }
    mapped_partners = Partner.browse(sorted(mapped_partner_ids))
    require(
        len(mapped_partner_ids) == len({partner.id for partner in partner_by_key.values()}),
        "mapped global partner count mismatch",
    )
    require(not mapped_partners.filtered(lambda p: p.company_id or p.parent_id or p.supplier_rank < 1), "a mapped partner is not global/top-level/supplier")
    require(SupplierMap.search_count([("run_id", "=", run.id)]) == report["source_supplier_maps"], "supplier map post-check mismatch")
    require(CategoryMap.search_count([("run_id", "=", run.id)]) == report["source_category_maps"], "category map post-check mismatch")
    verified_memberships = 0
    missing_memberships = []
    for partner_key, tag_ids in member_tags_by_partner_key.items():
        partner = partner_by_key[partner_key]
        for tag_id in tag_ids:
            if tag_id in partner.category_id.ids:
                verified_memberships += 1
            else:
                missing_memberships.append((partner_key, tag_id, partner.id))
    require(
        verified_memberships == effective_membership_count,
        "supplier tag membership post-check mismatch (%s/%s): %s" % (
            verified_memberships,
            effective_membership_count,
            missing_memberships,
        ),
    )

    result = {
        "status": "committed",
        "created_global_partners": created_count,
        "reused_global_partners": reused_count,
        "mapped_global_partners": len(mapped_partner_ids),
        "supplier_maps": report["source_supplier_maps"],
        "category_maps": report["source_category_maps"],
        "source_category_memberships": report["canonical_supplier_tag_memberships"],
        "verified_memberships": verified_memberships,
        "report": report,
    }
    run.write({"state": "committed", "finished_at": fields.Datetime.now(), "result_json": json.dumps(result, ensure_ascii=False, sort_keys=True)})
    env.cr.commit()
    print(json.dumps({"run_id": run.id, **result}, ensure_ascii=False, sort_keys=True))
