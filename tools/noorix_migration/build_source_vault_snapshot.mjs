/**
 * Read the fourteen approved vault rows directly from the restored Noorix
 * archive and emit a source-only, hash-pinned snapshot on stdout.
 *
 * This intentionally has no target database, Odoo, or write operation.
 */
import crypto from "node:crypto";
import { execFileSync } from "node:child_process";
import fs from "node:fs";

const manifestPath = "outputs/01a0926b-3b31-75f2-9e93-1679ceaef536/noorix-main-replay/source-manifest.json";
const sourceDatabase = "noorix_source_readonly_20260914";
const sourceContainer = "baseer_odoo_dev-db-1";

const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
const contract = manifest.contracts[25];
const decisions = contract.payload.vault_decisions;
const ids = decisions.map((row) => `'${row.source_vault_id}'`).join(",");
const sql = `
SELECT json_agg(row_to_json(source_row) ORDER BY source_row."companyId", source_row.id)
FROM (
  SELECT id, tenant_id AS "tenantId", company_id AS "companyId",
         name_ar AS "nameAr", COALESCE(name_en, '') AS "nameEn", type,
         is_active AS active, is_archived AS archived,
         is_sales_channel AS "salesChannel",
         COALESCE(payment_method, '') AS "paymentMethod", COALESCE(notes, '') AS notes,
         bank_reconciliation_enabled AS "bankReconciliationEnabled",
         created_at::text AS "createdAt", updated_at::text AS "updatedAt"
  FROM public.vaults
  WHERE id IN (${ids})
) source_row;
`;
// Base64 avoids shell/psql quoting ambiguity while retaining a pure SELECT.
const encodedSql = Buffer.from(sql, "utf8").toString("base64");
const command = `echo ${encodedSql} | base64 -d | psql -U "$POSTGRES_USER" -d ${sourceDatabase} -Atq`;
const raw = execFileSync("docker", ["exec", sourceContainer, "sh", "-lc", command], {
  encoding: "utf8",
}).trim();
const rows = JSON.parse(raw);
const byId = new Map(rows.map((row) => [row.id, row]));
const sha = (value) => crypto.createHash("sha256").update(JSON.stringify(value)).digest("hex");

const vault_source_rows = decisions.map((decision) => {
  const source = byId.get(decision.source_vault_id);
  if (!source || source.companyId !== decision.source_company_id) {
    throw new Error(`Archive vault identity does not match decision: ${decision.source_vault_id}`);
  }
  return {
    source_system: "noorix",
    source_tenant_id: source.tenantId,
    source_company_id: source.companyId,
    source_vault_id: source.id,
    source_vault_type: source.type,
    source_vault_name: source.nameAr,
    source_row_sha256: sha(source),
    source,
  };
});

if (vault_source_rows.length !== 14 || byId.size !== 14) {
  throw new Error(`Expected 14 approved source vaults; found ${vault_source_rows.length}/${byId.size}`);
}

const snapshot = {
  schema_version: 1,
  source_archive_sha256: contract.source_archive_sha256,
  parent_manifest_sha256: "84afbe3fa32dcb2ba89bb52451db032f3675baf50d97b243d63f4b31c9201fa6",
  contract_26_artifact_sha256: contract.artifact_sha256,
  vault_source_rows,
};
const rendered = `${JSON.stringify(snapshot, null, 2)}\n`;
process.stdout.write(rendered);
process.stderr.write(`snapshot_sha256=${crypto.createHash("sha256").update(rendered).digest("hex")}\n`);
