/** Build the frozen QA-only Karak paid-purchase payload from read-only databases. */
import crypto from "node:crypto";
import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";

const sourceDb = "noorix_source_inspection_archive159_20260913";
const targetDb = "baseer_noorix_data_migration_qa_20260912";
const dbContainer = "baseer_odoo_dev-db-1";
const outputDir = ".local-backups/noorix-migration/runs/20260913-karak-purchase-history-qa-1";
const outputPath = path.join(outputDir, "karak-purchase-payload.json");
const archiveSha = "024606ADD82DCD78DC1835828A12D7B22C56E34924FF998ABF752134160E79E2";
const tenantId = "default-tenant-noorix-2024";
const sourceCompanyId = "cmnvui7x70001etuf8p6xz3d0";
const targetCompanyId = 4;
const purchaseJournal = { id: 58, code: "BILL", type: "purchase" };
const taxId = 139;
const vaultPolicy = new Map([
  ["bank", { journal_id: 62, journal_code: "BNK1", journal_type: "bank", liquidity_account_code: "101001" }],
  ["cash", { journal_id: 67, journal_code: "CSH1", journal_type: "cash", liquidity_account_code: "105001" }],
]);

const policies = new Map([
  ["كهرباء", { code: "BASEER-SVC-ELECTRICITY", name: "Electricity", account: "400018", decision: "reuse_existing_service", tax: "tax_when_source_positive" }],
  ["اتصالات", { code: "BASEER-SVC-TELECOM", name: "Telecommunications", account: "400020", decision: "reuse_existing_service", tax: "tax_when_source_positive" }],
  ["مواد غذائية أخرى", { code: "NOORIX-HIST-KARAK-OTHER-FOOD", name: "تاريخي - مواد غذائية أخرى", account: "400047", decision: "create_historical_service", tax: "tax_when_source_positive" }],
  ["خضار وفواكه", { code: "NOORIX-HIST-KARAK-FRUIT-VEG", name: "تاريخي - خضار وفواكه", account: "400047", decision: "create_historical_service", tax: "tax_when_source_positive" }],
  ["غاز طبخ", { code: "NOORIX-HIST-KARAK-COOKING-GAS", name: "تاريخي - غاز طبخ", account: "400019", decision: "create_historical_service", tax: "no_tax" }],
  ["بلاستيكات", { code: "NOORIX-HIST-KARAK-PLASTICS", name: "تاريخي - بلاستيكات", account: "400047", decision: "create_historical_service", tax: "tax_when_source_positive" }],
  ["علب وأكواب", { code: "NOORIX-HIST-KARAK-CUPS", name: "تاريخي - علب وأكواب", account: "400047", decision: "create_historical_service", tax: "tax_when_source_positive" }],
  ["مستلزمات تشغيل مطبخ", { code: "NOORIX-HIST-KARAK-KITCHEN", name: "تاريخي - تشغيل مطبخ", account: "400047", decision: "create_historical_service", tax: "tax_when_source_positive" }],
  ["NO NAME", { code: "NOORIX-HIST-KARAK-SMALL-CASH", name: "تاريخي - مشتريات نقدية صغيرة", account: "400047", decision: "create_historical_service", tax: "no_tax" }],
  ["__UNCATEGORIZED__", { code: "NOORIX-HIST-KARAK-SMALL-CASH", name: "تاريخي - مشتريات نقدية صغيرة", account: "400047", decision: "create_historical_service", tax: "no_tax" }],
  ["صيانة وترميم", { code: "NOORIX-HIST-KARAK-REPAIRS", name: "تاريخي - صيانة وترميم", account: "400042", decision: "create_historical_service", tax: "tax_when_source_positive" }],
  ["التأمينات الاجتماعية (GOSI)", { code: "NOORIX-HIST-KARAK-GOSI", name: "تاريخي - التأمينات الاجتماعية", account: "400015", decision: "create_historical_service", tax: "no_tax" }],
  ["ضرائب ورسوم أخرى", { code: "NOORIX-HIST-KARAK-ZAKAT-FEES", name: "تاريخي - الزكاة والرسوم", account: "400072", decision: "create_historical_service", tax: "no_tax" }],
]);

function psql(database, sql) {
  if (database === "baseer_dev") throw new Error("Production database is forbidden");
  const output = execFileSync("docker", ["exec", dbContainer, "psql", "-U", "odoo", "-d", database, "-At", "-F", "\t", "-c", sql], { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
  return output.split(/\r?\n/).filter(Boolean).map((line) => line.split("\t"));
}

const sha = (value) => crypto.createHash("sha256").update(JSON.stringify(value)).digest("hex");

function fixed4(value) {
  const match = String(value).match(/^(\d+)(?:\.(\d+))?$/);
  if (!match) throw new Error(`Invalid non-negative source decimal: ${value}`);
  const fraction = (match[2] || "").padEnd(4, "0");
  if (fraction.length > 4 && [...fraction.slice(4)].some((digit) => digit !== "0")) throw new Error(`Source amount exceeds four decimals: ${value}`);
  return `${match[1]}.${fraction.slice(0, 4)}`;
}

function units4(value) {
  const [whole, fraction] = fixed4(value).split(".");
  return BigInt(whole) * 10000n + BigInt(fraction);
}

function roundHalfUp(numerator, denominator) {
  return (numerator * 2n + denominator) / (denominator * 2n);
}

function centsFromRaw(value) {
  return roundHalfUp(units4(value), 100n);
}

function money(cents) {
  return `${cents / 100n}.${String(cents % 100n).padStart(2, "0")}`;
}

function decimalDivision(numerator, denominator, places = 14) {
  const whole = numerator / denominator;
  let remainder = numerator % denominator;
  let fraction = "";
  for (let index = 0; index < places; index += 1) {
    remainder *= 10n;
    fraction += String(remainder / denominator);
    remainder %= denominator;
  }
  return `${whole}.${fraction}`;
}

const sourceRows = psql(sourceDb, `
SELECT i.id,i.tenant_id,i.company_id,i.kind,i.invoice_number,COALESCE(i.supplier_invoice_number,''),
       i.transaction_date::date::text,i.net_amount::text,i.tax_amount::text,i.total_amount::text,
       i.supplier_id,COALESCE(i.category_id,''),COALESCE(c.name_ar,''),
       a.id,a.vault_id,a.amount::text,v.type,v.name_ar,
       le.id,le.amount::text,COALESCE(asset.id,''),
       encode(convert_to(COALESCE(asset.name_ar,''),'UTF8'),'hex'),
       encode(convert_to(COALESCE(asset.name_en,''),'UTF8'),'hex'),
       COALESCE(asset.acquisition_cost::text,''),COALESCE(asset.warranty_end_date::text,''),
       i.created_at::text,i.updated_at::text,a.created_at::text,le.created_at::text
FROM invoices i
LEFT JOIN categories c ON c.id=i.category_id
JOIN invoice_vault_allocations a ON a.invoice_id=i.id
JOIN vaults v ON v.id=a.vault_id
JOIN ledger_entries le ON le.reference_type='invoice' AND le.reference_id=i.id
LEFT JOIN company_assets asset ON asset.invoice_id=i.id
WHERE i.company_id='${sourceCompanyId}' AND i.status='active'
  AND i.kind IN ('purchase','expense','fixed_expense')
  AND i.transaction_date >= '2026-01-01' AND i.transaction_date < '2027-01-01'
ORDER BY i.transaction_date,i.invoice_number,i.id;
`).map(([id, sourceTenantId, companyId, kind, invoiceNumber, supplierInvoiceNumber, businessDate,
  netRaw, taxRaw, totalRaw, supplierId, categoryId, categoryName, allocationId, vaultId,
  allocationRaw, vaultType, vaultName, ledgerId, ledgerRaw, assetId, assetNameArHex,
  assetNameEnHex, assetCostRaw, assetWarrantyEnd, createdAt, updatedAt, allocationCreatedAt,
  ledgerCreatedAt]) => ({
  id, sourceTenantId, companyId, kind, invoiceNumber, supplierInvoiceNumber, businessDate,
  netRaw: fixed4(netRaw), taxRaw: fixed4(taxRaw), totalRaw: fixed4(totalRaw), supplierId,
  categoryId: categoryId || null, categoryName: categoryName || "__UNCATEGORIZED__",
  allocationId, vaultId, allocationRaw: fixed4(allocationRaw), vaultType, vaultName,
  ledgerId, ledgerRaw: fixed4(ledgerRaw), assetId: assetId || null,
  assetNameAr: Buffer.from(assetNameArHex, "hex").toString("utf8"),
  assetNameEn: Buffer.from(assetNameEnHex, "hex").toString("utf8"),
  assetCostRaw: assetCostRaw ? fixed4(assetCostRaw) : null, assetWarrantyEnd: assetWarrantyEnd || null,
  createdAt, updatedAt, allocationCreatedAt, ledgerCreatedAt,
}));

if (sourceRows.length !== 306) throw new Error(`Expected 306 Karak documents, found ${sourceRows.length}`);
if (sourceRows.some((row) => row.sourceTenantId !== tenantId || row.companyId !== sourceCompanyId)) throw new Error("Source tenant/company boundary differs");
for (const row of sourceRows) {
  if (units4(row.netRaw) + units4(row.taxRaw) !== units4(row.totalRaw)) throw new Error(`Source net/tax mismatch: ${row.invoiceNumber}`);
  if (units4(row.allocationRaw) !== units4(row.totalRaw) || units4(row.ledgerRaw) !== units4(row.totalRaw)) throw new Error(`Ledger/allocation mismatch: ${row.invoiceNumber}`);
  if (!vaultPolicy.has(row.vaultType)) throw new Error(`Unsupported vault ${row.vaultType}: ${row.invoiceNumber}`);
}

const targetCompany = psql(targetDb, `
SELECT c.id,c.active,rc.name,co.code
FROM res_company c
JOIN res_currency rc ON rc.id=c.currency_id
JOIN res_partner p ON p.id=c.partner_id
JOIN res_country co ON co.id=p.country_id
WHERE c.id=${targetCompanyId};
`);
if (targetCompany.length !== 1 || targetCompany[0][1] !== "t" || targetCompany[0][2] !== "SAR" || targetCompany[0][3] !== "SA") {
  throw new Error("Karak QA company is not the approved active Saudi/SAR target");
}

const companyMapRows = psql(targetDb, `
SELECT company_id,source_tenant_id,source_archive_sha256,decision
FROM baseer_noorix_company_map
WHERE source_system='noorix' AND source_company_id='${sourceCompanyId}';
`);
if (companyMapRows.length !== 1 || Number(companyMapRows[0][0]) !== targetCompanyId || companyMapRows[0][1] !== tenantId || companyMapRows[0][2] !== archiveSha || companyMapRows[0][3] !== "create_historical_company") {
  throw new Error("Approved Karak company provenance differs");
}

const supplierRows = psql(targetDb, `
SELECT m.source_supplier_id,m.partner_id,m.source_tenant_id,m.source_archive_sha256,
       COALESCE(p.company_id::text,''),p.supplier_rank
FROM baseer_noorix_supplier_map m JOIN res_partner p ON p.id=m.partner_id
WHERE source_company_id='${sourceCompanyId}' ORDER BY source_supplier_id;
`);
const partnerBySupplier = new Map(supplierRows.map(([sourceId, partnerId, sourceTenantId, sourceArchiveSha, companyId, supplierRank]) => {
  if (sourceTenantId !== tenantId || sourceArchiveSha !== archiveSha || companyId || Number(supplierRank) <= 0) throw new Error(`Supplier provenance/target differs: ${sourceId}`);
  return [sourceId, Number(partnerId)];
}));
if (new Set(sourceRows.map((row) => row.supplierId)).size !== 23 || sourceRows.some((row) => !partnerBySupplier.has(row.supplierId))) throw new Error("Finite supplier map is incomplete");

const accountCodes = [...new Set([
  ...[...policies.values()].map((policy) => policy.account),
  "400050", "106003", "104041", "101001", "105001",
])];
const accountRows = psql(targetDb, `
SELECT id,code_store->>'${targetCompanyId}',account_type,active
FROM account_account WHERE code_store->>'${targetCompanyId}' IN (${accountCodes.map((code) => `'${code}'`).join(",")});
`);
const accountByCode = new Map(accountRows.map(([id, code, type, active]) => [code, { id: Number(id), type, active: active === "t" }]));
if (accountRows.length !== accountCodes.length || accountByCode.size !== accountCodes.length || [...accountByCode.values()].some((account) => !account.active)) throw new Error("Finite account allowlist differs");

const journalRows = psql(targetDb, `SELECT id,code,type,company_id,default_account_id FROM account_journal WHERE id IN (58,62,67,69,70) ORDER BY id;`);
const journalById = new Map(journalRows.map(([id, code, type, companyId, accountId]) => [Number(id), { code, type, companyId: Number(companyId), accountId: Number(accountId) }]));
for (const expected of [purchaseJournal, ...vaultPolicy.values().map((row) => ({ id: row.journal_id, code: row.journal_code }))]) {
  const actual = journalById.get(expected.id);
  if (!actual || actual.code !== expected.code || actual.companyId !== targetCompanyId) throw new Error(`Journal allowlist mismatch: ${expected.id}`);
}
if (journalById.get(58)?.type !== "purchase") throw new Error("BILL/58 is not the approved purchase journal");
for (const policy of vaultPolicy.values()) {
  const journal = journalById.get(policy.journal_id);
  if (!journal || journal.type !== policy.journal_type || journal.accountId !== accountByCode.get(policy.liquidity_account_code).id) {
    throw new Error(`Payment journal/liquidity account mismatch: ${policy.journal_id}`);
  }
}
if (journalById.get(69)?.code !== "PSBNK" || journalById.get(70)?.code !== "PSCSH") throw new Error("Forbidden POS journal identity differs");

const taxRows = psql(targetDb, `SELECT id,amount::text,type_tax_use,active,COALESCE(price_include_override::text,'') FROM account_tax WHERE id=${taxId};`);
if (taxRows.length !== 1 || taxRows[0][1] !== "15.0000" || taxRows[0][2] !== "purchase" || taxRows[0][3] !== "t" || taxRows[0][4] === "true") throw new Error("Purchase tax 139 differs");

const productRows = psql(targetDb, `
SELECT pp.id,pt.default_code,pt.type,pt.purchase_ok,pt.sale_ok,pt.company_id,pt.active,pp.active
FROM product_product pp JOIN product_template pt ON pt.id=pp.product_tmpl_id
WHERE pt.default_code IN ('BASEER-SVC-ELECTRICITY','BASEER-SVC-TELECOM') AND pt.company_id=${targetCompanyId};
`);
const existingProductByCode = new Map(productRows.map(([id, code, type, purchaseOk, saleOk, companyId, templateActive, variantActive]) => [code, { id: Number(id), type, purchaseOk: purchaseOk === "t", saleOk: saleOk === "t", companyId: Number(companyId), active: templateActive === "t" && variantActive === "t" }]));
if (["BASEER-SVC-ELECTRICITY", "BASEER-SVC-TELECOM"].some((code) => {
  const product = existingProductByCode.get(code);
  return !product || !product.active || product.type !== "service" || !product.purchaseOk || product.saleOk || product.companyId !== targetCompanyId;
})) throw new Error("Existing service-product allowlist differs");
if (productRows.length !== 2 || existingProductByCode.get("BASEER-SVC-ELECTRICITY").id !== 1044 || existingProductByCode.get("BASEER-SVC-TELECOM").id !== 1046) throw new Error("Existing service-product IDs differ");

function policyFor(row) {
  if (row.invoiceNumber === "EXP-20260323-001") return { code: "NOORIX-HIST-KARAK-ELECTRONICS", name: "تاريخي - أجهزة وإلكترونيات", account: "400050", decision: "document_expense_override", tax: "tax_when_source_positive", mappingKey: `document:${row.id}` };
  if (row.invoiceNumber === "EXP-20260323-002") return { code: "NOORIX-HIST-KARAK-CASHIER-COMPUTER", name: "تاريخي - كمبيوتر الكاشير", account: "106003", decision: "document_asset_override", tax: "tax_when_source_positive", mappingKey: `document:${row.id}` };
  const policy = policies.get(row.categoryName);
  if (!policy) throw new Error(`Category outside finite map: ${row.categoryName}`);
  return { ...policy, mappingKey: row.categoryId ? `category:${row.categoryId}` : "uncategorized" };
}

const categoryDecisions = new Map();
const documents = sourceRows.map((row) => {
  const policy = policyFor(row);
  const taxable = units4(row.taxRaw) > 0n;
  if ((policy.tax === "no_tax") === taxable) throw new Error(`Tax policy mismatch: ${row.invoiceNumber}`);
  const grossCents = centsFromRaw(row.totalRaw);
  const netCents = taxable ? roundHalfUp(grossCents * 100n, 115n) : grossCents;
  const targetTaxCents = grossCents - netCents;
  const priceUnit = taxable ? decimalDivision(grossCents, 115n) : money(grossCents);
  const existingProduct = existingProductByCode.get(policy.code);
  const targetAccount = accountByCode.get(policy.account);
  if (!targetAccount) throw new Error(`Approved target account is missing: ${policy.account}`);
  const categorySnapshot = { source_category_id: row.categoryId, source_category_name: row.categoryName, mapping_key: policy.mappingKey, product_code: policy.code, product_name: policy.name, account_code: policy.account, tax_policy: policy.tax, decision: policy.decision };
  const currentDecision = categoryDecisions.get(policy.mappingKey);
  if (currentDecision && currentDecision.source_row_sha256 !== sha(categorySnapshot)) throw new Error(`Conflicting category decision: ${policy.mappingKey}`);
  categoryDecisions.set(policy.mappingKey, {
    source_system: "noorix", source_tenant_id: tenantId, source_company_id: sourceCompanyId,
    source_mapping_key: policy.mappingKey, source_category_id: row.categoryId,
    source_category_name: row.categoryName === "__UNCATEGORIZED__" ? "" : row.categoryName,
    source_row_sha256: sha(categorySnapshot), source_archive_sha256: archiveSha,
    canonical_key: `karak-purchase:${policy.code}`, decision: policy.decision, tax_policy: policy.tax,
    target_product_id: existingProduct?.id || null, target_product_code: policy.code,
    target_product_name: policy.name, target_account_id: targetAccount.id,
    target_account_code: policy.account,
  });
  const vault = vaultPolicy.get(row.vaultType);
  const sourceSnapshot = { ...row, category_policy: categorySnapshot };
  return {
    source_system: "noorix", source_tenant_id: tenantId, source_company_id: sourceCompanyId,
    source_invoice_id: row.id, source_ledger_id: row.ledgerId, source_allocation_id: row.allocationId,
    source_vault_id: row.vaultId, source_supplier_id: row.supplierId, source_category_id: row.categoryId,
    source_invoice_number: row.invoiceNumber, source_supplier_invoice_number: row.supplierInvoiceNumber,
    source_document_kind: row.kind, business_date: row.businessDate, month: row.businessDate.slice(0, 7),
    source_net_raw: row.netRaw, source_tax_raw: row.taxRaw, source_total_raw: row.totalRaw,
    source_row_sha256: sha(sourceSnapshot), source_archive_sha256: archiveSha,
    canonical_key: `purchase:${sourceCompanyId}:${row.id}`,
    source_asset_id: row.assetId, source_asset_row_sha256: row.assetId ? sha({ id: row.assetId, name_ar: row.assetNameAr, name_en: row.assetNameEn, cost: row.assetCostRaw, warranty_end: row.assetWarrantyEnd }) : null,
    decision: row.invoiceNumber === "EXP-20260323-002" ? "capitalize_cashier_computer" : "create_paid_vendor_bill",
    category_mapping_key: policy.mappingKey, target_company_id: targetCompanyId,
    target_partner_id: partnerBySupplier.get(row.supplierId), target_tax_id: taxable ? taxId : null,
    target_purchase_journal_id: purchaseJournal.id, target_payment_journal_id: vault.journal_id,
    target_account_id: targetAccount.id, target_account_code: policy.account,
    target_product_id: existingProduct?.id || null, target_product_code: policy.code,
    target_product_name: policy.name, price_unit: priceUnit,
    target_net: money(netCents), target_tax: money(targetTaxCents), target_total: money(grossCents),
  };
});

const monthExpected = {
  "2026-03": { documents: 3, gross: "2951.03" },
  "2026-04": { documents: 144, gross: "25771.75" },
  "2026-05": { documents: 104, gross: "21213.50" },
  "2026-06": { documents: 53, gross: "9851.44" },
  "2026-07": { documents: 2, gross: "3324.58" },
};
const reportMonths = {};
for (const [month, expected] of Object.entries(monthExpected)) {
  const rows = documents.filter((row) => row.month === month);
  const gross = rows.reduce((sum, row) => sum + BigInt(row.target_total.replace(".", "")), 0n);
  reportMonths[month] = { documents: rows.length, gross: money(gross) };
  if (JSON.stringify(reportMonths[month]) !== JSON.stringify(expected)) throw new Error(`Monthly reconciliation differs: ${month}`);
}
const taxable = documents.filter((row) => row.target_tax_id === taxId);
if (taxable.length !== 228 || documents.filter((row) => !row.target_tax_id).length !== 78) throw new Error("Tax partition differs");
const total = (field) => money(documents.reduce((sum, row) => sum + BigInt(row[field].replace(".", "")), 0n));
const totals = { net: total("target_net"), tax: total("target_tax"), gross: total("target_total") };
if (JSON.stringify(totals) !== JSON.stringify({ net: "56425.71", tax: "6686.59", gross: "63112.30" })) throw new Error(`Target totals differ: ${JSON.stringify(totals)}`);
if (categoryDecisions.size !== 15) throw new Error(`Expected 15 finite category/document decisions, found ${categoryDecisions.size}`);

const payload = {
  target_database: targetDb, source_archive_sha256: archiveSha,
  approved_policy: "karak_306_paid_vendor_bills_native_accounting_monthly_atomic",
  report: { source_documents: 306, taxable_documents: 228, no_tax_documents: 78, category_decisions: 15, source_net: "56425.8068", source_tax: "6686.4972", source_gross: "63112.3040", target_net: totals.net, target_tax: totals.tax, target_gross: totals.gross, months: reportMonths },
  allowlist: { target_company_id: targetCompanyId, purchase_journal: purchaseJournal, payment_journals: Object.fromEntries(vaultPolicy), forbidden_journal_ids: [69, 70], purchase_tax_id: taxId, vat_input_account_id: accountByCode.get("104041").id },
  category_decisions: [...categoryDecisions.values()].sort((a, b) => a.source_mapping_key.localeCompare(b.source_mapping_key)),
  documents,
};

await fs.mkdir(outputDir, { recursive: true });
await fs.writeFile(outputPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
console.log(JSON.stringify({ outputPath, payloadSha256: crypto.createHash("sha256").update(await fs.readFile(outputPath)).digest("hex"), report: payload.report }, null, 2));
