import manifest from '../../compatibility/identities.json' with { type: 'json' };
/** One bounded owner for installed/data identity, not an old engine or API fallback. */
export const compatibility: Readonly<{
  version: number;
  qa: { applicationId: string; legacyScheme: string; certificateSha256: string };
  production: { applicationId: string; scheme: string };
  storage: { chatRoot: string; mediaDirectory: string; sqlite: string; snapshots: string; pushPreferences: string };
}> = Object.freeze(manifest);

export function configurationAlias(canonical: string | undefined, previous: string | undefined): string {
  if (canonical && previous && canonical !== previous) throw Error('BWork configuration aliases conflict');
  return (canonical || previous || '').trim();
}
