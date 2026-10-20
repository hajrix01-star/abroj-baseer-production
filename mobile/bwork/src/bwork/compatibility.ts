import manifest from '../../compatibility/identities.json' with { type: 'json' };
/** One bounded owner for installed/data identity, not an old engine or API fallback. */
export const compatibility: Readonly<{
  version: number;
  qa: { applicationId: string; legacyScheme: string; certificateSha256: string; version: string; versionCode: number };
  production: { applicationId: string; scheme: string; origin: string; database: string; version: string; versionCode: number };
  storage: { chatRoot: string; mediaDirectory: string; sqlite: string; snapshots: string; pushPreferences: string };
}> = Object.freeze(manifest);

export function configurationAlias(canonical: string | undefined, previous: string | undefined): string {
  if (canonical && previous && canonical !== previous) throw Error('BWork configuration aliases conflict');
  return (canonical || previous || '').trim();
}

/** One production realm in the bundle and native build; QA compatibility is unchanged. */
export function applicationRealm(input: { profile: string; origin: string; database: string }): Readonly<{ profile: 'qa' | 'production'; origin: string; database: string }> {
  if (input.profile !== 'qa' && input.profile !== 'production') throw Error('BWork profile mismatch');
  if (input.profile === 'production' && (input.origin !== compatibility.production.origin || input.database !== compatibility.production.database)) throw Error('BWork production requires the approved public origin/database');
  return Object.freeze({ ...input, profile: input.profile });
}
