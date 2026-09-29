/** Read-only freezer for the two explicitly approved Al Moallem supplier crosswalks. */
import crypto from "node:crypto";
import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";

const sourceDb = "noorix_source_inspection_archive159_20260913";
const targetDb = "baseer_noorix_data_migration_qa_20260912";
const container = "baseer_odoo_dev-db-1";
const archive = "024606ADD82DCD78DC1835828A12D7B22C56E34924FF998ABF752134160E79E2";
const tenant = "default-tenant-noorix-2024";
const company = "cmnaivif80001wavxxfgriptm";
const outputDir = ".local-backups/noorix-migration/runs/20260913-almoallem-owner-classified-qa-1";
const outputPath = path.join(outputDir, "almoallem-owner-classified-supplier-provenance-payload.json");
const sha = (value) => crypto.createHash("sha256").update(JSON.stringify(value)).digest("hex");
function q(database, sql) {
  if (database === "baseer_dev") throw new Error("production database is forbidden");
  const result = execFileSync("docker", ["exec", container, "psql", "-U", "odoo", "-d", database, "-At", "-F", "\t", "-c", sql], { encoding: "utf8" }).trim();
  return result ? result.split(/\r?\n/).map((line) => line.split("\t")) : [];
}
const approved = [
  ["cmnjfe52o005z13ina3f0tcpd", "شركة ديار صفوى للتجارة", "311262678500003", 1750],
  ["cmnjfe7ko007n13in9knmux11", "شركة حياة مثالية للتعبئة والتغليف", "310536346100003", 1721],
];
const sourceIds = approved.map(([id]) => `'${id}'`).join(",");
const source = q(sourceDb, `SELECT id,tenant_id,company_id,name_ar,COALESCE(tax_number,''),is_tax_registered::text,is_deleted::text,created_at::text,updated_at::text FROM suppliers WHERE id IN (${sourceIds}) ORDER BY id;`)
  .map(([id, sourceTenant, sourceCompany, name, vat, registered, deleted, created, updated]) => ({ id, sourceTenant, sourceCompany, name, vat, registered, deleted, created, updated }));
if (source.length !== 2) throw new Error("approved source supplier identities differ");
const target = q(targetDb, "SELECT id,name,COALESCE(vat,''),COALESCE(company_id::text,''),supplier_rank::text FROM res_partner WHERE id IN (1721,1750) ORDER BY id;")
  .map(([id, name, vat, partnerCompany, rank]) => ({ id: Number(id), name, vat, partnerCompany, rank }));
if (target.length !== 2) throw new Error("approved target partner identities differ");
const maps = q(targetDb, `SELECT source_supplier_id FROM baseer_noorix_supplier_map WHERE source_system='noorix' AND source_tenant_id='${tenant}' AND source_company_id='${company}' AND source_supplier_id IN (${sourceIds});`);
if (maps.length) throw new Error("one of the append-only source supplier maps already exists");
const records = approved.map(([sourceId, name, vat, targetPartnerId]) => {
  const sourceRow = source.find((row) => row.id === sourceId), partner = target.find((row) => row.id === targetPartnerId);
  // Noorix's supplier master rows are shared across companies.  These two
  // source rows currently carry Doha's master-company ID while their approved
  // invoices belong to Al Moallem; preserve that fact in the source receipt,
  // but use the invoice company for the target provenance namespace.
  if (!sourceRow || !partner || sourceRow.sourceTenant !== tenant || sourceRow.sourceCompany !== "cmnf5xrd0001uy8lm8vja50gp" || sourceRow.name !== name || sourceRow.vat !== vat || sourceRow.registered !== "true" || sourceRow.deleted !== "false" || partner.name !== name || partner.vat !== vat || partner.partnerCompany || Number(partner.rank) < 1) throw new Error(`supplier/partner evidence differs: ${sourceId}`);
  const snapshot = { source: sourceRow, target: partner, decision: "existing_global_vat" };
  return { source_system: "noorix", source_tenant_id: tenant, source_company_id: company, source_supplier_id: sourceId, source_supplier_name_ar: name, source_supplier_vat: vat, source_row_sha256: sha(snapshot), source_archive_sha256: archive, canonical_key: `supplier:${company}:${sourceId}`, decision: "existing_global_vat", target_partner_id: targetPartnerId, target_partner_vat: vat };
});
const payload = { schema_version: 1, target_database: targetDb, source_archive_sha256: archive, approved_policy: "almoallem_owner_authorized_existing_global_vat_supplier_provenance", run: { name: "20260913-noorix-almoallem-owner-classified-supplier-provenance-qa-1", scope: "supplier_master", target_company_id: 2 }, records };
await fs.mkdir(outputDir, { recursive: true });
await fs.writeFile(outputPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
const payloadSha256 = crypto.createHash("sha256").update(await fs.readFile(outputPath)).digest("hex");
console.log(JSON.stringify({ outputPath, payloadSha256, records: records.length, partners: records.map((row) => ({ source_supplier_id: row.source_supplier_id, target_partner_id: row.target_partner_id, vat: row.target_partner_vat })) }, null, 2));
