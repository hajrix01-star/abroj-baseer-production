/**
 * Build the finite, QA-only ARZ historical-purchases payload.
 *
 * This script is read-only against both databases.  It deliberately emits an
 * exclusion manifest instead of guessing any category that the approved ARZ
 * review did not classify.  The writer rejects any later payload alteration.
 */
import crypto from "node:crypto";
import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";

const sourceDb = "noorix_source_inspection_archive159_20260913";
const targetDb = "baseer_noorix_data_migration_qa_20260912";
const dbContainer = "baseer_odoo_dev-db-1";
const outputDir = ".local-backups/noorix-migration/runs/20260913-arz-general-purchases-qa-1";
const outputPath = path.join(outputDir, "arz-general-purchase-payload.json");
const exclusionsPath = path.join(outputDir, "arz-general-purchase-exclusions.json");
const archiveSha = "024606ADD82DCD78DC1835828A12D7B22C56E34924FF998ABF752134160E79E2";
const tenantId = "default-tenant-noorix-2024";
const sourceCompanyId = "cmnf604ka009ay8lm556wgd9c";
const targetCompanyId = 1;
const purchaseJournal = { id: 9, code: "BILL" };
const purchaseTaxId = 22;

const operational = new Set([
  "مواد غذائية", "مواد غذائية أخرى", "خضار وفواكه", "خامات", "لحوم", "بضاعة تموينية", "مشروبات", "مياه", "غازيات", "قهوة بن", "تعبئة وتغليف", "بلاستيكات", "علب وأكواب", "أكياس", "مستلزمات تشغيل مطبخ", "غاز طبخ", "فحم", "معسل", "شيشة",
]);
const categoryPolicies = new Map([
  ["إيجارات", ["400016", "expense", "إيجارات"]],
  ["كهرباء", ["400018", "expense", "كهرباء وماء"]],
  ["ماء", ["400018", "expense", "كهرباء وماء"]],
  ["اتصالات", ["400020", "expense", "اتصالات"]],
  ["رسوم إدارة حساب", ["400051", "expense", "رسوم إدارة حساب"]],
  ["صيانة آلات", ["400042", "expense", "صيانة وتشغيل"]],
  ["صيانة وتشغيل", ["400042", "expense", "صيانة وتشغيل"]],
  ["وقود ومواصلات", ["400048", "expense", "وقود ومواصلات"]],
  ["تسويق", ["400034", "expense", "تسويق"]],
  ["هدايا", ["400046", "expense", "هدايا"]],
  ["إقامات وجوازات", ["400093", "expense", "إقامات ورسوم حكومية"]],
  ["رسوم حكومية وإقامات", ["400093", "expense", "إقامات ورسوم حكومية"]],
  ["رخصة بلدية", ["400032", "expense", "رخصة بلدية"]],
  ["التأمينات الاجتماعية (GOSI)", ["400015", "expense", "التأمينات الاجتماعية"]],
  ["ضرائب ورسوم أخرى", ["400072", "expense", "ضرائب ورسوم أخرى"]],
]);

function psql(database, sql) {
  if (database === "baseer_dev") throw new Error("Production database is forbidden");
  const output = execFileSync("docker", ["exec", dbContainer, "psql", "-U", "odoo", "-d", database, "-At", "-F", "\t", "-c", sql], { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
  return output.split(/\r?\n/).filter(Boolean).map((line) => line.split("\t"));
}
const sha = (value) => crypto.createHash("sha256").update(JSON.stringify(value)).digest("hex");
function fixed4(value) {
  const match = String(value).match(/^(\d+)(?:\.(\d+))?$/);
  if (!match) throw new Error(`Invalid non-negative source amount: ${value}`);
  const fraction = (match[2] || "").padEnd(4, "0");
  if (fraction.length > 4 && /[1-9]/.test(fraction.slice(4))) throw new Error(`Source amount exceeds four decimals: ${value}`);
  return `${match[1]}.${fraction.slice(0, 4)}`;
}
function units4(value) { const [whole, fraction] = fixed4(value).split("."); return BigInt(whole) * 10000n + BigInt(fraction); }
function roundHalfUp(numerator, denominator) { return (numerator * 2n + denominator) / (denominator * 2n); }
function centsFromRaw(value) { return roundHalfUp(units4(value), 100n); }
function asMoney(cents) { return `${cents / 100n}.${String(cents % 100n).padStart(2, "0")}`; }
function priceExcludingVat(cents) {
  const whole = cents / 115n; let remainder = cents % 115n; let fraction = "";
  for (let i = 0; i < 14; i += 1) { remainder *= 10n; fraction += String(remainder / 115n); remainder %= 115n; }
  return `${whole}.${fraction}`;
}
function normal(value) { return String(value || "").replace(/[إأآ]/g, "ا").replace(/ة/g, "ه").replace(/\s+/g, " ").trim().toLowerCase(); }
function categoryCode(account, label) { return `NOORIX-HIST-ARZ-${account}-${sha(label).slice(0, 10).toUpperCase()}`; }

const sourceRows = psql(sourceDb, `
SELECT i.id,i.tenant_id,i.company_id,i.kind,i.invoice_number,COALESCE(i.supplier_invoice_number,''),
       i.transaction_date::date::text,i.net_amount::text,i.tax_amount::text,i.total_amount::text,
       i.supplier_id,COALESCE(i.category_id,''),COALESCE(c.name_ar,''),encode(convert_to(COALESCE(i.notes,''),'UTF8'),'hex'),
       a.id,a.vault_id,a.amount::text,v.type,v.name_ar,le.id,le.amount::text,
       COALESCE(asset.id,''),encode(convert_to(COALESCE(asset.name_ar,''),'UTF8'),'hex'),
       COALESCE(asset.acquisition_cost::text,''),COALESCE(asset.purchase_date::date::text,''),
       i.created_at::text,i.updated_at::text,a.created_at::text,le.created_at::text
FROM invoices i
LEFT JOIN categories c ON c.id=i.category_id
JOIN invoice_vault_allocations a ON a.invoice_id=i.id
JOIN vaults v ON v.id=a.vault_id
JOIN ledger_entries le ON le.reference_type='invoice' AND le.reference_id=i.id
LEFT JOIN company_assets asset ON asset.invoice_id=i.id
WHERE i.company_id='${sourceCompanyId}' AND i.status='active'
  AND i.kind IN ('purchase','expense','fixed_expense')
ORDER BY i.transaction_date,i.invoice_number,i.id;
`).map(([id, sourceTenantId, companyId, kind, invoiceNumber, supplierInvoiceNumber, businessDate, netRaw, taxRaw, totalRaw, supplierId, categoryId, categoryName, notesHex, allocationId, vaultId, allocationRaw, vaultType, vaultName, ledgerId, ledgerRaw, assetId, assetNameHex, assetCost, assetDate, createdAt, updatedAt, allocationCreatedAt, ledgerCreatedAt]) => ({
  id, sourceTenantId, companyId, kind, invoiceNumber, supplierInvoiceNumber, businessDate,
  netRaw: fixed4(netRaw), taxRaw: fixed4(taxRaw), totalRaw: fixed4(totalRaw), supplierId,
  categoryId: categoryId || null, categoryName: categoryName || "__UNCATEGORIZED__", notes: Buffer.from(notesHex, "hex").toString("utf8"),
  allocationId, vaultId, allocationRaw: fixed4(allocationRaw), vaultType, vaultName, ledgerId, ledgerRaw: fixed4(ledgerRaw),
  assetId: assetId || null, assetName: Buffer.from(assetNameHex, "hex").toString("utf8"), assetCost: assetCost ? fixed4(assetCost) : null, assetDate: assetDate || null,
  createdAt, updatedAt, allocationCreatedAt, ledgerCreatedAt,
}));
if (!sourceRows.length || sourceRows.some((r) => r.sourceTenantId !== tenantId || r.companyId !== sourceCompanyId)) throw new Error("ARZ source boundary differs");
for (const row of sourceRows) {
  if (units4(row.allocationRaw) !== units4(row.totalRaw) || units4(row.ledgerRaw) !== units4(row.totalRaw)) throw new Error(`Incomplete allocation/ledger evidence: ${row.invoiceNumber}`);
}

const companyMap = psql(targetDb, `SELECT company_id,source_archive_sha256 FROM baseer_noorix_company_map WHERE source_system='noorix' AND source_tenant_id='${tenantId}' AND source_company_id='${sourceCompanyId}';`);
if (companyMap.length !== 1 || Number(companyMap[0][0]) !== targetCompanyId || companyMap[0][1] !== archiveSha) throw new Error("ARZ company map differs");
const accountCodes = ["400001", "400016", "400018", "400020", "400051", "400042", "400048", "400034", "400046", "400093", "400032", "400015", "400072", "106002", "106003"];
const accountRows = psql(targetDb, `SELECT id,code_store->>'1',account_type,active FROM account_account WHERE code_store->>'1' IN (${accountCodes.map((v) => `'${v}'`).join(",")});`);
const accountByCode = new Map(accountRows.map(([id, code, type, active]) => [code, { id: Number(id), type, active: active === "t" }]));
if (accountByCode.size !== accountCodes.length || [...accountByCode.values()].some((a) => !a.active)) throw new Error("ARZ account allowlist differs");
const journals = psql(targetDb, "SELECT id,code,type,company_id FROM account_journal WHERE id IN (9,13,39,49,50,72,73,74) ORDER BY id;");
const journalById = new Map(journals.map(([id, code, type, companyId]) => [Number(id), { code, type, companyId: Number(companyId) }]));
if (journalById.get(9)?.code !== "BILL" || journalById.get(9)?.type !== "purchase" || journalById.get(9)?.companyId !== targetCompanyId) throw new Error("ARZ BILL journal differs");
const tax = psql(targetDb, "SELECT id,amount,type_tax_use,active,COALESCE(price_include_override::text,'') FROM account_tax WHERE id=22;");
if (tax.length !== 1 || tax[0][1] !== "15.0000" || tax[0][2] !== "purchase" || tax[0][3] !== "t" || tax[0][4] === "true") throw new Error("ARZ purchase tax 22 differs");
const supplierRows = psql(targetDb, `SELECT m.source_supplier_id,m.partner_id,m.source_archive_sha256,COALESCE(p.company_id::text,''),p.supplier_rank FROM baseer_noorix_supplier_map m JOIN res_partner p ON p.id=m.partner_id WHERE m.source_system='noorix' AND m.source_tenant_id='${tenantId}' AND m.source_company_id='${sourceCompanyId}';`);
const partnerBySource = new Map(supplierRows.map(([sourceId, partnerId, sourceArchive, companyId, rank]) => {
  if (sourceArchive !== archiveSha || companyId || Number(rank) <= 0) throw new Error(`Supplier map differs: ${sourceId}`);
  return [sourceId, Number(partnerId)];
}));
const vaultRows = psql(targetDb, `SELECT source_vault_id,journal_id,source_archive_sha256 FROM baseer_noorix_liquidity_vault_map WHERE source_system='noorix' AND source_tenant_id='${tenantId}' AND source_company_id='${sourceCompanyId}' AND company_id=${targetCompanyId};`);
const journalByVault = new Map(vaultRows.map(([vaultId, journalId, sourceArchive]) => {
  if (sourceArchive !== archiveSha || !journalById.has(Number(journalId)) || ["PSBNK", "PSCSH"].includes(journalById.get(Number(journalId)).code)) throw new Error(`Vault map differs: ${vaultId}`);
  return [vaultId, Number(journalId)];
}));

function policyFor(row) {
  const category = row.categoryName;
  if (operational.has(category)) return ["400001", "expense_direct_cost", category, `category:${row.categoryId}`];
  if (categoryPolicies.has(category)) { const [account, type, label] = categoryPolicies.get(category); return [account, type, label, `category:${row.categoryId}`]; }
  if (category === "تسويق وهدايا") {
    const text = normal(`${row.notes} ${row.supplierName || ""}`);
    if (/(مطبعه|قوقل|تقييمات|اعلان|تسويق)/.test(text)) return ["400034", "expense", "تسويق", `category:${row.categoryId}:marketing`];
    if (/هدي/.test(text)) return ["400046", "expense", "هدايا", `category:${row.categoryId}:gifts`];
    return null;
  }
  if (["أثاث", "أصول ومعدات", "أجهزة وإلكترونيات"].includes(category)) {
    if (!row.assetId) return null;
    const electronic = category === "أجهزة وإلكترونيات";
    return [electronic ? "106003" : "106002", "asset_fixed", electronic ? "أجهزة وإلكترونيات" : "أصول ومعدات", `asset:${row.id}`];
  }
  if (category !== "__UNCATEGORIZED__") return null;
  const text = normal(`${row.notes} ${row.supplierName || ""}`);
  if (/(اوبر|بنزين)/.test(text)) return ["400048", "expense", "وقود ومواصلات", "uncategorized:transport"];
  if (/(لحم|تموينات المواد اليوميه|تموينات)/.test(text)) return ["400001", "expense_direct_cost", "تموينات يومية", "uncategorized:daily-food"];
  if (/(صيانه المصعد|تصليح ماكينه اسبرسو|عزل)/.test(text)) return ["400042", "expense", "صيانة وتشغيل", "uncategorized:repair"];
  return null;
}

// Supplier name is needed only for the reviewed text classification; add it
// through a source-only companion lookup to avoid changing the evidence grain.
const supplierNames = new Map(psql(sourceDb, `SELECT id,COALESCE(name_ar,'') FROM suppliers WHERE company_id='${sourceCompanyId}';`).map(([id, name]) => [id, name]));
for (const row of sourceRows) row.supplierName = supplierNames.get(row.supplierId) || "";

const documents = []; const excluded = []; const decisions = new Map();
for (const row of sourceRows) {
  if (row.categoryName === "رواتب وأجور") { excluded.push({ id: row.id, invoice_number: row.invoiceNumber, amount: row.totalRaw, reason: "already_migrated_historical_daily_wages" }); continue; }
  const policy = policyFor(row);
  if (!policy) { excluded.push({ id: row.id, invoice_number: row.invoiceNumber, amount: row.totalRaw, category: row.categoryName, notes: row.notes, reason: row.categoryName === "__UNCATEGORIZED__" ? "uncategorized_outside_approved_rules" : "outside_approved_category_or_missing_asset_evidence" }); continue; }
  if (!partnerBySource.has(row.supplierId) || !journalByVault.has(row.vaultId)) throw new Error(`Supplier/vault mapping missing: ${row.invoiceNumber}; supplier=${row.supplierId}:${partnerBySource.has(row.supplierId)} vault=${row.vaultId}:${journalByVault.has(row.vaultId)}`);
  const [accountCode, accountType, label, mappingKey] = policy;
  const account = accountByCode.get(accountCode);
  const gross = centsFromRaw(row.totalRaw); const net = roundHalfUp(gross * 100n, 115n); const vat = gross - net;
  const categorySnapshot = { source_category_id: row.categoryId, source_category_name: row.categoryName, mappingKey, accountCode, accountType, label };
  const category = { source_system: "noorix", source_tenant_id: tenantId, source_company_id: sourceCompanyId, source_mapping_key: mappingKey, source_category_id: row.categoryId, source_category_name: row.categoryName === "__UNCATEGORIZED__" ? "" : row.categoryName, source_row_sha256: sha(categorySnapshot), source_archive_sha256: archiveSha, canonical_key: `arz-general:${accountCode}:${mappingKey}`, decision: "create_historical_service", target_product_id: null, target_product_code: categoryCode(accountCode, mappingKey), target_product_name: `تاريخي ARZ - ${label}`, target_account_id: account.id, target_account_code: accountCode, target_account_type: accountType, tax_policy: "owner_declared_inclusive_15" };
  const current = decisions.get(mappingKey);
  if (current && JSON.stringify(current) !== JSON.stringify(category)) throw new Error(`Conflicting category policy: ${mappingKey}`);
  decisions.set(mappingKey, category);
  const assetSnapshot = row.assetId ? { id: row.assetId, name_ar: row.assetName, acquisition_cost: row.assetCost, purchase_date: row.assetDate } : null;
  documents.push({ source_system: "noorix", source_tenant_id: tenantId, source_company_id: sourceCompanyId, source_invoice_id: row.id, source_ledger_id: row.ledgerId, source_allocation_id: row.allocationId, source_vault_id: row.vaultId, source_supplier_id: row.supplierId, source_category_id: row.categoryId, source_invoice_number: row.invoiceNumber, source_supplier_invoice_number: row.supplierInvoiceNumber, source_document_kind: row.kind, business_date: row.businessDate, month: row.businessDate.slice(0, 7), source_net_raw: row.netRaw, source_tax_raw: row.taxRaw, source_total_raw: row.totalRaw, source_row_sha256: sha({ ...row, supplierName: undefined, category_policy: categorySnapshot }), source_archive_sha256: archiveSha, canonical_key: `purchase:${sourceCompanyId}:${row.id}`, source_asset_id: row.assetId, source_asset_row_sha256: assetSnapshot ? sha(assetSnapshot) : null, decision: "create_paid_vendor_bill", category_mapping_key: mappingKey, target_product_id: null, target_product_code: category.target_product_code, target_product_name: category.target_product_name, target_account_id: account.id, target_account_code: accountCode, target_partner_id: partnerBySource.get(row.supplierId), target_payment_journal_id: journalByVault.get(row.vaultId), target_tax_id: purchaseTaxId, price_unit: priceExcludingVat(gross), target_net: asMoney(net), target_tax: asMoney(vat), target_total: asMoney(gross) });
}
const excludedUncategorized = excluded.filter((row) => row.reason === "uncategorized_outside_approved_rules");
if (excludedUncategorized.length !== 30) throw new Error(`Expected 30 unresolved uncategorized rows, found ${excludedUncategorized.length}`);
const total = (field) => asMoney(documents.reduce((sum, row) => sum + BigInt(row[field].replace(".", "")), 0n));
const months = Object.fromEntries([...new Set(documents.map((row) => row.month))].sort().map((month) => { const rows = documents.filter((row) => row.month === month); return [month, { documents: rows.length, gross: asMoney(rows.reduce((sum, row) => sum + BigInt(row.target_total.replace(".", "")), 0n)) }]; }));
const payload = { schema_version: 1, target_database: targetDb, source_archive_sha256: archiveSha, approved_policy: "general_paid_vendor_bills_native_accounting_monthly_atomic", run_prefix: "20260913-noorix-arz-general-purchases-qa", company: { source_system: "noorix", source_tenant_id: tenantId, source_company_id: sourceCompanyId, target_company_id: targetCompanyId }, allowlist: { purchase_journal_id: purchaseJournal.id, purchase_journal_code: purchaseJournal.code, purchase_tax_id: purchaseTaxId, vat_input_account_code: "104041", forbidden_journal_codes: ["PSBNK", "PSCSH"] }, category_decisions: [...decisions.values()].sort((a, b) => a.source_mapping_key.localeCompare(b.source_mapping_key)), documents, report: { source_documents: documents.length, target_net: total("target_net"), target_tax: total("target_tax"), target_gross: total("target_total"), months } };
await fs.mkdir(outputDir, { recursive: true });
await fs.writeFile(outputPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
await fs.writeFile(exclusionsPath, `${JSON.stringify({ source_documents: sourceRows.length, included_documents: documents.length, excluded_documents: excluded.length, excluded_uncategorized_documents: excludedUncategorized.length, exclusions: excluded }, null, 2)}\n`, "utf8");
console.log(JSON.stringify({ outputPath, payload_sha256: crypto.createHash("sha256").update(await fs.readFile(outputPath)).digest("hex"), report: payload.report, exclusions: { total: excluded.length, uncategorized: excludedUncategorized.length } }, null, 2));
