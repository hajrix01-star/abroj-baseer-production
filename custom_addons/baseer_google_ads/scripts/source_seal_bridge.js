// Runs only inside the legacy server for a one-time QA migration.
// It receives a QA bridge key plus an encrypted legacy credential, decrypts
// only in process memory, and emits a new authenticated sealed payload.
// No credential is logged or written to disk.
const { createCipheriv, createDecipheriv, createHash, randomBytes } = require("node:crypto");
const { readFileSync } = require("node:fs");

function fail(code) {
  process.stderr.write(code + "\n");
  process.exit(1);
}

try {
  const lines = readFileSync(0, "utf8").trim().split("\n");
  if (lines.length !== 2) fail("source_bridge_input_invalid");
  const bridgeKey = Buffer.from(lines[0], "base64");
  if (bridgeKey.length !== 32) fail("source_bridge_key_invalid");
  const [legacyConnectionId, customerId, encryptedPayload, iv, tag, keyVersion] = lines[1].split("|");
  if (!legacyConnectionId || !customerId || !encryptedPayload || !iv || !tag || !keyVersion) {
    fail("source_bridge_record_invalid");
  }
  const sourceKey = createHash("sha256").update(process.env.AUTH_ENCRYPTION_KEY || "", "utf8").digest();
  const decipher = createDecipheriv("aes-256-gcm", sourceKey, Buffer.from(iv, "base64"));
  decipher.setAuthTag(Buffer.from(tag, "base64"));
  const stored = JSON.parse(Buffer.concat([
    decipher.update(Buffer.from(encryptedPayload, "base64")), decipher.final(),
  ]).toString("utf8"));
  if (!stored.refreshToken) fail("source_bridge_credential_invalid");
  const payload = Buffer.from(JSON.stringify({
    legacy_connection_id: legacyConnectionId,
    customer_id: customerId,
    login_customer_id: stored.loginCustomerId || null,
    refresh_token: stored.refreshToken,
  }), "utf8");
  const nonce = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", bridgeKey, nonce);
  const encrypted = Buffer.concat([cipher.update(payload), cipher.final(), cipher.getAuthTag()]);
  process.stdout.write(nonce.toString("base64") + "." + encrypted.toString("base64"));
} catch {
  fail("source_bridge_failed");
}
