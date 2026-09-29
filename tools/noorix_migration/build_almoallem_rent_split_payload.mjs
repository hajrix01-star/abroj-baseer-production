/** Build the one approved, split-paid Al Moallem rent payload (read-only). */
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
const sourceInvoiceId = "cmoa4yfs000283gpglz1hg33a";
const runName = "20260913-noorix-almoallem-rent-split-qa-2026-04-1";
const runDir = ".local-backups/noorix-migration/runs/20260913-almoallem-rent-split-qa-1";
const outputPath = path.join(runDir, "almoallem-rent-split-payload.json");
const sha = (value) => crypto.createHash("sha256").update(JSON.stringify(value)).digest("hex");
const fileSha = async (value) => crypto.createHash("sha256").update(await fs.readFile(value)).digest("hex");
const q = (db, sql) => {
  if (db === "baseer_dev") throw new Error("production database is forbidden");
  const output = execFileSync("docker", ["exec", container, "psql", "-U", "odoo", "-d", db, "-At", "-F", "\t", "-c", sql], { encoding: "utf8" }).trim();
  return output ? output.split(/\r?\n/).map((line) => line.split("\t")) : [];
};
const f4 = (value) => {
  const match = String(value).match(/^(\d+)(?:\.(\d+))?$/);
  if (!match) throw new Error(`invalid source amount: ${value}`);
  return `${match[1]}.${(match[2] || "").padEnd(4, "0").slice(0, 4)}`;
};
const cents = (value) => {
  const [whole, fraction] = f4(value).split(".");
  return BigInt(whole) * 100n + (BigInt(fraction) + 50n) / 100n;
};
const money = (value) => `${value / 100n}.${String(value % 100n).padStart(2, "0")}`;

const invoices = q(sourceDb, `
  SELECT i.id,i.tenant_id,i.company_id,i.kind,i.invoice_number,COALESCE(i.supplier_invoice_number,''),
         i.transaction_date::date::text,i.net_amount::text,i.tax_amount::text,i.total_amount::text,
         i.supplier_id,COALESCE(c.name_ar,''),i.status,encode(convert_to(COALESCE(i.notes,''),'UTF8'),'hex')
  FROM invoices i LEFT JOIN categories c ON c.id=i.category_id
  WHERE i.id='${sourceInvoiceId}';
`).map(([id, sourceTenant, sourceCompany, kind, number, supplierInvoiceNumber, date, net, tax, total, supplier, category, status, notes]) => ({
  id, source_tenant_id: sourceTenant, source_company_id: sourceCompany, kind, number, supplier_invoice_number: supplierInvoiceNumber,
  date, net: f4(net), tax: f4(tax), total: f4(total), supplier, category, status, notes: Buffer.from(notes, "hex").toString("utf8"),
}));
if (invoices.length !== 1) throw new Error("rent source invoice is missing or ambiguous");
const invoice = invoices[0];
const expectedInvoice = { source_tenant_id: tenant, source_company_id: companyId, kind: "fixed_expense", number: "EXP-20260422-001", date: "2026-04-22", net: "27325.0000", tax: "0.0000", total: "27325.0000", supplier: "cmnv066vr0007mm1ckppi6oti", category: "إيجارات", status: "active" };
for (const [key, value] of Object.entries(expectedInvoice)) if (invoice[key] !== value) throw new Error(`rent source invoice differs: ${key}`);

const ledgers = q(sourceDb, `
  SELECT id,amount::text,transaction_date::date::text,vault_id,status,COALESCE(employee_id,''),
         COALESCE(reporting_category_name_ar,''),debit_account_id,credit_account_id,created_at::text
  FROM ledger_entries WHERE reference_type='invoice' AND reference_id='${sourceInvoiceId}' ORDER BY vault_id,id;
`).map(([id, amount, date, vault, status, employee, category, debit, credit, created]) => ({ id, amount: f4(amount), date, vault, status, employee, category, debit, credit, created }));
const allocations = q(sourceDb, `
  SELECT id,vault_id,amount::text,created_at::text FROM invoice_vault_allocations
  WHERE invoice_id='${sourceInvoiceId}' ORDER BY vault_id,id;
`).map(([id, vault, amount, created]) => ({ id, vault, amount: f4(amount), created }));
const expectedLegs = new Map([
  ["cmngf47fp0027gwgizvpdbssf", { ledger_id: "cmoa4yfs9002a3gpgyvax8t36", allocation_id: "cmoa4yfsd002c3gpgyrlj1a7v", amount: "9237.0000", journal_id: 75, journal_code: "KEET", liquidity_account_id: 813, liquidity_account_code: "101020", vault_name: "كيتا" }],
  ["cmnazrhgy000g2646c45q6zi6", { ledger_id: "cmoa4yfsh002e3gpgks1fcdd6", allocation_id: "cmoa4yfsi002g3gpgkmxe9uqi", amount: "18088.0000", journal_id: 76, journal_code: "HNGR", liquidity_account_id: 814, liquidity_account_code: "101021", vault_name: "هنجر" }],
]);
if (ledgers.length !== 2 || allocations.length !== 2) throw new Error("rent split source ledger/allocation cardinality differs");
const settlements = [...expectedLegs.entries()].map(([vault, expected]) => {
  const ledger = ledgers.find((row) => row.vault === vault), allocation = allocations.find((row) => row.vault === vault);
  if (!ledger || !allocation) throw new Error(`rent source split is incomplete: ${vault}`);
  for (const [key, value] of Object.entries({ id: expected.ledger_id, amount: expected.amount, date: invoice.date, vault, status: "active", employee: "", category: "إيجارات" })) if (ledger[key] !== value) throw new Error(`rent ledger differs: ${vault}/${key}`);
  for (const [key, value] of Object.entries({ id: expected.allocation_id, amount: expected.amount, vault })) if (allocation[key] !== value) throw new Error(`rent allocation differs: ${vault}/${key}`);
  return { source_vault_id: vault, source_vault_name: expected.vault_name, source_ledger_id: ledger.id, source_allocation_id: allocation.id, source_allocation_raw: allocation.amount, target_payment_journal_id: expected.journal_id, target_payment_journal_code: expected.journal_code, target_liquidity_account_id: expected.liquidity_account_id, target_liquidity_account_code: expected.liquidity_account_code, target_payment_amount: money(cents(allocation.amount)) };
});
if (settlements.reduce((total, row) => total + cents(row.source_allocation_raw), 0n) !== cents(invoice.total)) throw new Error("rent split payments do not equal invoice total");

const targetRows = q(targetDb, `
  SELECT cm.company_id::text,cm.source_archive_sha256,cm.decision FROM baseer_noorix_company_map cm
  WHERE cm.source_system='noorix' AND cm.source_tenant_id='${tenant}' AND cm.source_company_id='${companyId}';
  SELECT m.source_supplier_id,m.partner_id::text,p.company_id::text,p.supplier_rank::text,m.source_archive_sha256
  FROM baseer_noorix_supplier_map m JOIN res_partner p ON p.id=m.partner_id
  WHERE m.source_system='noorix' AND m.source_tenant_id='${tenant}' AND m.source_company_id='${companyId}' AND m.source_supplier_id='${invoice.supplier}';
  SELECT m.source_vault_id,m.source_vault_name,m.source_vault_type,m.journal_id::text,j.code,j.type,j.default_account_id::text,m.decision,m.source_archive_sha256
  FROM baseer_noorix_liquidity_vault_map m JOIN account_journal j ON j.id=m.journal_id
  WHERE m.source_system='noorix' AND m.source_tenant_id='${tenant}' AND m.source_company_id='${companyId}' AND m.company_id=${targetCompanyId} AND m.source_vault_id IN ('cmngf47fp0027gwgizvpdbssf','cmnazrhgy000g2646c45q6zi6') ORDER BY m.source_vault_id;
`).flat();
// The grouped checks below deliberately avoid accepting a partial target map.
const companyMap = q(targetDb, `SELECT company_id::text,source_archive_sha256,decision FROM baseer_noorix_company_map WHERE source_system='noorix' AND source_tenant_id='${tenant}' AND source_company_id='${companyId}';`);
if (companyMap.length !== 1 || companyMap[0].join("|") !== `${targetCompanyId}|${archive}|reuse_existing_company`) throw new Error("target company provenance differs");
const supplierMap = q(targetDb, `SELECT m.partner_id::text,COALESCE(p.company_id::text,''),p.supplier_rank::text,m.source_archive_sha256 FROM baseer_noorix_supplier_map m JOIN res_partner p ON p.id=m.partner_id WHERE m.source_system='noorix' AND m.source_tenant_id='${tenant}' AND m.source_company_id='${companyId}' AND m.source_supplier_id='${invoice.supplier}';`);
if (supplierMap.length !== 1 || supplierMap[0].join("|") !== `1552||3|${archive}`) throw new Error("rent supplier provenance differs");
const vaultMaps = q(targetDb, `SELECT m.source_vault_id,m.source_vault_name,m.source_vault_type,m.journal_id::text,j.code,j.type,j.default_account_id::text,m.decision,m.source_archive_sha256 FROM baseer_noorix_liquidity_vault_map m JOIN account_journal j ON j.id=m.journal_id WHERE m.source_system='noorix' AND m.source_tenant_id='${tenant}' AND m.source_company_id='${companyId}' AND m.company_id=${targetCompanyId} AND m.source_vault_id IN ('cmngf47fp0027gwgizvpdbssf','cmnazrhgy000g2646c45q6zi6') ORDER BY m.source_vault_id;`);
if (vaultMaps.length !== 2) throw new Error("rent liquidity maps are incomplete");
for (const [vault, expected] of expectedLegs) {
  const row = vaultMaps.find(([id]) => id === vault);
  if (!row || row.join("|") !== `${vault}|${expected.vault_name}|app|${expected.journal_id}|${expected.journal_code}|bank|${expected.liquidity_account_id}|create_historical_wallet|${archive}`) throw new Error(`rent liquidity map differs: ${vault}`);
}
const account = q(targetDb, `SELECT id::text,code_store->>'2',account_type,active::text FROM account_account WHERE id=328;`);
if (account.length !== 1 || account[0].join("|") !== "328|400016|expense|true") throw new Error("rent account differs");
const journals = q(targetDb, `SELECT id::text,code,type,company_id::text,default_account_id::text FROM account_journal WHERE id IN (19,75,76) ORDER BY id;`);
if (journals.map((row) => row.join("|")).join("\n") !== "19|BILL|purchase|2|313\n75|KEET|bank|2|813\n76|HNGR|bank|2|814") throw new Error("rent journals differ");
const outbound = q(targetDb, `SELECT pml.journal_id::text,pml.id::text,pm.code,pml.payment_account_id::text FROM account_payment_method_line pml JOIN account_payment_method pm ON pm.id=pml.payment_method_id WHERE pml.journal_id IN (75,76) AND pm.payment_type='outbound' ORDER BY pml.journal_id;`);
if (outbound.map((row) => row.join("|")).join("\n") !== "75|50|manual|813\n76|52|manual|814") throw new Error("outbound native liquidity method differs");
const splitEvidenceTable = q(targetDb, "SELECT COALESCE(to_regclass('public.baseer_noorix_split_paid_vendor_bill_map')::text,'absent');")[0][0] !== "absent";
const conflicts = q(targetDb, `SELECT source_invoice_id FROM baseer_noorix_purchase_invoice_map WHERE source_system='noorix' AND source_tenant_id='${tenant}' AND source_company_id='${companyId}' AND source_invoice_id='${sourceInvoiceId}'${splitEvidenceTable ? ` UNION ALL SELECT source_invoice_id FROM baseer_noorix_split_paid_vendor_bill_map WHERE source_system='noorix' AND source_tenant_id='${tenant}' AND source_company_id='${companyId}' AND source_invoice_id='${sourceInvoiceId}'` : ""};`);
if (conflicts.length) throw new Error("rent source has already been mapped");

const category = { source_system: "noorix", source_tenant_id: tenant, source_company_id: companyId, source_mapping_key: "almoallem-rent-split:no-tax", source_category_id: null, source_category_name: "إيجارات", source_row_sha256: sha({ source_category_name: "إيجارات", account_code: "400016", tax_policy: "no_tax", settlement_shape: "two_native_wallet_payments" }), source_archive_sha256: archive, canonical_key: "almoallem:400016:rent-split:no-tax", decision: "create_historical_service", target_product_id: null, target_product_code: "NOORIX-HIST-ALM-400016-RENT-SPLIT-NOTAX", target_product_name: "تاريخي المعلم - إيجارات (تسوية كيتا وهنجر، بدون ضريبة)", target_account_id: 328, target_account_code: "400016", target_account_type: "expense", tax_policy: "no_tax" };
const payload = { schema_version: 1, target_database: targetDb, source_archive_sha256: archive, approved_policy: "almoallem_single_rent_split_paid_vendor_bill_native_accounting", run: { name: runName, scope: "purchase_history", month: "2026-04", target_company_id: targetCompanyId }, company: { source_system: "noorix", source_tenant_id: tenant, source_company_id: companyId, target_company_id: targetCompanyId }, allowlist: { purchase_journal: { id: 19, code: "BILL", type: "purchase" }, rent_expense_account: { id: 328, code: "400016", type: "expense" }, supplier: { source_supplier_id: invoice.supplier, target_partner_id: 1552, name: "الكهلان" }, forbidden_journal_codes: ["PSBNK", "PSCSH"], forbidden_outputs: ["stock.move", "stock.picking", "pos.order", "pos.session", "account.asset", "account.asset.depreciation"] }, category_decision: category, invoice: { source_system: "noorix", source_tenant_id: tenant, source_company_id: companyId, source_invoice_id: invoice.id, source_supplier_id: invoice.supplier, source_invoice_number: invoice.number, source_supplier_invoice_number: invoice.supplier_invoice_number, source_document_kind: invoice.kind, business_date: invoice.date, month: "2026-04", source_net_raw: invoice.net, source_tax_raw: invoice.tax, source_total_raw: invoice.total, source_archive_sha256: archive, canonical_key: `split-paid-vendor-bill:${companyId}:${invoice.id}`, source_row_sha256: sha({ invoice, settlements }), decision: "create_split_paid_vendor_bill", target_partner_id: 1552, target_account_id: 328, target_account_code: "400016", target_tax_id: null, price_unit: "27325.00", target_net: "27325.00", target_tax: "0.00", target_total: "27325.00", target_product_code: category.target_product_code, target_product_name: category.target_product_name }, settlements, report: { source_invoices: 1, source_ledgers: 2, source_allocations: 2, vendor_bills: 1, payments: 2, target_net: "27325.00", target_tax: "0.00", target_gross: "27325.00", payment_total: "27325.00", months: { "2026-04": { documents: 1, gross: "27325.00", payments: 2 } } } };
await fs.mkdir(runDir, { recursive: true });
await fs.writeFile(outputPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
console.log(JSON.stringify({ outputPath, payload_sha256: await fileSha(outputPath), report: payload.report, source_ledger_ids: settlements.map((row) => row.source_ledger_id), source_allocation_ids: settlements.map((row) => row.source_allocation_id) }, null, 2));
