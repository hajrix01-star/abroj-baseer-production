import assert from "node:assert/strict";
import { createCipheriv, createDecipheriv, createHash, generateKeyPairSync, privateDecrypt, randomBytes, constants } from "node:crypto";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const auth = "test-legacy-auth-key";
const key = createHash("sha256").update(auth).digest();
const iv = randomBytes(12);
const legacy = createCipheriv("aes-256-gcm", key, iv);
const legacyCiphertext = Buffer.concat([legacy.update(Buffer.from(JSON.stringify({ refreshToken: "test-token", loginCustomerId: "1234567890" }))), legacy.final()]);
const { publicKey, privateKey } = generateKeyPairSync("rsa", { modulusLength: 3072 });
const aad = { company_id: "1", customer_id: "6990834484", environment: "production", external_account_id: "6990834484", external_location_id: "", legacy_connection_id: "test-connection", provider: "google_ads" };
const input = {
  public_key_pem: publicKey.export({ type: "spki", format: "pem" }), aad,
  legacy_connection_id: "test-connection", encrypted_payload: legacyCiphertext.toString("base64"),
  initialization_vector: iv.toString("base64"), authentication_tag: legacy.getAuthTag().toString("base64"), key_version: "test",
};
const script = new URL("./legacy_google_envelope.js", import.meta.url);
const result = spawnSync(process.execPath, [fileURLToPath(script)], { input: JSON.stringify(input), env: { ...process.env, AUTH_ENCRYPTION_KEY: auth }, encoding: "utf8" });
assert.equal(result.status, 0, result.stderr);
const envelope = JSON.parse(result.stdout);
const aadBytes = Buffer.from(JSON.stringify(Object.fromEntries(Object.entries(aad).sort())), "utf8");
const dataKey = privateDecrypt({ key: privateKey, padding: constants.RSA_PKCS1_OAEP_PADDING, oaepHash: "sha256" }, Buffer.from(envelope.wrapped_key, "base64"));
const decipher = createDecipheriv("aes-256-gcm", dataKey, Buffer.from(envelope.nonce, "base64"));
decipher.setAAD(aadBytes);
decipher.setAuthTag(Buffer.from(envelope.tag, "base64"));
const payload = JSON.parse(Buffer.concat([decipher.update(Buffer.from(envelope.ciphertext, "base64")), decipher.final()]).toString("utf8"));
assert.equal(payload.refresh_token, "test-token");
assert.equal(payload.customer_id, "6990834484");
console.log("legacy_google_envelope_contract_ok");
