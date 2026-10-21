/** Presentation metadata never changes native company authorization. */
export interface CompanyPreference {
  id: number; name: string; short_name_ar: string; short_name_en: string; hidden: boolean;
}
export function validCompanyPreferences(value: unknown, authorized: number[]): value is CompanyPreference[] | undefined {
  if (value === undefined) return true;
  if (!Array.isArray(value) || value.length > 1000) return false;
  const seen = new Set<number>();
  const label = (v: unknown, max: number) => typeof v === 'string' && [...v].length <= max && !/[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/.test(v);
  return value.every(row => {
    if (!row || typeof row !== 'object' || !Number.isSafeInteger(row.id) || !authorized.includes(row.id) || seen.has(row.id)
        || !label(row.name, 512) || !label(row.short_name_ar, 64) || !label(row.short_name_en, 64) || typeof row.hidden !== 'boolean') return false;
    seen.add(row.id); return true;
  });
}
