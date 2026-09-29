/** Read-only builder for fully-evidenced Al Moallem paid historical bills. */
import crypto from "node:crypto";
import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";

const sourceDb = "noorix_source_inspection_archive159_20260913";
const targetDb = "baseer_noorix_data_migration_qa_20260912";
const container = "baseer_odoo_dev-db-1";
const tenant = "default-tenant-noorix-2024";
const companyId = "cmnaivif80001wavxxfgriptm";
const targetCompanyId = 2;
const archive = "024606ADD82DCD78DC1835828A12D7B22C56E34924FF998ABF752134160E79E2";
const dir = ".local-backups/noorix-migration/runs/20260913-almoallem-general-purchases-qa-1";
const outputPath = path.join(dir, "almoallem-general-purchase-payload.json");
const exclusionsPath = path.join(dir, "almoallem-general-purchase-exclusions.json");

// Only these categories have an established operating-expense policy.  Every
// other category is reported in the exclusion artifact, never inferred.
const approved = new Map([
  ["purchase:بضاعة تموينية", [313, "400001", "expense_direct_cost", "بضاعة تموينية"]],
  ["purchase:بلاستيكات", [313, "400001", "expense_direct_cost", "بلاستيكات"]],
  ["purchase:خامات", [313, "400001", "expense_direct_cost", "خامات"]],
  ["purchase:خضار وفواكه", [313, "400001", "expense_direct_cost", "خضار وفواكه"]],
  ["purchase:دجاج", [313, "400001", "expense_direct_cost", "دجاج"]],
  ["purchase:شحم", [313, "400001", "expense_direct_cost", "شحم"]],
  ["purchase:غاز طبخ", [313, "400001", "expense_direct_cost", "غاز طبخ"]],
  ["purchase:غازيات", [313, "400001", "expense_direct_cost", "غازيات"]],
  ["purchase:فحم", [313, "400001", "expense_direct_cost", "فحم"]],
  ["purchase:لحوم", [313, "400001", "expense_direct_cost", "لحوم"]],
  ["purchase:مواد غذائية أخرى", [313, "400001", "expense_direct_cost", "مواد غذائية أخرى"]],
  ["expense:اتصالات", [332, "400020", "expense", "اتصالات"]],
  ["expense:صيانة آلات", [354, "400042", "expense", "صيانة آلات"]],
  ["expense:منصة قوى", [596, "400093", "expense", "منصة قوى / رسوم حكومية"]],
  ["expense:وقود ومواصلات", [360, "400048", "expense", "وقود ومواصلات"]],
  ["fixed_expense:إيجارات", [328, "400016", "expense", "إيجارات"]],
  ["fixed_expense:اتصالات", [332, "400020", "expense", "اتصالات"]],
  ["fixed_expense:التأمينات الاجتماعية (GOSI)", [327, "400015", "expense", "التأمينات الاجتماعية (GOSI)"]],
  ["fixed_expense:ضرائب ورسوم أخرى", [382, "400072", "expense", "ضرائب ورسوم أخرى"]],
  ["fixed_expense:كهرباء", [330, "400018", "expense", "كهرباء"]],
]);

function q(db, sql) {
  if (db === "baseer_dev") throw new Error("production database is forbidden");
  const result = execFileSync("docker", ["exec", container, "psql", "-U", "odoo", "-d", db, "-At", "-F", "\t", "-c", sql], { encoding: "utf8", maxBuffer: 128 * 1024 * 1024 }).trim();
  return result ? result.split(/\r?\n/).map((line) => line.split("\t")) : [];
}
const sha = (value) => crypto.createHash("sha256").update(JSON.stringify(value)).digest("hex");
function fixed4(value) { const m = String(value).match(/^(\d+)(?:\.(\d+))?$/); if (!m) throw new Error(`invalid source amount ${value}`); const d = (m[2] || "").padEnd(4, "0"); if (d.length > 4 && /[1-9]/.test(d.slice(4))) throw new Error(`source precision exceeds four decimals: ${value}`); return `${m[1]}.${d.slice(0, 4)}`; }
const units4 = (value) => { const [whole, fraction] = fixed4(value).split("."); return BigInt(whole) * 10000n + BigInt(fraction); };
const roundUnits = (numerator, denominator) => (numerator * 2n + denominator) / (denominator * 2n);
const cents = (value) => roundUnits(units4(value), 100n);
const money = (value) => `${value / 100n}.${String(value % 100n).padStart(2, "0")}`;
function netPrice(grossCents) { const whole = grossCents / 115n; let remainder = grossCents % 115n; let fraction = ""; for (let index = 0; index < 14; index += 1) { remainder *= 10n; fraction += String(remainder / 115n); remainder %= 115n; } return `${whole}.${fraction}`; }
const group = (items, key) => items.reduce((result, item) => { const bucket = key(item); (result.get(bucket) || result.set(bucket, []).get(bucket)).push(item); return result; }, new Map());

const invoices = q(sourceDb, `
SELECT i.id,i.tenant_id,i.company_id,i.kind,i.invoice_number,COALESCE(i.supplier_invoice_number,''),
       i.transaction_date::date::text,i.net_amount::text,i.tax_amount::text,i.total_amount::text,
       COALESCE(i.supplier_id,''),COALESCE(i.category_id,''),COALESCE(c.name_ar,''),COALESCE(i.vault_id,''),
       COALESCE(i.employee_id,''),encode(convert_to(COALESCE(i.notes,''),'UTF8'),'hex'),i.status,
       i.created_at::text,i.updated_at::text
FROM invoices i LEFT JOIN categories c ON c.id=i.category_id
WHERE i.company_id='${companyId}' AND i.kind IN ('purchase','expense','fixed_expense')
ORDER BY i.transaction_date,i.invoice_number,i.id;
`).map(([id, sourceTenant, sourceCompany, kind, number, supplierNumber, date, net, tax, total, supplier, categoryId, categoryName, vault, employee, notes, status, created, updated]) => ({
  id, source_tenant_id: sourceTenant, source_company_id: sourceCompany, kind, number, supplier_number: supplierNumber,
  date, net: fixed4(net), tax: fixed4(tax), total: fixed4(total), supplier, category_id: categoryId || null,
  category_name: categoryName || "__UNCATEGORIZED__", vault: vault || null, employee: employee || null,
  notes: Buffer.from(notes, "hex").toString("utf8"), status, created, updated,
}));
if (invoices.length !== 1577) throw new Error(`Al Moallem source count differs: ${invoices.length}`);
if (invoices.some((row) => row.source_tenant_id !== tenant || row.source_company_id !== companyId)) throw new Error("source invoice company/tenant differs");

const scopedInvoiceSql = `SELECT id FROM invoices WHERE company_id='${companyId}' AND kind IN ('purchase','expense','fixed_expense')`;
const ledgerByInvoice = group(q(sourceDb, `SELECT id,reference_id,amount::text,debit_account_id,credit_account_id,transaction_date::date::text,COALESCE(vault_id,''),COALESCE(employee_id,''),status,COALESCE(reporting_category_name_ar,''),created_at::text FROM ledger_entries WHERE reference_type='invoice' AND reference_id IN (${scopedInvoiceSql}) ORDER BY reference_id,id;`).map(([id, invoiceId, amount, debit, credit, date, vault, employee, status, category, created]) => ({ id, invoice_id: invoiceId, amount: fixed4(amount), debit, credit, date, vault: vault || null, employee: employee || null, status, category, created })), (row) => row.invoice_id);
const allocationByInvoice = group(q(sourceDb, `SELECT id,invoice_id,vault_id,amount::text,created_at::text FROM invoice_vault_allocations WHERE invoice_id IN (${scopedInvoiceSql}) ORDER BY invoice_id,id;`).map(([id, invoiceId, vault, amount, created]) => ({ id, invoice_id: invoiceId, vault, amount: fixed4(amount), created })), (row) => row.invoice_id);
const assetByInvoice = group(q(sourceDb, `SELECT id,invoice_id,name_ar,acquisition_cost::text,purchase_date::text,created_at::text FROM company_assets WHERE company_id='${companyId}' AND invoice_id IN (${scopedInvoiceSql}) ORDER BY invoice_id,id;`).map(([id, invoiceId, name, cost, date, created]) => ({ id, invoice_id: invoiceId, name, cost: fixed4(cost), date, created })), (row) => row.invoice_id);
const sourceVaults = new Map(q(sourceDb, `SELECT id,name_ar,type,is_active::text,is_archived::text FROM vaults WHERE company_id='${companyId}';`).map(([id, name, type, active, archived]) => [id, { id, name, type, active: ["t", "true"].includes(active), archived: ["t", "true"].includes(archived) }]));

const excluded = [], candidates = [];
for (const row of invoices) {
  const base = { source_invoice_id: row.id, invoice_number: row.number, kind: row.kind, category: row.category_name, business_date: row.date, gross: row.total };
  if (row.status !== "active") { excluded.push({ ...base, reason: "source_status_not_active" }); continue; }
  const policy = approved.get(`${row.kind}:${row.category_name}`);
  if (!policy) {
    const reason = row.category_name === "__UNCATEGORIZED__" ? "missing_invoice_category_no_safe_operational_classification" :
      row.category_name === "رواتب وأجور" ? "salary_or_overtime_requires_separate_historical_evidence" :
      ["أجهزة وإلكترونيات", "معدات مكتبية"].includes(row.category_name) ? "asset_category_without_source_asset_evidence" : "outside_approved_operational_scope";
    excluded.push({ ...base, reason }); continue;
  }
  if (row.employee) { excluded.push({ ...base, reason: "employee_linked_document_outside_purchase_scope" }); continue; }
  if ((assetByInvoice.get(row.id) || []).length) { excluded.push({ ...base, reason: "source_asset_present_requires_asset_scope" }); continue; }
  const ledgers = ledgerByInvoice.get(row.id) || [], allocations = allocationByInvoice.get(row.id) || [];
  const vault = row.vault && sourceVaults.get(row.vault);
  if (ledgers.length !== 1 || ledgers[0].status !== "active" || ledgers[0].amount !== row.total || ledgers[0].date !== row.date || ledgers[0].vault !== row.vault || ledgers[0].employee) { excluded.push({ ...base, reason: "incomplete_or_nonunique_source_ledger_evidence" }); continue; }
  if (allocations.length !== 1 || allocations[0].amount !== row.total || allocations[0].vault !== row.vault || !vault || !vault.active || vault.archived) { excluded.push({ ...base, reason: "incomplete_or_nonunique_source_vault_allocation" }); continue; }
  candidates.push({ ...row, ledger: ledgers[0], allocation: allocations[0], source_vault: vault, policy });
}

const company = q(targetDb, `SELECT company_id::text,source_archive_sha256,decision FROM baseer_noorix_company_map WHERE source_system='noorix' AND source_tenant_id='${tenant}' AND source_company_id='${companyId}';`);
if (company.length !== 1 || Number(company[0][0]) !== targetCompanyId || company[0][1] !== archive || company[0][2] !== "reuse_existing_company") throw new Error("target company provenance differs");
const accountExpectations = new Map([...approved.values()].map(([id, code, type]) => [id, [code, type]]));
const accountRows = q(targetDb, `SELECT id,code_store->>'2',account_type,active FROM account_account WHERE id IN (${[...accountExpectations.keys()].join(",")}) ORDER BY id;`);
if (accountRows.length !== accountExpectations.size) throw new Error("target account allowlist incomplete");
for (const [rawId, code, type, active] of accountRows) { const expected = accountExpectations.get(Number(rawId)); if (!expected || code !== expected[0] || type !== expected[1] || active !== "t") throw new Error(`target account differs: ${rawId}`); }
const sourceSupplierIds = [...new Set(candidates.map((row) => row.supplier))].sort();
const suppliers = new Map(q(targetDb, `SELECT m.source_supplier_id,m.partner_id::text,m.source_archive_sha256,COALESCE(p.company_id::text,''),p.supplier_rank::text FROM baseer_noorix_supplier_map m JOIN res_partner p ON p.id=m.partner_id WHERE m.source_system='noorix' AND m.source_tenant_id='${tenant}' AND m.source_company_id='${companyId}' AND m.source_supplier_id IN (${sourceSupplierIds.map((id) => `'${id}'`).join(",")});`).map(([id, partner, sourceArchive, partnerCompany, rank]) => { if (sourceArchive !== archive || partnerCompany || Number(rank) < 1) throw new Error(`supplier map differs: ${id}`); return [id, Number(partner)]; }));
const targetVaults = new Map(q(targetDb, `SELECT m.source_vault_id,m.journal_id::text,m.source_archive_sha256,m.source_vault_type,m.source_vault_name,m.decision,j.code,j.type,j.company_id::text FROM baseer_noorix_liquidity_vault_map m JOIN account_journal j ON j.id=m.journal_id WHERE m.source_system='noorix' AND m.source_tenant_id='${tenant}' AND m.source_company_id='${companyId}' AND m.company_id=${targetCompanyId};`).map(([vaultId, journal, sourceArchive, sourceType, sourceName, decision, code, journalType, targetCompany]) => {
  const nativeReuse = decision === "reuse_existing_liquidity" && sourceType === journalType;
  const sourceProvenAppWallet = decision === "create_historical_wallet" && sourceType === "app" && journalType === "bank";
  if (sourceArchive !== archive || Number(targetCompany) !== targetCompanyId || ["PSBNK", "PSCSH"].includes(code) || (!nativeReuse && !sourceProvenAppWallet)) throw new Error(`vault map differs: ${vaultId}`);
  return [vaultId, Number(journal)];
}));
const viable = [];
for (const row of candidates) {
  const base = { source_invoice_id: row.id, invoice_number: row.number, kind: row.kind, category: row.category_name, business_date: row.date, gross: row.total };
  if (!suppliers.has(row.supplier)) { excluded.push({ ...base, reason: "target_supplier_map_missing" }); continue; }
  if (!targetVaults.has(row.vault)) { excluded.push({ ...base, reason: "target_vault_map_missing" }); continue; }
  viable.push(row);
}
if (!viable.length) throw new Error("no fully-evidenced Al Moallem operational documents remain");

const decisions = new Map(), documents = [];
for (const row of viable) {
  const [accountId, accountCode, accountType, label] = row.policy;
  const taxable = units4(row.tax) > 0n;
  const key = `category:${row.category_id}:${taxable ? "vat15" : "no-tax"}`;
  const categorySnapshot = { source_category_id: row.category_id, source_category_name: row.category_name, source_kind: row.kind, mapping_key: key, account_code: accountCode, account_type: accountType, vat_positive: taxable };
  const decision = {
    source_system: "noorix", source_tenant_id: tenant, source_company_id: companyId, source_mapping_key: key,
    source_category_id: row.category_id, source_category_name: row.category_name, source_row_sha256: sha(categorySnapshot), source_archive_sha256: archive,
    canonical_key: `almoallem:${accountCode}:${row.category_id}:${taxable ? "vat15" : "no-tax"}`,
    decision: "create_historical_service", target_product_id: null,
    target_product_code: `NOORIX-HIST-ALM-${accountCode}-${sha(key).slice(0, 10).toUpperCase()}`,
    target_product_name: `تاريخي المعلم - ${label}${taxable ? " (ضريبة 15%)" : " (بدون ضريبة)"}`,
    target_account_id: accountId, target_account_code: accountCode, target_account_type: accountType,
    tax_policy: taxable ? "owner_declared_inclusive_15" : "no_tax",
  };
  decisions.set(key, decision);
  const gross = cents(row.total), net = taxable ? roundUnits(gross * 100n, 115n) : gross, tax = gross - net;
  documents.push({
    source_system: "noorix", source_tenant_id: tenant, source_company_id: companyId,
    source_invoice_id: row.id, source_ledger_id: row.ledger.id, source_allocation_id: row.allocation.id,
    source_vault_id: row.vault, source_supplier_id: row.supplier, source_category_id: row.category_id,
    source_invoice_number: row.number, source_supplier_invoice_number: row.supplier_number,
    source_document_kind: row.kind, business_date: row.date, month: row.date.slice(0, 7),
    source_net_raw: row.net, source_tax_raw: row.tax, source_total_raw: row.total,
    source_row_sha256: sha({ invoice: row, ledger: row.ledger, allocation: row.allocation, category_policy: categorySnapshot }),
    source_archive_sha256: archive, canonical_key: `purchase:${companyId}:${row.id}`,
    source_asset_id: null, source_asset_row_sha256: null, decision: "create_paid_vendor_bill", category_mapping_key: key,
    target_product_id: null, target_product_code: decision.target_product_code, target_product_name: decision.target_product_name,
    target_account_id: accountId, target_account_code: accountCode, target_partner_id: suppliers.get(row.supplier),
    target_payment_journal_id: targetVaults.get(row.vault), target_tax_id: taxable ? 61 : null,
    price_unit: taxable ? netPrice(gross) : money(gross), target_net: money(net), target_tax: money(tax), target_total: money(gross),
  });
}
documents.sort((left, right) => left.business_date.localeCompare(right.business_date) || left.source_invoice_number.localeCompare(right.source_invoice_number) || left.source_invoice_id.localeCompare(right.source_invoice_id));
const sum = (items, field) => items.reduce((total, item) => total + BigInt(item[field].replace(".", "")), 0n);
const months = Object.fromEntries([...new Set(documents.map((row) => row.month))].sort().map((month) => { const rows = documents.filter((row) => row.month === month); return [month, { documents: rows.length, gross: money(sum(rows, "target_total")) }]; }));
const payload = { schema_version: 1, target_database: targetDb, source_archive_sha256: archive, approved_policy: "general_paid_vendor_bills_native_accounting_monthly_atomic", run_prefix: "20260913-noorix-almoallem-general-purchases-qa", company: { source_system: "noorix", source_tenant_id: tenant, source_company_id: companyId, target_company_id: targetCompanyId }, allowlist: { purchase_journal_id: 19, purchase_journal_code: "BILL", purchase_tax_id: 61, vat_input_account_code: "104041", forbidden_journal_codes: ["PSBNK", "PSCSH"] }, category_decisions: [...decisions.values()].sort((left, right) => left.source_mapping_key.localeCompare(right.source_mapping_key)), documents, report: { source_documents: documents.length, target_net: money(sum(documents, "target_net")), target_tax: money(sum(documents, "target_tax")), target_gross: money(sum(documents, "target_total")), months } };
const exclusionTotals = Object.fromEntries(
  [...group(excluded, (row) => row.reason).entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([reason, rows]) => [reason, { documents: rows.length, gross: money(sum(rows.map((row) => ({ value: row.gross.slice(0, -2) })), "value")) }]),
);
const exclusions = { source_documents: invoices.length, included_documents: documents.length, included_gross: payload.report.target_gross, excluded_documents: excluded.length, excluded_gross: money(sum(excluded.map((row) => ({ value: row.gross.slice(0, -2) })), "value")), exclusions: excluded, totals_by_reason: exclusionTotals };
await fs.mkdir(dir, { recursive: true });
await fs.writeFile(outputPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
await fs.writeFile(exclusionsPath, `${JSON.stringify(exclusions, null, 2)}\n`, "utf8");
console.log(JSON.stringify({ outputPath, exclusionsPath, payload_sha256: crypto.createHash("sha256").update(await fs.readFile(outputPath)).digest("hex"), report: payload.report, exclusions: { documents: exclusions.excluded_documents, gross: exclusions.excluded_gross, totals_by_reason: exclusionTotals } }, null, 2));
