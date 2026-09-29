/** Build the approved QA-only Noorix company crosswalk payload. */
import crypto from "node:crypto";
import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";

const sourceDb = "noorix_source_inspection_archive159_20260913";
const targetDb = "baseer_noorix_data_migration_qa_20260912";
const dbContainer = "baseer_odoo_dev-db-1";
const outputDir = ".local-backups/noorix-migration/runs/20260913-company-master-qa-1";
const outputPath = path.join(outputDir, "company-payload.json");
const archiveSha = "024606ADD82DCD78DC1835828A12D7B22C56E34924FF998ABF752134160E79E2";
const tenantId = "default-tenant-noorix-2024";

const decisions = new Map([
  ["cmnf604ka009ay8lm556wgd9c", { key: "arz", decision: "reuse_existing_company", targetName: "ARZ" }],
  ["cmnaivif80001wavxxfgriptm", { key: "almoallem", decision: "reuse_existing_company", targetName: "المعلم الشامي" }],
  ["cmnf5xrd0001uy8lm8vja50gp", { key: "doha", decision: "reuse_existing_company", targetName: "دوحة المستهلك" }],
  ["cmnvui7x70001etuf8p6xz3d0", { key: "karak", decision: "create_historical_company", targetName: "وقت الكرك | Karak" }],
  ["cmnf5zx10005ky8lml9hx2rpq", { key: "karak", decision: "alias_archived_company", targetName: "وقت الكرك | Karak" }],
]);

function psql(database, sql) {
  const output = execFileSync("docker", ["exec", dbContainer, "psql", "-U", "odoo", "-d", database, "-At", "-F", "\t", "-c", sql], { encoding: "utf8" }).trim();
  return output ? output.split("\n").map((line) => line.split("\t")) : [];
}

function rowSha(value) {
  return crypto.createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

const ids = [...decisions.keys()].map((id) => `'${id}'`).join(",");
const sourceRows = psql(sourceDb, `
SELECT id,tenant_id,name_ar,COALESCE(name_en,''),COALESCE(phone,''),COALESCE(address,''),
       COALESCE(tax_number,''),COALESCE(email,''),is_archived::text,vat_enabled_for_sales::text,
       vat_rate_percent::text,created_at::text,updated_at::text,sort_order::text
FROM companies WHERE id IN (${ids}) ORDER BY id;
`).map(([id, sourceTenantId, nameAr, nameEn, phone, address, taxNumber, email, archived, vatEnabled, vatRate, createdAt, updatedAt, sortOrder]) => ({
  id, sourceTenantId, nameAr, nameEn, phone, address, taxNumber, email,
  archived: archived === "t", vatEnabled: vatEnabled === "t", vatRate: Number(vatRate),
  createdAt, updatedAt, sortOrder: Number(sortOrder),
}));

if (sourceRows.length !== 5 || sourceRows.some((row) => row.sourceTenantId !== tenantId)) {
  throw new Error(`Expected five approved source company identities, found ${sourceRows.length}`);
}

const targetRows = psql(targetDb, "SELECT id,name FROM res_company WHERE active ORDER BY id;");
const targetByName = new Map(targetRows.map(([id, name]) => [name, Number(id)]));
for (const expected of ["ARZ", "المعلم الشامي", "دوحة المستهلك"]) {
  if (!targetByName.has(expected)) throw new Error(`Missing existing QA company: ${expected}`);
}
if (targetRows.some(([, name]) => name.includes("وقت الكرك"))) {
  throw new Error("Karak already exists in QA without the approved company map");
}

const companies = sourceRows.map((source) => {
  const policy = decisions.get(source.id);
  const normalized = {
    source_company_id: source.id,
    source_tenant_id: source.sourceTenantId,
    source_name_ar: source.nameAr,
    source_name_en: source.nameEn,
    source_phone: source.phone,
    source_address: source.address,
    source_tax_number: source.taxNumber,
    source_email: source.email,
    source_is_archived: source.archived,
    source_vat_enabled_for_sales: source.vatEnabled,
    source_vat_rate_percent: source.vatRate,
    source_created_at: source.createdAt,
    source_updated_at: source.updatedAt,
    source_sort_order: source.sortOrder,
  };
  return {
    source_system: "noorix",
    source_tenant_id: tenantId,
    source_company_id: source.id,
    source_row_sha256: rowSha(normalized),
    source_archive_sha256: archiveSha,
    canonical_key: `company:${policy.key}`,
    decision: policy.decision,
    target_company_name: policy.targetName,
    target_company_id: policy.decision === "reuse_existing_company" ? targetByName.get(policy.targetName) : null,
    source: normalized,
  };
});

const payload = {
  run_name: "20260913-noorix-company-master-qa-1",
  target_database: targetDb,
  source_archive_sha256: archiveSha,
  approved_policy: "reuse_three_existing_companies_create_karak_and_alias_its_archived_source_identity",
  report: {
    source_company_maps: 5,
    reused_existing_companies: 3,
    created_historical_companies: 1,
    archived_source_aliases: 1,
    excluded_test_companies: 2,
    deferred_shami_tax_companies: 1,
  },
  companies,
};

await fs.mkdir(outputDir, { recursive: true });
await fs.writeFile(outputPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
const payloadSha256 = crypto.createHash("sha256").update(await fs.readFile(outputPath)).digest("hex");
console.log(JSON.stringify({ outputPath, payloadSha256, report: payload.report }, null, 2));
