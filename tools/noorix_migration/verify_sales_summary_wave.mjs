/** Reconcile Noorix active sales to QA by company, month and payment channel. */
import { execFileSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";

const container = "baseer_odoo_dev-db-1";
const sourceDb = "noorix_source_inspection_archive159_20260913";
const targetDb = "baseer_noorix_data_migration_qa_20260912";
const originalDb = "baseer_dev";
const outputPath = ".local-backups/noorix-migration/runs/20260913-sales-summary-qa-1/reconciliation.json";
const sourceCompanies = [
  "cmnf604ka009ay8lm556wgd9c",
  "cmnaivif80001wavxxfgriptm",
  "cmnf5xrd0001uy8lm8vja50gp",
  "cmnvui7x70001etuf8p6xz3d0",
];

function psql(db, sql) {
  const output = execFileSync("docker", ["exec", container, "psql", "-U", "odoo", "-d", db, "-At", "-F", "\t", "-c", sql], { encoding: "utf8", maxBuffer: 32 * 1024 * 1024 });
  return output.split(/\r?\n/).filter(Boolean).map((row) => row.split("\t"));
}

function cents(value) {
  const [whole, fraction = ""] = String(value).split(".");
  return Number(whole) * 100 + Math.sign(Number(whole) || 1) * Number(fraction.padEnd(2, "0").slice(0, 2));
}

function sourceChannel(name, type) {
  const value = name.trim().toLowerCase();
  if (type === "cash" || value === "نقد" || value === "نقدي") return "cash";
  if (type === "bank" || value === "بنك" || value === "البنك") return "bank";
  if (value.includes("هنجر") || value.includes("هنقر") || value.includes("hunger")) return "hungerstation";
  if (value.includes("كيتا") || value.includes("keeta")) return "keeta";
  if (value.includes("جاهز") || value.includes("jahez")) return "jahez";
  throw new Error(`Unsupported source channel ${name}/${type}`);
}

function targetChannel(kind, name) {
  return kind === "platform" ? sourceChannel(name, "app") : kind;
}

const ids = sourceCompanies.map((id) => `'${id}'`).join(",");
const sourceMonthly = new Map(psql(sourceDb, `
  SELECT company_id,to_char(transaction_date,'YYYY-MM'),count(*)::text,
         sum(total_amount)::text,sum(customer_count)::text
  FROM daily_sales_summaries
  WHERE status='active' AND company_id IN (${ids})
  GROUP BY company_id,to_char(transaction_date,'YYYY-MM') ORDER BY 1,2;
`).map(([company, month, count, gross, customers]) => [`${company}|${month}`, { count: Number(count), gross: cents(gross), customers: Number(customers) }]));

const targetMonthly = new Map(psql(targetDb, `
  WITH mapped AS (
    SELECT DISTINCT m.source_company_id,m.summary_id
    FROM baseer_noorix_sales_summary_map m
    JOIN baseer_noorix_migration_run r ON r.id=m.run_id
    WHERE r.scope='sales_summary' AND r.state='reconciled'
  )
  SELECT mapped.source_company_id,to_char(s.business_date,'YYYY-MM'),count(*)::text,
         sum(s.amount_gross)::text,sum(s.customer_count)::text
  FROM mapped JOIN baseer_pos_summary s ON s.id=mapped.summary_id
  GROUP BY mapped.source_company_id,to_char(s.business_date,'YYYY-MM') ORDER BY 1,2;
`).map(([company, month, count, gross, customers]) => [`${company}|${month}`, { count: Number(count), gross: cents(gross), customers: Number(customers) }]));

const sourceChannels = new Map();
for (const [company, month, name, type, amount] of psql(sourceDb, `
  SELECT ds.company_id,to_char(ds.transaction_date,'YYYY-MM'),v.name_ar,v.type,sum(ch.amount)::text
  FROM daily_sales_channels ch
  JOIN daily_sales_summaries ds ON ds.id=ch.summary_id
  JOIN vaults v ON v.id=ch.vault_id
  WHERE ds.status='active' AND ds.company_id IN (${ids})
  GROUP BY ds.company_id,to_char(ds.transaction_date,'YYYY-MM'),v.name_ar,v.type ORDER BY 1,2,3;
`)) {
  const key = `${company}|${month}|${sourceChannel(name, type)}`;
  sourceChannels.set(key, (sourceChannels.get(key) || 0) + cents(amount));
}

const targetChannels = new Map();
for (const [company, month, kind, name, amount] of psql(targetDb, `
  WITH mapped AS (
    SELECT DISTINCT m.source_company_id,m.summary_id
    FROM baseer_noorix_sales_summary_map m
    JOIN baseer_noorix_migration_run r ON r.id=m.run_id
    WHERE r.scope='sales_summary' AND r.state='reconciled'
  )
  SELECT mapped.source_company_id,to_char(s.business_date,'YYYY-MM'),cat.kind,ppm.name->>'en_US',sum(a.amount)::text
  FROM mapped
  JOIN baseer_pos_summary s ON s.id=mapped.summary_id
  JOIN baseer_pos_summary_allocation a ON a.summary_id=s.id
  JOIN pos_payment_method ppm ON ppm.id=a.payment_method_id
  JOIN baseer_pos_payment_category cat ON cat.id=ppm.baseer_category_id
  GROUP BY mapped.source_company_id,to_char(s.business_date,'YYYY-MM'),cat.kind,ppm.name->>'en_US' ORDER BY 1,2,3,4;
`)) {
  const key = `${company}|${month}|${targetChannel(kind, name)}`;
  targetChannels.set(key, (targetChannels.get(key) || 0) + cents(amount));
}

const monthlyDiffs = [];
for (const key of new Set([...sourceMonthly.keys(), ...targetMonthly.keys()])) {
  const source = sourceMonthly.get(key);
  const target = targetMonthly.get(key);
  if (!source || !target || source.gross !== target.gross || source.customers !== target.customers) monthlyDiffs.push({ key, source, target });
}
const channelDiffs = [];
for (const key of new Set([...sourceChannels.keys(), ...targetChannels.keys()])) {
  if (sourceChannels.get(key) !== targetChannels.get(key)) channelDiffs.push({ key, source: sourceChannels.get(key), target: targetChannels.get(key) });
}
if (monthlyDiffs.length || channelDiffs.length) throw new Error(JSON.stringify({ monthlyDiffs, channelDiffs }, null, 2));

const [targetInvariant] = psql(targetDb, `
  SELECT count(DISTINCT m.summary_id),count(*),sum(m.source_gross)::text,sum(m.source_customers)::text,
         count(*) FILTER (WHERE s.state!='approved' OR ps.state!='closed' OR po.state!='done'),
         count(*) FILTER (WHERE EXISTS (SELECT 1 FROM stock_picking sp WHERE sp.pos_order_id=po.id))
  FROM baseer_noorix_sales_summary_map m
  JOIN baseer_noorix_migration_run r ON r.id=m.run_id
  JOIN baseer_pos_summary s ON s.id=m.summary_id
  JOIN pos_session ps ON ps.id=s.session_id
  JOIN pos_order po ON po.id=s.order_id
  WHERE r.scope='sales_summary' AND r.state='reconciled';
`);
const totals = psql(targetDb, `
  WITH mapped AS (SELECT DISTINCT summary_id FROM baseer_noorix_sales_summary_map)
  SELECT count(*)::text,sum(s.amount_gross)::text,sum(s.amount_net)::text,sum(s.amount_tax)::text,sum(s.customer_count)::text
  FROM mapped JOIN baseer_pos_summary s ON s.id=mapped.summary_id;
`)[0];
const runs = psql(targetDb, `SELECT name,state FROM baseer_noorix_migration_run WHERE scope='sales_summary' ORDER BY name;`);
const original = psql(originalDb, `SELECT (SELECT count(*) FROM res_company),(SELECT count(*) FROM res_partner),(SELECT count(*) FROM product_template),(SELECT count(*) FROM account_move),(SELECT count(*) FROM stock_move);`)[0];
const stock = psql(targetDb, `SELECT count(*) FROM stock_move;`)[0][0];

if (targetInvariant[0] !== "669" || targetInvariant[1] !== "670" || cents(targetInvariant[2]) !== 616806806 || targetInvariant[3] !== "72017" || targetInvariant[4] !== "0" || targetInvariant[5] !== "0") throw new Error(`Target invariant mismatch: ${targetInvariant.join("|")}`);
if (totals[0] !== "669" || cents(totals[1]) !== 616806806 || cents(totals[2]) + cents(totals[3]) !== cents(totals[1]) || totals[4] !== "72017") throw new Error(`Target total mismatch: ${totals.join("|")}`);
if (runs.length !== 4 || runs.some(([, state]) => state !== "reconciled")) throw new Error(`Run states differ: ${JSON.stringify(runs)}`);
if (stock !== "0") throw new Error(`QA stock moves changed: ${stock}`);
if (original.join("|") !== "3|80|89|2|0") throw new Error(`Original fingerprint changed: ${original.join("|")}`);

const result = {
  status: "PASS",
  source_records: 670,
  target_summaries: 669,
  source_maps: 670,
  gross: Number(totals[1]),
  net: Number(totals[2]),
  tax: Number(totals[3]),
  customers: Number(totals[4]),
  monthly_groups_compared: sourceMonthly.size,
  monthly_amount_customer_differences: monthlyDiffs.length,
  channel_groups_compared: sourceChannels.size,
  channel_amount_differences: channelDiffs.length,
  invalid_native_documents: Number(targetInvariant[4]),
  stock_pickings: Number(targetInvariant[5]),
  qa_stock_moves: Number(stock),
  runs: Object.fromEntries(runs),
  original_fingerprint: { companies: 3, partners: 80, products: 89, account_moves: 2, stock_moves: 0 },
};
await fs.mkdir(path.dirname(outputPath), { recursive: true });
await fs.writeFile(outputPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
const sha256 = crypto.createHash("sha256").update(await fs.readFile(outputPath)).digest("hex");
console.log(JSON.stringify({ outputPath, sha256, ...result }, null, 2));
