const fs = require('node:fs');
const identity = require('./compatibility/identities.json');
function origin(value) {
  const url = new URL(value);
  if (url.protocol !== 'https:' || url.origin !== value || url.username || url.password) throw Error('BWork profile requires an exact HTTPS origin');
  return value;
}
function setting(env, canonical, previous) {
  const next = env[canonical], old = env[previous];
  if (next && old && next !== old) throw Error('BWork configuration aliases conflict');
  return next || old || '';
}
function profile(env = process.env, exists = fs.existsSync) {
  const name = env.BWORK_PROFILE || env.EXPO_PUBLIC_BWORK_PROFILE || 'qa';
  if (!['qa','production'].includes(name) || env.BWORK_PROFILE && env.EXPO_PUBLIC_BWORK_PROFILE && env.BWORK_PROFILE !== env.EXPO_PUBLIC_BWORK_PROFILE) throw Error('BWork profile mismatch');
  const server = setting(env,'EXPO_PUBLIC_BWORK_ORIGIN',identity.environmentAliases.origin);
  const database = setting(env,'EXPO_PUBLIC_BWORK_DATABASE',identity.environmentAliases.database);
  if (server) origin(server);
  if (name === 'production') {
    if (env.BWORK_PROFILE !== 'production' || env.EXPO_PUBLIC_BWORK_PROFILE !== 'production') throw Error('BWork production profile must match native and public bundle configuration');
    if (!env.EXPO_PUBLIC_BWORK_ORIGIN || !env.EXPO_PUBLIC_BWORK_DATABASE || !database.trim()) throw Error('BWork production requires explicit origin/database');
    if (!env.BWORK_RELEASE_KEYSTORE || !exists(env.BWORK_RELEASE_KEYSTORE) || !env.BWORK_RELEASE_KEY_ALIAS || !env.BWORK_RELEASE_STORE_PASSWORD || !env.BWORK_RELEASE_KEY_PASSWORD) throw Error('BWork production release signing is required; debug fallback is forbidden');
    if (/androiddebugkey|^debug$/i.test(env.BWORK_RELEASE_KEY_ALIAS)) throw Error('BWork production cannot use a debug signing alias');
  }
  return Object.freeze({name,applicationId:identity[name].applicationId,scheme:identity.production.scheme,
    schemes:name==='qa'?[identity.production.scheme,identity.qa.legacyScheme]:[identity.production.scheme],origin:server,database});
}
module.exports = { profile, setting };
