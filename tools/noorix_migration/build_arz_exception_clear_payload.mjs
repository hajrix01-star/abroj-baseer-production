/** Build exactly seven owner-cleared ARZ historical-repair vendor bills.
 *
 * The main ARZ payload remains immutable.  This additive builder has a hard
 * source-invoice allowlist and fails closed if the source identity, supplier,
 * ledger/allocation/vault evidence, target supplier/vault map, or target
 * account/tax primitives differ.  It performs read-only SQL only.
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
const outputDir = ".local-backups/noorix-migration/runs/20260913-arz-exception-clear-qa-1";
const outputPath = path.join(outputDir, "arz-exception-clear-payload.json");
const remainingPath = path.join(outputDir, "arz-main-payload-remaining-exclusions.json");
const mainExclusionsPath = ".local-backups/noorix-migration/runs/20260913-arz-general-purchases-qa-1/arz-general-purchase-exclusions.json";
const approved = new Map([
  ["PUR-20260613-001", "نديم لتركيب الدش"], ["PUR-20260621-007", "نديم لتركيب الدش"],
  ["PUR-20260708-002", "نديم لتركيب الدش"], ["PUR-20260814-013", "نديم لتركيب الدش"],
  ["PUR-20260811-001", "الرمز السري للمفاتيح"], ["PUR-20260623-007", "سحم الدوحه للتجاره"],
  ["PUR-20260729-002", "سحم الدوحه للتجاره"],
]);
const repair = { accountCode: "400042", accountType: "expense", productCode: "NOORIX-HIST-ARZ-400042-EXCEPTION-CLEAR", productName: "تاريخي ARZ - صيانة استثنائية موثقة", mappingKey: "exception-clear:approved-uncategorized-repairs" };

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
function netPrice(value) { const whole = value / 115n; let rem = value % 115n; let digits = ""; for (let i = 0; i < 14; i += 1) { rem *= 10n; digits += String(rem / 115n); rem %= 115n; } return `${whole}.${digits}`; }

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
  id, rowTenant, companyId, kind, status, number, supplierInvoice, date, netRaw: fixed4(netRaw), taxRaw: fixed4(taxRaw), totalRaw: fixed4(totalRaw), supplierId, supplierName, categoryId: categoryId || null, categoryName: categoryName || "__UNCATEGORIZED__", notes: Buffer.from(notesHex, "hex").toString("utf8"), allocationId, vaultId, allocationRaw: fixed4(allocationRaw), ledgerId, ledgerRaw: fixed4(ledgerRaw), createdAt, updatedAt, allocationCreatedAt, ledgerCreatedAt,
}));
if (sourceRows.length !== approved.size || new Set(sourceRows.map((row) => row.number)).size !== approved.size) throw new Error(`Expected exactly ${approved.size} cleared source invoices, found ${sourceRows.length}`);
for (const row of sourceRows) {
  if (row.rowTenant !== tenantId || row.companyId !== sourceCompanyId || row.kind !== "purchase" || row.status !== "active" || row.categoryName !== "__UNCATEGORIZED__" || approved.get(row.number) !== row.supplierName) throw new Error(`Cleared source identity/status/category/supplier differs: ${row.number}`);
  if (units4(row.allocationRaw) !== units4(row.totalRaw) || units4(row.ledgerRaw) !== units4(row.totalRaw)) throw new Error(`Source allocation/ledger differs: ${row.number}`);
}

const companyMap = psql(targetDb, `SELECT company_id,source_archive_sha256 FROM baseer_noorix_company_map WHERE source_system='noorix' AND source_tenant_id='${tenantId}' AND source_company_id='${sourceCompanyId}';`);
if (companyMap.length !== 1 || Number(companyMap[0][0]) !== targetCompanyId || companyMap[0][1] !== archiveSha) throw new Error("ARZ company map differs");
const account = psql(targetDb, "SELECT id,account_type,active FROM account_account WHERE code_store->>'1'='400042';");
if (account.length !== 1 || account[0][1] !== repair.accountType || account[0][2] !== "t") throw new Error("Approved repair account differs");
const [repairAccountId] = account[0].map(Number);
const tax = psql(targetDb, "SELECT id,amount,type_tax_use,active,COALESCE(price_include_override::text,'') FROM account_tax WHERE id=22;");
if (tax.length !== 1 || tax[0][1] !== "15.0000" || tax[0][2] !== "purchase" || tax[0][3] !== "t" || tax[0][4] === "true") throw new Error("Tax 22 differs");
const purchaseJournal = psql(targetDb, "SELECT id,code,type,company_id FROM account_journal WHERE id=9;");
if (purchaseJournal.length !== 1 || purchaseJournal[0][1] !== "BILL" || purchaseJournal[0][2] !== "purchase" || Number(purchaseJournal[0][3]) !== targetCompanyId) throw new Error("BILL/9 differs");
const sourceSupplierIds = sourceRows.map((row) => `'${row.supplierId}'`).join(",");
const partnerBySource = new Map(psql(targetDb, `SELECT m.source_supplier_id,m.partner_id,m.source_archive_sha256,COALESCE(p.company_id::text,''),p.supplier_rank FROM baseer_noorix_supplier_map m JOIN res_partner p ON p.id=m.partner_id WHERE m.source_system='noorix' AND m.source_tenant_id='${tenantId}' AND m.source_company_id='${sourceCompanyId}' AND m.source_supplier_id IN (${sourceSupplierIds});`).map(([sourceId, partnerId, archive, companyId, rank]) => { if (archive !== archiveSha || companyId || Number(rank) <= 0) throw new Error(`Supplier map differs: ${sourceId}`); return [sourceId, Number(partnerId)]; }));
const sourceVaultIds = [...new Set(sourceRows.map((row) => row.vaultId))].map((value) => `'${value}'`).join(",");
const journalByVault = new Map(psql(targetDb, `SELECT m.source_vault_id,m.journal_id,m.source_archive_sha256,j.code FROM baseer_noorix_liquidity_vault_map m JOIN account_journal j ON j.id=m.journal_id WHERE m.source_system='noorix' AND m.source_tenant_id='${tenantId}' AND m.source_company_id='${sourceCompanyId}' AND m.company_id=${targetCompanyId} AND m.source_vault_id IN (${sourceVaultIds});`).map(([vaultId, journalId, archive, code]) => { if (archive !== archiveSha || ["PSBNK", "PSCSH"].includes(code)) throw new Error(`Vault map differs: ${vaultId}`); return [vaultId, Number(journalId)]; }));
if (partnerBySource.size !== new Set(sourceRows.map((row) => row.supplierId)).size || journalByVault.size !== new Set(sourceRows.map((row) => row.vaultId)).size) throw new Error("Cleared source supplier/vault mapping is incomplete");
const existing = psql(targetDb, `SELECT source_invoice_id FROM baseer_noorix_purchase_invoice_map WHERE source_system='noorix' AND source_tenant_id='${tenantId}' AND source_company_id='${sourceCompanyId}' AND source_invoice_id IN (${sourceRows.map((row) => `'${row.id}'`).join(",")});`);
if (existing.length) throw new Error(`A cleared invoice is already mapped: ${existing.map((row) => row[0]).join(",")}`);

const categoryDecision = { source_system: "noorix", source_tenant_id: tenantId, source_company_id: sourceCompanyId, source_mapping_key: repair.mappingKey, source_category_id: null, source_category_name: "غير مصنف — استثناء صيانة موثق", source_row_sha256: sha({ mappingKey: repair.mappingKey, approved_invoices: [...approved.keys()], account: repair.accountCode, policy: "VAT-inclusive-15" }), source_archive_sha256: archiveSha, canonical_key: "arz-exception-clear:approved-repairs", decision: "create_historical_service", target_product_id: null, target_product_code: repair.productCode, target_product_name: repair.productName, target_account_id: repairAccountId, target_account_code: repair.accountCode, target_account_type: repair.accountType, tax_policy: "owner_declared_inclusive_15" };
const documents = sourceRows.map((row) => {
  const gross = cents(row.totalRaw); const net = halfUp(gross * 100n, 115n); const vat = gross - net;
  return { source_system: "noorix", source_tenant_id: tenantId, source_company_id: sourceCompanyId, source_invoice_id: row.id, source_ledger_id: row.ledgerId, source_allocation_id: row.allocationId, source_vault_id: row.vaultId, source_supplier_id: row.supplierId, source_category_id: null, source_invoice_number: row.number, source_supplier_invoice_number: row.supplierInvoice, source_document_kind: "purchase", business_date: row.date, month: row.date.slice(0, 7), source_net_raw: row.netRaw, source_tax_raw: row.taxRaw, source_total_raw: row.totalRaw, source_row_sha256: sha({ ...row, approved_supplier: approved.get(row.number), decision: categoryDecision.canonical_key }), source_archive_sha256: archiveSha, canonical_key: `purchase:${sourceCompanyId}:${row.id}`, source_asset_id: null, source_asset_row_sha256: null, decision: "create_paid_vendor_bill", category_mapping_key: repair.mappingKey, target_product_id: null, target_product_code: repair.productCode, target_product_name: repair.productName, target_account_id: repairAccountId, target_account_code: repair.accountCode, target_partner_id: partnerBySource.get(row.supplierId), target_payment_journal_id: journalByVault.get(row.vaultId), target_tax_id: 22, price_unit: netPrice(gross), target_net: money(net), target_tax: money(vat), target_total: money(gross) };
});
const total = (field) => money(documents.reduce((sum, row) => sum + BigInt(row[field].replace(".", "")), 0n));
const months = Object.fromEntries([...new Set(documents.map((row) => row.month))].sort().map((month) => { const rows = documents.filter((row) => row.month === month); return [month, { documents: rows.length, gross: money(rows.reduce((sum, row) => sum + BigInt(row.target_total.replace(".", "")), 0n)) }]; }));
const payload = { schema_version: 1, target_database: targetDb, source_archive_sha256: archiveSha, approved_policy: "general_paid_vendor_bills_native_accounting_monthly_atomic", run_prefix: "20260913-noorix-arz-exception-clear-qa", company: { source_system: "noorix", source_tenant_id: tenantId, source_company_id: sourceCompanyId, target_company_id: targetCompanyId }, allowlist: { purchase_journal_id: 9, purchase_journal_code: "BILL", purchase_tax_id: 22, vat_input_account_code: "104041", forbidden_journal_codes: ["PSBNK", "PSCSH"] }, category_decisions: [categoryDecision], documents, report: { source_documents: documents.length, target_net: total("target_net"), target_tax: total("target_tax"), target_gross: total("target_total"), months } };
const mainExclusions = JSON.parse(await fs.readFile(mainExclusionsPath, "utf8"));
const remaining = mainExclusions.exclusions.filter((row) => !approved.has(row.invoice_number));
if (mainExclusions.exclusions.length - remaining.length !== approved.size) throw new Error("Cleared invoice set is not exactly seven rows from the main exclusions manifest");
const amount = (rows) => rows.reduce((sum, row) => sum + Number(row.amount), 0);
await fs.mkdir(outputDir, { recursive: true });
await fs.writeFile(outputPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
await fs.writeFile(remainingPath, `${JSON.stringify({ main_exclusion_count: mainExclusions.exclusions.length, cleared_count: approved.size, remaining_count: remaining.length, remaining_total: amount(remaining).toFixed(2), remaining_uncategorized_count: remaining.filter((row) => row.reason === "uncategorized_outside_approved_rules").length, remaining_uncategorized_total: amount(remaining.filter((row) => row.reason === "uncategorized_outside_approved_rules")).toFixed(2), remaining }, null, 2)}\n`, "utf8");
console.log(JSON.stringify({ outputPath, payload_sha256: crypto.createHash("sha256").update(await fs.readFile(outputPath)).digest("hex"), report: payload.report, remaining_exclusions: { count: remaining.length, total: amount(remaining).toFixed(2), uncategorized_count: remaining.filter((row) => row.reason === "uncategorized_outside_approved_rules").length, uncategorized_total: amount(remaining.filter((row) => row.reason === "uncategorized_outside_approved_rules")).toFixed(2) } }, null, 2));
