/** Build approved company-scoped Noorix sales-summary waves for isolated QA. */
import crypto from "node:crypto";
import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";

const sourceDb = "noorix_source_inspection_archive159_20260913";
const targetDb = "baseer_noorix_data_migration_qa_20260912";
const dbContainer = "baseer_odoo_dev-db-1";
const outputDir = ".local-backups/noorix-migration/runs/20260913-sales-summary-qa-1";
const outputPath = path.join(outputDir, "sales-summary-payload.json");
const archiveSha = "024606ADD82DCD78DC1835828A12D7B22C56E34924FF998ABF752134160E79E2";
const tenantId = "default-tenant-noorix-2024";
const companyKeys = new Map([
  ["cmnf604ka009ay8lm556wgd9c", "arz"],
  ["cmnaivif80001wavxxfgriptm", "almoallem"],
  ["cmnf5xrd0001uy8lm8vja50gp", "doha"],
  ["cmnvui7x70001etuf8p6xz3d0", "karak"],
]);

function psql(database, sql) {
  const output = execFileSync("docker", ["exec", dbContainer, "psql", "-U", "odoo", "-d", database, "-At", "-F", "\t", "-c", sql], { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
  return output.split(/\r?\n/).filter((line) => line.length).map((line) => line.split("\t"));
}

function sha(value) {
  return crypto.createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

function cents(value) {
  const text = typeof value === "number" ? value.toFixed(2) : String(value);
  const match = text.match(/^(-?)(\d+)(?:\.(\d+))?$/);
  if (!match) throw new Error(`Invalid money amount: ${value}`);
  const fraction = match[3] || "";
  if (fraction.slice(2).split("").some((digit) => digit !== "0")) throw new Error(`Non-cent amount: ${value}`);
  const absolute = Number(match[2]) * 100 + Number(fraction.padEnd(2, "0").slice(0, 2));
  return match[1] ? -absolute : absolute;
}

function moneyFromCents(value) {
  return Number((value / 100).toFixed(2));
}

function channelKey(name, type) {
  const normalized = name.trim().toLowerCase();
  if (type === "cash" || normalized === "نقد" || normalized === "نقدي") return "cash";
  if (type === "bank" || normalized === "بنك" || normalized === "البنك") return "bank";
  if (normalized.includes("هنجر") || normalized.includes("هنقر") || normalized.includes("hunger")) return "hungerstation";
  if (normalized.includes("كيتا") || normalized.includes("keeta")) return "keeta";
  if (normalized.includes("جاهز") || normalized.includes("jahez")) return "jahez";
  throw new Error(`Unsupported Noorix sales channel: ${name} (${type})`);
}

const ids = [...companyKeys.keys()].map((id) => `'${id}'`).join(",");
const sourceRows = psql(sourceDb, `
SELECT ds.id,ds.tenant_id,ds.company_id,ds.summary_number,ds.transaction_date::date::text,
       ds.customer_count::text,ds.cash_on_hand::text,ds.total_amount::text,
       encode(convert_to(COALESCE(ds.notes,''),'UTF8'),'hex'),
       ds.status,ds.entry_date::text,ds.created_at::text,ds.updated_at::text,ds.shift,
       encode(convert_to(COALESCE(ds.day_context::text,''),'UTF8'),'hex'),COALESCE(i.id,''),COALESCE(i.invoice_number,''),
       COALESCE(i.total_amount::text,''),COALESCE(i.net_amount::text,''),COALESCE(i.tax_amount::text,'')
FROM daily_sales_summaries ds
LEFT JOIN invoices i ON i.daily_sales_summary_id=ds.id
WHERE ds.company_id IN (${ids}) AND ds.status='active'
ORDER BY ds.company_id,ds.transaction_date,ds.shift,ds.id;
`).map(([id, sourceTenantId, companyId, summaryNumber, businessDate, customers, cashOnHand, gross, notes, status,
  entryDate, createdAt, updatedAt, shift, dayContext, invoiceId, invoiceNumber, invoiceTotal, invoiceNet, invoiceTax]) => ({
  id, sourceTenantId, companyId, summaryNumber, businessDate, customers: Number(customers),
  cashOnHand: Number(cashOnHand), grossCents: cents(gross), notes: Buffer.from(notes, "hex").toString("utf8"),
  status, entryDate, createdAt, updatedAt,
  shift, dayContext: Buffer.from(dayContext, "hex").toString("utf8"), invoiceId, invoiceNumber,
  invoiceTotal: invoiceTotal ? Number(invoiceTotal) : null,
  invoiceNet: invoiceNet ? Number(invoiceNet) : null,
  invoiceTax: invoiceTax ? Number(invoiceTax) : null,
}));
if (sourceRows.length !== 670 || sourceRows.some((row) => row.sourceTenantId !== tenantId || !companyKeys.has(row.companyId))) {
  throw new Error(`Expected 670 active approved source summaries, found ${sourceRows.length}`);
}

const channelRows = psql(sourceDb, `
SELECT ch.id,ch.summary_id,v.id,v.name_ar,v.type,COALESCE(v.payment_method,''),ch.amount::text
FROM daily_sales_channels ch
JOIN daily_sales_summaries ds ON ds.id=ch.summary_id
JOIN vaults v ON v.id=ch.vault_id
WHERE ds.company_id IN (${ids}) AND ds.status='active'
ORDER BY ch.summary_id,v.id,ch.id;
`).map(([id, summaryId, vaultId, name, type, paymentMethod, amount]) => ({
  id, summaryId, vaultId, name, type, paymentMethod, amountCents: cents(amount), key: channelKey(name, type),
}));
const channelsBySummary = new Map();
for (const row of channelRows) channelsBySummary.set(row.summaryId, [...(channelsBySummary.get(row.summaryId) || []), row]);
for (const row of sourceRows) {
  const channelTotal = (channelsBySummary.get(row.id) || []).reduce((sum, channel) => sum + channel.amountCents, 0);
  if (channelTotal !== row.grossCents) throw new Error(`Channel total mismatch for ${row.summaryNumber}`);
}

const targetCompanyRows = psql(targetDb, `
SELECT m.source_company_id,m.company_id
FROM baseer_noorix_company_map m
JOIN baseer_noorix_migration_run r ON r.id=m.run_id
WHERE r.name='20260913-noorix-company-master-qa-1' AND m.source_company_id IN (${ids})
ORDER BY m.source_company_id;
`);
if (targetCompanyRows.length !== 4) throw new Error(`Expected four target company maps, found ${targetCompanyRows.length}`);
const targetCompanyBySource = new Map(targetCompanyRows.map(([sourceId, targetId]) => [sourceId, Number(targetId)]));

const targetSetupRows = psql(targetDb, `
SELECT pc.company_id,pc.id,ppm.id,cat.kind,ppm.name->>'en_US'
FROM pos_config pc
JOIN pos_config_pos_payment_method_rel rel ON rel.pos_config_id=pc.id
JOIN pos_payment_method ppm ON ppm.id=rel.pos_payment_method_id
JOIN baseer_pos_payment_category cat ON cat.id=ppm.baseer_category_id
WHERE pc.baseer_summary_only AND pc.active AND pc.company_id IN (${[...targetCompanyBySource.values()].join(",")})
ORDER BY pc.company_id,ppm.id;
`);
const targetSetup = new Map();
for (const [companyIdText, configIdText, methodIdText, kind, methodName] of targetSetupRows) {
  const companyId = Number(companyIdText);
  const current = targetSetup.get(companyId) || { configId: Number(configIdText), methods: new Map() };
  if (current.configId !== Number(configIdText)) throw new Error(`Multiple active summary configs for company ${companyId}`);
  let key = kind;
  if (kind === "platform") key = channelKey(methodName, "app");
  current.methods.set(key, Number(methodIdText));
  targetSetup.set(companyId, current);
}

const groups = new Map();
for (const source of sourceRows) {
  const mergeArz = companyKeys.get(source.companyId) === "arz" && source.businessDate === "2026-05-26";
  const targetShift = mergeArz ? "all" : source.shift;
  const canonicalKey = `sales:${companyKeys.get(source.companyId)}:${source.businessDate}:${targetShift}`;
  const group = groups.get(canonicalKey) || {
    canonical_key: canonicalKey,
    wave_key: companyKeys.get(source.companyId),
    source_company_id: source.companyId,
    target_company_id: targetCompanyBySource.get(source.companyId),
    business_date: source.businessDate,
    period_scope: targetShift,
    day_schedule: targetShift === "all" ? "all" : "split",
    customer_count: 0,
    grossCents: 0,
    allocationCents: new Map(),
    source_rows: [],
  };
  group.customer_count += source.customers;
  group.grossCents += source.grossCents;
  for (const channel of channelsBySummary.get(source.id) || []) {
    group.allocationCents.set(channel.key, (group.allocationCents.get(channel.key) || 0) + channel.amountCents);
  }
  const sourceSnapshot = {
    id: source.id,
    sourceTenantId: source.sourceTenantId,
    companyId: source.companyId,
    summaryNumber: source.summaryNumber,
    businessDate: source.businessDate,
    customers: source.customers,
    cashOnHand: source.cashOnHand,
    gross: moneyFromCents(source.grossCents),
    notes: source.notes,
    status: source.status,
    entryDate: source.entryDate,
    createdAt: source.createdAt,
    updatedAt: source.updatedAt,
    shift: source.shift,
    dayContext: source.dayContext,
    invoiceId: source.invoiceId,
    invoiceNumber: source.invoiceNumber,
    invoiceTotal: source.invoiceTotal,
    invoiceNet: source.invoiceNet,
    invoiceTax: source.invoiceTax,
    channels: (channelsBySummary.get(source.id) || []).map((channel) => ({
      id: channel.id, vaultId: channel.vaultId, name: channel.name, type: channel.type,
      paymentMethod: channel.paymentMethod, key: channel.key, amount: moneyFromCents(channel.amountCents),
    })),
  };
  group.source_rows.push({
    source_system: "noorix",
    source_tenant_id: tenantId,
    source_company_id: source.companyId,
    source_summary_id: source.id,
    source_row_sha256: sha(sourceSnapshot),
    source_archive_sha256: archiveSha,
    canonical_key: canonicalKey,
    source_gross: moneyFromCents(source.grossCents),
    source_customers: source.customers,
    business_date: source.businessDate,
    shift: source.shift,
    decision: mergeArz ? "merge_into_all_day" : "create_summary",
    source_summary_number: source.summaryNumber,
  });
  groups.set(canonicalKey, group);
}

const summaries = [...groups.values()].sort((a, b) => a.wave_key.localeCompare(b.wave_key) || a.business_date.localeCompare(b.business_date) || a.period_scope.localeCompare(b.period_scope)).map((group) => {
  const setup = targetSetup.get(group.target_company_id);
  if (!setup) throw new Error(`Missing target POS summary setup for company ${group.target_company_id}`);
  const allocations = [...group.allocationCents.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([key, amountCents]) => {
    const targetPaymentMethodId = setup.methods.get(key);
    if (!targetPaymentMethodId) throw new Error(`Missing target payment method ${key} for company ${group.target_company_id}`);
    return { channel_key: key, amount: moneyFromCents(amountCents), target_payment_method_id: targetPaymentMethodId };
  });
  if (allocations.reduce((sum, row) => sum + cents(row.amount), 0) !== group.grossCents) throw new Error(`Target allocation mismatch for ${group.canonical_key}`);
  const references = group.source_rows.map((row) => row.source_summary_number).join("+");
  return {
    canonical_key: group.canonical_key,
    wave_key: group.wave_key,
    source_company_id: group.source_company_id,
    target_company_id: group.target_company_id,
    target_config_id: setup.configId,
    business_date: group.business_date,
    period_scope: group.period_scope,
    day_schedule: group.day_schedule,
    customer_count: group.customer_count,
    amount_gross: moneyFromCents(group.grossCents),
    external_reference: `Noorix ${references}`,
    notes: "ترحيل نوركس؛ المبلغ شامل ضريبة القيمة المضافة 15% حسب اعتماد المالك بتاريخ 2026-09-13.",
    allocations,
    source_rows: group.source_rows,
  };
});

if (summaries.length !== 669) throw new Error(`Expected 669 target summaries after the approved merge, found ${summaries.length}`);
const expected = {
  arz: { summaries: 239, sources: 240, gross: 2154301.00, customers: 34320 },
  almoallem: { summaries: 164, sources: 164, gross: 1518655.00, customers: 20794 },
  doha: { summaries: 164, sources: 164, gross: 472467.00, customers: 10614 },
  karak: { summaries: 102, sources: 102, gross: 2022645.06, customers: 6289 },
};
const waves = {};
for (const [waveKey, expectedValues] of Object.entries(expected)) {
  const waveRows = summaries.filter((row) => row.wave_key === waveKey);
  const actual = {
    summaries: waveRows.length,
    sources: waveRows.reduce((sum, row) => sum + row.source_rows.length, 0),
    gross: moneyFromCents(waveRows.reduce((sum, row) => sum + cents(row.amount_gross), 0)),
    customers: waveRows.reduce((sum, row) => sum + row.customer_count, 0),
  };
  if (JSON.stringify(actual) !== JSON.stringify(expectedValues)) throw new Error(`Unexpected ${waveKey} totals: ${JSON.stringify(actual)}`);
  waves[waveKey] = actual;
}

const payload = {
  target_database: targetDb,
  source_archive_sha256: archiveSha,
  approved_policy: "gross_includes_15_percent_vat_and_arz_20260526_sources_merge_into_one_all_day_summary",
  owner_decision_at: "2026-09-13",
  report: {
    active_source_summaries: 670,
    target_summaries: 669,
    merged_source_summaries: 2,
    target_gross: 6168068.06,
    target_customers: 72017,
    excluded_cancelled_summaries: 15,
    excluded_test_summaries: 15,
    waves,
  },
  summaries,
};

await fs.mkdir(outputDir, { recursive: true });
await fs.writeFile(outputPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
const payloadSha256 = crypto.createHash("sha256").update(await fs.readFile(outputPath)).digest("hex");
console.log(JSON.stringify({ outputPath, payloadSha256, report: payload.report }, null, 2));
