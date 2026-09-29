/** Build the final owner-approved ARZ pending-document payload read-only.
 *
 * The finite document/account decisions are bound to the returned owner
 * workbook SHA-256.  This script neither mutates Noorix nor Odoo; it only
 * freezes a payload after re-reading the exact source, target maps and
 * accounting primitives needed by the generic QA writer.
 */
import crypto from "node:crypto";
import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";

const sourceDb = "noorix_source_inspection_archive159_20260913";
const targetDb = "baseer_noorix_data_migration_qa_20260912";
const dbContainer = "baseer_odoo_dev-db-1";
const sourceCompanyId = "cmnf604ka009ay8lm556wgd9c";
const tenantId = "default-tenant-noorix-2024";
const targetCompanyId = 1;
const archiveSha = "024606ADD82DCD78DC1835828A12D7B22C56E34924FF998ABF752134160E79E2";
const ownerWorkbook = "outputs/01a0926b-3b31-75f2-9e93-1679ceaef536/noorix-arz-pending/arz_pending_operations_for_owner.xlsx";
const ownerWorkbookSha = "4da9e4b714e32635429ca1fca0ded15e0bba48989c9aaf27f70e50d189bbdf6c";
const outputDir = ".local-backups/noorix-migration/runs/20260913-arz-owner-pending-qa-1";
const outputPath = path.join(outputDir, "arz-owner-pending-payload.json");
const finalReconciliationPath = path.join(outputDir, "arz-final-source-reconciliation.json");
const previousRemainingPath = ".local-backups/noorix-migration/runs/20260913-arz-exception-clear-qa-1/arz-main-payload-remaining-exclusions.json";

const approved = new Map([
  ["EXP-20260430-003", "106002"], ["EXP-20260430-004", "106003"], ["EXP-20260430-005", "106002"],
  ["EXP-20260615-001", "106003"], ["PUR-20260618-001", "400001"], ["EXP-20260620-002", "106003"],
  ["EXP-20260620-003", "106003"], ["EXP-20260621-003", "106003"], ["PUR-20260621-001", "400001"],
  ["EXP-20260623-001", "106003"], ["EXP-20260628-001", "106003"], ["EXP-20260704-001", "106003"],
  ["PUR-20260709-006", "400001"], ["PUR-20260713-005", "400001"], ["PUR-20260713-006", "400001"],
  ["PUR-20260715-001", "400001"], ["PUR-20260717-003", "400001"], ["PUR-20260721-004", "400001"],
  ["PUR-20260722-001", "400001"], ["PUR-20260729-006", "400001"], ["PUR-20260805-010", "400001"],
  ["PUR-20260807-001", "400001"], ["PUR-20260808-001", "400001"], ["EXP-20260810-001", "106003"],
  ["PUR-20260814-002", "400001"], ["PUR-20260814-011", "400001"], ["PUR-20260814-014", "400001"],
  ["EXP-20260821-001", "106003"], ["PUR-20260821-001", "400001"], ["PUR-20260824-002", "400001"],
  ["PUR-20260827-006", "400001"], ["PUR-20260829-008", "400001"], ["PUR-20260906-001", "400001"],
  ["EXP-20260908-001", "400001"], ["PUR-20260908-003", "400001"], ["PUR-20260910-001", "400001"],
]);

const groups = {
  "400001": { accountType: "expense_direct_cost", mappingKey: "owner-pending:uncategorized-materials", productCode: "NOORIX-HIST-ARZ-400001-OWNER-PENDING", productName: "تاريخي ARZ - مواد معتمدة من المالك", categoryName: "غير مصنف — مواد بقرار المالك" },
  "106002": { accountType: "asset_fixed", mappingKey: "owner-pending:owner-approved-furniture", productCode: "NOORIX-HIST-ARZ-106002-OWNER-PENDING", productName: "تاريخي ARZ - أثاث بقرار المالك", categoryName: "أثاث — بقرار المالك" },
  "106003": { accountType: "asset_fixed", mappingKey: "owner-pending:owner-approved-electronics", productCode: "NOORIX-HIST-ARZ-106003-OWNER-PENDING", productName: "تاريخي ARZ - أجهزة بقرار المالك", categoryName: "أجهزة وإلكترونيات — بقرار المالك" },
};

function psql(database, sql) {
  if (database === "baseer_dev") throw new Error("Production database is forbidden");
  const output = execFileSync("docker", ["exec", dbContainer, "psql", "-U", "odoo", "-d", database, "-At", "-F", "\t", "-c", sql], { encoding: "utf8", maxBuffer: 32 * 1024 * 1024 });
  return output.split(/\r?\n/).filter(Boolean).map((line) => line.split("\t"));
}
const sha = (value) => crypto.createHash("sha256").update(JSON.stringify(value)).digest("hex");
function fixed4(value) { const match = String(value).match(/^(\d+)(?:\.(\d+))?$/); if (!match) throw new Error(`Invalid source amount: ${value}`); const fraction = (match[2] || "").padEnd(4, "0"); if (fraction.length > 4 && /[1-9]/.test(fraction.slice(4))) throw new Error(`Source amount precision differs: ${value}`); return `${match[1]}.${fraction.slice(0, 4)}`; }
function units4(value) { const [whole, fraction] = fixed4(value).split("."); return BigInt(whole) * 10000n + BigInt(fraction); }
function halfUp(numerator, denominator) { return (numerator * 2n + denominator) / (denominator * 2n); }
function cents(value) { return halfUp(units4(value), 100n); }
function money(value) { return `${value / 100n}.${String(value % 100n).padStart(2, "0")}`; }
function netPrice(value) { const whole = value / 115n; let remainder = value % 115n; let digits = ""; for (let i = 0; i < 14; i += 1) { remainder *= 10n; digits += String(remainder / 115n); remainder %= 115n; } return `${whole}.${digits}`; }
function total(rows, field) { return money(rows.reduce((sum, row) => sum + BigInt(row[field].replace(".", "")), 0n)); }

const actualWorkbookSha = crypto.createHash("sha256").update(await fs.readFile(ownerWorkbook)).digest("hex");
if (actualWorkbookSha !== ownerWorkbookSha) throw new Error("Returned owner workbook receipt differs; rebuild decisions from the returned file");
const invoiceList = [...approved.keys()].map((value) => `'${value}'`).join(",");
const sourceRows = psql(sourceDb, `
SELECT i.id,i.tenant_id,i.company_id,i.kind,i.status,i.invoice_number,COALESCE(i.supplier_invoice_number,''),i.transaction_date::date::text,
       i.net_amount::text,i.tax_amount::text,i.total_amount::text,i.supplier_id,s.name_ar,COALESCE(i.category_id,''),COALESCE(c.name_ar,''),
       encode(convert_to(COALESCE(i.notes,''),'UTF8'),'hex'),a.id,a.vault_id,a.amount::text,le.id,le.amount::text,
       i.created_at::text,i.updated_at::text,a.created_at::text,le.created_at::text
FROM invoices i JOIN suppliers s ON s.id=i.supplier_id LEFT JOIN categories c ON c.id=i.category_id
JOIN invoice_vault_allocations a ON a.invoice_id=i.id JOIN ledger_entries le ON le.reference_type='invoice' AND le.reference_id=i.id
WHERE i.company_id='${sourceCompanyId}' AND i.invoice_number IN (${invoiceList})
ORDER BY i.transaction_date,i.invoice_number,i.id;
`).map(([id, rowTenant, companyId, kind, status, number, supplierInvoice, date, netRaw, taxRaw, totalRaw, supplierId, supplierName, categoryId, categoryName, notesHex, allocationId, vaultId, allocationRaw, ledgerId, ledgerRaw, createdAt, updatedAt, allocationCreatedAt, ledgerCreatedAt]) => ({
  id, rowTenant, companyId, kind, status, number, supplierInvoice, date, netRaw: fixed4(netRaw), taxRaw: fixed4(taxRaw), totalRaw: fixed4(totalRaw), supplierId, supplierName,
  categoryId: categoryId || null, categoryName: categoryName || "__UNCATEGORIZED__", notes: Buffer.from(notesHex, "hex").toString("utf8"), allocationId, vaultId,
  allocationRaw: fixed4(allocationRaw), ledgerId, ledgerRaw: fixed4(ledgerRaw), createdAt, updatedAt, allocationCreatedAt, ledgerCreatedAt,
}));
if (sourceRows.length !== approved.size || new Set(sourceRows.map((row) => row.number)).size !== approved.size) throw new Error(`Expected ${approved.size} owner-approved source invoices, found ${sourceRows.length}`);
for (const row of sourceRows) {
  if (row.rowTenant !== tenantId || row.companyId !== sourceCompanyId || !["purchase", "expense", "fixed_expense"].includes(row.kind) || row.status !== "active" || !approved.has(row.number)) throw new Error(`Owner-approved source identity/status differs: ${row.number}`);
  if (units4(row.allocationRaw) !== units4(row.totalRaw) || units4(row.ledgerRaw) !== units4(row.totalRaw)) throw new Error(`Source allocation/ledger differs: ${row.number}`);
}

const companyMap = psql(targetDb, `SELECT company_id,source_archive_sha256 FROM baseer_noorix_company_map WHERE source_system='noorix' AND source_tenant_id='${tenantId}' AND source_company_id='${sourceCompanyId}';`);
if (companyMap.length !== 1 || Number(companyMap[0][0]) !== targetCompanyId || companyMap[0][1] !== archiveSha) throw new Error("ARZ company map differs");
const accountByCode = new Map(psql(targetDb, "SELECT id,code_store->>'1',account_type,active FROM account_account WHERE code_store->>'1' IN ('400001','106002','106003');").map(([id, code, type, active]) => {
  if (!groups[code] || groups[code].accountType !== type || active !== "t") throw new Error(`Approved account differs: ${code}`);
  return [code, Number(id)];
}));
if (accountByCode.size !== Object.keys(groups).length) throw new Error("One or more approved accounts are missing");
const tax = psql(targetDb, "SELECT id,amount,type_tax_use,active,COALESCE(price_include_override::text,'') FROM account_tax WHERE id=22;");
if (tax.length !== 1 || tax[0][1] !== "15.0000" || tax[0][2] !== "purchase" || tax[0][3] !== "t" || tax[0][4] === "true") throw new Error("Tax 22 differs");
const purchaseJournal = psql(targetDb, "SELECT id,code,type,company_id FROM account_journal WHERE id=9;");
if (purchaseJournal.length !== 1 || purchaseJournal[0][1] !== "BILL" || purchaseJournal[0][2] !== "purchase" || Number(purchaseJournal[0][3]) !== targetCompanyId) throw new Error("BILL/9 differs");
const sourceSupplierIds = [...new Set(sourceRows.map((row) => row.supplierId))].map((value) => `'${value}'`).join(",");
const partnerBySource = new Map(psql(targetDb, `SELECT m.source_supplier_id,m.partner_id,m.source_archive_sha256,COALESCE(p.company_id::text,''),p.supplier_rank FROM baseer_noorix_supplier_map m JOIN res_partner p ON p.id=m.partner_id WHERE m.source_system='noorix' AND m.source_tenant_id='${tenantId}' AND m.source_company_id='${sourceCompanyId}' AND m.source_supplier_id IN (${sourceSupplierIds});`).map(([sourceId, partnerId, archive, companyId, rank]) => {
  if (archive !== archiveSha || companyId || Number(rank) <= 0) throw new Error(`Supplier map differs: ${sourceId}`);
  return [sourceId, Number(partnerId)];
}));
const sourceVaultIds = [...new Set(sourceRows.map((row) => row.vaultId))].map((value) => `'${value}'`).join(",");
const journalByVault = new Map(psql(targetDb, `SELECT m.source_vault_id,m.journal_id,m.source_archive_sha256,j.code FROM baseer_noorix_liquidity_vault_map m JOIN account_journal j ON j.id=m.journal_id WHERE m.source_system='noorix' AND m.source_tenant_id='${tenantId}' AND m.source_company_id='${sourceCompanyId}' AND m.company_id=${targetCompanyId} AND m.source_vault_id IN (${sourceVaultIds});`).map(([vaultId, journalId, archive, code]) => {
  if (archive !== archiveSha || ["PSBNK", "PSCSH"].includes(code)) throw new Error(`Vault map differs: ${vaultId}`);
  return [vaultId, Number(journalId)];
}));
if (partnerBySource.size !== new Set(sourceRows.map((row) => row.supplierId)).size || journalByVault.size !== new Set(sourceRows.map((row) => row.vaultId)).size) throw new Error("Approved source supplier/vault mapping is incomplete");
const existing = psql(targetDb, `SELECT source_invoice_id FROM baseer_noorix_purchase_invoice_map WHERE source_system='noorix' AND source_tenant_id='${tenantId}' AND source_company_id='${sourceCompanyId}' AND source_invoice_id IN (${sourceRows.map((row) => `'${row.id}'`).join(",")});`);
if (existing.length) throw new Error(`Owner-approved invoice already mapped: ${existing.map((row) => row[0]).join(",")}`);

const categoryDecisions = Object.entries(groups).map(([code, group]) => ({
  source_system: "noorix", source_tenant_id: tenantId, source_company_id: sourceCompanyId, source_mapping_key: group.mappingKey, source_category_id: null, source_category_name: group.categoryName,
  source_row_sha256: sha({ owner_workbook_sha256: ownerWorkbookSha, source_mapping_key: group.mappingKey, selected_invoices: sourceRows.filter((row) => approved.get(row.number) === code).map((row) => row.number), target_account_code: code }),
  source_archive_sha256: archiveSha, canonical_key: `arz-owner-workbook:${group.mappingKey}`, decision: "create_historical_service", target_product_id: null, target_product_code: group.productCode,
  target_product_name: group.productName, target_account_id: accountByCode.get(code), target_account_code: code, target_account_type: group.accountType, tax_policy: "owner_declared_inclusive_15",
}));
const decisionByCode = new Map(categoryDecisions.map((decision) => [decision.target_account_code, decision]));
const documents = sourceRows.map((row) => {
  const code = approved.get(row.number); const group = groups[code]; const decision = decisionByCode.get(code); const gross = cents(row.totalRaw); const net = halfUp(gross * 100n, 115n); const vat = gross - net;
  const ownerAsset = group.accountType === "asset_fixed";
  const ownerReceipt = ownerAsset ? sha({ owner_workbook_sha256: ownerWorkbookSha, source_invoice_id: row.id, source_invoice_number: row.number, target_account_code: code, classification: "owner_approved_fixed_asset" }) : null;
  return {
    source_system: "noorix", source_tenant_id: tenantId, source_company_id: sourceCompanyId, source_invoice_id: row.id, source_ledger_id: row.ledgerId, source_allocation_id: row.allocationId, source_vault_id: row.vaultId,
    source_supplier_id: row.supplierId, source_category_id: row.categoryId, source_invoice_number: row.number, source_supplier_invoice_number: row.supplierInvoice, source_document_kind: row.kind,
    business_date: row.date, month: row.date.slice(0, 7), source_net_raw: row.netRaw, source_tax_raw: row.taxRaw, source_total_raw: row.totalRaw,
    source_row_sha256: sha({ ...row, owner_workbook_sha256: ownerWorkbookSha, selected_account_code: code, owner_classification: ownerAsset ? "owner_approved_fixed_asset" : null }),
    source_archive_sha256: archiveSha, canonical_key: `purchase:${sourceCompanyId}:${row.id}`, source_asset_id: null, source_asset_row_sha256: null,
    owner_classification: ownerAsset ? "owner_approved_fixed_asset" : null, owner_decision_sha256: ownerReceipt, decision: "create_paid_vendor_bill", category_mapping_key: decision.source_mapping_key,
    target_product_id: null, target_product_code: group.productCode, target_product_name: group.productName, target_account_id: accountByCode.get(code), target_account_code: code,
    target_partner_id: partnerBySource.get(row.supplierId), target_payment_journal_id: journalByVault.get(row.vaultId), target_tax_id: 22, price_unit: netPrice(gross), target_net: money(net), target_tax: money(vat), target_total: money(gross),
  };
});
const months = Object.fromEntries([...new Set(documents.map((row) => row.month))].sort().map((month) => { const rows = documents.filter((row) => row.month === month); return [month, { documents: rows.length, gross: total(rows, "target_total") }]; }));
const payload = {
  schema_version: 1, target_database: targetDb, source_archive_sha256: archiveSha, approved_policy: "general_paid_vendor_bills_native_accounting_monthly_atomic", run_prefix: "20260913-noorix-arz-owner-pending-qa",
  company: { source_system: "noorix", source_tenant_id: tenantId, source_company_id: sourceCompanyId, target_company_id: targetCompanyId },
  allowlist: { purchase_journal_id: 9, purchase_journal_code: "BILL", purchase_tax_id: 22, vat_input_account_code: "104041", forbidden_journal_codes: ["PSBNK", "PSCSH"] },
  owner_workbook: { path: ownerWorkbook, sha256: ownerWorkbookSha, decisions: documents.length }, category_decisions: categoryDecisions, documents,
  report: { source_documents: documents.length, target_net: total(documents, "target_net"), target_tax: total(documents, "target_tax"), target_gross: total(documents, "target_total"), months },
};
const previousRemaining = JSON.parse(await fs.readFile(previousRemainingPath, "utf8"));
const remaining = previousRemaining.remaining.filter((row) => !approved.has(row.invoice_number));
if (previousRemaining.remaining.length - remaining.length !== approved.size || remaining.some((row) => row.reason !== "already_migrated_historical_daily_wages")) throw new Error("Final owner decision set does not leave only already-migrated daily wages");
await fs.mkdir(outputDir, { recursive: true });
await fs.writeFile(outputPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
await fs.writeFile(finalReconciliationPath, `${JSON.stringify({ source_financial_documents: 861, main_vendor_bills: 795, exception_vendor_bills: 7, owner_approved_vendor_bills: 36, total_vendor_bills: 838, daily_wages_already_migrated_as_journal_entries: remaining.length, daily_wages_gross: remaining.reduce((sum, row) => sum + Number(row.amount), 0).toFixed(2), owner_workbook_sha256: ownerWorkbookSha, remaining }, null, 2)}\n`, "utf8");
console.log(JSON.stringify({ outputPath, payload_sha256: crypto.createHash("sha256").update(await fs.readFile(outputPath)).digest("hex"), report: payload.report, category_decisions: categoryDecisions.map((item) => ({ mapping_key: item.source_mapping_key, account: item.target_account_code })), final_reconciliation: { vendor_bills: 838, daily_wages_already_migrated: remaining.length } }, null, 2));
