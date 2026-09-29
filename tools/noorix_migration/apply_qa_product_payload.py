"""Apply the approved Noorix product-master payload to the isolated QA database.

Run only through the QA Odoo shell after the QA-only migration add-on upgrade.
The writer uses one advisory-locked transaction and is an idempotent no-op after
the same payload has committed.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from odoo import fields
from odoo.exceptions import UserError


PAYLOAD_PATH = Path("/mnt/noorix-payload/runs/20260912-product-master-qa-1/product-payload.json")
RUN_NAME = "20260912-noorix-product-master-qa-1"
EXPECTED_PAYLOAD_SHA256 = "09c4d6f757a4e81d055b7785ddb4cf6874dd200d561d8ac388ba84b87dac178b"
WRITER_CONTEXT = "baseer_noorix_migration_writer"
SOURCE_ARCHIVE_SHA256 = "024606ADD82DCD78DC1835828A12D7B22C56E34924FF998ABF752134160E79E2"


def fail(message):
    raise UserError("Noorix QA product migration: %s" % message)


def require(condition, message):
    if not condition:
        fail(message)


def writer_model(name):
    return env[name].sudo().with_context(**{WRITER_CONTEXT: True})


def translated_value(record, field_name, lang):
    return record.with_context(lang=lang)[field_name] or ""


def write_bilingual(record, field_name, arabic, english):
    record.with_context(lang="ar_001").write({field_name: arabic})
    if not record._fields[field_name].translate:
        # Odoo 19 product.category.name is deliberately a single, non-translatable
        # technical label.  Keep its approved Arabic display value; the English
        # counterpart remains in the hash-pinned payload and evidence mapping.
        require(record[field_name] == arabic, "single-language field did not persist")
        return
    record.with_context(lang="en_US").write({field_name: english or arabic})
    require(translated_value(record, field_name, "ar_001") == arabic, "Arabic translation did not persist")
    require(translated_value(record, field_name, "en_US") == (english or arabic), "English translation did not persist")


payload_bytes = PAYLOAD_PATH.read_bytes()
payload_sha256 = hashlib.sha256(payload_bytes).hexdigest()
require(payload_sha256 == EXPECTED_PAYLOAD_SHA256, "payload SHA-256 does not match the approved payload")
payload = json.loads(payload_bytes.decode("utf-8"))
report = payload["report"]
require(payload["source_archive_sha256"] == SOURCE_ARCHIVE_SHA256, "source archive SHA-256 mismatch")
require(payload["target_database"] == env.cr.dbname, "payload targets a different database")
require(report == {
    "active_source_products": 468,
    "canonical_target_products": 467,
    "company_1_products": 382,
    "company_2_products": 85,
    "product_maps": 468,
    "active_source_category_maps": 56,
    "canonical_category_leaves": 47,
    "active_source_uom_maps": 12,
    "canonical_target_uoms": 9,
    "reused_existing_uoms": 5,
    "package_root_uoms": 4,
    "no_source_category_products": 21,
    "purchase_products": 364,
    "sale_products": 103,
}, "payload report does not match the approved product scope")

Run = writer_model("baseer.noorix.migration.run")
ProductMap = writer_model("baseer.noorix.product.map")
CategoryMap = writer_model("baseer.noorix.product.category.map")
UomMap = writer_model("baseer.noorix.product.uom.map")
Product = writer_model("product.template")
Category = writer_model("product.category")
Uom = writer_model("uom.uom")
Company = writer_model("res.company")
Language = writer_model("res.lang")

# Acquire this before reading the run so two concurrent writers cannot both
# observe an absent run and race on the unique run identity.
env.cr.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ["%s:noorix-product-master" % env.cr.dbname])


def verify_mapping_evidence(mappings, payload_rows, source_id_field, target_field, target_by_key):
    expected = {(row["source_company_id"], row[source_id_field]): row for row in payload_rows}
    actual = {(mapping.source_company_id, getattr(mapping, source_id_field)): mapping for mapping in mappings}
    require(set(actual) == set(expected), "committed source identities differ from the approved payload")
    evidence_fields = ("source_system", "source_tenant_id", "source_company_id", source_id_field,
                       "source_row_sha256", "source_archive_sha256", "canonical_key", "decision")
    for source_identity, mapping in actual.items():
        row = expected[source_identity]
        require(all(getattr(mapping, field_name) == row[field_name] for field_name in evidence_fields), "committed mapping evidence differs from payload")
        require(getattr(mapping, target_field).id == target_by_key[row["canonical_key"]].id, "committed mapping target differs from payload")


def verify_committed_run(run):
    product_maps = ProductMap.search([("run_id", "=", run.id)])
    category_maps = CategoryMap.search([("run_id", "=", run.id)])
    uom_maps = UomMap.search([("run_id", "=", run.id)])
    require(len(product_maps) == 468 and len(category_maps) == 56 and len(uom_maps) == 12, "committed run map counts differ")

    roots = {}
    for root_name in ("Food", "Goods"):
        root = Category.with_context(lang="en_US").search([("name", "=", root_name), ("parent_id", "=", False)], limit=2)
        require(len(root) == 1, "required product-category root is ambiguous or absent: %s" % root_name)
        roots[root_name.lower()] = root

    category_by_key = {"root:goods": roots["goods"]}
    for row in payload["canonical_categories"]:
        targets = category_maps.filtered(lambda mapping: mapping.canonical_key == row["canonical_key"]).mapped("category_id")
        require(len(targets) == 1, "canonical category has an ambiguous target")
        category = targets[0]
        require(category.name == row["name_ar"] and category.parent_id.id == roots[row["root"].lower()].id, "committed category differs from payload")
        category_by_key[row["canonical_key"]] = category
    require(len(category_by_key) == 48, "committed category count differs from payload")

    uom_by_key = {}
    existing_uom_xmlids = {
        "existing:unit": "uom.product_uom_unit", "existing:g": "uom.product_uom_gram", "existing:kg": "uom.product_uom_kgm",
        "existing:l": "uom.product_uom_litre", "existing:ml": "uom.product_uom_milliliter",
    }
    for row in payload["canonical_uoms"]:
        if row["decision"] == "reuse_existing_uom":
            uom = env.ref(existing_uom_xmlids[row["canonical_key"]], raise_if_not_found=False)
            require(uom and uom.exists(), "required existing UoM is missing during replay")
        else:
            targets = uom_maps.filtered(lambda mapping: mapping.canonical_key == row["canonical_key"]).mapped("uom_id")
            require(len(targets) == 1, "canonical package UoM has an ambiguous target")
            uom = targets[0]
            require(not uom.relative_uom_id and uom.relative_factor == 1 and uom.factor == 1 and not uom.package_type_id, "package UoM replay invariant failed")
            require(translated_value(uom, "name", "ar_001") == row["name"] and translated_value(uom, "name", "en_US") == (row.get("name_en") or row["name"]), "package UoM translation differs from payload")
        uom_by_key[row["canonical_key"]] = uom
    require(len(uom_by_key) == 9, "committed UoM count differs from payload")

    product_by_key = {}
    for row in payload["canonical_products"]:
        targets = product_maps.filtered(lambda mapping: mapping.canonical_key == row["canonical_key"]).mapped("product_tmpl_id")
        require(len(targets) == 1, "canonical product has an ambiguous target")
        product = targets[0]
        require(product.company_id.id == row["target_company_id"] and product.categ_id.id == category_by_key[row["category_key"]].id and product.uom_id.id == uom_by_key[row["uom_key"]].id, "committed product relation differs from payload")
        require(product.type == "consu" and product.tracking == "none" and product.active and product.is_storable == row["is_storable"] and product.purchase_ok == row["purchase_ok"] and product.sale_ok == row["sale_ok"], "committed product field differs from payload")
        require(translated_value(product, "name", "ar_001") == row["name_ar"] and translated_value(product, "name", "en_US") == row["name_en"], "committed product translation differs from payload")
        product_by_key[row["canonical_key"]] = product
    require(len(product_by_key) == 467, "committed product count differs from payload")
    require(len([product for product in product_by_key.values() if product.company_id.id == 1]) == 382 and len([product for product in product_by_key.values() if product.company_id.id == 2]) == 85, "committed company split differs from payload")

    verify_mapping_evidence(product_maps, payload["product_maps"], "source_product_id", "product_tmpl_id", product_by_key)
    verify_mapping_evidence(category_maps, payload["category_maps"], "source_category_id", "category_id", category_by_key)
    verify_mapping_evidence(uom_maps, payload["uom_maps"], "source_uom_id", "uom_id", uom_by_key)
    category_property_columns = [name for name in Category._fields if name.startswith("property_")]
    env.cr.execute(
        "SELECT %s FROM product_category WHERE id = ANY(%%s)" % ", ".join(category_property_columns),
        [[category_by_key[row["canonical_key"]].id for row in payload["canonical_categories"]]],
    )
    require(not any(any(value is not None for value in values) for values in env.cr.fetchall()), "committed category stores an accounting property")
    package_uoms = [uom for key, uom in uom_by_key.items() if key.startswith("package:")]
    require(len(package_uoms) == 4 and not Uom.search_count([("relative_uom_id", "in", [uom.id for uom in package_uoms])]), "package UoM conversion replay invariant failed")
    return {"product_maps": len(product_maps), "category_maps": len(category_maps), "uom_maps": len(uom_maps), "distinct_products": len(product_by_key)}


existing_run = Run.search([("name", "=", RUN_NAME)], limit=1)
if existing_run:
    require(existing_run.payload_sha256 == payload_sha256, "existing run name belongs to a different payload")
    if existing_run.state in {"committed", "reconciled"}:
        result = {
            "status": "already_committed",
            "run_id": existing_run.id,
            "state": existing_run.state,
            **verify_committed_run(existing_run),
        }
        receipt_hash = os.environ.get("NOORIX_WRITER_ARTIFACT_SHA256", "")
        require(len(receipt_hash) == 64 and all(char in "0123456789abcdef" for char in receipt_hash.lower()), "replay needs a writer-artifact SHA-256 receipt")
        stored_result = json.loads(existing_run.result_json or "{}")
        receipts = stored_result.setdefault("replay_receipts", [])
        receipts.append({"at": fields.Datetime.to_string(fields.Datetime.now()), "writer_artifact_sha256": receipt_hash, "verification": result.copy()})
        existing_run.write({"result_json": json.dumps(stored_result, ensure_ascii=False, sort_keys=True)})
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        env.cr.commit()
    else:
        fail("a non-final run with this name already exists")
else:
    require(Language.search_count([("code", "=", "ar_001"), ("active", "=", True)]) == 1, "Arabic language ar_001 is unavailable")
    require(Language.search_count([("code", "=", "en_US"), ("active", "=", True)]) == 1, "English language en_US is unavailable")
    require(ProductMap.search_count([]) == 0 and CategoryMap.search_count([]) == 0 and UomMap.search_count([]) == 0, "product provenance tables are not empty")

    companies = {company.id: company for company in Company.browse([1, 2]).exists()}
    require(set(companies) == {1, 2}, "target companies 1 and 2 are missing")
    require(companies[1].name == "ARZ" and companies[2].name == "المعلم الشامي", "target company names no longer match the approved contract")

    roots = {}
    for root_name in ("Food", "Goods"):
        root = Category.with_context(lang="en_US").search([("name", "=", root_name), ("parent_id", "=", False)], limit=2)
        require(len(root) == 1, "required product-category root is ambiguous or absent: %s" % root_name)
        roots[root_name.lower()] = root
    root_write_dates = {root.id: root.write_date for root in roots.values()}

    existing_uom_xmlids = {
        "existing:unit": "uom.product_uom_unit",
        "existing:g": "uom.product_uom_gram",
        "existing:kg": "uom.product_uom_kgm",
        "existing:l": "uom.product_uom_litre",
        "existing:ml": "uom.product_uom_milliliter",
    }
    uom_by_key = {}
    existing_uom_write_dates = {}
    for key, xmlid in existing_uom_xmlids.items():
        uom = env.ref(xmlid, raise_if_not_found=False)
        require(uom and uom.exists(), "required existing UoM is missing: %s" % xmlid)
        uom_by_key[key] = uom
        existing_uom_write_dates[uom.id] = uom.write_date

    # Translation support is proven inside a savepoint and cannot leave test records.
    class _PreflightRollback(Exception):
        pass

    try:
        with env.cr.savepoint():
            test_category = Category.with_context(lang="ar_001").create({"name": "__noorix_preflight_category__", "parent_id": roots["goods"].id})
            write_bilingual(test_category, "name", "اختبار نوركس", "Noorix test")
            test_product = Product.with_company(companies[1]).with_context(allowed_company_ids=[1], lang="ar_001").create({
                "name": "اختبار نوركس", "company_id": 1, "categ_id": test_category.id, "uom_id": uom_by_key["existing:unit"].id,
                "type": "consu", "is_storable": False, "purchase_ok": False, "sale_ok": True, "active": True, "tracking": "none",
            })
            write_bilingual(test_product, "name", "اختبار نوركس", "Noorix test")
            raise _PreflightRollback()
    except _PreflightRollback:
        pass

    run = Run.create({
        "name": RUN_NAME,
        "source_archive_sha256": SOURCE_ARCHIVE_SHA256,
        "source_tenant_id": "all-companies",
        "payload_sha256": payload_sha256,
        "scope": "product_master",
        "state": "planned",
        "started_at": fields.Datetime.now(),
        "result_json": json.dumps({"stage": "preflight_passed", "report": report}, ensure_ascii=False, sort_keys=True),
    })

    category_by_key = {"root:goods": roots["goods"]}
    created_category_ids = []
    for row in payload["canonical_categories"]:
        root = roots[row["root"].lower()]
        existing = Category.with_context(lang="ar_001").search([("name", "=", row["name_ar"]), ("parent_id", "=", root.id)], limit=2)
        require(not existing, "a proposed category already exists in QA: %s" % row["canonical_key"])
        category = Category.with_context(lang="ar_001").create({"name": row["name_ar"], "parent_id": root.id})
        write_bilingual(category, "name", row["name_ar"], row["name_en"])
        category_by_key[row["canonical_key"]] = category
        created_category_ids.append(category.id)
    require(len(created_category_ids) == 47, "created category count mismatch")

    for row in payload["canonical_uoms"]:
        if row["decision"] == "reuse_existing_uom":
            require(row["canonical_key"] in uom_by_key, "unapproved existing UoM key")
            continue
        require(row["decision"] == "create_package_root_uom", "unapproved UoM decision")
        existing = Uom.with_context(lang="ar_001").search([("name", "=", row["name"]), ("relative_uom_id", "=", False)], limit=2)
        require(not existing, "a package root UoM already exists in QA: %s" % row["canonical_key"])
        uom = Uom.with_context(lang="ar_001").create({"name": row["name"], "relative_uom_id": False, "relative_factor": 1})
        write_bilingual(uom, "name", row["name"], row.get("name_en") or row["name"])
        require(not uom.relative_uom_id and uom.relative_factor == 1 and uom.factor == 1 and not uom.package_type_id, "package UoM root invariant failed")
        uom_by_key[row["canonical_key"]] = uom
    require(len(uom_by_key) == 9, "target UoM count mismatch")

    CategoryMap.create([{
        **row, "category_id": category_by_key[row["canonical_key"]].id, "run_id": run.id,
    } for row in payload["category_maps"]])
    UomMap.create([{
        **row, "uom_id": uom_by_key[row["canonical_key"]].id, "run_id": run.id,
    } for row in payload["uom_maps"]])

    product_by_key = {}
    for row in payload["canonical_products"]:
        company = companies[row["target_company_id"]]
        product = Product.with_company(company).with_context(allowed_company_ids=[company.id], lang="ar_001").create({
            "name": row["name_ar"], "company_id": company.id, "categ_id": category_by_key[row["category_key"]].id,
            "uom_id": uom_by_key[row["uom_key"]].id, "type": row["type"], "is_storable": row["is_storable"],
            "purchase_ok": row["purchase_ok"], "sale_ok": row["sale_ok"], "active": row["active"], "tracking": row["tracking"],
        })
        write_bilingual(product, "name", row["name_ar"], row["name_en"])
        product_by_key[row["canonical_key"]] = product
    require(len(product_by_key) == 467, "created product count mismatch")

    ProductMap.create([{
        **row, "product_tmpl_id": product_by_key[row["canonical_key"]].id, "run_id": run.id,
    } for row in payload["product_maps"]])

    require(CategoryMap.search_count([("run_id", "=", run.id)]) == 56, "category-map post-check mismatch")
    require(UomMap.search_count([("run_id", "=", run.id)]) == 12, "UoM-map post-check mismatch")
    require(ProductMap.search_count([("run_id", "=", run.id)]) == 468, "product-map post-check mismatch")
    mapped_products = Product.browse(sorted({row.product_tmpl_id.id for row in ProductMap.search([("run_id", "=", run.id)])}))
    require(len(mapped_products) == 467, "mapped product count mismatch")
    require(not mapped_products.filtered(lambda product: not product.company_id or product.company_id.id not in {1, 2}), "a mapped product is shared or in the wrong company")
    require(len(mapped_products.filtered(lambda product: product.company_id.id == 1)) == 382, "company 1 product count mismatch")
    require(len(mapped_products.filtered(lambda product: product.company_id.id == 2)) == 85, "company 2 product count mismatch")
    require(not mapped_products.filtered(lambda product: product.purchase_ok == product.sale_ok), "purchase/sale flags violate the approved contract")
    require(not mapped_products.filtered(lambda product: product.type != "consu" or product.tracking != "none" or not product.active), "product type/tracking/activity invariant failed")
    for row in payload["canonical_products"]:
        product = product_by_key[row["canonical_key"]]
        require(product.company_id.id == row["target_company_id"] and product.categ_id.id == category_by_key[row["category_key"]].id and product.uom_id.id == uom_by_key[row["uom_key"]].id, "product target relation mismatch")
        require(product.is_storable == row["is_storable"] and product.purchase_ok == row["purchase_ok"] and product.sale_ok == row["sale_ok"], "product flag mismatch")
        require(translated_value(product, "name", "ar_001") == row["name_ar"] and translated_value(product, "name", "en_US") == row["name_en"], "product translation mismatch")
    created_categories = Category.browse(created_category_ids)
    # Odoo reads company-level accounting defaults through these fields even when
    # the new category stores no value.  Inspect the category's own database
    # columns (read-only) so inherited defaults are not mistaken for a migration
    # write; all seven columns must remain NULL.
    category_property_columns = [name for name in created_categories._fields if name.startswith("property_")]
    env.cr.execute(
        "SELECT %s FROM product_category WHERE id = ANY(%%s)" % ", ".join(category_property_columns),
        [created_category_ids],
    )
    require(not any(any(value is not None for value in values) for values in env.cr.fetchall()), "new category stores an accounting property")
    require(all(root.write_date == root_write_dates[root.id] for root in roots.values()), "an existing category root was modified")
    require(all(Uom.browse(uom_id).write_date == write_date for uom_id, write_date in existing_uom_write_dates.items()), "an existing UoM was modified")
    package_uoms = [uom for key, uom in uom_by_key.items() if key.startswith("package:")]
    require(len(package_uoms) == 4 and len({uom.id for uom in package_uoms}) == 4, "package UoM identity mismatch")
    require(not Uom.search_count([("relative_uom_id", "in", [uom.id for uom in package_uoms])]), "a package UoM has an unapproved conversion child")

    result = {
        "status": "committed", "created_categories": len(created_category_ids), "created_package_uoms": len(package_uoms),
        "created_company_products": len(product_by_key), "category_maps": 56, "uom_maps": 12, "product_maps": 468,
        "report": report,
    }
    run.write({"state": "committed", "finished_at": fields.Datetime.now(), "result_json": json.dumps(result, ensure_ascii=False, sort_keys=True)})
    env.cr.commit()
    print(json.dumps({"run_id": run.id, **result}, ensure_ascii=False, sort_keys=True))
