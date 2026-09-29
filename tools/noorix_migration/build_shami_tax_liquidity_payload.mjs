/** Build the one-vault, QA-only SHAMI TAX liquidity provenance payload.
 *
 * Both database reads are through psql. This script never writes to either
 * database: the separate Odoo-shell entrypoint is the only writer.
 */
import crypto from "node:crypto";
import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";

const sourceDb = "noorix_source_inspection_archive159_20260913";
const targetDb = "baseer_noorix_data_migration_qa_20260912";
const dbContainer = "baseer_odoo_dev-db-1";
const outputDir = ".local-backups/noorix-migration/runs/20260913-shami-tax-liquidity-qa-1";
const outputPath = path.join(outputDir, "shami-tax-liquidity-payload.json");
const archiveSha = "024606ADD82DCD78DC1835828A12D7B22C56E34924FF998ABF752134160E79E2";
const tenantId = "default-tenant-noorix-2024";
const sourceCompanyId = "cmr3fd0y3000hycziou1o2c47";
const sourceVaultId = "cmr3fd0z9001lycziqkw21grp";
const targetCompanyId = 5;
const targetJournal = { id: 82, code: "BNK1", type: "bank", defaultAccountCode: "101001" };

function psql(database, sql) {
  if (database === "baseer_dev") throw new Error("Production database is forbidden");
  const out = execFileSync("docker", ["exec", dbContainer, "psql", "-U", "odoo", "-d", database, "-At", "-F", "\t", "-c", sql], { encoding: "utf8" }).trim();
  return out ? out.split("\n").map((line) => line.split("\t")) : [];
}
const sha = (value) => crypto.createHash("sha256").update(JSON.stringify(value)).digest("hex");

const vaultRows = psql(sourceDb, `
SELECT v.id,v.tenant_id,v.company_id,v.name_ar,COALESCE(v.name_en,''),v.type,
       v.is_active::text,v.is_archived::text,v.is_sales_channel::text,
       COALESCE(v.payment_method,''),COALESCE(v.notes,''),
       v.bank_reconciliation_enabled::text,v.created_at::text,v.updated_at::text,
       COUNT(i.id)::text,COALESCE(SUM(i.total_amount)::text,'0')
FROM vaults v
LEFT JOIN invoices i ON i.vault_id=v.id AND i.company_id=v.company_id
  AND i.status='active' AND i.kind IN ('purchase','expense','fixed_expense')
WHERE v.id='${sourceVaultId}'
GROUP BY v.id;
`);
if (vaultRows.length !== 1) throw new Error("Expected exactly one SHAMI TAX source vault");
const [id, sourceTenantId, companyId, nameAr, nameEn, type, active, archived, salesChannel, paymentMethod, notes, reconciliation, createdAt, updatedAt, documents, gross] = vaultRows[0];
if (sourceTenantId !== tenantId || companyId !== sourceCompanyId || type !== "bank" || active !== "true" || archived !== "false" || salesChannel !== "false" || paymentMethod !== "bank" || reconciliation !== "true") {
  throw new Error("SHAMI TAX source vault identity/type/activity differs");
}
const source = { id, tenantId: sourceTenantId, companyId, nameAr, nameEn, type, active: active === "true", archived: archived === "true", salesChannel: salesChannel === "true", paymentMethod, notes, bankReconciliationEnabled: reconciliation === "true", createdAt, updatedAt };

const companyMap = psql(targetDb, `SELECT company_id::text,source_archive_sha256 FROM baseer_noorix_company_map WHERE source_system='noorix' AND source_tenant_id='${tenantId}' AND source_company_id='${sourceCompanyId}';`);
if (companyMap.length !== 1 || Number(companyMap[0][0]) !== targetCompanyId || companyMap[0][1] !== archiveSha) throw new Error("SHAMI TAX company provenance differs");
const journalRows = psql(targetDb, `
SELECT j.id::text,j.code,j.type,j.company_id::text,COALESCE(a.code_store->>'5',''),j.active::text
FROM account_journal j JOIN account_account a ON a.id=j.default_account_id
WHERE j.id=${targetJournal.id};
`);
if (journalRows.length !== 1) throw new Error("Approved SHAMI TAX bank journal is missing");
const [journalId, code, journalType, journalCompanyId, accountCode, journalActive] = journalRows[0];
if (Number(journalId) !== targetJournal.id || code !== targetJournal.code || journalType !== targetJournal.type || Number(journalCompanyId) !== targetCompanyId || accountCode !== targetJournal.defaultAccountCode || journalActive !== "true") {
  throw new Error("Approved SHAMI TAX bank journal identity differs");
}
const methodRows = psql(targetDb, `
SELECT l.id::text,COALESCE(a.code_store->>'5','')
FROM account_payment_method_line l
JOIN account_account a ON a.id=l.payment_account_id
WHERE l.journal_id=${targetJournal.id} AND l.payment_account_id IS NOT NULL
ORDER BY l.id;
`);
if (methodRows.length !== 1 || methodRows[0][1] !== targetJournal.defaultAccountCode) throw new Error("SHAMI TAX bank journal needs exactly one manual liquidity method");
const existing = psql(targetDb, `SELECT id::text,journal_id::text,source_archive_sha256 FROM baseer_noorix_liquidity_vault_map WHERE source_system='noorix' AND source_tenant_id='${tenantId}' AND source_company_id='${sourceCompanyId}' AND source_vault_id='${sourceVaultId}';`);
if (existing.length) throw new Error("SHAMI TAX source vault is already mapped; use replay verification instead");

const payload = {
  schema_version: 1,
  target_database: targetDb,
  source_archive_sha256: archiveSha,
  run_name: "20260913-noorix-shami-tax-liquidity-qa-1",
  approved_policy: "reuse_existing_native_company_bank_for_exact_active_source_bank_vault",
  report: { source_vaults: 1, mapped_vaults: 1, source_purchase_documents: Number(documents), source_purchase_gross: gross },
  vault: {
    source_system: "noorix", source_tenant_id: tenantId, source_company_id: sourceCompanyId,
    source_vault_id: sourceVaultId, source_vault_type: type, source_vault_name: nameAr,
    source_row_sha256: sha(source), source_archive_sha256: archiveSha,
    canonical_key: "shami-tax:bank:cmr3fd0z9001lycziqkw21grp", decision: "reuse_existing_liquidity",
    target_company_id: targetCompanyId, target_journal_id: targetJournal.id, target_journal_code: targetJournal.code,
    target_journal_type: targetJournal.type, target_liquidity_account_code: targetJournal.defaultAccountCode,
    source,
  },
};
await fs.mkdir(outputDir, { recursive: true });
await fs.writeFile(outputPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
console.log(JSON.stringify({ outputPath, payload_sha256: crypto.createHash("sha256").update(await fs.readFile(outputPath)).digest("hex"), report: payload.report }, null, 2));
