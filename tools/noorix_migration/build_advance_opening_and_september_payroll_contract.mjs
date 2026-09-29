/**
 * Read-only freezer for the Noorix cut-over employee-advance opening balances
 * and the two separately authorised September net-payroll settlements.
 *
 * It intentionally does not create a loan, employee, payslip, journal entry,
 * provenance map, or database record.  The payload is the contract for a
 * later QA-only writer.
 */
import crypto from "node:crypto";
import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";

const sourceDb = "noorix_source_inspection_archive159_20260913";
const targetDb = "baseer_noorix_data_migration_qa_20260912";
const dbContainer = "baseer_odoo_dev-db-1";
const outputDir = ".local-backups/noorix-migration/runs/20260913-advance-opening-and-september-payroll-qa-1";
const outputPath = path.join(outputDir, "advance-opening-and-september-payroll-contract.json");
const archiveSha = "024606ADD82DCD78DC1835828A12D7B22C56E34924FF998ABF752134160E79E2";
const tenantId = "default-tenant-noorix-2024";
const cutoverDate = "2026-09-13";

const companies = new Map([
  ["cmnf604ka009ay8lm556wgd9c", { targetCompanyId: 1, openingJournalId: 10, advanceAccountId: 588, openingEquityAccountId: 220 }],
  ["cmnaivif80001wavxxfgriptm", { targetCompanyId: 2, openingJournalId: 20, advanceAccountId: 590, openingEquityAccountId: 398 }],
  ["cmnf5xrd0001uy8lm8vja50gp", { targetCompanyId: 3, openingJournalId: 30, advanceAccountId: 593, openingEquityAccountId: 576 }],
  ["cmnvui7x70001etuf8p6xz3d0", { targetCompanyId: 4, openingJournalId: 59, advanceAccountId: 802, openingEquityAccountId: 791 }],
]);

function psql(database, sql) {
  if (database === "baseer_dev") throw new Error("Production database is forbidden");
  const output = execFileSync("docker", [
    "exec", dbContainer, "psql", "-U", "odoo", "-d", database,
    "-At", "-F", "\t", "-c", sql,
  ], { encoding: "utf8", maxBuffer: 16 * 1024 * 1024 });
  return output.split(/\r?\n/).filter(Boolean).map((line) => line.split("\t"));
}

const sha = (value) => crypto.createHash("sha256").update(JSON.stringify(value)).digest("hex");
const fileSha = async (file) => crypto.createHash("sha256").update(await fs.readFile(file)).digest("hex");
const fixed4 = (value) => {
  const match = String(value || "0").match(/^(\d+)(?:\.(\d+))?$/);
  if (!match || ((match[2] || "").length > 4 && /[1-9]/.test((match[2] || "").slice(4)))) throw new Error(`Invalid source amount: ${value}`);
  return `${match[1]}.${(match[2] || "").padEnd(4, "0").slice(0, 4)}`;
};
const units4 = (value) => { const [whole, fraction] = fixed4(value).split("."); return BigInt(whole) * 10000n + BigInt(fraction); };
const cents = (value) => (units4(value) * 2n + 100n) / 200n;
const money = (value) => `${value / 100n}.${String(value % 100n).padStart(2, "0")}`;
const sumMoney = (rows, field) => money(rows.reduce((total, row) => total + cents(row[field]), 0n));
// Exact normalized Arabic identity: Unicode NFKC, no tatweel/diacritics and
// collapsed whitespace.  It deliberately does not treat different letters as
// equivalent, so there is no fuzzy employee matching.
const normalizeArabicName = (name) => String(name || "").normalize("NFKC")
  .replace(/[\u064B-\u065F\u0670\u0640]/g, "").replace(/\s+/g, " ").trim();

const companySql = [...companies.keys()].map((id) => `'${id}'`).join(",");
const advanceRows = psql(sourceDb, `
SELECT i.id,i.tenant_id,i.company_id,i.invoice_number,i.transaction_date::date::text,
       i.total_amount::text,COALESCE(i.settled_amount,0)::text,COALESCE(i.settled_at::date::text,''),
       i.vault_id,i.status,i.employee_id,e.name
FROM invoices i JOIN employees e ON e.id=i.employee_id
WHERE i.status='active' AND i.kind='advance' AND i.company_id IN (${companySql})
ORDER BY i.company_id,i.transaction_date,i.id;
`).map(([id, tenant, companyId, invoiceNumber, date, total, settled, settledAt, vaultId, status, employeeId, employeeName]) => ({
  id, tenant, company_id: companyId, invoice_number: invoiceNumber, date,
  total_raw: fixed4(total), settled_raw: fixed4(settled), settled_at: settledAt || null,
  vault_id: vaultId, status, employee_id: employeeId, employee_name: employeeName,
}));
if (advanceRows.length !== 194 || sumMoney(advanceRows, "total_raw") !== "154526.00") throw new Error("Active advance source population differs");
if (advanceRows.some((row) => row.tenant !== tenantId || !companies.has(row.company_id) || row.status !== "active" || cents(row.settled_raw) > cents(row.total_raw))) throw new Error("Advance source identity or amount differs");

const targetEmployees = psql(targetDb, `
SELECT id::text,company_id::text,name::text,active::text,COALESCE(work_contact_id::text,'')
FROM hr_employee WHERE company_id IN (1,2,3,4) ORDER BY company_id,id;
`).map(([id, companyId, name, active, workContactId]) => ({ id: Number(id), company_id: Number(companyId), name: name.replace(/^"|"$/g, ""), active: active === "t" || active === "true", work_contact_id: workContactId ? Number(workContactId) : null }));

const liquidityMaps = psql(targetDb, `
SELECT source_company_id,source_vault_id,journal_id::text,source_vault_type,source_vault_name
FROM baseer_noorix_liquidity_vault_map
WHERE source_system='noorix' AND source_tenant_id='${tenantId}' AND source_company_id IN (${companySql})
ORDER BY source_company_id,source_vault_id;
`).map(([companyId, vaultId, journalId, vaultType, vaultName]) => ({ company_id: companyId, vault_id: vaultId, journal_id: Number(journalId), vault_type: vaultType, vault_name: vaultName }));
const liquidityByKey = new Map(liquidityMaps.map((row) => [`${row.company_id}:${row.vault_id}`, row]));

const openingRows = advanceRows.map((row) => ({ ...row, residual_raw: fixed4((units4(row.total_raw) - units4(row.settled_raw)).toString().replace(/(\d{4})$/, ".$1")) })).filter((row) => cents(row.residual_raw) > 0n);
if (openingRows.length !== 12 || sumMoney(openingRows, "residual_raw") !== "17210.00") throw new Error("Opening advance residual population differs");
const karakOpening = openingRows.filter((row) => row.company_id === "cmnvui7x70001etuf8p6xz3d0");
if (karakOpening.length) throw new Error("Karak must have no outstanding opening advance");

const targetUsed = new Map();
const openingRecords = openingRows.map((row) => {
  const target = companies.get(row.company_id);
  const normalized = normalizeArabicName(row.employee_name);
  const candidates = targetEmployees.filter((employee) => employee.company_id === target.targetCompanyId && normalizeArabicName(employee.name) === normalized);
  if (candidates.length !== 1) throw new Error(`Employee crosswalk is not one-to-one for ${row.invoice_number}: ${row.employee_name}`);
  const employee = candidates[0];
  if (!employee.active || !employee.work_contact_id) throw new Error(`Target employee is not issuable for ${row.invoice_number}`);
  const prior = targetUsed.get(employee.id);
  if (prior && prior !== row.employee_id) throw new Error(`Target employee would map from multiple source employees: ${employee.id}`);
  targetUsed.set(employee.id, row.employee_id);
  const vault = liquidityByKey.get(`${row.company_id}:${row.vault_id}`);
  if (!vault) throw new Error(`Missing source-vault mapping for ${row.invoice_number}`);
  return {
    source_system: "noorix", source_tenant_id: tenantId, source_company_id: row.company_id,
    source_invoice_id: row.id, source_invoice_number: row.invoice_number,
    source_employee_id: row.employee_id, source_employee_name: row.employee_name,
    source_employee_name_normalized: normalized, source_vault_id: row.vault_id,
    source_issued_raw: row.total_raw, source_settled_raw: row.settled_raw,
    source_opening_residual_raw: row.residual_raw, source_as_of_date: cutoverDate,
    source_row_sha256: sha(row), source_archive_sha256: archiveSha,
    canonical_key: `employee-advance-opening:${row.company_id}:${row.id}`,
    decision: "opening_outstanding_only_invoice_settled_amount_authoritative",
    target_company_id: target.targetCompanyId, target_employee_id: employee.id,
    target_employee_work_contact_id: employee.work_contact_id,
    target_loan_origin_journal_id: vault.journal_id,
    target_opening_journal_id: target.openingJournalId,
    target_advance_account_id: target.advanceAccountId,
    target_opening_equity_account_id: target.openingEquityAccountId,
    target_amount: money(cents(row.residual_raw)), target_posting_date: cutoverDate,
    target_reference: `Noorix opening advance ${row.invoice_number}`,
  };
});

const groupedOpening = Object.fromEntries([...companies.entries()].map(([sourceCompanyId, target]) => {
  const rows = openingRecords.filter((row) => row.source_company_id === sourceCompanyId);
  return [sourceCompanyId, { target_company_id: target.targetCompanyId, documents: rows.length, employees: new Set(rows.map((row) => row.target_employee_id)).size, total: sumMoney(rows, "target_amount") }];
}));
if (JSON.stringify(groupedOpening) !== JSON.stringify({
  cmnf604ka009ay8lm556wgd9c: { target_company_id: 1, documents: 4, employees: 3, total: "5100.00" },
  cmnaivif80001wavxxfgriptm: { target_company_id: 2, documents: 6, employees: 5, total: "12000.00" },
  cmnf5xrd0001uy8lm8vja50gp: { target_company_id: 3, documents: 2, employees: 1, total: "110.00" },
  cmnvui7x70001etuf8p6xz3d0: { target_company_id: 4, documents: 0, employees: 0, total: "0.00" },
})) throw new Error("Opening advance grouping differs");

const septemberRows = psql(sourceDb, `
SELECT i.id,i.tenant_id,i.company_id,i.invoice_number,i.transaction_date::date::text,i.kind,i.status,
       i.net_amount::text,i.tax_amount::text,i.total_amount::text,
       COALESCE(l.id,''),COALESCE(l.amount::text,''),COALESCE(l.vault_id,''),COALESCE(l.status,''),
       COALESCE(a.id,''),COALESCE(a.vault_id,''),COALESCE(a.amount::text,'')
FROM invoices i
LEFT JOIN ledger_entries l ON l.reference_type='salary' AND l.reference_id=i.id
LEFT JOIN invoice_vault_allocations a ON a.invoice_id=i.id
WHERE i.id IN ('cmtptodv8000510d67ed5krb7','cmtpttvig000g10d6il41nm44')
ORDER BY i.id,l.id,a.id;
`);
const salaryRows = new Map();
for (const row of septemberRows) {
  const [invoiceId, tenant, companyId, number, date, kind, status, net, tax, total, ledgerId, ledgerAmount, ledgerVault, ledgerStatus, allocationId, allocationVault, allocationAmount] = row;
  if (!salaryRows.has(invoiceId)) salaryRows.set(invoiceId, { id: invoiceId, tenant, company_id: companyId, number, date, kind, status, net_raw: fixed4(net), tax_raw: fixed4(tax), total_raw: fixed4(total), ledgers: [], allocations: [] });
  const record = salaryRows.get(invoiceId);
  if (ledgerId && !record.ledgers.some((item) => item.id === ledgerId)) record.ledgers.push({ id: ledgerId, amount_raw: fixed4(ledgerAmount), vault_id: ledgerVault, status: ledgerStatus });
  if (allocationId && !record.allocations.some((item) => item.id === allocationId)) record.allocations.push({ id: allocationId, vault_id: allocationVault, amount_raw: fixed4(allocationAmount) });
}
if (salaryRows.size !== 2) throw new Error("September salary source cardinality differs");
const salaryPolicy = new Map([
  ["cmtptodv8000510d67ed5krb7", { target_company_id: 1, payroll_journal_id: 40, salary_account_id: 137, expected_total: "17749.97", expected_vaults: [["cmnf604l100a6y8lm6h3y6ocx", 13, "17749.97"]] }],
  ["cmtpttvig000g10d6il41nm44", { target_company_id: 2, payroll_journal_id: 42, salary_account_id: 315, expected_total: "29363.10", expected_vaults: [["cmnaiviq8000xwavxoqjln3z7", 23, "6565.00"], ["cmngf47fp0027gwgizvpdbssf", 75, "22798.10"]] }],
]);
const septemberPayrollRecords = [...salaryRows.values()].sort((a, b) => a.id.localeCompare(b.id)).map((row) => {
  const policy = salaryPolicy.get(row.id);
  if (!policy || row.tenant !== tenantId || row.kind !== "salary" || row.status !== "active" || row.tax_raw !== "0.0000" || row.total_raw !== row.net_raw || money(cents(row.total_raw)) !== policy.expected_total) throw new Error(`September payroll source contract differs: ${row.id}`);
  if (row.ledgers.length !== policy.expected_vaults.length || row.allocations.length !== policy.expected_vaults.length) throw new Error(`September payroll ledger/allocation cardinality differs: ${row.id}`);
  const settlements = policy.expected_vaults.map(([sourceVaultId, journalId, amount]) => {
    const ledger = row.ledgers.find((item) => item.vault_id === sourceVaultId && item.amount_raw === fixed4(amount) && item.status === "active");
    const allocation = row.allocations.find((item) => item.vault_id === sourceVaultId && item.amount_raw === fixed4(amount));
    const mappedVault = liquidityByKey.get(`${row.company_id}:${sourceVaultId}`);
    if (!ledger || !allocation || !mappedVault || mappedVault.journal_id !== journalId) throw new Error(`September payroll settlement evidence differs: ${row.id}:${sourceVaultId}`);
    return { source_ledger_id: ledger.id, source_allocation_id: allocation.id, source_vault_id: sourceVaultId, target_liquidity_journal_id: journalId, target_amount: amount };
  });
  if (sumMoney(settlements, "target_amount") !== policy.expected_total) throw new Error(`September payroll settlement total differs: ${row.id}`);
  return {
    source_system: "noorix", source_tenant_id: tenantId, source_company_id: row.company_id,
    source_invoice_id: row.id, source_invoice_number: row.number, source_date: row.date,
    source_net_raw: row.net_raw, source_tax_raw: row.tax_raw, source_total_raw: row.total_raw,
    source_archive_sha256: archiveSha, source_row_sha256: sha(row),
    canonical_key: `historical-net-payroll:${row.company_id}:${row.id}`,
    decision: "historical_net_payroll_only_no_payslip_no_employee_no_advance_recovery",
    target_company_id: policy.target_company_id, target_payroll_journal_id: policy.payroll_journal_id,
    target_salary_expense_account_id: policy.salary_account_id, target_posting_date: row.date,
    target_amount: policy.expected_total, target_reference: `Noorix ${row.number} — historical net salary settlement`, settlements,
  };
});

const payload = {
  schema_version: 1,
  generated_at: "2026-09-13T00:00:00.000Z",
  target_database: targetDb,
  source_archive_sha256: archiveSha,
  source_tenant_id: tenantId,
  run_prefix: "20260913-noorix-advance-opening-and-september-payroll-qa-1",
  policy: {
    advance_balance_authority: "invoices.settled_amount; payroll_advance_settlements and advance_settlement ledger history are retained only as conflicting source evidence and are not replayed",
    advance_strategy: "opening_outstanding_only; do not recreate historic cash/bank disbursements or historic recoveries",
    employee_crosswalk: "exact normalized Arabic name, same target company, exactly one target employee, append-only provenance",
    prohibited: ["baseer_dev", "employee_creation", "payslip_creation", "stock", "pos", "cash_or_bank_effect_for_opening_advances", "replay_of_source_advance_settlements"],
  },
  preflight: {
    active_source_advances: 194, source_issued_total: "154526.00", source_settled_total_by_invoice_field: "137316.00",
    source_opening_total: "17210.00", source_opening_documents: 12, source_opening_employees: 9,
    crosswalks_one_to_one: 9, crosswalks_missing: 0, crosswalks_ambiguous: 0,
    karak_opening_documents: 0, karak_opening_total: "0.00",
    native_loan_model_limitation: "baseer.hr.loan.action_disburse always credits a cash/bank journal; it cannot be used to establish an opening residual without a dedicated migration writer that links the loan to the opening MISC entry instead",
    required_runtime_contract: "QA-only migration writer/model must create a posted MISC opening entry plus a running baseer.hr.loan and append-only source map in one transaction; no native action_disburse call",
  },
  accounting_effects: {
    opening_advances: "For each of 12 residual source invoices: debit the company employee-advance receivable (102090) with the mapped employee work contact; credit only that company's undisttributed-profits/losses opening account (999999). No liquidity account, payment, or payroll expense is affected.",
    september_net_payroll: "Two posted BPAY historical entries only: ARZ debit salary expense 400003 17,749.97 / credit BNK1 17,749.97; Al Moallem debit salary expense 400003 29,363.10 / credit BNK1 6,565.00 and KEET 22,798.10. No employee, payslip, payable, or advance account line is created by either September move.",
  },
  opening_by_company: groupedOpening,
  opening_advance_records: openingRecords,
  september_net_payroll_records: septemberPayrollRecords,
};

await fs.mkdir(outputDir, { recursive: true });
await fs.writeFile(outputPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
console.log(JSON.stringify({ outputPath, payloadSha256: await fileSha(outputPath), opening: { documents: openingRecords.length, employees: new Set(openingRecords.map((row) => row.target_employee_id)).size, total: sumMoney(openingRecords, "target_amount"), byCompany: groupedOpening }, septemberPayroll: { moves: septemberPayrollRecords.length, total: sumMoney(septemberPayrollRecords, "target_amount") }, qaWrite: false }, null, 2));
