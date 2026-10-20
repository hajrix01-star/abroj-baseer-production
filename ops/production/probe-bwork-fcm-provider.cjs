#!/usr/bin/env node
'use strict';
// OAuth authentication only: never sends FCM messages, persists tokens or changes IAM.
const fs = require('node:fs');
const crypto = require('node:crypto');
const PROJECT = 'bchat-9cab1';
const TOKEN_URI = 'https://oauth2.googleapis.com/token';
const MAX_INPUT = 16 * 1024;
const MAX_RESPONSE = 64 * 1024;

class Refused extends Error {}
function requireSafe(condition, code) { if (!condition) throw new Refused(code); }

// JSON.parse alone silently accepts duplicate keys; this bounded lexical pass does not.
function strictJson(text) {
  requireSafe(typeof text === 'string' && !text.includes('\0'), 'invalid_json');
  let i = 0;
  const ws = () => { while (/\s/.test(text[i] || '') && i < text.length) i++; };
  const string = () => {
    const start = i++;
    while (i < text.length) {
      if (text[i] === '\\') { i += 2; continue; }
      if (text[i++] === '"') return JSON.parse(text.slice(start, i));
    }
    throw new Refused('invalid_json');
  };
  const value = (depth = 0) => {
    requireSafe(depth <= 16, 'invalid_json'); ws();
    if (text[i] === '"') { const s = string(); requireSafe(!s.includes('\0'), 'invalid_json'); return; }
    if (text[i] === '{') {
      i++; ws(); const keys = new Set(); if (text[i] === '}') { i++; return; }
      while (i < text.length) {
        requireSafe(text[i] === '"', 'invalid_json'); const key = string();
        requireSafe(!keys.has(key) && !key.includes('\0'), 'duplicate_or_invalid_json_key'); keys.add(key);
        ws(); requireSafe(text[i++] === ':', 'invalid_json'); value(depth + 1); ws();
        if (text[i] === '}') { i++; return; }
        requireSafe(text[i++] === ',', 'invalid_json'); ws();
      }
    } else if (text[i] === '[') {
      i++; ws(); if (text[i] === ']') { i++; return; }
      while (i < text.length) {
        value(depth + 1); ws(); if (text[i] === ']') { i++; return; }
        requireSafe(text[i++] === ',', 'invalid_json');
      }
    } else {
      const match = /^(?:true|false|null|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)/.exec(text.slice(i));
      requireSafe(Boolean(match), 'invalid_json'); i += match[0].length; return;
    }
    throw new Refused('invalid_json');
  };
  try { value(); ws(); requireSafe(i === text.length, 'invalid_json'); return JSON.parse(text); }
  catch (error) { if (error instanceof Refused) throw error; throw new Refused('invalid_json'); }
}

function validateAccount(raw) {
  requireSafe(Buffer.isBuffer(raw) && raw.length > 0 && raw.length <= MAX_INPUT, 'credential_size');
  const text = new TextDecoder('utf-8', { fatal: true }).decode(raw);
  const config = strictJson(text);
  requireSafe(config && typeof config === 'object' && !Array.isArray(config)
    && config.type === 'service_account' && config.project_id === PROJECT
    && config.token_uri === TOKEN_URI, 'account_identity');
  requireSafe(typeof config.client_email === 'string'
    && /^[A-Za-z0-9._-]+@bchat-9cab1\.iam\.gserviceaccount\.com$/.test(config.client_email), 'account_email');
  requireSafe(typeof config.private_key === 'string' && config.private_key.length <= 8192
    && /^-----BEGIN PRIVATE KEY-----\n[A-Za-z0-9+/=\n]+\n-----END PRIVATE KEY-----\n?$/.test(config.private_key), 'private_key_shape');
  const compact = JSON.stringify(config);
  requireSafe(!/[\u0000\r\n'$]/.test(compact) && !compact.includes('\\u0000'), 'unsafe_dotenv_value');
  let key;
  try { key = crypto.createPrivateKey({ key: config.private_key, format: 'pem', type: 'pkcs8' }); }
  catch { throw new Refused('invalid_rsa_key'); }
  requireSafe(key.type === 'private' && key.asymmetricKeyType === 'rsa'
    && key.asymmetricKeyDetails.modulusLength >= 2048, 'rsa_2048_required');
  return { email: config.client_email, key,
    rawInputSha256: crypto.createHash('sha256').update(raw).digest('hex'), rsa2048Verified: true };
}

function readCandidate(path) {
  const original = fs.lstatSync(path);
  requireSafe(original.isFile() && !original.isSymbolicLink() && original.size <= MAX_INPUT, 'unsafe_candidate');
  const fd = fs.openSync(path, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW || 0));
  try {
    const current = fs.fstatSync(fd);
    requireSafe(current.isFile() && current.dev === original.dev && current.ino === original.ino
      && current.size <= MAX_INPUT, 'candidate_changed');
    const bytes = Buffer.alloc(MAX_INPUT + 1); let length = 0;
    while (length < bytes.length) { const n = fs.readSync(fd, bytes, length, bytes.length - length, null); if (!n) break; length += n; }
    requireSafe(length > 0 && length <= MAX_INPUT, 'credential_size');
    return bytes.subarray(0, length);
  } finally { fs.closeSync(fd); }
}

async function boundedJson(response) {
  requireSafe(response.body && typeof response.body.getReader === 'function', 'invalid_oauth_response');
  const reader = response.body.getReader(); const chunks = []; let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read(); if (done) break;
      size += value.byteLength; requireSafe(size <= MAX_RESPONSE, 'oauth_response_size'); chunks.push(Buffer.from(value));
    }
    return strictJson(new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks)));
  } finally { await reader.cancel().catch(() => {}); }
}

async function authenticate(account, fetchImpl = globalThis.fetch, now = Math.floor(Date.now() / 1000)) {
  requireSafe(account.rsa2048Verified === true && /^[a-f0-9]{64}$/.test(account.rawInputSha256), 'unvalidated_account');
  const proof = { rawInputSha256: account.rawInputSha256, rsa2048Verified: true };
  const header = Buffer.from(JSON.stringify({ alg: 'RS256', typ: 'JWT' })).toString('base64url');
  const claims = Buffer.from(JSON.stringify({ iss: account.email,
    scope: 'https://www.googleapis.com/auth/firebase.messaging', aud: TOKEN_URI,
    iat: now, exp: now + 300 })).toString('base64url');
  const input = `${header}.${claims}`;
  const jwt = `${input}.${crypto.sign('RSA-SHA256', Buffer.from(input), account.key).toString('base64url')}`;
  const response = await fetchImpl(TOKEN_URI, { method: 'POST', redirect: 'error',
    signal: AbortSignal.timeout(10000), headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ grant_type: 'urn:ietf:params:oauth:grant-type:jwt-bearer', assertion: jwt }) });
  const body = await boundedJson(response);
  if (response.status === 200) {
    requireSafe(body && typeof body.access_token === 'string' && body.access_token.length >= 20
      && body.access_token.length <= 4096 && body.token_type === 'Bearer', 'invalid_oauth_response');
    return { authSuccess: true, http: 200, project: PROJECT, ...proof };
  }
  // Never return provider descriptions, JWTs, tokens or arbitrary provider strings.
  const allowed = new Set(['invalid_request', 'invalid_client', 'invalid_grant', 'unauthorized_client', 'unsupported_grant_type', 'invalid_scope']);
  return { authSuccess: false, http: response.status, project: PROJECT, ...proof,
    errorCode: allowed.has(body?.error) ? body.error : 'oauth_rejected' };
}

async function main() {
  try {
    requireSafe(process.argv.length === 4 && process.argv[2] === '--file', 'invalid_arguments');
    const result = await authenticate(validateAccount(readCandidate(process.argv[3])));
    console.log(JSON.stringify(result)); return result.authSuccess ? 0 : 1;
  } catch (error) {
    console.log(JSON.stringify({ authSuccess: false, http: null, project: PROJECT,
      errorCode: error instanceof Refused ? error.message : 'probe_failed' })); return 1;
  }
}
module.exports = { validateAccount, readCandidate, authenticate, strictJson };
if (require.main === module) main().then(code => { process.exitCode = code; });
