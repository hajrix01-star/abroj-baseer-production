/**
 * Build the frozen, QA-only owner-declared Doha overtime settlement payload.
 *
 * This program is deliberately read-only: it asks PostgreSQL for the four
 * source documents and their target mappings, then freezes their exact source
 * evidence and the owner's bounded accounting decision.
 */
import crypto from "node:crypto";
import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";

const sourceDb = "noorix_source_inspection_archive159_20260913";
const targetDb = "baseer_noorix_data_migration_qa_20260912";
const dbContainer = "baseer_odoo_dev-db-1";
const outputDir = ".local-backups/noorix-migration/runs/20260913-doha-overtime-historical-settlement-qa-1";
const outputPath = path.join(outputDir, "doha-overtime-historical-settlement-payload.json");
const decisionPath = path.join(outputDir, "doha-overtime-owner-decision.json");
const archiveSha = "024606ADD82DCD78DC1835828A12D7B22C56E34924FF998ABF752134160E79E2";
const tenantId = "default-tenant-noorix-2024";
const sourceCompanyId = "cmnf5xrd0001uy8lm8vja50gp";
const targetCompanyId = 3;
const sourceVaultId = "cmnf5xrdt002oy8lmpyszg9uy";
const sourceIds = [
  "cmprc4zky000qclq0nn6x3nxy",
  "cmprc3jz9000ki0ht7yeim2g6",
  "cmprbxuyy000eclq0151rt9u3",
  "cmprbvjiv0004clq04bu9v8af",
];
const runName = "20260913-noorix-doha-overtime-historical-settlement-qa-2026-05-1";

function query(database, sql) {
  if (database === "baseer_dev") throw new Error("Production database is forbidden");
  const output = execFileSync("docker", [
    "exec", dbContainer, "psql", "-U", "odoo", "-d", database,
    "-At", "-F", "\t", "-c", sql,
  ], { encoding: "utf8", maxBuffer: 16 * 1024 * 1024 });
  return output.split(/\r?\n/).filter(Boolean).map((line) => line.split("\t"));
}

function sha(value) {
  return crypto.createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

function fixed4(value) {
  const match = String(value).match(/^(\d+)(?:\.(\d+))?$/);
  if (!match) throw new Error(`invalid non-negative source decimal: ${value}`);
  const fraction = match[2] || "";
  if (fraction.length > 4 && [...fraction.slice(4)].some((digit) => digit !== "0")) {
    throw new Error(`source decimal exceeds four places: ${value}`);
  }
  return `${match[1]}.${fraction.padEnd(4, "0").slice(0, 4)}`;
}

function money(raw) {
  const [whole, fraction] = fixed4(raw).split(".");
  const digits = Number(fraction.slice(0, 2)) + (Number(fraction[2]) >= 5 ? 1 : 0);
  return `${Number(whole) + Math.floor(digits / 100)}.${String(digits % 100).padStart(2, "0")}`;
}

const idsSql = sourceIds.map((id) => `'${id}'`).join(",");
const invoiceRows = query(sourceDb, `
SELECT i.id,i.tenant_id,i.company_id,i.invoice_number,i.kind,
       i.total_amount::text,i.net_amount::text,i.tax_amount::text,
       i.transaction_date::date::text,i.invoice_date::date::text,
       COALESCE(i.vault_id,''),COALESCE(i.employee_id,''),COALESCE(i.supplier_id,''),
       COALESCE(i.notes,''),i.status,COALESCE(i.entry_date::text,''),i.created_at::text,
       COALESCE(s.name_ar,''),COALESCE(v.name_ar,''),COALESCE(v.type,''),
       COALESCE(v.is_active::text,''),COALESCE(v.is_archived::text,''),
       COUNT(a.id)::text,COALESCE(SUM(a.amount),0)::text
FROM invoices i
LEFT JOIN suppliers s ON s.id=i.supplier_id
LEFT JOIN vaults v ON v.id=i.vault_id
LEFT JOIN invoice_vault_allocations a ON a.invoice_id=i.id
WHERE i.id IN (${idsSql})
GROUP BY i.id,s.name_ar,v.name_ar,v.type,v.is_active,v.is_archived
ORDER BY i.transaction_date,i.id;
`).map((row) => {
  const [id, tenant, company, invoiceNumber, kind, total, net, tax, transactionDate,
    invoiceDate, vaultId, employeeId, supplierId, notes, status, entryDate, createdAt,
    supplierName, vaultName, vaultType, vaultActive, vaultArchived, allocationCount,
    allocationTotal] = row;
  return {
    id, tenant_id: tenant, company_id: company, invoice_number: invoiceNumber, kind,
    total_raw: fixed4(total), net_raw: fixed4(net), tax_raw: fixed4(tax),
    transaction_date: transactionDate, invoice_date: invoiceDate, vault_id: vaultId,
    employee_id: employeeId || null, supplier_id: supplierId, notes, status,
    entry_date: entryDate, created_at: createdAt, supplier_name_ar: supplierName,
    vault_name_ar: vaultName, vault_type: vaultType, vault_active: ["t", "true"].includes(vaultActive),
    vault_archived: ["t", "true"].includes(vaultArchived), allocation_count: Number(allocationCount),
    allocation_total_raw: fixed4(allocationTotal),
  };
});

if (invoiceRows.length !== sourceIds.length || new Set(invoiceRows.map((row) => row.id)).size !== sourceIds.length) {
  throw new Error("the bounded overtime source document set differs");
}
for (const row of invoiceRows) {
  if (row.tenant_id !== tenantId || row.company_id !== sourceCompanyId || row.kind !== "expense" ||
      row.status !== "active" || row.employee_id || row.vault_id !== sourceVaultId ||
      row.supplier_name_ar !== "اوفر تايم" || row.vault_name_ar !== "نقد" ||
      row.vault_type !== "cash" || !row.vault_active || row.vault_archived ||
      row.tax_raw !== "0.0000" || row.total_raw !== row.net_raw ||
      row.allocation_count !== 1 || row.allocation_total_raw !== row.total_raw) {
    throw new Error(`source overtime evidence differs: ${row.id}`);
  }
}

const ledgerRows = query(sourceDb, `
SELECT id,reference_id,amount::text,debit_account_id,credit_account_id,
       transaction_date::date::text,COALESCE(vault_id,''),COALESCE(employee_id,''),
       status,COALESCE(reporting_class,''),COALESCE(reporting_category_name_ar,'')
FROM ledger_entries
WHERE reference_type='invoice' AND reference_id IN (${idsSql})
ORDER BY transaction_date,reference_id,id;
`).map(([id, invoiceId, amount, debitAccountId, creditAccountId, transactionDate, vaultId,
  employeeId, status, reportingClass, reportingCategory]) => ({
  id, source_invoice_id: invoiceId, amount_raw: fixed4(amount), debit_account_id: debitAccountId,
  credit_account_id: creditAccountId, transaction_date: transactionDate, vault_id: vaultId,
  employee_id: employeeId || null, status, reporting_class: reportingClass,
  reporting_category_name_ar: reportingCategory,
}));
if (ledgerRows.length !== sourceIds.length || new Set(ledgerRows.map((row) => row.source_invoice_id)).size !== sourceIds.length) {
  throw new Error("expected exactly one active ledger row per overtime invoice");
}
for (const row of ledgerRows) {
  const invoice = invoiceRows.find((candidate) => candidate.id === row.source_invoice_id);
  if (!invoice || row.amount_raw !== invoice.total_raw || row.transaction_date !== invoice.transaction_date ||
      row.vault_id !== sourceVaultId || row.employee_id || row.status !== "active" ||
      row.reporting_category_name_ar !== "رواتب وأجور") {
    throw new Error(`source overtime ledger evidence differs: ${row.source_invoice_id}`);
  }
}

const allocationRows = query(sourceDb, `
SELECT id,invoice_id,vault_id,amount::text,created_at::text
FROM invoice_vault_allocations WHERE invoice_id IN (${idsSql}) ORDER BY invoice_id,id;
`).map(([id, invoiceId, vaultId, amount, createdAt]) => ({
  id, source_invoice_id: invoiceId, vault_id: vaultId, amount_raw: fixed4(amount), created_at: createdAt,
}));
if (allocationRows.length !== sourceIds.length || new Set(allocationRows.map((row) => row.source_invoice_id)).size !== sourceIds.length) {
  throw new Error("expected exactly one source cash allocation per overtime invoice");
}
for (const row of allocationRows) {
  const invoice = invoiceRows.find((candidate) => candidate.id === row.source_invoice_id);
  if (!invoice || row.vault_id !== sourceVaultId || row.amount_raw !== invoice.total_raw) {
    throw new Error(`source overtime allocation evidence differs: ${row.source_invoice_id}`);
  }
}

const companyRows = query(targetDb, `
SELECT c.id,c.active,rc.name,co.code,m.source_archive_sha256,m.decision
FROM res_company c JOIN res_currency rc ON rc.id=c.currency_id
JOIN res_partner p ON p.id=c.partner_id JOIN res_country co ON co.id=p.country_id
JOIN baseer_noorix_company_map m ON m.company_id=c.id
WHERE c.id=${targetCompanyId} AND m.source_system='noorix' AND m.source_tenant_id='${tenantId}'
  AND m.source_company_id='${sourceCompanyId}';
`);
if (companyRows.length !== 1 || companyRows[0].join("|") !== `3|t|SAR|SA|${archiveSha}|reuse_existing_company`) {
  throw new Error("target Doha company provenance differs");
}

const vaultRows = query(targetDb, `
SELECT m.source_vault_id,m.source_vault_name,m.source_vault_type,m.decision,m.source_archive_sha256,
       j.id,j.code,j.type,j.company_id,j.default_account_id,a.code_store->>'3'
FROM baseer_noorix_liquidity_vault_map m JOIN account_journal j ON j.id=m.journal_id
JOIN account_account a ON a.id=j.default_account_id
WHERE m.source_system='noorix' AND m.source_tenant_id='${tenantId}' AND m.source_company_id='${sourceCompanyId}'
  AND m.source_vault_id='${sourceVaultId}';
`);
if (vaultRows.length !== 1 || vaultRows[0].join("|") !== `cmnf5xrdt002oy8lmpyszg9uy|نقد|cash|reuse_existing_liquidity|${archiveSha}|43|CSH1|cash|3|594|105001`) {
  throw new Error("approved Doha cash-vault map differs");
}

const journalRows = query(targetDb, "SELECT id,code,type,company_id,active FROM account_journal WHERE id=44;");
if (journalRows.length !== 1 || journalRows[0].join("|") !== "44|BPAY|general|3|t") {
  throw new Error("target Doha BPAY/44 journal differs");
}
const accountRows = query(targetDb, "SELECT id,code_store->>'3',account_type,active FROM account_account WHERE id IN (493,594) ORDER BY id;");
if (accountRows.length !== 2 || accountRows[0].join("|") !== "493|400003|expense|t" || accountRows[1].join("|") !== "594|105001|asset_cash|t") {
  throw new Error("target Doha salary/cash account allowlist differs");
}

const priorMaps = query(targetDb, `
SELECT source_invoice_id FROM baseer_noorix_historical_salary_map
WHERE source_system='noorix' AND source_tenant_id='${tenantId}' AND source_company_id='${sourceCompanyId}'
  AND source_invoice_id IN (${idsSql});
`);
if (priorMaps.length) throw new Error("a bounded overtime invoice is already historically mapped");

const ownerDecision = {
  decision_type: "owner_declared_overtime_historical_cash_settlement",
  decision_date: "2026-09-13",
  source_company_id: sourceCompanyId,
  source_invoice_ids: sourceIds,
  instruction: "Treat the four evidenced zero-tax overtime invoices as historical overtime. Do not create purchase bills, vendors, employee payslips, or employees. Post one balanced BPAY/44 entry per source invoice: debit salary expense 400003/id493 and credit only the mapped cash liquidity account 105001/id594.",
  constraints: {
    target_company_id: targetCompanyId,
    journal: { id: 44, code: "BPAY", type: "general" },
    salary_expense_account: { id: 493, code: "400003" },
    cash_liquidity: { source_vault_id: sourceVaultId, journal_id: 43, journal_code: "CSH1", account_id: 594, account_code: "105001" },
    no_purchase_bill: true, no_payment: true, no_stock: true, no_pos: true, no_payslip: true, no_employee: true,
  },
};
const ownerDecisionSha256 = sha(ownerDecision);
const records = invoiceRows.map((invoice) => {
  const ledger = ledgerRows.find((row) => row.source_invoice_id === invoice.id);
  const allocation = allocationRows.find((row) => row.source_invoice_id === invoice.id);
  const sourceEvidence = { invoice, ledger, allocation };
  return {
    source_system: "noorix", source_tenant_id: tenantId, source_company_id: sourceCompanyId,
    source_invoice_id: invoice.id, source_ledger_id: ledger.id, source_allocation_id: allocation.id,
    source_vault_id: sourceVaultId, source_supplier_id: invoice.supplier_id,
    source_invoice_number: invoice.invoice_number, source_document_kind: invoice.kind,
    business_date: invoice.transaction_date, source_net_raw: invoice.net_raw,
    source_tax_raw: invoice.tax_raw, source_total_raw: invoice.total_raw,
    source_row_sha256: sha(sourceEvidence), source_archive_sha256: archiveSha,
    canonical_key: `historical-overtime:${sourceCompanyId}:${invoice.id}`,
    owner_decision_sha256: ownerDecisionSha256,
    decision: "create_owner_declared_overtime_cash_move",
    target_company_id: targetCompanyId, target_journal_id: 44,
    target_salary_expense_account_id: 493, target_cash_journal_id: 43,
    target_cash_account_id: 594, target_amount: money(invoice.total_raw),
    target_posting_date: invoice.transaction_date,
    target_reference: `Noorix ${invoice.invoice_number} — Overtime historical cash settlement`,
    target_debit_label: `Noorix ${invoice.invoice_number} — Overtime / عمل إضافي تاريخي`,
    target_credit_label: `Noorix ${invoice.invoice_number} — Overtime cash payment / نقد`,
  };
});
const totalCents = records.reduce((sum, row) => sum + BigInt(row.target_amount.replace(".", "")), 0n);
const payload = {
  target_database: targetDb, source_archive_sha256: archiveSha,
  approved_policy: "doha_owner_declared_overtime_historical_cash_entries",
  owner_decision_sha256: ownerDecisionSha256,
  run: { name: runName, scope: "historical_salary", month: "2026-05", target_company_id: targetCompanyId },
  allowlist: {
    payroll_journal: { id: 44, code: "BPAY", type: "general" },
    salary_expense_account: { id: 493, code: "400003", type: "expense" },
    source_cash_vault: { id: sourceVaultId, name_ar: "نقد", type: "cash", target_journal_id: 43, target_journal_code: "CSH1", target_account_id: 594, target_account_code: "105001" },
  },
  report: { source_invoices: records.length, target_moves: records.length, target_move_lines: records.length * 2, total: `${totalCents / 100n}.${String(totalCents % 100n).padStart(2, "0")}`, tax: "0.00" },
  records,
};

await fs.mkdir(outputDir, { recursive: true });
await fs.writeFile(decisionPath, `${JSON.stringify(ownerDecision, null, 2)}\n`, "utf8");
await fs.writeFile(outputPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
const payloadSha256 = crypto.createHash("sha256").update(await fs.readFile(outputPath)).digest("hex");
console.log(JSON.stringify({ outputPath, decisionPath, payloadSha256, ownerDecisionSha256, report: payload.report }, null, 2));
