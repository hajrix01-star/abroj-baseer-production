import type { Bootstrap } from '../core/ChatEngine';
import type { Language } from './dictionary';

type CompanyName = { name?: string; name_ar?: string; name_en?: string };
const clean = (value: unknown): string => (typeof value === 'string' ? value.trim() : '');

export function companyDisplayName(
  company: CompanyName | undefined,
  language: Language,
  id: number,
): string {
  return (
    clean(language === 'ar' ? company?.name_ar : company?.name_en) ||
    clean(company?.name) ||
    String(id)
  );
}

/** Profile metadata never expands the server-authorized company ID list. */
export function authorizedCompanies(
  identity: Bootstrap,
  language: Language,
): { id: number; name: string }[] {
  const ids = [...new Set(identity.company_ids)].filter(id => Number.isSafeInteger(id) && id > 0);
  return ids.map(id => ({
    id,
    name: companyDisplayName(
      identity.profile?.companies.find(company => company.id === id),
      language,
      id,
    ),
  }));
}
