/** Create a coherent QA database + filestore checkpoint before Karak financial writes. */
import { execFileSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";

const database = "baseer_noorix_data_migration_qa_20260912";
const dbContainer = "baseer_odoo_dev-db-1";
const qaContainer = "baseer_odoo_dev-noorix_migration_qa-1";
const candidateManifest = ".local-backups/procurement-product-source1-20260913/candidate-v15/candidate-manifest.json";
const label = process.argv[2] || "20260913-karak-financial-prewrite-qa-1";
if (!/^[a-z0-9-]+$/.test(label)) throw new Error("Invalid checkpoint label");

const outputDir = path.resolve(".local-backups/noorix-migration", label);
const dumpInDb = `/tmp/${label}.dump`;
const helper = `baseer-noorix-snapshot-${Date.now()}`;
const helperTar = `/tmp/${label}-filestore.tar`;

function run(args) {
  return execFileSync("docker", args, { encoding: "utf8" }).trim();
}

async function sha256(file) {
  return crypto.createHash("sha256").update(await fs.readFile(file)).digest("hex");
}

if (await fs.stat(outputDir).then(() => true).catch(() => false)) {
  throw new Error(`Checkpoint already exists: ${outputDir}`);
}
await fs.mkdir(outputDir, { recursive: true });

let paused = false;
let helperCreated = false;
try {
  run(["pause", qaContainer]);
  paused = true;
  run(["exec", dbContainer, "pg_dump", "-U", "odoo", "-Fc", "-d", database, "-f", dumpInDb]);
  run(["cp", `${dbContainer}:${dumpInDb}`, path.join(outputDir, "database.dump")]);

  const image = run(["inspect", "-f", "{{.Image}}", qaContainer]);
  run(["create", "--name", helper, "--volumes-from", qaContainer, image, "sleep", "infinity"]);
  helperCreated = true;
  run(["start", helper]);
  run(["exec", helper, "tar", "-C", "/var/lib/odoo/filestore", "-cf", helperTar, database]);
  run(["exec", helper, "tar", "-tf", helperTar]);
  run(["cp", `${helper}:${helperTar}`, path.join(outputDir, "filestore.tar")]);

  const baseline = run([
    "exec", dbContainer, "psql", "-U", "odoo", "-d", database, "-At", "-F", "|", "-c",
    "SELECT (SELECT count(*) FROM res_company),(SELECT count(*) FROM res_partner),(SELECT count(*) FROM product_template),(SELECT count(*) FROM account_move),(SELECT count(*) FROM account_payment),(SELECT count(*) FROM stock_move),(SELECT count(*) FROM stock_picking),(SELECT count(*) FROM pos_order),(SELECT count(*) FROM pos_session);",
  ]);
  const candidate = JSON.parse(await fs.readFile(candidateManifest, "utf8"));
  const manifest = {
    checkpoint: label,
    database,
    created_at_utc: new Date().toISOString(),
    database_dump_sha256: await sha256(path.join(outputDir, "database.dump")),
    filestore_archive_sha256: await sha256(path.join(outputDir, "filestore.tar")),
    baseline_columns: ["companies", "partners", "product_templates", "account_moves", "payments", "stock_moves", "stock_pickings", "pos_orders", "pos_sessions"],
    baseline_values: baseline.split("|").map(Number),
    runtime_image_digest: image,
    candidate: candidate.candidate,
    candidate_manifest_sha256: await sha256(candidateManifest),
    candidate_custom_addons_tree_sha256: candidate.runtime_mounts.custom_addons.tree_sha256,
    purchase_payload_sha256: candidate.payloads.karak_purchase_history.sha256,
    payroll_payload_sha256: candidate.payloads.karak_net_payroll_settlement.sha256,
    protected_database: candidate.protected_database,
    original_write_authorized: false,
  };
  await fs.writeFile(path.join(outputDir, "checkpoint-manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
  console.log(JSON.stringify(manifest, null, 2));
} finally {
  try { run(["exec", dbContainer, "rm", "-f", dumpInDb]); } catch {}
  if (helperCreated) {
    try { run(["rm", "-f", helper]); } catch {}
  }
  if (paused) {
    try { run(["unpause", qaContainer]); } catch {}
  }
}
