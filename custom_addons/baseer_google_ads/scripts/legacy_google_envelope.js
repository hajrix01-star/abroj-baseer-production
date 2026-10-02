/* One-time legacy-side sealer for the production Google migration.
 *
 * It decrypts a single legacy credential only in the legacy container, then
 * emits a hybrid RSA-OAEP/AES-GCM envelope.  The target private key never
 * enters this container.  stdin and stdout are pipes controlled by the
 * operator script: nothing is logged or written to disk.
 */
const { createCipheriv, createDecipheriv, createHash, publicEncrypt, randomBytes, constants } = require("node:crypto");
const { readFileSync } = require("node:fs");

function fail(code) {
  process.stderr.write(code + "\n");
  process.exit(1);
}

function canonical(value) {
  const ordered = {};
  for (const key of Object.keys(value).sort()) ordered[key] = String(value[key] ?? "");
  return Buffer.from(JSON.stringify(ordered), "utf8");
}

try {
  const input = JSON.parse(readFileSync(0, "utf8"));
  const required = ["public_key_pem", "aad", "legacy_connection_id", "encrypted_payload", "initialization_vector", "authentication_tag", "key_version"];
  if (!required.every((key) => input[key])) fail("legacy_envelope_input_invalid");

  const sourceKey = createHash("sha256").update(process.env.AUTH_ENCRYPTION_KEY || "", "utf8").digest();
  const decipher = createDecipheriv("aes-256-gcm", sourceKey, Buffer.from(input.initialization_vector, "base64"));
  decipher.setAuthTag(Buffer.from(input.authentication_tag, "base64"));
  const stored = JSON.parse(Buffer.concat([
    decipher.update(Buffer.from(input.encrypted_payload, "base64")), decipher.final(),
  ]).toString("utf8"));
  if (!stored.refreshToken) fail("legacy_envelope_credential_invalid");

  const aad = canonical(input.aad);
  const payload = Buffer.from(JSON.stringify({
    provider: input.aad.provider,
    legacy_connection_id: input.legacy_connection_id,
    customer_id: input.aad.customer_id || "",
    refresh_token: stored.refreshToken,
    login_customer_id: stored.loginCustomerId || "",
  }), "utf8");
  const dataKey = randomBytes(32);
  const nonce = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", dataKey, nonce);
  cipher.setAAD(aad);
  const ciphertext = Buffer.concat([cipher.update(payload), cipher.final()]);
  const wrappedKey = publicEncrypt({
    key: input.public_key_pem,
    padding: constants.RSA_PKCS1_OAEP_PADDING,
    oaepHash: "sha256",
  }, dataKey);
  process.stdout.write(JSON.stringify({
    version: 1,
    aad: aad.toString("base64"),
    wrapped_key: wrappedKey.toString("base64"),
    nonce: nonce.toString("base64"),
    ciphertext: ciphertext.toString("base64"),
    tag: cipher.getAuthTag().toString("base64"),
  }));
} catch (_) {
  fail("legacy_envelope_failed");
}
