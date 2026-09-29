/** Build the finite QA-only SHAMI TAX purchase-history payload.
 *
 * Source and QA are read only.  The builder deliberately accepts just the
 * owner-approved chicken category and the one append-only source-bank map.
 */
import crypto from "node:crypto";
import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";

const sourceDb = "noorix_source_inspection_archive159_20260913";
const targetDb = "baseer_noorix_data_migration_qa_20260912";
const dbContainer = "baseer_odoo_dev-db-1";
const outputDir = ".local-backups/noorix-migration/runs/20260913-shami-tax-purchases-qa-1";
const outputPath = path.join(outputDir, "shami-tax-purchase-payload.json");
const evidencePath = path.join(outputDir, "shami-tax-purchase-evidence.json");
const archiveSha = "024606ADD82DCD78DC1835828A12D7B22C56E34924FF998ABF752134160E79E2";
const tenantId = "default-tenant-noorix-2024";
const sourceCompanyId = "cmr3fd0y3000hycziou1o2c47";
const sourceCategoryId = "cmr3fd105002fycziq19peout";
const sourceVaultId = "cmr3fd0z9001lycziqkw21grp";
const targetCompanyId = 5;
const purchaseJournal = { id: 78, code: "BILL" };
const paymentJournal = { id: 82, code: "BNK1" };
const purchaseTax = { id: 178, inputAccountCode: "104041" };
const account = { id: 898, code: "400001", type: "expense_direct_cost" };
const category = {
  mappingKey: `category:${sourceCategoryId}`,
  productCode: "NOORIX-HIST-SHAMI-TAX-400001-CHICKEN",
  productName: "تاريخي SHAMI TAX - دجاج",
};

function psql(database, sql) {
  if (database === "baseer_dev") throw new Error("Production database is forbidden");
  const out = execFileSync("docker", ["exec", dbContainer, "psql", "-U", "odoo", "-d", database, "-At", "-F", "\t", "-c", sql], { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 }).trim();
  return out ? out.split("\n").map((line) => line.split("\t")) : [];
}
const sha = (value) => crypto.createHash("sha256").update(JSON.stringify(value)).digest("hex");
function fixed4(value) {
  const match = String(value).match(/^(\d+)(?:\.(\d+))?$/);
  if (!match) throw new Error(`Invalid amount: ${value}`);
  const fraction = (match[2] || "").padEnd(4, "0");
  if (fraction.length > 4 && /[1-9]/.test(fraction.slice(4))) throw new Error(`Amount precision exceeds source contract: ${value}`);
  return `${match[1]}.${fraction.slice(0, 4)}`;
}
function units4(value) { const [whole, fraction] = fixed4(value).split("."); return BigInt(whole) * 10000n + BigInt(fraction); }
function roundHalfUp(numerator, denominator) { return (numerator * 2n + denominator) / (denominator * 2n); }
function centsFromRaw(value) { return roundHalfUp(units4(value), 100n); }
function money(cents) { return `${cents / 100n}.${String(cents % 100n).padStart(2, "0")}`; }
function priceExcludingVat(cents) {
  const whole = cents / 115n; let remainder = cents % 115n; let fraction = "";
  for (let i = 0; i < 14; i += 1) { remainder *= 10n; fraction += String(remainder / 115n); remainder %= 115n; }
  return `${whole}.${fraction}`;
}
function sumCents(rows, field) { return rows.reduce((total, row) => total + BigInt(row[field].replace(".", "")), 0n); }

const rows = psql(sourceDb, `
SELECT i.id,i.tenant_id,i.company_id,i.kind,i.invoice_number,COALESCE(i.supplier_invoice_number,''),
       i.transaction_date::date::text,i.net_amount::text,i.tax_amount::text,i.total_amount::text,
       i.supplier_id,i.category_id,c.name_ar,encode(convert_to(COALESCE(i.notes,''),'UTF8'),'hex'),
       a.id,a.vault_id,a.amount::text,v.type,v.name_ar,v.is_active::text,v.is_archived::text,
       le.id,le.amount::text,i.created_at::text,i.updated_at::text,a.created_at::text,le.created_at::text
FROM invoices i
JOIN categories c ON c.id=i.category_id
JOIN invoice_vault_allocations a ON a.invoice_id=i.id
JOIN vaults v ON v.id=a.vault_id
JOIN ledger_entries le ON le.reference_type='invoice' AND le.reference_id=i.id
WHERE i.company_id='${sourceCompanyId}' AND i.status='active'
  AND i.kind='purchase' AND i.category_id='${sourceCategoryId}'
ORDER BY i.transaction_date,i.invoice_number,i.id;
`).map(([id, sourceTenantId, companyId, kind, invoiceNumber, supplierInvoiceNumber, businessDate, netRaw, taxRaw, totalRaw, supplierId, categoryId, categoryName, notesHex, allocationId, vaultId, allocationRaw, vaultType, vaultName, vaultActive, vaultArchived, ledgerId, ledgerRaw, createdAt, updatedAt, allocationCreatedAt, ledgerCreatedAt]) => ({
  id, sourceTenantId, companyId, kind, invoiceNumber, supplierInvoiceNumber, businessDate,
  netRaw: fixed4(netRaw), taxRaw: fixed4(taxRaw), totalRaw: fixed4(totalRaw), supplierId, categoryId, categoryName,
  notes: Buffer.from(notesHex, "hex").toString("utf8"), allocationId, vaultId, allocationRaw: fixed4(allocationRaw), vaultType, vaultName,
  vaultActive: vaultActive === "true", vaultArchived: vaultArchived === "true", ledgerId, ledgerRaw: fixed4(ledgerRaw), createdAt, updatedAt, allocationCreatedAt, ledgerCreatedAt,
}));
if (rows.length !== 36) throw new Error(`Expected exactly 36 approved SHAMI TAX documents, found ${rows.length}`);
for (const row of rows) {
  if (row.sourceTenantId !== tenantId || row.companyId !== sourceCompanyId || row.kind !== "purchase" || row.categoryId !== sourceCategoryId || row.categoryName !== "دجاج" || row.vaultId !== sourceVaultId || row.vaultType !== "bank" || !row.vaultActive || row.vaultArchived) throw new Error(`Source boundary differs: ${row.invoiceNumber}`);
  if (units4(row.allocationRaw) !== units4(row.totalRaw) || units4(row.ledgerRaw) !== units4(row.totalRaw)) throw new Error(`Payment evidence differs: ${row.invoiceNumber}`);
  const gross = centsFromRaw(row.totalRaw); const net = roundHalfUp(gross * 100n, 115n); const vat = gross - net;
  if (centsFromRaw(row.netRaw) !== net || centsFromRaw(row.taxRaw) !== vat) throw new Error(`VAT-inclusive source arithmetic differs: ${row.invoiceNumber}`);
}

const companyMap = psql(targetDb, `SELECT company_id::text,source_archive_sha256 FROM baseer_noorix_company_map WHERE source_system='noorix' AND source_tenant_id='${tenantId}' AND source_company_id='${sourceCompanyId}';`);
if (companyMap.length !== 1 || Number(companyMap[0][0]) !== targetCompanyId || companyMap[0][1] !== archiveSha) throw new Error("SHAMI TAX company provenance differs");
const sourceSupplierIds = [...new Set(rows.map((row) => row.supplierId))].sort();
const supplierRows = psql(targetDb, `SELECT m.source_supplier_id,m.partner_id::text,m.source_archive_sha256,COALESCE(p.company_id::text,''),p.supplier_rank::text FROM baseer_noorix_supplier_map m JOIN res_partner p ON p.id=m.partner_id WHERE m.source_system='noorix' AND m.source_tenant_id='${tenantId}' AND m.source_company_id='${sourceCompanyId}' AND m.source_supplier_id IN (${sourceSupplierIds.map((id) => `'${id}'`).join(",")});`);
const partnerBySource = new Map(supplierRows.map(([supplierId, partnerId, sourceArchive, partnerCompanyId, rank]) => {
  if (sourceArchive !== archiveSha || partnerCompanyId || Number(rank) < 1) throw new Error(`Supplier provenance differs: ${supplierId}`);
  return [supplierId, Number(partnerId)];
}));
for (const row of rows) if (!partnerBySource.has(row.supplierId)) throw new Error(`Supplier map missing: ${row.invoiceNumber}`);
const vaultRows = psql(targetDb, `SELECT m.journal_id::text,m.source_archive_sha256,m.source_vault_type,m.source_vault_name,m.decision,j.code,j.type,j.company_id::text FROM baseer_noorix_liquidity_vault_map m JOIN account_journal j ON j.id=m.journal_id WHERE m.source_system='noorix' AND m.source_tenant_id='${tenantId}' AND m.source_company_id='${sourceCompanyId}' AND m.source_vault_id='${sourceVaultId}';`);
if (vaultRows.length !== 1) throw new Error("Approved SHAMI TAX bank provenance map is missing or ambiguous");
const [mappedJournalId, mappedArchive, mappedType, mappedName, mappedDecision, mappedCode, mappedJournalType, mappedCompanyId] = vaultRows[0];
if (Number(mappedJournalId) !== paymentJournal.id || mappedArchive !== archiveSha || mappedType !== "bank" || mappedName !== "بنك" || mappedDecision !== "reuse_existing_liquidity" || mappedCode !== paymentJournal.code || mappedJournalType !== "bank" || Number(mappedCompanyId) !== targetCompanyId) throw new Error("SHAMI TAX bank provenance target differs");
const targetRows = psql(targetDb, `
SELECT (SELECT code FROM account_journal WHERE id=${purchaseJournal.id}),
       (SELECT type FROM account_journal WHERE id=${purchaseJournal.id}),
       (SELECT company_id::text FROM account_journal WHERE id=${purchaseJournal.id}),
       (SELECT amount::text FROM account_tax WHERE id=${purchaseTax.id}),
       (SELECT type_tax_use FROM account_tax WHERE id=${purchaseTax.id}),
       (SELECT active::text FROM account_tax WHERE id=${purchaseTax.id}),
       (SELECT COALESCE(price_include_override::text,'') FROM account_tax WHERE id=${purchaseTax.id}),
       (SELECT code_store->>'5' FROM account_account WHERE id=${account.id}),
       (SELECT account_type FROM account_account WHERE id=${account.id}),
       (SELECT active::text FROM account_account WHERE id=${account.id}),
       (SELECT code_store->>'5' FROM account_account WHERE id=(SELECT account_id FROM account_tax_repartition_line WHERE tax_id=${purchaseTax.id} AND repartition_type='tax' AND document_type='invoice'));
`);
if (targetRows.length !== 1) throw new Error("SHAMI TAX target master data is unavailable");
const [purchaseCode, purchaseType, purchaseCompany, taxAmount, taxUse, taxActive, priceInclude, accountCode, accountType, accountActive, vatInputCode] = targetRows[0];
if (purchaseCode !== purchaseJournal.code || purchaseType !== "purchase" || Number(purchaseCompany) !== targetCompanyId || taxAmount !== "15.0000" || taxUse !== "purchase" || !["t", "true"].includes(taxActive) || priceInclude === "true" || accountCode !== account.code || accountType !== account.type || !["t", "true"].includes(accountActive) || vatInputCode !== purchaseTax.inputAccountCode) throw new Error("SHAMI TAX target journal/tax/account differs");
const existingInvoices = psql(targetDb, `SELECT source_invoice_id FROM baseer_noorix_purchase_invoice_map WHERE source_system='noorix' AND source_tenant_id='${tenantId}' AND source_company_id='${sourceCompanyId}';`);
if (existingInvoices.length) throw new Error("SHAMI TAX purchase source identity is already mapped; use replay verification");

const snapshot = { source_category_id: sourceCategoryId, source_category_name: "دجاج", mappingKey: category.mappingKey, accountCode: account.code, accountType: account.type, label: "دجاج" };
const decision = { source_system: "noorix", source_tenant_id: tenantId, source_company_id: sourceCompanyId, source_mapping_key: category.mappingKey, source_category_id: sourceCategoryId, source_category_name: "دجاج", source_row_sha256: sha(snapshot), source_archive_sha256: archiveSha, canonical_key: "shami-tax-purchase:400001:chicken", decision: "create_historical_service", target_product_id: null, target_product_code: category.productCode, target_product_name: category.productName, target_account_id: account.id, target_account_code: account.code, target_account_type: account.type, tax_policy: "owner_declared_inclusive_15" };
const documents = rows.map((row) => {
  const gross = centsFromRaw(row.totalRaw); const net = roundHalfUp(gross * 100n, 115n); const vat = gross - net;
  return { source_system: "noorix", source_tenant_id: tenantId, source_company_id: sourceCompanyId, source_invoice_id: row.id, source_ledger_id: row.ledgerId, source_allocation_id: row.allocationId, source_vault_id: row.vaultId, source_supplier_id: row.supplierId, source_category_id: row.categoryId, source_invoice_number: row.invoiceNumber, source_supplier_invoice_number: row.supplierInvoiceNumber, source_document_kind: row.kind, business_date: row.businessDate, month: row.businessDate.slice(0, 7), source_net_raw: row.netRaw, source_tax_raw: row.taxRaw, source_total_raw: row.totalRaw, source_row_sha256: sha({ ...row, category_policy: snapshot }), source_archive_sha256: archiveSha, canonical_key: `purchase:${sourceCompanyId}:${row.id}`, source_asset_id: null, source_asset_row_sha256: null, decision: "create_paid_vendor_bill", category_mapping_key: category.mappingKey, target_product_id: null, target_product_code: category.productCode, target_product_name: category.productName, target_account_id: account.id, target_account_code: account.code, target_partner_id: partnerBySource.get(row.supplierId), target_payment_journal_id: paymentJournal.id, target_tax_id: purchaseTax.id, price_unit: priceExcludingVat(gross), target_net: money(net), target_tax: money(vat), target_total: money(gross) };
});
const months = Object.fromEntries([...new Set(documents.map((row) => row.month))].sort().map((month) => {
  const rowsForMonth = documents.filter((row) => row.month === month);
  return [month, { documents: rowsForMonth.length, gross: money(sumCents(rowsForMonth, "target_total")) }];
}));
const payload = { schema_version: 1, target_database: targetDb, source_archive_sha256: archiveSha, approved_policy: "general_paid_vendor_bills_native_accounting_monthly_atomic", run_prefix: "20260913-noorix-shami-tax-purchases-qa", company: { source_system: "noorix", source_tenant_id: tenantId, source_company_id: sourceCompanyId, target_company_id: targetCompanyId }, allowlist: { purchase_journal_id: purchaseJournal.id, purchase_journal_code: purchaseJournal.code, purchase_tax_id: purchaseTax.id, vat_input_account_code: purchaseTax.inputAccountCode, forbidden_journal_codes: ["PSBNK", "PSCSH"] }, category_decisions: [decision], documents, report: { source_documents: documents.length, target_net: money(sumCents(documents, "target_net")), target_tax: money(sumCents(documents, "target_tax")), target_gross: money(sumCents(documents, "target_total")), months } };
const evidence = { scope: "SHAMI TAX active purchase invoices only", source_documents: rows.length, category: { source_category_id: sourceCategoryId, source_category_name: "دجاج", product_line_evidence: "Noorix invoices contain no product-line identifier; category is the only source product classification." }, supplier: { source_supplier_ids: [...new Set(rows.map((row) => row.supplierId))], target_partner_ids: [...new Set(documents.map((row) => row.target_partner_id))] }, vault: { source_vault_id: sourceVaultId, source_type: "bank", target_journal_id: paymentJournal.id, target_journal_code: paymentJournal.code }, vat: { policy: "owner_declared_inclusive_15", source_tax_total: payload.report.target_tax, target_tax_id: purchaseTax.id }, report: payload.report };
await fs.mkdir(outputDir, { recursive: true });
await fs.writeFile(outputPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
await fs.writeFile(evidencePath, `${JSON.stringify(evidence, null, 2)}\n`, "utf8");
console.log(JSON.stringify({ outputPath, payload_sha256: crypto.createHash("sha256").update(await fs.readFile(outputPath)).digest("hex"), evidencePath, report: payload.report }, null, 2));
