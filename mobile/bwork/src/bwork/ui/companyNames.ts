import type { Bootstrap } from '../core/ChatEngine';
import type { Language } from './dictionary';

type CompanyName = { name?: string; name_ar?: string; name_en?: string; short_name_ar?: string; short_name_en?: string };
const clean = (value: unknown): string => (typeof value === 'string' ? value.trim() : '');
const compact = (value: string) => value.replace(/^شركة\s+/u, '').replace(/\s+(?:شركة\s+)?(?:ذات مسؤولية محدودة|ذات مسئولية محدودة|مساهمة مقفلة|مساهمة سعودية مقفلة|مساهمة سعودية|مساهمة خاصة|ذ\.م\.م\.?)$/u, '').trim().slice(0, 64);

export function visibleCompanyIds(identity: Bootstrap | null): number[] {
  return [...new Set(identity?.company_ids ?? [])].filter(id => Number.isSafeInteger(id) && id > 0
    && !identity?.company_preferences?.some(company => company.id === id && company.hidden));
}
export function isCompanyVisible(identity: Bootstrap | null, id: number): boolean { return visibleCompanyIds(identity).includes(id); }
export function identityCompanyName(identity: Bootstrap, language: Language, id: number, fallback?: CompanyName): string {
  const preference = identity.company_preferences?.find(company => company.id === id);
  const profile = identity.profile?.companies.find(company => company.id === id);
  return companyDisplayName({ ...fallback, ...profile, ...preference }, language, id);
}

export function companyDisplayName(
  company: CompanyName | undefined,
  language: Language,
  id: number,
): string {
  return (
    clean(language === 'ar' ? company?.short_name_ar : company?.short_name_en) ||
    compact(clean(language === 'ar' ? company?.name_ar : company?.name_en) || clean(company?.name)) ||
    String(id)
  );
}

/** Profile metadata never expands the server-authorized company ID list. */
export function authorizedCompanies(
  identity: Bootstrap,
  language: Language,
): { id: number; name: string }[] {
  const ids = visibleCompanyIds(identity);
  return ids.map(id => ({
    id,
    name: identityCompanyName(identity, language, id),
  }));
}
