/** Build the owner-approved Noorix product-master payload without writing Odoo. */
import { execFileSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const sourceDb = "noorix_product_execute_20260912";
const targetDb = "baseer_noorix_data_migration_qa_20260912";
const archiveSha256 = "024606ADD82DCD78DC1835828A12D7B22C56E34924FF998ABF752134160E79E2";
const reviewWorkbook = "outputs/noorix_product_review_20260912/noorix_products_odoo_qa_import_plan.xlsx";
const outputDir = ".local-backups/noorix-migration/runs/20260912-product-master-qa-1";
const outputPath = `${outputDir}/product-payload.json`;
const avocadoPrimaryId = "v4m_5e72f130d19098f85987";
const avocadoAliasId = "v4m_aa29dd6c8907b8135acf";

function docker(args) {
  return execFileSync("docker", args, { encoding: "utf8" }).trim();
}

function queryJson(containerArgs, database, sql) {
  const output = docker([...containerArgs, "psql", "-U", "odoo", "-d", database, "-At", "-c", sql]);
  return output ? JSON.parse(output) : [];
}

function stableJson(value) {
  return JSON.stringify(value, Object.keys(value).sort(), 0);
}

function digest(value) {
  return crypto.createHash("sha256").update(stableJson(value)).digest("hex");
}

function sha256Bytes(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function normalize(value) {
  return String(value ?? "")
    .normalize("NFKC").toLowerCase().trim()
    .replace(/[أإآ]/g, "ا").replace(/ى/g, "ي").replace(/ة/g, "ه").replace(/ـ/g, "")
    .replace(/[^\p{L}\p{N}\u0600-\u06FF]/gu, "");
}

function assert(condition, message) {
  if (!condition) throw new Error(`Product payload: ${message}`);
}

function recordsById(rows) {
  return new Map(rows.slice(1).filter((row) => row[0]).map((row) => [String(row[0]), row]));
}

const sourceItemsSql = `
SELECT COALESCE(json_agg(json_build_object(
  'id', i.id, 'tenant_id', i.tenant_id, 'company_id', i.company_id, 'company_name', co.name_ar,
  'name_ar', i.name_ar, 'name_en', i.name_en, 'sku', i.sku, 'item_type', i.item_type,
  'track_inventory', i.track_inventory, 'active', i.is_active, 'category_id', i.category_id,
  'unit_id', i.inventory_unit_id
) ORDER BY co.name_ar, i.id), '[]'::json)::text
FROM orders_v4_items i JOIN companies co ON co.id=i.company_id
WHERE co.name_ar NOT IN ('TEST','TEST1') AND i.is_active;`;

const sourceCategoriesSql = `
SELECT COALESCE(json_agg(json_build_object(
  'id', ca.id, 'tenant_id', ca.tenant_id, 'company_id', ca.company_id, 'company_name', co.name_ar,
  'name_ar', ca.name_ar, 'name_en', ca.name_en, 'active', ca.is_active
) ORDER BY co.name_ar, ca.id), '[]'::json)::text
FROM orders_v4_categories ca JOIN companies co ON co.id=ca.company_id
WHERE co.name_ar NOT IN ('TEST','TEST1');`;

const sourceUnitsSql = `
SELECT COALESCE(json_agg(json_build_object(
  'id', u.id, 'tenant_id', u.tenant_id, 'company_id', u.company_id, 'company_name', co.name_ar,
  'code', u.code, 'name_ar', u.name_ar, 'name_en', u.name_en, 'dimension', u.dimension,
  'canonical_factor', u.canonical_factor, 'decimal_scale', u.decimal_scale, 'active', u.is_active
) ORDER BY co.name_ar, u.id), '[]'::json)::text
FROM orders_v4_units u JOIN companies co ON co.id=u.company_id
WHERE co.name_ar NOT IN ('TEST','TEST1');`;

const targetCompaniesSql = `
SELECT COALESCE(json_agg(json_build_object('id', id, 'name', name) ORDER BY id), '[]'::json)::text
FROM res_company WHERE id IN (1,2);`;

const sourceItems = queryJson(["exec", "baseer_odoo_dev-db-1"], sourceDb, sourceItemsSql);
const sourceCategories = queryJson(["exec", "baseer_odoo_dev-db-1"], sourceDb, sourceCategoriesSql);
const sourceUnits = queryJson(["exec", "baseer_odoo_dev-db-1"], sourceDb, sourceUnitsSql);
const targetCompanies = queryJson(["compose", "exec", "-T", "db"], targetDb, targetCompaniesSql);

const workbookBytes = await fs.readFile(reviewWorkbook);
const reviewWorkbookSha256 = sha256Bytes(workbookBytes);
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(reviewWorkbook));
const itemRows = await workbook.worksheets.getItem("أصناف نوركس").getRange("A1:S799").values;
const categoryRows = await workbook.worksheets.getItem("الفئات").getRange("A1:L60").values;
const unitRows = await workbook.worksheets.getItem("وحدات القياس").getRange("A1:M76").values;
const itemPlanById = recordsById(itemRows);
const categoryPlanById = recordsById(categoryRows);
const unitPlanById = recordsById(unitRows);

assert(sourceItems.length === 468, "active source item count must be 468");
assert(sourceCategories.length === 59, "source category count must be 59");
assert(sourceUnits.length === 75, "source UoM count must be 75");
assert(targetCompanies.length === 2 && targetCompanies[0].id === 1 && targetCompanies[1].id === 2, "QA company ids 1/2 are missing");

const targetCompanyBySourceName = new Map([["ARZ", 1], ["المعلم الشامي", 2]]);
const activeCategoryIds = new Set(sourceItems.map((item) => item.category_id).filter(Boolean));
const activeUnitIds = new Set(sourceItems.map((item) => item.unit_id));
assert(activeCategoryIds.size === 56, "active source-category identity count must be 56");
assert(activeUnitIds.size === 12, "active source-UoM identity count must be 12");

const categoryMaps = [];
const canonicalCategoriesByKey = new Map();
for (const category of sourceCategories.filter((row) => activeCategoryIds.has(row.id))) {
  const plan = categoryPlanById.get(category.id);
  assert(plan && Number(plan[6]) > 0 && plan[9] === "إنشاء فئة فرعية في QA", `missing active category plan for ${category.id}`);
  const root = String(plan[7]);
  const arabic = String(plan[3]);
  const english = String(plan[4]);
  const canonicalKey = `${root.toLowerCase()}:${normalize(arabic)}`;
  const sourceRow = { id: category.id, tenant_id: category.tenant_id, company_id: category.company_id, name_ar: category.name_ar, name_en: category.name_en, active: category.active };
  categoryMaps.push({
    source_system: "noorix", source_tenant_id: category.tenant_id, source_company_id: category.company_id,
    source_category_id: category.id, source_row_sha256: digest(sourceRow), source_archive_sha256: archiveSha256,
    canonical_key: canonicalKey, decision: "create_qa_leaf",
  });
  const prior = canonicalCategoriesByKey.get(canonicalKey);
  const candidate = {
    canonical_key: canonicalKey, root, name_ar: arabic, name_en: english,
    translation_priority: String(plan[2]) === arabic ? 2 : 1,
  };
  assert(!prior || (prior.root === candidate.root && prior.name_ar === candidate.name_ar), `conflicting category payload for ${canonicalKey}`);
  if (!prior || candidate.translation_priority > prior.translation_priority) canonicalCategoriesByKey.set(canonicalKey, candidate);
}
assert(categoryMaps.length === 56 && canonicalCategoriesByKey.size === 47, "category-map reconciliation failed");

const existingUomKeyByPlanName = new Map([
  ["الوحدات", "existing:unit"], ["g", "existing:g"], ["كجم", "existing:kg"], ["L", "existing:l"], ["مل", "existing:ml"],
]);
const uomMaps = [];
const canonicalUomsByKey = new Map();
for (const unit of sourceUnits.filter((row) => activeUnitIds.has(row.id))) {
  const plan = unitPlanById.get(unit.id);
  assert(plan && Number(plan[8]) > 0, `missing active UoM plan for ${unit.id}`);
  const targetName = String(plan[9] ?? "");
  const action = String(plan[10] ?? "");
  const existingKey = existingUomKeyByPlanName.get(targetName);
  const canonicalKey = existingKey ?? `package:${normalize(unit.name_ar)}`;
  const decision = existingKey ? "reuse_existing_uom" : "create_package_root_uom";
  assert(
    (decision === "reuse_existing_uom" && action === "إعادة استخدام وحدة أودو") ||
    (decision === "create_package_root_uom" && action === "إنشاء وحدة مستقلة بلا تحويل في QA"),
    `invalid UoM decision for ${unit.id}`,
  );
  const sourceRow = { id: unit.id, tenant_id: unit.tenant_id, company_id: unit.company_id, code: unit.code, name_ar: unit.name_ar, name_en: unit.name_en, dimension: unit.dimension, canonical_factor: unit.canonical_factor, decimal_scale: unit.decimal_scale, active: unit.active };
  uomMaps.push({
    source_system: "noorix", source_tenant_id: unit.tenant_id, source_company_id: unit.company_id,
    source_uom_id: unit.id, source_row_sha256: digest(sourceRow), source_archive_sha256: archiveSha256,
    canonical_key: canonicalKey, decision,
  });
  const candidate = decision === "reuse_existing_uom"
    ? { canonical_key: canonicalKey, decision, expected_name: targetName }
    : { canonical_key: canonicalKey, decision, name: String(unit.name_ar), name_en: String(unit.name_en ?? "") };
  const prior = canonicalUomsByKey.get(canonicalKey);
  assert(!prior || stableJson(prior) === stableJson(candidate), `conflicting UoM payload for ${canonicalKey}`);
  canonicalUomsByKey.set(canonicalKey, candidate);
}
assert(uomMaps.length === 12 && canonicalUomsByKey.size === 9, "UoM-map reconciliation failed");
assert([...canonicalUomsByKey.values()].filter((row) => row.decision === "create_package_root_uom").length === 4, "package UoM count must be 4");

const categoryMapBySourceId = new Map(categoryMaps.map((row) => [row.source_category_id, row]));
const uomMapBySourceId = new Map(uomMaps.map((row) => [row.source_uom_id, row]));
const canonicalProductsByKey = new Map();
const productMaps = [];
for (const item of sourceItems) {
  const plan = itemPlanById.get(item.id);
  assert(plan && plan[18] !== "مستبعد: غير نشط", `missing item plan for ${item.id}`);
  const isAvocadoAlias = item.id === avocadoAliasId;
  const canonicalSourceId = isAvocadoAlias ? avocadoPrimaryId : item.id;
  const canonicalKey = `product:${item.tenant_id}:${item.company_id}:${canonicalSourceId}`;
  const categoryKey = item.category_id ? categoryMapBySourceId.get(item.category_id)?.canonical_key : "root:goods";
  const uomKey = uomMapBySourceId.get(item.unit_id)?.canonical_key;
  assert(categoryKey && uomKey, `missing category/UoM target for ${item.id}`);
  const purchaseOk = item.item_type === "purchased";
  const saleOk = item.item_type === "sale";
  assert(purchaseOk !== saleOk, `unapproved item type for ${item.id}`);
  const sourceRow = { id: item.id, tenant_id: item.tenant_id, company_id: item.company_id, name_ar: item.name_ar, name_en: item.name_en, sku: item.sku, item_type: item.item_type, track_inventory: item.track_inventory, active: item.active, category_id: item.category_id, unit_id: item.unit_id };
  productMaps.push({
    source_system: "noorix", source_tenant_id: item.tenant_id, source_company_id: item.company_id,
    source_product_id: item.id, source_row_sha256: digest(sourceRow), source_archive_sha256: archiveSha256,
    canonical_key: canonicalKey, decision: isAvocadoAlias ? "canonical_alias" : "create_company_product",
  });
  if (!isAvocadoAlias) {
    const targetCompanyId = targetCompanyBySourceName.get(item.company_name);
    assert(targetCompanyId, `unmapped source company ${item.company_name}`);
    canonicalProductsByKey.set(canonicalKey, {
      canonical_key: canonicalKey, primary_source_product_id: item.id, source_company_id: item.company_id,
      target_company_id: targetCompanyId, name_ar: String(plan[2]), name_en: String(plan[3]),
      category_key: categoryKey, uom_key: uomKey, type: "consu", is_storable: Boolean(item.track_inventory),
      purchase_ok: purchaseOk, sale_ok: saleOk, active: true, tracking: "none",
    });
  }
}
assert(productMaps.length === 468 && canonicalProductsByKey.size === 467, "product-map reconciliation failed");
assert(productMaps.some((row) => row.source_product_id === avocadoAliasId && row.decision === "canonical_alias"), "avocado alias missing");

const canonicalProducts = [...canonicalProductsByKey.values()].sort((a, b) => a.canonical_key.localeCompare(b.canonical_key));
const report = {
  active_source_products: productMaps.length,
  canonical_target_products: canonicalProducts.length,
  company_1_products: canonicalProducts.filter((row) => row.target_company_id === 1).length,
  company_2_products: canonicalProducts.filter((row) => row.target_company_id === 2).length,
  product_maps: productMaps.length,
  active_source_category_maps: categoryMaps.length,
  canonical_category_leaves: canonicalCategoriesByKey.size,
  active_source_uom_maps: uomMaps.length,
  canonical_target_uoms: canonicalUomsByKey.size,
  reused_existing_uoms: [...canonicalUomsByKey.values()].filter((row) => row.decision === "reuse_existing_uom").length,
  package_root_uoms: [...canonicalUomsByKey.values()].filter((row) => row.decision === "create_package_root_uom").length,
  no_source_category_products: sourceItems.filter((item) => !item.category_id).length,
  purchase_products: canonicalProducts.filter((row) => row.purchase_ok).length,
  sale_products: canonicalProducts.filter((row) => row.sale_ok).length,
};
assert(report.company_1_products === 382 && report.company_2_products === 85, "company product split failed");
assert(report.purchase_products === 364 && report.sale_products === 103, "purchase/sale reconciliation failed");

const payload = {
  schema_version: 1, source_system: "noorix", source_archive_sha256: archiveSha256,
  review_workbook_sha256: reviewWorkbookSha256, target_database: targetDb,
  canonical_categories: [...canonicalCategoriesByKey.values()]
    .map(({ translation_priority, ...row }) => row)
    .sort((a, b) => a.canonical_key.localeCompare(b.canonical_key)),
  category_maps: categoryMaps.sort((a, b) => a.source_category_id.localeCompare(b.source_category_id)),
  canonical_uoms: [...canonicalUomsByKey.values()].sort((a, b) => a.canonical_key.localeCompare(b.canonical_key)),
  uom_maps: uomMaps.sort((a, b) => a.source_uom_id.localeCompare(b.source_uom_id)),
  canonical_products: canonicalProducts, product_maps: productMaps.sort((a, b) => a.source_product_id.localeCompare(b.source_product_id)), report,
};

await fs.mkdir(outputDir, { recursive: true });
const payloadText = `${JSON.stringify(payload, null, 2)}\n`;
await fs.writeFile(outputPath, payloadText, "utf8");
await fs.writeFile(`${outputDir}/product-payload-report.json`, `${JSON.stringify({ payload_sha256: sha256Bytes(payloadText), review_workbook_sha256: reviewWorkbookSha256, ...report }, null, 2)}\n`, "utf8");
console.log(JSON.stringify({ outputPath, payload_sha256: sha256Bytes(payloadText), review_workbook_sha256: reviewWorkbookSha256, ...report }, null, 2));
