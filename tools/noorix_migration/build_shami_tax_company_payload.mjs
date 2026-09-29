/** Build the one-company, QA-only SHAMI TAX master-data payload. */
import crypto from "node:crypto";
import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";

const sourceDb = "noorix_source_inspection_archive159_20260913";
const targetDb = "baseer_noorix_data_migration_qa_20260912";
const dbContainer = "baseer_odoo_dev-db-1";
const outputDir = ".local-backups/noorix-migration/runs/20260913-shami-tax-company-master-qa-1";
const outputPath = path.join(outputDir, "shami-tax-company-payload.json");
const archiveSha = "024606ADD82DCD78DC1835828A12D7B22C56E34924FF998ABF752134160E79E2";
const tenantId = "default-tenant-noorix-2024";
const sourceCompanyId = "cmr3fd0y3000hycziou1o2c47";
const sourceSupplierId = "cmr3fea680059yczi1umh4zk7";
const supplierVat = "311262678500003";

function psql(database, sql) {
  const output = execFileSync("docker", ["exec", dbContainer, "psql", "-U", "odoo", "-d", database, "-At", "-F", "\t", "-c", sql], { encoding: "utf8" }).trim();
  return output ? output.split("\n").map((line) => line.split("\t")) : [];
}
function sha(value) {
  return crypto.createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

const companyRows = psql(sourceDb, `
SELECT id, tenant_id, name_ar, COALESCE(name_en,''), COALESCE(phone,''), COALESCE(address,''),
       COALESCE(tax_number,''), COALESCE(email,''), is_archived::text, vat_enabled_for_sales::text,
       vat_rate_percent::text, created_at::text, updated_at::text, sort_order::text
FROM companies WHERE id = '${sourceCompanyId}';
`);
if (companyRows.length !== 1) throw new Error("Expected exactly one SHAMI TAX source company");
const [id, companyTenant, nameAr, nameEn, phone, address, taxNumber, email, archived, vatEnabled, vatRate, createdAt, updatedAt, sortOrder] = companyRows[0];
if (companyTenant !== tenantId || nameAr !== "SHAMI TAX" || archived !== "false") throw new Error("SHAMI TAX source identity or active state differs");
const companySource = { id, tenantId: companyTenant, nameAr, nameEn, phone, address, taxNumber, email,
  archived: archived === "true", vatEnabledForSales: vatEnabled === "true", vatRatePercent: Number(vatRate), createdAt, updatedAt, sortOrder: Number(sortOrder) };

const supplierRows = psql(sourceDb, `
SELECT id, tenant_id, company_id, COALESCE(name_ar,''), COALESCE(name_en,''), COALESCE(tax_number,''),
       COALESCE(phone,''), ''::text, ''::text, COALESCE(is_deleted,false)::text
FROM suppliers WHERE id = '${sourceSupplierId}';
`);
if (supplierRows.length !== 1) throw new Error("Expected exactly one SHAMI TAX source supplier");
const [supplierId, supplierTenant, supplierCompany, supplierNameAr, supplierNameEn, sourceVat, supplierPhone, supplierEmail, supplierAddress, deleted] = supplierRows[0];
if (supplierTenant !== tenantId || supplierCompany !== sourceCompanyId || sourceVat !== supplierVat || deleted !== "false") throw new Error("SHAMI TAX supplier source identity differs");
const supplierSource = { id: supplierId, tenantId: supplierTenant, companyId: supplierCompany, nameAr: supplierNameAr,
  nameEn: supplierNameEn, taxNumber: sourceVat, phone: supplierPhone, email: supplierEmail, address: supplierAddress, deleted: deleted === "true" };

const targetSupplierRows = psql(targetDb, `
SELECT id, name, COALESCE(vat,''), COALESCE(company_id::text,''), COALESCE(parent_id::text,''), active::text, supplier_rank::text
FROM res_partner WHERE vat = '${supplierVat}' ORDER BY id;
`);
if (targetSupplierRows.length !== 1) throw new Error("Expected exactly one Odoo supplier with the SHAMI TAX VAT");
const [targetPartnerId, targetPartnerName, targetVat, companyId, parentId, active, supplierRank] = targetSupplierRows[0];
if (companyId || parentId || active !== "true" || Number(supplierRank) < 1 || targetVat !== supplierVat) throw new Error("Odoo supplier VAT target is not active global supplier");
const existingMapRows = psql(targetDb, `
SELECT sm.partner_id::text, sm.source_archive_sha256, sm.canonical_key, sm.decision, r.name, r.state
FROM baseer_noorix_supplier_map sm
JOIN baseer_noorix_migration_run r ON r.id = sm.run_id
WHERE sm.source_system = 'noorix' AND sm.source_tenant_id = '${tenantId}'
  AND sm.source_company_id = '${sourceCompanyId}' AND sm.source_supplier_id = '${sourceSupplierId}';
`);
if (existingMapRows.length !== 1) throw new Error("Expected exactly one existing SHAMI TAX supplier provenance mapping");
const [mappedPartnerId, mappedArchiveSha, mappedKey, mappedDecision, mappedRunName, mappedRunState] = existingMapRows[0];
if (Number(mappedPartnerId) !== Number(targetPartnerId) || mappedArchiveSha !== archiveSha || mappedKey !== `vat:${supplierVat}` || !["automatic_valid_vat", "existing_global_vat"].includes(mappedDecision) || !["committed", "reconciled"].includes(mappedRunState)) {
  throw new Error("Existing SHAMI TAX supplier provenance does not prove the exact global VAT mapping");
}

const payload = {
  run_name: "20260913-shami-tax-company-master-qa-1",
  target_database: targetDb,
  source_archive_sha256: archiveSha,
  approved_policy: "create_active_shami_tax_company_and_reuse_exact_global_supplier_vat",
  report: { source_company_maps: 1, new_companies: 1, reused_global_suppliers: 1, reused_existing_supplier_maps: 1 },
  company: { source_system: "noorix", source_tenant_id: tenantId, source_company_id: sourceCompanyId,
    source_row_sha256: sha(companySource), source_archive_sha256: archiveSha, canonical_key: "company:shami_tax",
    decision: "create_active_company", target_company_name: "SHAMI TAX", source: companySource },
  supplier: { source_system: "noorix", source_tenant_id: tenantId, source_company_id: sourceCompanyId,
    source_supplier_id: sourceSupplierId, source_row_sha256: sha(supplierSource), source_archive_sha256: archiveSha,
    canonical_key: `vat:${supplierVat}`, decision: "existing_global_vat", target_partner_id: Number(targetPartnerId),
    target_partner_name: targetPartnerName, target_vat: targetVat, existing_mapping_decision: mappedDecision, existing_mapping_run_name: mappedRunName, source: supplierSource },
};
await fs.mkdir(outputDir, { recursive: true });
await fs.writeFile(outputPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
console.log(JSON.stringify({ outputPath, payloadSha256: crypto.createHash("sha256").update(await fs.readFile(outputPath)).digest("hex"), report: payload.report }, null, 2));
