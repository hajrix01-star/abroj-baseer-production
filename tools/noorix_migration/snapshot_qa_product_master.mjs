/** Create one coherent, local recovery snapshot before the QA product-master wave. */
import { execFileSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";

const database = "baseer_noorix_data_migration_qa_20260912";
const dbContainer = "baseer_odoo_dev-db-1";
const qaContainer = "baseer_odoo_dev-noorix_migration_qa-1";
const snapshotLabel = process.argv[2] || "product-master-prewrite-qa-1";
if (!/^[a-z0-9-]+$/.test(snapshotLabel)) throw new Error("Snapshot label must contain only lowercase letters, digits and hyphens");
const outputDir = `.local-backups/noorix-migration/${snapshotLabel}`;
const containerDump = "/tmp/noorix-product-master-prewrite.dump";
const containerFilestoreTar = "/tmp/noorix-product-master-prewrite-filestore.tar";

function run(args) {
  return execFileSync("docker", args, { encoding: "utf8" }).trim();
}

async function sha256File(file) {
  const bytes = await fs.readFile(file);
  return crypto.createHash("sha256").update(bytes).digest("hex");
}

async function listFiles(directory) {
  const output = [];
  async function walk(current) {
    for (const entry of await fs.readdir(current, { withFileTypes: true })) {
      const target = path.join(current, entry.name);
      if (entry.isDirectory()) await walk(target);
      else if (entry.isFile()) output.push(target);
    }
  }
  try {
    await walk(directory);
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  return output.sort();
}

const outputExists = await fs.stat(outputDir).then(() => true).catch(() => false);
if (outputExists) throw new Error(`Snapshot directory already exists: ${outputDir}`);
await fs.mkdir(outputDir, { recursive: true });

try {
  run(["exec", dbContainer, "pg_dump", "-U", "odoo", "-Fc", "-d", database, "-f", containerDump]);
  run(["cp", `${dbContainer}:${containerDump}`, `${outputDir}/database.dump`]);
  run(["exec", qaContainer, "tar", "-C", "/var/lib/odoo/filestore", "-cf", containerFilestoreTar, database]);
  run(["cp", `${qaContainer}:${containerFilestoreTar}`, `${outputDir}/filestore.tar`]);
} finally {
  try { run(["exec", dbContainer, "rm", "-f", containerDump]); } catch {}
  try { run(["exec", qaContainer, "rm", "-f", containerFilestoreTar]); } catch {}
}

const filestoreDir = `${outputDir}/filestore`;
run(["cp", `${qaContainer}:/var/lib/odoo/filestore/${database}`, filestoreDir]);
const files = await listFiles(filestoreDir);
const fileHashes = [];
for (const file of files) {
  fileHashes.push({ path: path.relative(filestoreDir, file).replaceAll("\\", "/"), sha256: await sha256File(file) });
}
const contentManifestText = `${JSON.stringify(fileHashes, null, 2)}\n`;
await fs.writeFile(`${outputDir}/filestore-content-manifest.json`, contentManifestText, "utf8");

const runtimeImage = run(["inspect", "-f", "{{.Image}}", qaContainer]);
const addonFiles = [
  "custom_addons/baseer_noorix_migration/__manifest__.py",
  "custom_addons/baseer_noorix_migration/models/migration_models.py",
  "tools/noorix_migration/apply_qa_product_payload.py",
];
const addonHashes = {};
for (const file of addonFiles) addonHashes[file] = await sha256File(file);
const manifest = {
  database,
  created_at_utc: new Date().toISOString(),
  database_dump_sha256: await sha256File(`${outputDir}/database.dump`),
  filestore_archive_sha256: await sha256File(`${outputDir}/filestore.tar`),
  filestore_content_manifest_sha256: crypto.createHash("sha256").update(contentManifestText).digest("hex"),
  filestore_file_count: fileHashes.length,
  runtime_image_digest: runtimeImage,
  addon_source_sha256: crypto.createHash("sha256").update(JSON.stringify(addonHashes)).digest("hex"),
  addon_files: addonHashes,
};
await fs.writeFile(`${outputDir}/snapshot-manifest.json`, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
console.log(JSON.stringify(manifest, null, 2));
