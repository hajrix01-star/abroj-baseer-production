/** Build the approved QA-only Noorix latest-purchase-cost payload. */
import crypto from "node:crypto";
import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";

const sourceDb = "noorix_price_execute_20260912";
const targetDb = "baseer_noorix_data_migration_qa_20260912";
const dbContainer = "baseer_odoo_dev-db-1";
const outputDir = ".local-backups/noorix-migration/runs/20260912-product-cost-qa-1";
const outputPath = path.join(outputDir, "product-cost-payload.json");
const archiveSha = "024606ADD82DCD78DC1835828A12D7B22C56E34924FF998ABF752134160E79E2";
const tenantId = "default-tenant-noorix-2024";
const primaryAvocado = "v4m_5e72f130d19098f85987";
const aliasAvocado = "v4m_aa29dd6c8907b8135acf";

function psql(database, sql) {
  const output = execFileSync("docker", ["exec", dbContainer, "psql", "-U", "odoo", "-d", database, "-At", "-F", "\t", "-c", sql], { encoding: "utf8" }).trim();
  return output ? output.split("\n").map((line) => line.split("\t")) : [];
}

function sha(value) {
  return crypto.createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

const sourceRows = psql(sourceDb, `
WITH latest AS (
  SELECT ph.id AS history_id, ph.tenant_id, ph.company_id, ph.item_id, ph.inventory_unit_price,
         ph.effective_at, ph.created_at,
         row_number() OVER (PARTITION BY ph.item_id ORDER BY ph.effective_at DESC, ph.created_at DESC, ph.id DESC) AS rn
  FROM orders_v4_price_history ph
  JOIN orders_v4_documents d ON d.id = ph.document_id
  WHERE d.document_type = 'purchase' AND d.status = 'received'
)
SELECT l.history_id, l.tenant_id, l.company_id, l.item_id, l.inventory_unit_price::text,
       l.effective_at::text, l.created_at::text
FROM latest l
JOIN orders_v4_items i ON i.id = l.item_id
WHERE l.rn = 1 AND i.tenant_id = '${tenantId}' AND i.is_active
  AND i.item_type = 'purchased'
  AND i.company_id IN ('cmnf604ka009ay8lm556wgd9c', 'cmnaivif80001wavxxfgriptm')
ORDER BY l.company_id, l.item_id;
`).map(([historyId, sourceTenantId, companyId, productId, cost, effectiveAt, createdAt]) => ({
  historyId, sourceTenantId, companyId, productId, cost: Number(cost), effectiveAt, createdAt,
}));

if (sourceRows.length !== 279) throw new Error(`Expected 279 latest source purchase costs, found ${sourceRows.length}`);
const grouped = new Map();
for (const row of sourceRows) {
  const canonicalProductId = row.productId === aliasAvocado ? primaryAvocado : row.productId;
  const values = grouped.get(canonicalProductId) || [];
  values.push(row);
  grouped.set(canonicalProductId, values);
}
const selected = [];
for (const [canonicalProductId, candidates] of grouped) {
  const choice = [...candidates].sort((a, b) => b.effectiveAt.localeCompare(a.effectiveAt) || b.createdAt.localeCompare(a.createdAt) || b.historyId.localeCompare(a.historyId))[0];
  if (choice.cost > 0) selected.push({ ...choice, canonicalProductId });
}
if (selected.length !== 277) throw new Error(`Expected 277 non-zero canonical cost candidates, found ${selected.length}`);

const targetRows = psql(targetDb, `
SELECT pm.source_company_id, pm.source_product_id, pm.canonical_key, pp.id, pt.company_id
FROM baseer_noorix_product_map pm
JOIN baseer_noorix_migration_run r ON r.id = pm.run_id AND r.name = '20260912-noorix-product-master-qa-1'
JOIN product_template pt ON pt.id = pm.product_tmpl_id
JOIN product_product pp ON pp.product_tmpl_id = pt.id
ORDER BY pm.source_company_id, pm.source_product_id;
`).map(([companyId, productId, canonicalKey, productIdTarget, targetCompanyId]) => ({ companyId, productId, canonicalKey, productIdTarget: Number(productIdTarget), targetCompanyId: Number(targetCompanyId) }));
if (targetRows.length !== 468) throw new Error(`Expected 468 target source maps, found ${targetRows.length}`);
const targetBySource = new Map(targetRows.map((row) => [`${row.companyId}:${row.productId}`, row]));

const costs = selected.map((row) => {
  const target = targetBySource.get(`${row.companyId}:${row.canonicalProductId}`);
  if (!target) throw new Error(`Missing QA product map for ${row.companyId}:${row.canonicalProductId}`);
  return {
    source_system: "noorix",
    source_tenant_id: row.sourceTenantId,
    source_company_id: row.companyId,
    source_product_id: row.productId,
    source_price_history_id: row.historyId,
    source_row_sha256: sha(row),
    source_archive_sha256: archiveSha,
    canonical_key: target.canonicalKey,
    decision: "set_latest_received_cost",
    source_cost: row.cost,
    effective_at: row.effectiveAt,
    target_product_id: target.productIdTarget,
    target_company_id: target.targetCompanyId,
  };
});
const companyCounts = costs.reduce((acc, row) => ({ ...acc, [row.target_company_id]: (acc[row.target_company_id] || 0) + 1 }), {});
if (companyCounts[1] !== 193 || companyCounts[2] !== 84) throw new Error(`Unexpected cost company partition: ${JSON.stringify(companyCounts)}`);

const payload = {
  run_name: "20260912-noorix-product-cost-qa-1",
  target_database: targetDb,
  source_archive_sha256: archiveSha,
  approved_policy: "latest_nonzero_received_purchase_cost_per_canonical_company_product",
  report: {
    source_latest_received_purchase_costs: 279,
    excluded_zero_costs: 1,
    avocado_alias_resolved_by_latest_effective_cost: 1,
    target_cost_updates: 277,
    company_1_cost_updates: 193,
    company_2_cost_updates: 84,
    excluded_purchase_without_cost: 86,
    excluded_sale_without_sales_price: 103,
  },
  costs,
};
await fs.mkdir(outputDir, { recursive: true });
await fs.writeFile(outputPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
console.log(JSON.stringify({ outputPath, payloadSha256: crypto.createHash("sha256").update(await fs.readFile(outputPath)).digest("hex"), report: payload.report }, null, 2));
