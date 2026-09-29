/** Read-only freezer for the owner-declared September unpaid-payroll correction. */
import crypto from "node:crypto";
import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";

const sourceDb = "noorix_source_inspection_archive159_20260913";
const targetDb = "baseer_noorix_data_migration_qa_20260912";
const container = "baseer_odoo_dev-db-1";
const archive = "024606ADD82DCD78DC1835828A12D7B22C56E34924FF998ABF752134160E79E2";
const tenant = "default-tenant-noorix-2024";
const outputDir = ".local-backups/noorix-migration/runs/20260913-september-payroll-unpaid-correction-qa-1";
const payloadPath = path.join(outputDir, "september-payroll-unpaid-correction-contract.json");
const decisionPath = path.join(outputDir, "owner-unpaid-decision.json");

function q(db, sql) {
  if (db === "baseer_dev") throw new Error("Production database is forbidden");
  return execFileSync("docker", ["exec", container, "psql", "-U", "odoo", "-d", db, "-At", "-F", "\t", "-c", sql], { encoding: "utf8" })
    .split(/\r?\n/).filter(Boolean).map((line) => line.split("\t"));
}
const sha = (v) => crypto.createHash("sha256").update(JSON.stringify(v)).digest("hex");
const fileSha = async (p) => crypto.createHash("sha256").update(await fs.readFile(p)).digest("hex");
const fixed4 = (v) => {
  const m = String(v || "0").match(/^(\d+)(?:\.(\d+))?$/);
  if (!m || ((m[2] || "").length > 4 && /[1-9]/.test((m[2] || "").slice(4)))) throw new Error(`invalid amount ${v}`);
  return `${m[1]}.${(m[2] || "").padEnd(4, "0").slice(0, 4)}`;
};
const cents = (v) => { const [w, f] = fixed4(v).split("."); return ((BigInt(w) * 10000n + BigInt(f)) * 2n + 100n) / 200n; };
const money = (v) => `${v / 100n}.${String(v % 100n).padStart(2, "0")}`;

const ownerDecision = {
  decision_date: "2026-09-13",
  owner_instruction: "SAL-PR-2609-001 for ARZ and Al Moallem remains unpaid; preserve the audit trail by reversing the incorrect net-liquidity moves and replacing them with historical salary accruals.",
  accounting_decision: "reverse_posted_net_settlement_then_post_historical_accrual",
  prohibited: ["payment", "payslip", "employee", "advance_change", "cash_bank_keeta_effect_after_correction"],
};
await fs.mkdir(outputDir, { recursive: true });
await fs.writeFile(decisionPath, `${JSON.stringify(ownerDecision, null, 2)}\n`);
const ownerDecisionSha = await fileSha(decisionPath);

const sourceRuns = q(sourceDb, `
SELECT pr.id,pr.tenant_id,pr.company_id,pr.run_number,pr.payroll_month::date::text,pr.status,pr.total_amount::text,
       pr.advance_settlements_applied_at::text,COUNT(i.id),SUM(i.gross_salary)::text,SUM(i.advances_deduct)::text,SUM(i.net_salary)::text
FROM payroll_runs pr JOIN payroll_run_items i ON i.payroll_run_id=pr.id
WHERE pr.id IN ('cmtpq3jhg038rgvswzfhshmxy','cmtpqox61039hgvswhq77ha46') GROUP BY pr.id ORDER BY pr.id;
`).map(([id, tenantId, companyId, number, month, status, total, appliedAt, items, gross, advances, net]) => ({ id, tenant_id: tenantId, company_id: companyId, number, month, status, total_raw: fixed4(total), advance_settlements_applied_at: appliedAt, items: Number(items), gross_raw: fixed4(gross), advances_raw: fixed4(advances), net_raw: fixed4(net) }));
if (sourceRuns.length !== 2) throw new Error("source payroll runs differ");

const sourceInvoices = q(sourceDb, `
SELECT id,tenant_id,company_id,invoice_number,kind,transaction_date::date::text,status,net_amount::text,tax_amount::text,total_amount::text
FROM invoices WHERE id IN ('cmtptodv8000510d67ed5krb7','cmtpttvig000g10d6il41nm44') ORDER BY id;
`).map(([id, tenantId, companyId, number, kind, date, status, net, tax, total]) => ({ id, tenant_id: tenantId, company_id: companyId, number, kind, date, status, net_raw: fixed4(net), tax_raw: fixed4(tax), total_raw: fixed4(total) }));
if (sourceInvoices.length !== 2) throw new Error("source salary invoices differ");
const sourceLedgers = q(sourceDb, `SELECT id,reference_id,reference_type,amount::text,COALESCE(vault_id,''),status,transaction_date::date::text FROM ledger_entries WHERE reference_id IN ('cmtptodv8000510d67ed5krb7','cmtpttvig000g10d6il41nm44') ORDER BY reference_id,id;`).map(([id, invoiceId, type, amount, vault, status, date]) => ({ id, invoice_id: invoiceId, type, amount_raw: fixed4(amount), vault_id: vault || null, status, date }));
const sourceAllocations = q(sourceDb, `SELECT id,invoice_id,vault_id,amount::text FROM invoice_vault_allocations WHERE invoice_id IN ('cmtptodv8000510d67ed5krb7','cmtpttvig000g10d6il41nm44') ORDER BY invoice_id,id;`).map(([id, invoiceId, vaultId, amount]) => ({ id, invoice_id: invoiceId, vault_id: vaultId, amount_raw: fixed4(amount) }));

const maps = q(targetDb, `
SELECT m.id::text,m.source_company_id,m.source_invoice_id,m.target_amount::text,m.move_id::text,am.state,am.date::text,am.journal_id::text,COALESCE(am.reversed_entry_id::text,''),am.ref
FROM baseer_noorix_historical_salary_map m JOIN account_move am ON am.id=m.move_id
WHERE m.source_invoice_id IN ('cmtptodv8000510d67ed5krb7','cmtpttvig000g10d6il41nm44') ORDER BY m.source_invoice_id;
`).map(([mapId, companyId, invoiceId, amount, moveId, state, date, journalId, reversedEntryId, ref]) => ({ map_id: Number(mapId), source_company_id: companyId, source_invoice_id: invoiceId, target_amount: money(cents(amount)), original_move_id: Number(moveId), original_move_state: state, original_move_date: date, original_journal_id: Number(journalId), original_reversed_entry_id: reversedEntryId ? Number(reversedEntryId) : null, original_ref: ref }));
if (maps.length !== 2 || maps.some((m) => m.original_move_state !== "posted" || m.original_reversed_entry_id)) throw new Error("original historical payroll maps/moves differ");

const policy = new Map([
  ["cmtptodv8000510d67ed5krb7", { source_company_id: "cmnf604ka009ay8lm556wgd9c", source_run_id: "cmtpq3jhg038rgvswzfhshmxy", target_company_id: 1, payroll_journal_id: 40, salary_account_id: 137, salary_payable_account_id: 587, expected_total: "17749.97" }],
  ["cmtpttvig000g10d6il41nm44", { source_company_id: "cmnaivif80001wavxxfgriptm", source_run_id: "cmtpqox61039hgvswhq77ha46", target_company_id: 2, payroll_journal_id: 42, salary_account_id: 315, salary_payable_account_id: 589, expected_total: "29363.10" }],
]);
const records = [...policy.entries()].map(([invoiceId, p]) => {
  const invoice = sourceInvoices.find((r) => r.id === invoiceId);
  const run = sourceRuns.find((r) => r.id === p.source_run_id);
  const original = maps.find((r) => r.source_invoice_id === invoiceId);
  const allocations = sourceAllocations.filter((r) => r.invoice_id === invoiceId);
  const ledgers = sourceLedgers.filter((r) => r.invoice_id === invoiceId);
  const contract = { invoice: !!invoice, run: !!run, original: !!original, invoiceTenant: invoice?.tenant_id === tenant, invoiceCompany: invoice?.company_id === p.source_company_id, invoiceKind: invoice?.kind === "salary", invoiceStatus: invoice?.status === "active", invoiceDate: invoice?.date === "2026-08-31", invoiceTax: invoice?.tax_raw === "0.0000", invoiceTotal: invoice && money(cents(invoice.total_raw)) === p.expected_total, runTenant: run?.tenant_id === tenant, runCompany: run?.company_id === p.source_company_id, runNumber: run?.number === "PR-2609-001", runMonth: run?.month === "2026-08-01", runStatus: run?.status === "completed", runNet: run?.net_raw === invoice?.total_raw, mapTotal: original?.target_amount === p.expected_total, mapDate: original?.original_move_date === "2026-08-31", mapJournal: original?.original_journal_id === p.payroll_journal_id };
  if (Object.values(contract).some((value) => value === false)) throw new Error(`source/target contract differs: ${invoiceId}: ${JSON.stringify(contract)}`);
  if (!allocations.length) throw new Error(`missing source allocation: ${invoiceId}`);
  const ledgerTotal = money(ledgers.reduce((n, l) => n + cents(l.amount_raw), 0n));
  const allocationTotal = money(allocations.reduce((n, a) => n + cents(a.amount_raw), 0n));
  if (allocationTotal !== p.expected_total) throw new Error(`allocation total differs: ${invoiceId}`);
  return {
    source_system: "noorix", source_tenant_id: tenant, source_company_id: p.source_company_id,
    source_payroll_run_id: p.source_run_id, source_invoice_id: invoiceId, source_invoice_number: invoice.number,
    source_payroll_month: run.month, source_invoice_date: invoice.date, source_net_raw: invoice.net_raw,
    source_advances_raw: run.advances_raw, source_total_raw: invoice.total_raw, source_tax_raw: invoice.tax_raw,
    source_allocations: allocations, source_ledger_rows_observed: ledgers,
    source_ledger_total_observed: ledgerTotal, source_allocation_total: allocationTotal,
    source_evidence_conflict: "owner_declared_unpaid_overrides_observed_source_ledger_rows; do_not_replay_liquidity",
    source_row_sha256: sha({ invoice, run, allocations, ledgers, original }), source_archive_sha256: archive,
    owner_decision_sha256: ownerDecisionSha, canonical_key: `historical-salary-unpaid-correction:${p.source_company_id}:${invoiceId}`,
    decision: "reverse_incorrect_net_liquidity_move_and_create_historical_salary_payable_accrual",
    target_company_id: p.target_company_id, target_payroll_journal_id: p.payroll_journal_id,
    target_salary_expense_account_id: p.salary_account_id, target_salary_payable_account_id: p.salary_payable_account_id,
    target_amount: p.expected_total, target_posting_date: "2026-08-31",
    original_historical_salary_map_id: original.map_id, original_move_id: original.original_move_id,
    reversal_reference: `Noorix ${invoice.number} — reverse incorrect net settlement (unpaid)`,
    replacement_reference: `Noorix ${invoice.number} — historical unpaid salary accrual`,
  };
});
if (money(records.reduce((n, r) => n + cents(r.target_amount), 0n)) !== "47113.07") throw new Error("correction total differs");

const payload = { schema_version: 1, generated_at: "2026-09-13T00:00:00.000Z", target_database: targetDb, source_archive_sha256: archive, source_tenant_id: tenant, run_prefix: "20260913-noorix-september-payroll-unpaid-correction-qa-1", owner_decision_sha256: ownerDecisionSha, policy: { original_salary_maps_are_immutable: true, preserve_audit: "post_reversal_then_replacement_accrual; never edit/delete original map or move", no_cash_after_correction: true, prohibited: ownerDecision.prohibited }, records, report: { source_invoices: 2, original_incorrect_moves: 2, reversals: 2, replacement_accrual_moves: 2, correction_moves: 4, total: "47113.07", opening_advances_touched: "0.00", expected_final_effect: { salary_expense_debit: "47113.07", salary_payable_credit: "47113.07", bank_cash_keeta_net_effect: "0.00" } } };
await fs.writeFile(payloadPath, `${JSON.stringify(payload, null, 2)}\n`);
console.log(JSON.stringify({ decisionPath, ownerDecisionSha256: ownerDecisionSha, payloadPath, payloadSha256: await fileSha(payloadPath), report: payload.report, observedSourceLedgerRows: sourceLedgers.length, observedSourceLedgerTotal: money(sourceLedgers.reduce((n, r) => n + cents(r.amount_raw), 0n)) }, null, 2));
