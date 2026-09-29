/** Build the frozen QA-only Karak owner-declared net-payroll payload read-only. */
import crypto from "node:crypto";
import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";

const sourceDb = "noorix_source_inspection_archive159_20260913";
const targetDb = "baseer_noorix_data_migration_qa_20260912";
const dbContainer = "baseer_odoo_dev-db-1";
const outputDir = ".local-backups/noorix-migration/runs/20260913-karak-net-payroll-settlement-qa-1";
const outputPath = path.join(outputDir, "karak-net-payroll-settlement-payload.json");
const archiveSha = "024606ADD82DCD78DC1835828A12D7B22C56E34924FF998ABF752134160E79E2";
const tenantId = "default-tenant-noorix-2024";
const sourceCompanyId = "cmnvui7x70001etuf8p6xz3d0";
const sourcePayrollRunId = "cmotzl3tn016i11ch29ycedtd";
const sourceRunNumber = "PR-2605-001";
const targetCompanyId = 4;

function psql(database, sql) {
  if (database === "baseer_dev") throw new Error("Production database is forbidden");
  const output = execFileSync("docker", [
    "exec", dbContainer, "psql", "-U", "odoo", "-d", database,
    "-At", "-F", "\t", "-c", sql,
  ], { encoding: "utf8", maxBuffer: 16 * 1024 * 1024 });
  return output.split(/\r?\n/).filter(Boolean).map((line) => line.split("\t"));
}

const sha = (value) => crypto.createHash("sha256").update(JSON.stringify(value)).digest("hex");

function fixed4(value) {
  const match = String(value).match(/^(\d+)(?:\.(\d+))?$/);
  if (!match) throw new Error(`Invalid non-negative source decimal: ${value}`);
  const fraction = match[2] || "";
  if (fraction.length > 4 && [...fraction.slice(4)].some((digit) => digit !== "0")) {
    throw new Error(`Source amount exceeds four decimals: ${value}`);
  }
  return `${match[1]}.${fraction.padEnd(4, "0").slice(0, 4)}`;
}

const runRows = psql(sourceDb, `
SELECT pr.id,pr.tenant_id,pr.company_id,pr.run_number,pr.payroll_month::date::text,
       pr.total_amount::text,pr.employee_count,pr.status,
       pr.advance_settlements_applied_at::date::text,pr.kind,
       pr.created_at::text,pr.updated_at::text,
       COUNT(i.id),SUM(i.gross_salary)::text,SUM(i.advances_deduct)::text,
       SUM(i.net_salary)::text,SUM(i.allowances_add)::text,SUM(i.deductions)::text
FROM payroll_runs pr JOIN payroll_run_items i ON i.payroll_run_id=pr.id
WHERE pr.id='${sourcePayrollRunId}'
GROUP BY pr.id;
`);
if (runRows.length !== 1) throw new Error(`Expected one source payroll run, found ${runRows.length}`);
const [id, sourceTenantId, companyId, runNumber, period, runNetRaw, employeeCountRaw,
  status, completionDate, kind, createdAt, updatedAt, itemCountRaw, grossRaw,
  advancesRaw, itemNetRaw, allowancesRaw, deductionsRaw] = runRows[0];
const source = {
  id, sourceTenantId, companyId, runNumber, period,
  runNetRaw: fixed4(runNetRaw), employeeCount: Number(employeeCountRaw), status,
  completionDate, kind, createdAt, updatedAt, itemCount: Number(itemCountRaw),
  grossRaw: fixed4(grossRaw), advancesRaw: fixed4(advancesRaw),
  itemNetRaw: fixed4(itemNetRaw), allowancesRaw: fixed4(allowancesRaw),
  deductionsRaw: fixed4(deductionsRaw),
};
if (source.id !== sourcePayrollRunId || source.sourceTenantId !== tenantId || source.companyId !== sourceCompanyId || source.runNumber !== sourceRunNumber) throw new Error("Source payroll identity differs");
if (source.period !== "2026-04-01" || source.completionDate !== "2026-05-06" || source.status !== "completed" || source.kind !== "regular") throw new Error("Source payroll period/completion/status differs");
if (source.employeeCount !== 8 || source.itemCount !== 8 || source.grossRaw !== "19266.6700" || source.advancesRaw !== "9050.0000" || source.itemNetRaw !== "10216.6700" || source.runNetRaw !== "10216.6700") throw new Error("Source payroll totals differ");
if (source.allowancesRaw !== "0.0000" || source.deductionsRaw !== "0.0000") throw new Error("Unexpected source allowances/deductions in bounded payroll run");

const itemRows = psql(sourceDb, `
SELECT id,employee_id,gross_salary::text,allowances_add::text,deductions::text,
       advances_deduct::text,net_salary::text
FROM payroll_run_items WHERE payroll_run_id='${sourcePayrollRunId}' ORDER BY id;
`).map(([itemId, employeeId, itemGross, allowances, deductions, advances, net]) => ({
  id: itemId, employee_id: employeeId, gross_raw: fixed4(itemGross),
  allowances_raw: fixed4(allowances), deductions_raw: fixed4(deductions),
  advances_raw: fixed4(advances), net_raw: fixed4(net),
}));
if (itemRows.length !== 8) throw new Error("Source payroll item cardinality differs");

const sourceSalaryAccountId = "cmnvui7y6000petuf4baejcs2";
const sourcePayableAccountId = `payroll-payable-${sourceCompanyId}`;
const accrualRows = psql(sourceDb, `
SELECT id,reference_type,reference_id,amount::text,debit_account_id,credit_account_id,
       transaction_date::date::text,entry_date::text,COALESCE(vault_id,''),
       COALESCE(employee_id,''),status,created_at::text
FROM ledger_entries
WHERE reference_type='payroll_accrual' AND reference_id='${sourcePayrollRunId}'
ORDER BY id;
`).map(([entryId, referenceType, referenceId, amount, debitAccountId, creditAccountId,
  transactionDate, entryDate, vaultId, employeeId, entryStatus, entryCreatedAt]) => ({
  id: entryId, reference_type: referenceType, reference_id: referenceId,
  amount_raw: fixed4(amount), debit_account_id: debitAccountId,
  credit_account_id: creditAccountId, transaction_date: transactionDate,
  entry_date: entryDate, vault_id: vaultId || null, employee_id: employeeId,
  status: entryStatus, created_at: entryCreatedAt,
}));
if (accrualRows.length !== 5) throw new Error(`Expected five source accrual rows, found ${accrualRows.length}`);
if (accrualRows.some((row) => row.reference_id !== sourcePayrollRunId || row.debit_account_id !== sourceSalaryAccountId || row.credit_account_id !== sourcePayableAccountId || row.transaction_date !== "2026-04-30" || row.vault_id || row.status !== "active")) throw new Error("Source accrual evidence differs");
const accrualTotal = accrualRows.reduce((sum, row) => sum + BigInt(row.amount_raw.replace(".", "")), 0n);
if (accrualTotal !== 102166700n) throw new Error("Five source accrual rows do not total 10,216.6700");

const vaultEvidence = psql(sourceDb, `
SELECT
 (SELECT COUNT(*) FROM payroll_run_vaults WHERE payroll_run_id='${sourcePayrollRunId}'),
 (SELECT COUNT(*) FROM payroll_run_item_vaults WHERE payroll_item_id IN
    (SELECT id FROM payroll_run_items WHERE payroll_run_id='${sourcePayrollRunId}'));
`);
if (vaultEvidence.length !== 1 || vaultEvidence[0][0] !== "0" || vaultEvidence[0][1] !== "0") throw new Error("Source unexpectedly contains a payroll bank/cash allocation");

const companyRows = psql(targetDb, `
SELECT c.id,c.active,rc.name,co.code,m.source_tenant_id,m.source_archive_sha256,m.decision
FROM res_company c
JOIN res_currency rc ON rc.id=c.currency_id
JOIN res_partner p ON p.id=c.partner_id
JOIN res_country co ON co.id=p.country_id
JOIN baseer_noorix_company_map m ON m.company_id=c.id
WHERE c.id=${targetCompanyId} AND m.source_system='noorix'
  AND m.source_company_id='${sourceCompanyId}';
`);
if (companyRows.length !== 1 || companyRows[0][1] !== "t" || companyRows[0][2] !== "SAR" || companyRows[0][3] !== "SA" || companyRows[0][4] !== tenantId || companyRows[0][5] !== archiveSha || companyRows[0][6] !== "create_historical_company") throw new Error("Approved Karak company provenance differs");

const accountRows = psql(targetDb, `
SELECT id,code_store->>'${targetCompanyId}',account_type,active
FROM account_account WHERE id IN (708,792,801,802) ORDER BY id;
`);
const expectedAccounts = new Map([
  [708, ["400003", "expense"]], [792, ["101001", "asset_cash"]],
  [801, ["201090", "liability_payable"]], [802, ["102090", "asset_receivable"]],
]);
if (accountRows.length !== 4) throw new Error("Finite payroll account allowlist is incomplete");
for (const [rawId, code, type, active] of accountRows) {
  const accountId = Number(rawId);
  const expected = expectedAccounts.get(accountId);
  if (!expected || code !== expected[0] || type !== expected[1] || active !== "t") throw new Error(`Payroll account differs: ${accountId}`);
}

const journalRows = psql(targetDb, `
SELECT id,code,type,company_id,default_account_id,active
FROM account_journal WHERE id IN (62,68,69,70) ORDER BY id;
`);
const journalById = new Map(journalRows.map(([rawId, code, type, rawCompanyId, rawAccountId, active]) => [
  Number(rawId), { code, type, company_id: Number(rawCompanyId), default_account_id: Number(rawAccountId), active: active === "t" },
]));
const bankJournal = journalById.get(62);
if (!bankJournal || !bankJournal.active || bankJournal.code !== "BNK1" || bankJournal.type !== "bank" || bankJournal.company_id !== targetCompanyId || bankJournal.default_account_id !== 792) throw new Error("BNK1/62 differs");
if (journalById.get(68)?.code !== "BPAY" || journalById.get(69)?.code !== "PSBNK" || journalById.get(70)?.code !== "PSCSH") throw new Error("Forbidden journal identities differ");

const sourceSnapshot = { payroll_run: source, payroll_items: itemRows };
const payload = {
  target_database: targetDb,
  source_archive_sha256: archiveSha,
  approved_policy: "karak_owner_declared_net_payroll_paid_from_bank_one_native_move",
  report: {
    source_payroll_runs: 1, source_items: 8, source_accrual_rows: 5,
    source_gross: "19266.6700", source_advances: "9050.0000",
    source_net: "10216.6700", target_amount: "10216.67",
    target_moves: 1, target_move_lines: 2,
  },
  allowlist: {
    target_company_id: targetCompanyId,
    bank_journal: { id: 62, code: "BNK1", type: "bank", default_account_id: 792 },
    salary_expense_account: { id: 708, code: "400003", type: "expense" },
    bank_account: { id: 792, code: "101001", type: "asset_cash" },
    unchanged_accounts: [
      { id: 801, code: "201090", type: "liability_payable" },
      { id: 802, code: "102090", type: "asset_receivable" },
    ],
    forbidden_journal_ids: [68, 69, 70],
  },
  settlement: {
    source_system: "noorix", source_tenant_id: tenantId,
    source_company_id: sourceCompanyId, source_payroll_run_id: sourcePayrollRunId,
    source_run_number: sourceRunNumber, source_row_sha256: sha(sourceSnapshot),
    source_accrual_rows_sha256: sha(accrualRows), source_accrual_count: 5,
    source_archive_sha256: archiveSha,
    canonical_key: `payroll-settlement:${sourceCompanyId}:${sourcePayrollRunId}`,
    source_gross_raw: "19266.6700", source_advances_raw: "9050.0000",
    source_net_raw: "10216.6700", source_period: "2026-04-01",
    source_completion_date: "2026-05-06", target_posting_date: "2026-05-06",
    date_basis: "owner_declaration_plus_source_completion",
    owner_declaration: "treat_net_as_paid_from_bank",
    decision: "create_owner_declared_bank_move",
    target_company_id: targetCompanyId, target_journal_id: 62,
    target_salary_expense_account_id: 708, target_bank_account_id: 792,
    target_amount: "10216.67",
    target_reference: "Noorix PR-2605-001 — owner-declared historical net salary paid",
  },
};

await fs.mkdir(outputDir, { recursive: true });
await fs.writeFile(outputPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
const payloadSha256 = crypto.createHash("sha256").update(await fs.readFile(outputPath)).digest("hex");
console.log(JSON.stringify({ outputPath, payloadSha256, report: payload.report }, null, 2));
