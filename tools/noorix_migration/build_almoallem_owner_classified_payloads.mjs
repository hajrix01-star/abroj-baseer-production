/**
 * Read-only freezer for the owner-classified Al Moallem historical exceptions.
 * It deliberately produces two bounded payloads: paid supplier documents for
 * the generic writer, and non-vendor historical salary/overtime entries.
 */
import crypto from "node:crypto";
import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";

const sourceDb = "noorix_source_inspection_archive159_20260913";
const targetDb = "baseer_noorix_data_migration_qa_20260912";
const container = "baseer_odoo_dev-db-1";
const archive = "024606ADD82DCD78DC1835828A12D7B22C56E34924FF998ABF752134160E79E2";
const tenant = "default-tenant-noorix-2024";
const companyId = "cmnaivif80001wavxxfgriptm";
const targetCompanyId = 2;
const priorExclusionsPath = ".local-backups/noorix-migration/runs/20260913-almoallem-general-purchases-qa-1/almoallem-general-purchase-exclusions.json";
const priorExclusionsSha = "dd5d58f1ef8c795cdaea883885a1fda2f2f1bb73dca628925f1d22c4f5a6db83";
const outputDir = ".local-backups/noorix-migration/runs/20260913-almoallem-owner-classified-qa-1";
const generalPath = path.join(outputDir, "almoallem-owner-classified-general-purchase-payload.json");
const payrollPath = path.join(outputDir, "almoallem-owner-classified-payroll-payload.json");
const decisionPath = path.join(outputDir, "almoallem-owner-classified-decision.json");
const unresolvedPath = path.join(outputDir, "almoallem-owner-classified-unresolved.json");

const SHA256 = /^[0-9a-f]{64}$/i;
const fixed4 = (value) => {
  const match = String(value).match(/^(\d+)(?:\.(\d+))?$/);
  if (!match || ((match[2] || "").length > 4 && /[1-9]/.test((match[2] || "").slice(4)))) throw new Error(`invalid source amount: ${value}`);
  return `${match[1]}.${(match[2] || "").padEnd(4, "0").slice(0, 4)}`;
};
const units4 = (value) => { const [whole, fraction] = fixed4(value).split("."); return BigInt(whole) * 10000n + BigInt(fraction); };
const cents = (value) => (units4(value) * 2n + 100n) / 200n;
const money = (value) => `${value / 100n}.${String(value % 100n).padStart(2, "0")}`;
const sha = (value) => crypto.createHash("sha256").update(JSON.stringify(value)).digest("hex");
const fileSha = async (file) => crypto.createHash("sha256").update(await fs.readFile(file)).digest("hex");
const sum = (rows, field) => rows.reduce((total, row) => total + BigInt(String(row[field]).replace(".", "")), 0n);
const netPrice = (gross) => {
  const whole = gross / 115n; let rem = gross % 115n; let digits = "";
  for (let i = 0; i < 14; i += 1) { rem *= 10n; digits += String(rem / 115n); rem %= 115n; }
  return `${whole}.${digits}`;
};
const group = (items, key) => items.reduce((result, item) => { const value = key(item); if (!result.has(value)) result.set(value, []); result.get(value).push(item); return result; }, new Map());

function q(database, sql) {
  if (database === "baseer_dev") throw new Error("production database is forbidden");
  const output = execFileSync("docker", ["exec", container, "psql", "-U", "odoo", "-d", database, "-At", "-F", "\t", "-c", sql], { encoding: "utf8", maxBuffer: 128 * 1024 * 1024 }).trim();
  return output ? output.split(/\r?\n/).map((line) => line.split("\t")) : [];
}
const sqlList = (values) => values.map((value) => `'${value}'`).join(",");

/* The owner-approved classification is finite; IDs are source identities, not
 * a supplier-name heuristic.  Tax policy is derived and then checked against
 * each authoritative source row. */
const groups = [
  ["meat-no-tax", "لحوم (تصنيف المورد)", 313, "400001", "expense_direct_cost", "no_tax", "لحوم", ["cmnvc4uos0010mm1c39d31kgt", "cmnvcbio60026mm1ctxhc5f44", "cmnvcl3ob003cmm1ckrkduyj8", "cmnuu73tw000qmc8j2ar6le78"]],
  ["chicken-vat", "دجاج (تصنيف المورد)", 313, "400001", "expense_direct_cost", "owner_declared_inclusive_15", "دجاج", ["cmnvc4uph0018mm1cp6zkjxoa", "cmnvcbiom002emm1cwtjpzhhf", "cmnvcl3os003kmm1c9wzpwelo", "cmnuu73u5000ymc8jyxolrvce", "cmobzs5i7003t1s4erdjxqmvf"]],
  ["plastics-vat", "بلاستيكات (تصنيف المورد)", 313, "400001", "expense_direct_cost", "owner_declared_inclusive_15", "بلاستيكات", ["cmnvc4upo001gmm1c6pmklemw", "cmnuu73uw001umc8juznd7nhh"]],
  ["other-food-vat", "مواد غذائية أخرى (تصنيف المورد)", 313, "400001", "expense_direct_cost", "owner_declared_inclusive_15", "مواد غذائية أخرى", ["cmnvc4upw001omm1cx5vpf9zp", "cmnvcbipb0032mm1cxkyfli7x", "cmnvcl3pe0048mm1cl6vruc92", "cmnuu73vr0022mc8j7g25jknb"]],
  ["produce-no-tax", "خضار وفواكه (تصنيف المورد)", 313, "400001", "expense_direct_cost", "no_tax", "خضار وفواكه", ["cmnvc4uq2001wmm1crfx4quaw", "cmnvcbip2002umm1cays308r0", "cmnvcl3p0003smm1c7cclzzm1", "cmnuu73up001mmc8j1zd2kpx0"]],
  ["fat-no-tax", "شحم (تصنيف المورد)", 313, "400001", "expense_direct_cost", "no_tax", "شحم", ["cmnuu73ud0016mc8jyvnpm1rz"]],
  ["packaging-vat", "تعبئة وتغليف (قرار المالك)", 313, "400001", "expense_direct_cost", "owner_declared_inclusive_15", null, ["cmp8sujxb002cyvby455n73mt"]],
  ["omar-food-vat", "مواد غذائية (قرار المالك)", 313, "400001", "expense_direct_cost", "owner_declared_inclusive_15", null, ["cmnxehv5o000z1480zpre73pn", "cmo67pwvl00eng1b6k7kbfbk0", "cmpdqm77600c6m8wrgt2rp7th", "cmpiub38w0139m8wr5hlw8amv", "cmswav8iz01azs10iqhjlvg7w"]],
  ["vehicles-vat", "وقود ومركبات (تصنيف المورد)", 360, "400048", "expense", "owner_declared_inclusive_15", "وقود ومواصلات", ["cmnvcbiov002mmm1caflqrnr5", "cmnvcl3p70040mm1c5v6bx9so", "cmnuu73uk001emc8j0vsgmtwr"]],
  ["vehicles-no-tax", "مركبات وصيانة سيارة (قرار المالك)", 360, "400048", "expense", "no_tax", "وقود ومواصلات", ["cmnxns37g004yzbslnfuzwvn3", "cmnxllp0a001uzbslwomljmgw", "cmrdo74b30147tmqp5ahk8xn5", "cms93obyf000fsnklm2s4mqy0"]],
  ["advertising-no-tax", "إعلانات (قرار المالك)", 346, "400034", "expense", "no_tax", null, ["cmpocwc6u0002vfypawzh4oyy", "cmsny70q5000de481p6au8erb", "cmsny9afm0005gl39y4t8ctfk"]],
  ["hunger-commission-vat", "عمولة مبيعات HungerStation (قرار المالك)", 323, "400011", "expense", "owner_declared_inclusive_15", null, ["cmpflxlie00mlw8hfwf31f6y0", "cmsajmuz4002r14o7478epir0"]],
  ["fine-no-tax", "غرامة غير تشغيلية (قرار المالك)", 369, "400057", "expense", "no_tax", null, ["cmopuh4t1001rymufavef0emn"]],
  ["trade-license-no-tax", "رخصة تجارية (قرار المالك)", 344, "400032", "expense", "no_tax", null, ["cmrzidr2c00aql1xatwlcnir7"]],
  ["parts-maintenance-vat", "قطع غيار وصيانة (قرار المالك)", 354, "400042", "expense", "owner_declared_inclusive_15", null, ["cmnxllozo001ezbsl4wxyx33f", "cmnxllp01001mzbslwvz02msx"]],
  ["electronics-asset-vat", "أجهزة وإلكترونيات تاريخية (قرار أصل بلا بطاقة)", 272, "106003", "asset_fixed", "owner_declared_inclusive_15", null, ["cmoft6r91001e11xlezredg36", "cmpg3jp4x00s7m8wriwzi67kq", "cmpxv7o1n009bc57e0mclc0ws", "cmqfmy67o00gq2uogmayqpe23", "cmqhrm8em00to2uogyp8uk60c", "cmqmv50x8002ydmkieyfjd7a5", "cmqo9y5np0090dmkiijiw7w9t", "cmr6v8peu0028tmqpm9j2c2wr", "cmrtle1ag004p12kvl6c7h160", "cms0v0ky4002blqrkagmpt2hk", "cms3qi39w004v56br0ffiwqyu", "cmsq8bwzb001h2pp5nwd3o8cs", "cmsysd64501o0s10ivzzl1b18"]],
  ["office-equipment-asset-vat", "معدات مكتبية تاريخية (قرار أصل بلا بطاقة)", 271, "106002", "asset_fixed", "owner_declared_inclusive_15", null, ["cmqzpumar000e2l8npd44ijnk"]],
].map(([key, label, accountId, accountCode, accountType, taxPolicy, reuseCategory, sourceIds]) => ({ key, label, accountId, accountCode, accountType, taxPolicy, reuseCategory, sourceIds }));

const payroll = [
  ["cmovdeibf01eb11chcerak0yn", "salary", "راتب", "2026-04"],
  ["cmq15ljty00jtdogt7gaxx7ja", "overtime", "OVER TIME", "2026-05"],
  ["cmq167osa00k3dogtwjxokvnr", "overtime", "OVER TIME", "2026-05"],
  ["cmq167ot900kjdogt5l3bt3l8", "overtime", "OVER TIME", "2026-05"],
].map(([id, settlementKind, expectedSupplier, month]) => ({ id, settlementKind, expectedSupplier, month }));
const rentId = "cmoa4yfs000283gpglz1hg33a";
const generalIds = groups.flatMap((entry) => entry.sourceIds);
const selectedIds = [...generalIds, ...payroll.map((row) => row.id)];
if (new Set(selectedIds).size !== 60 || generalIds.length !== 56) throw new Error("owner classified source identity manifest differs");

const priorBytes = await fs.readFile(priorExclusionsPath);
if (crypto.createHash("sha256").update(priorBytes).digest("hex") !== priorExclusionsSha) throw new Error("prior exclusion evidence receipt differs");
const prior = JSON.parse(priorBytes.toString("utf8"));
const priorActive = prior.exclusions.filter((row) => row.reason !== "source_status_not_active");
if (priorActive.length !== 61 || new Set(priorActive.map((row) => row.source_invoice_id)).size !== 61 || !priorActive.some((row) => row.source_invoice_id === rentId) || !selectedIds.every((id) => priorActive.some((row) => row.source_invoice_id === id))) throw new Error("prior active exclusion set differs");

const ownerDecision = {
  decision_type: "owner_classified_almoallem_active_exceptions",
  decision_date: "2026-09-13", source_company_id: companyId, target_company_id: targetCompanyId,
  instruction: "Classify only these 60 active source invoices as explicitly approved. Use non-stock historical services. Electronics and office equipment post only to the stated fixed-asset account with no asset card, depreciation, or stock. Salary/overtime are separate historical BPAY entries with no vendor bill, payment, employee, or payslip.",
  general_groups: groups.map(({ key, label, accountCode, taxPolicy, sourceIds }) => ({ key, label, accountCode, taxPolicy, source_ids: sourceIds })),
  payroll: payroll.map(({ id, settlementKind }) => ({ source_invoice_id: id, settlement_kind: settlementKind, account_code: "400003" })),
  unresolved: { rent_source_invoice_id: rentId, reason: "incomplete_or_nonunique_source_ledger_evidence" },
  prohibited: { asset_cards: true, depreciation: true, stock: true, pos: true, payroll_employees: true, payslips: true, vendor_bills_for_payroll: true, payments_for_payroll: true },
};
const ownerDecisionSha = sha(ownerDecision);

const sourceIdsSql = sqlList(selectedIds);
const invoices = q(sourceDb, `
SELECT i.id,i.tenant_id,i.company_id,i.kind,i.invoice_number,COALESCE(i.supplier_invoice_number,''),i.transaction_date::date::text,
 i.net_amount::text,i.tax_amount::text,i.total_amount::text,COALESCE(i.supplier_id,''),COALESCE(i.category_id,''),COALESCE(c.name_ar,''),COALESCE(i.vault_id,''),COALESCE(i.employee_id,''),encode(convert_to(COALESCE(i.notes,''),'UTF8'),'hex'),i.status,
 COALESCE(s.name_ar,''),COALESCE(v.name_ar,''),COALESCE(v.type,''),v.is_active::text,v.is_archived::text
FROM invoices i LEFT JOIN categories c ON c.id=i.category_id LEFT JOIN suppliers s ON s.id=i.supplier_id LEFT JOIN vaults v ON v.id=i.vault_id
WHERE i.id IN (${sourceIdsSql}) ORDER BY i.transaction_date,i.invoice_number,i.id;
`).map(([id, sourceTenant, sourceCompany, kind, number, supplierNumber, date, net, tax, total, supplier, categoryId, categoryName, vault, employee, notes, status, supplierName, vaultName, vaultType, vaultActive, vaultArchived]) => ({
  id, source_tenant_id: sourceTenant, source_company_id: sourceCompany, kind, number, supplier_number: supplierNumber, date,
  net: fixed4(net), tax: fixed4(tax), total: fixed4(total), supplier, category_id: categoryId || null, category_name: categoryName || null,
  vault: vault || null, employee: employee || null, notes: Buffer.from(notes, "hex").toString("utf8"), status, supplier_name: supplierName,
  vault_name: vaultName, vault_type: vaultType, vault_active: ["t", "true"].includes(vaultActive), vault_archived: ["t", "true"].includes(vaultArchived),
}));
if (invoices.length !== 60 || new Set(invoices.map((row) => row.id)).size !== 60) throw new Error("selected source invoice set differs");
for (const row of invoices) {
  if (row.source_tenant_id !== tenant || row.source_company_id !== companyId || row.status !== "active" || !row.vault || !row.supplier || !row.vault_active || row.vault_archived) throw new Error(`source invoice scope differs: ${row.id}`);
}

const ledgers = q(sourceDb, `SELECT id,reference_id,amount::text,transaction_date::date::text,COALESCE(vault_id,''),COALESCE(employee_id,''),status,COALESCE(reporting_category_name_ar,''),created_at::text FROM ledger_entries WHERE reference_type='invoice' AND reference_id IN (${sourceIdsSql}) ORDER BY reference_id,id;`).map(([id, invoiceId, amount, date, vault, employee, status, category, created]) => ({ id, invoice_id: invoiceId, amount: fixed4(amount), date, vault: vault || null, employee: employee || null, status, category, created }));
const allocations = q(sourceDb, `SELECT id,invoice_id,vault_id,amount::text,created_at::text FROM invoice_vault_allocations WHERE invoice_id IN (${sourceIdsSql}) ORDER BY invoice_id,id;`).map(([id, invoiceId, vault, amount, created]) => ({ id, invoice_id: invoiceId, vault, amount: fixed4(amount), created }));
const ledgerByInvoice = group(ledgers, (row) => row.invoice_id);
const allocationByInvoice = group(allocations, (row) => row.invoice_id);
for (const invoice of invoices) {
  const invoiceLedgers = ledgerByInvoice.get(invoice.id) || [], invoiceAllocations = allocationByInvoice.get(invoice.id) || [];
  if (invoiceLedgers.length !== 1 || invoiceAllocations.length !== 1 || invoiceLedgers[0].status !== "active" || invoiceLedgers[0].amount !== invoice.total || invoiceLedgers[0].date !== invoice.date || invoiceLedgers[0].vault !== invoice.vault || invoiceLedgers[0].employee || invoiceAllocations[0].amount !== invoice.total || invoiceAllocations[0].vault !== invoice.vault) throw new Error(`source ledger/allocation contract differs: ${invoice.id}`);
}

const companyMap = q(targetDb, `SELECT company_id::text,source_archive_sha256,decision FROM baseer_noorix_company_map WHERE source_system='noorix' AND source_tenant_id='${tenant}' AND source_company_id='${companyId}';`);
if (companyMap.length !== 1 || companyMap[0].join("|") !== `${targetCompanyId}|${archive}|reuse_existing_company`) throw new Error("target company provenance differs");
const accountExpected = new Map([[313, ["400001", "expense_direct_cost"]], [360, ["400048", "expense"]], [346, ["400034", "expense"]], [323, ["400011", "expense"]], [369, ["400057", "expense"]], [344, ["400032", "expense"]], [354, ["400042", "expense"]], [272, ["106003", "asset_fixed"]], [271, ["106002", "asset_fixed"]], [315, ["400003", "expense"]]]);
const accountRows = q(targetDb, `SELECT id,code_store->>'2',account_type,active::text FROM account_account WHERE id IN (${[...accountExpected.keys()].join(",")}) ORDER BY id;`);
if (accountRows.length !== accountExpected.size) throw new Error("account allowlist is incomplete");
for (const [id, code, type, active] of accountRows) { const expected = accountExpected.get(Number(id)); if (!expected || expected[0] !== code || expected[1] !== type || !["t", "true"].includes(active)) throw new Error(`account differs: ${id}`); }

const nonPayrollInvoices = invoices.filter((row) => generalIds.includes(row.id));
const supplierRows = q(targetDb, `SELECT m.source_supplier_id,m.partner_id::text,m.source_archive_sha256,COALESCE(p.company_id::text,''),p.supplier_rank::text FROM baseer_noorix_supplier_map m JOIN res_partner p ON p.id=m.partner_id WHERE m.source_system='noorix' AND m.source_tenant_id='${tenant}' AND m.source_company_id='${companyId}' AND m.source_supplier_id IN (${sqlList([...new Set(nonPayrollInvoices.map((row) => row.supplier))])});`);
const suppliers = new Map(supplierRows.map(([sourceId, partner, sourceArchive, partnerCompany, rank]) => { if (sourceArchive !== archive || partnerCompany || Number(rank) < 1) throw new Error(`supplier map differs: ${sourceId}`); return [sourceId, Number(partner)]; }));
if (suppliers.size !== new Set(nonPayrollInvoices.map((row) => row.supplier)).size) throw new Error("supplier map incomplete");
const vaultRows = q(targetDb, `SELECT m.source_vault_id,m.source_archive_sha256,m.decision,m.source_vault_type,m.source_vault_name,j.id,j.code,j.type,j.company_id::text FROM baseer_noorix_liquidity_vault_map m JOIN account_journal j ON j.id=m.journal_id WHERE m.source_system='noorix' AND m.source_tenant_id='${tenant}' AND m.source_company_id='${companyId}' AND m.company_id=${targetCompanyId};`);
const vaults = new Map(vaultRows.map(([sourceId, sourceArchive, decision, sourceType, sourceName, journal, code, type, targetCompany]) => {
  const native = decision === "reuse_existing_liquidity" && sourceType === type;
  const app = decision === "create_historical_wallet" && sourceType === "app" && type === "bank";
  if (sourceArchive !== archive || Number(targetCompany) !== targetCompanyId || ["PSBNK", "PSCSH"].includes(code) || (!native && !app)) throw new Error(`vault map differs: ${sourceId}`);
  return [sourceId, { journal: Number(journal), code, type, sourceType, sourceName }];
}));
if (nonPayrollInvoices.some((row) => !vaults.has(row.vault))) throw new Error("non-payroll vault map is incomplete");

const categoryRows = q(targetDb, `SELECT m.source_category_name,m.tax_policy,m.product_id::text,p.default_code,pt.name,m.account_id::text,a.code_store->>'2',a.account_type FROM baseer_noorix_purchase_category_map m JOIN product_product p ON p.id=m.product_id JOIN product_template pt ON pt.id=p.product_tmpl_id JOIN account_account a ON a.id=m.account_id WHERE m.source_system='noorix' AND m.source_tenant_id='${tenant}' AND m.source_company_id='${companyId}';`);
const existingProducts = new Map(categoryRows.map(([category, taxPolicy, productId, productCode, productName, accountId, accountCode, accountType]) => [`${category}:${taxPolicy}`, { productId: Number(productId), productCode, productName: JSON.parse(productName).en_US, accountId: Number(accountId), accountCode, accountType }]));

const ruleById = new Map(groups.flatMap((rule) => rule.sourceIds.map((id) => [id, rule])));
const decisions = new Map();
for (const rule of groups) {
  const expectedTax = rule.taxPolicy === "owner_declared_inclusive_15";
  const ruleInvoices = rule.sourceIds.map((id) => invoices.find((row) => row.id === id));
  if (ruleInvoices.some((row) => !row || (units4(row.tax) > 0n) !== expectedTax || (units4(row.tax) === 0n) !== !expectedTax)) throw new Error(`source VAT policy differs: ${rule.key}`);
  const mappingKey = `owner-classified:${rule.key}`;
  const snapshot = { mapping_key: mappingKey, label: rule.label, source_ids: rule.sourceIds, account_code: rule.accountCode, account_type: rule.accountType, tax_policy: rule.taxPolicy, owner_decision_sha256: ownerDecisionSha };
  let product;
  if (rule.reuseCategory) {
    const expectedMapTax = expectedTax ? "tax_when_source_positive" : "no_tax";
    product = existingProducts.get(`${rule.reuseCategory}:${expectedMapTax}`);
    if (!product || product.accountId !== rule.accountId || product.accountCode !== rule.accountCode || product.accountType !== rule.accountType) throw new Error(`existing service mapping differs: ${rule.key}`);
  } else {
    product = { productId: null, productCode: `NOORIX-HIST-ALM-OWNER-${rule.accountCode}-${sha(mappingKey).slice(0, 10).toUpperCase()}`, productName: `تاريخي المعلم - ${rule.label}${expectedTax ? " (ضريبة 15%)" : " (بدون ضريبة)"}` };
  }
  decisions.set(rule.key, {
    source_system: "noorix", source_tenant_id: tenant, source_company_id: companyId, source_mapping_key: mappingKey,
    source_category_id: null, source_category_name: rule.label, source_row_sha256: sha(snapshot), source_archive_sha256: archive,
    canonical_key: `almoallem-owner:${rule.accountCode}:${rule.key}`, decision: product.productId ? "reuse_existing_service" : "create_historical_service",
    target_product_id: product.productId, target_product_code: product.productCode, target_product_name: product.productName,
    target_account_id: rule.accountId, target_account_code: rule.accountCode, target_account_type: rule.accountType, tax_policy: rule.taxPolicy,
  });
}

const documents = nonPayrollInvoices.map((invoice) => {
  const rule = ruleById.get(invoice.id), decision = decisions.get(rule.key), ledger = ledgerByInvoice.get(invoice.id)[0], allocation = allocationByInvoice.get(invoice.id)[0];
  const gross = cents(invoice.total), taxable = units4(invoice.tax) > 0n, net = taxable ? (gross * 100n + 57n) / 115n : gross, tax = gross - net;
  const asset = rule.accountType === "asset_fixed";
  return {
    source_system: "noorix", source_tenant_id: tenant, source_company_id: companyId, source_invoice_id: invoice.id, source_ledger_id: ledger.id, source_allocation_id: allocation.id,
    source_vault_id: invoice.vault, source_supplier_id: invoice.supplier, source_category_id: invoice.category_id, source_invoice_number: invoice.number, source_supplier_invoice_number: invoice.supplier_number,
    source_document_kind: invoice.kind, business_date: invoice.date, month: invoice.date.slice(0, 7), source_net_raw: invoice.net, source_tax_raw: invoice.tax, source_total_raw: invoice.total,
    source_row_sha256: sha({ invoice, ledger, allocation, classification: rule.key, owner_decision_sha256: ownerDecisionSha }), source_archive_sha256: archive, canonical_key: `purchase:${companyId}:${invoice.id}`,
    source_asset_id: null, source_asset_row_sha256: null, owner_classification: asset ? "owner_approved_fixed_asset" : null, owner_decision_sha256: asset ? ownerDecisionSha : null,
    decision: "create_paid_vendor_bill", category_mapping_key: decision.source_mapping_key, target_product_id: decision.target_product_id, target_product_code: decision.target_product_code, target_product_name: decision.target_product_name,
    target_account_id: decision.target_account_id, target_account_code: decision.target_account_code, target_partner_id: suppliers.get(invoice.supplier), target_payment_journal_id: vaults.get(invoice.vault).journal,
    target_tax_id: taxable ? 61 : null, price_unit: taxable ? netPrice(gross) : money(gross), target_net: money(net), target_tax: money(tax), target_total: money(gross),
  };
}).sort((left, right) => left.business_date.localeCompare(right.business_date) || left.source_invoice_number.localeCompare(right.source_invoice_number));
if (documents.length !== 56 || new Set(documents.map((row) => row.source_invoice_id)).size !== 56) throw new Error("general document count differs");
const months = Object.fromEntries([...new Set(documents.map((row) => row.month))].sort().map((month) => { const rows = documents.filter((row) => row.month === month); return [month, { documents: rows.length, gross: money(sum(rows, "target_total")) }]; }));
const generalPayload = { schema_version: 1, target_database: targetDb, source_archive_sha256: archive, approved_policy: "general_paid_vendor_bills_native_accounting_monthly_atomic", run_prefix: "20260913-noorix-almoallem-owner-classified-qa", company: { source_system: "noorix", source_tenant_id: tenant, source_company_id: companyId, target_company_id: targetCompanyId }, allowlist: { purchase_journal_id: 19, purchase_journal_code: "BILL", purchase_tax_id: 61, vat_input_account_code: "104041", forbidden_journal_codes: ["PSBNK", "PSCSH"] }, owner_decision_sha256: ownerDecisionSha, category_decisions: [...decisions.values()].sort((a, b) => a.source_mapping_key.localeCompare(b.source_mapping_key)), documents, report: { source_documents: documents.length, target_net: money(sum(documents, "target_net")), target_tax: money(sum(documents, "target_tax")), target_gross: money(sum(documents, "target_total")), months } };

const payrollRecords = payroll.map((policy) => {
  const invoice = invoices.find((row) => row.id === policy.id), ledger = ledgerByInvoice.get(policy.id)[0], allocation = allocationByInvoice.get(policy.id)[0], vault = vaults.get(invoice.vault);
  if (!invoice || invoice.kind !== "expense" || invoice.employee || invoice.supplier_name !== policy.expectedSupplier || units4(invoice.tax) !== 0n || invoice.net !== invoice.total || policy.month !== invoice.date.slice(0, 7) || !vault) throw new Error(`payroll source contract differs: ${policy.id}`);
  return { source_system: "noorix", source_tenant_id: tenant, source_company_id: companyId, source_invoice_id: invoice.id, source_ledger_id: ledger.id, source_allocation_id: allocation.id, source_vault_id: invoice.vault, source_invoice_number: invoice.number, source_document_kind: invoice.kind, business_date: invoice.date, month: policy.month, source_net_raw: invoice.net, source_tax_raw: invoice.tax, source_total_raw: invoice.total, source_row_sha256: sha({ invoice, ledger, allocation, payroll_kind: policy.settlementKind, owner_decision_sha256: ownerDecisionSha }), source_archive_sha256: archive, canonical_key: `historical-payroll:${companyId}:${invoice.id}`, owner_decision_sha256: ownerDecisionSha, decision: "create_owner_declared_historical_payroll_move", settlement_kind: policy.settlementKind, target_company_id: targetCompanyId, target_journal_id: 42, target_salary_expense_account_id: 315, target_liquidity_journal_id: vault.journal, target_liquidity_account_id: invoice.vault === "cmnaiviq4000vwavxwjndkfev" ? 591 : 399, target_amount: money(cents(invoice.total)), target_posting_date: invoice.date, target_reference: `Noorix ${invoice.number} — ${policy.settlementKind === "overtime" ? "Overtime" : "Salary"} historical settlement`, target_debit_label: `Noorix ${invoice.number} — ${policy.settlementKind === "overtime" ? "Overtime / عمل إضافي تاريخي" : "Salary / راتب تاريخي"}`, target_credit_label: `Noorix ${invoice.number} — historical ${vault.sourceName || invoice.vault} settlement` };
}).sort((left, right) => left.business_date.localeCompare(right.business_date) || left.source_invoice_number.localeCompare(right.source_invoice_number));
if (payrollRecords.length !== 4 || new Set(payrollRecords.map((row) => row.source_invoice_id)).size !== 4) throw new Error("payroll count differs");
const payrollMonths = Object.fromEntries([...new Set(payrollRecords.map((row) => row.month))].sort().map((month) => { const rows = payrollRecords.filter((row) => row.month === month); return [month, { records: rows.length, total: money(sum(rows, "target_amount")) }]; }));
const payrollPayload = { schema_version: 1, target_database: targetDb, source_archive_sha256: archive, approved_policy: "almoallem_owner_classified_historical_payroll_entries", run_prefix: "20260913-noorix-almoallem-owner-classified-payroll-qa", company: { source_system: "noorix", source_tenant_id: tenant, source_company_id: companyId, target_company_id: targetCompanyId }, owner_decision_sha256: ownerDecisionSha, allowlist: { payroll_journal: { id: 42, code: "BPAY", type: "general" }, salary_expense_account: { id: 315, code: "400003", type: "expense" }, liquidity: { bank: { source_vault_id: "cmnaiviq8000xwavxoqjln3z7", journal_id: 23, journal_code: "BNK1", account_id: 399, account_code: "101001" }, cash: { source_vault_id: "cmnaiviq4000vwavxwjndkfev", journal_id: 41, journal_code: "CSH1", account_id: 591, account_code: "105001" } }, forbidden: { vendor_bills: true, payments: true, stock: true, pos: true, employees: true, payslips: true } }, records: payrollRecords, report: { source_invoices: payrollRecords.length, target_moves: payrollRecords.length, target_move_lines: payrollRecords.length * 2, total: money(sum(payrollRecords, "target_amount")), tax: "0.00", months: payrollMonths } };

const selectedSet = new Set(selectedIds);
const unresolved = prior.exclusions.filter((row) => !selectedSet.has(row.source_invoice_id));
if (unresolved.length !== 47 || unresolved.filter((row) => row.reason === "source_status_not_active").length !== 46 || unresolved.filter((row) => row.source_invoice_id === rentId).length !== 1) throw new Error("unresolved manifest differs");
const cancelledIds = unresolved.filter((row) => row.reason === "source_status_not_active").map((row) => row.source_invoice_id);
const cancelledStatuses = q(sourceDb, `SELECT id,status FROM invoices WHERE id IN (${sqlList(cancelledIds)}) ORDER BY id;`);
if (cancelledStatuses.length !== 46 || cancelledStatuses.some(([, status]) => status === "active")) throw new Error("cancelled evidence differs");
const unresolvedPayload = { prior_exclusions_path: priorExclusionsPath, prior_exclusions_sha256: priorExclusionsSha, selected_active_documents: 60, selected_general_documents: 56, selected_payroll_documents: 4, unresolved_documents: 47, unresolved: { rent: unresolved.find((row) => row.source_invoice_id === rentId), cancelled: unresolved.filter((row) => row.reason === "source_status_not_active") } };

await fs.mkdir(outputDir, { recursive: true });
await fs.writeFile(decisionPath, `${JSON.stringify(ownerDecision, null, 2)}\n`, "utf8");
await fs.writeFile(generalPath, `${JSON.stringify(generalPayload, null, 2)}\n`, "utf8");
await fs.writeFile(payrollPath, `${JSON.stringify(payrollPayload, null, 2)}\n`, "utf8");
await fs.writeFile(unresolvedPath, `${JSON.stringify(unresolvedPayload, null, 2)}\n`, "utf8");
console.log(JSON.stringify({ ownerDecisionPath: decisionPath, ownerDecisionSha256: ownerDecisionSha, generalPath, generalPayloadSha256: await fileSha(generalPath), generalReport: generalPayload.report, payrollPath, payrollPayloadSha256: await fileSha(payrollPath), payrollReport: payrollPayload.report, unresolvedPath, unresolvedDocuments: unresolvedPayload.unresolved_documents }, null, 2));
