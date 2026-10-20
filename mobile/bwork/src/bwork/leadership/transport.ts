import type { Request } from '../core/ChatEngine';
import { LeadershipError } from './types.ts';
import type { LeadershipRequest } from './types.ts';
import { id, query, ROOT } from './validation.ts';

/** GET-only native facade. No arbitrary routes, request body, token or mutation. */
export function leadershipNativeRequest(input: LeadershipRequest): Request {
  if (!input || input.method !== 'GET' || ![ROOT, `${ROOT}/options`].includes(input.path)) throw new LeadershipError('invalid_path');
  if (input.payload !== undefined || Object.keys(input).some(k => !['method', 'path', 'query', 'signal'].includes(k))) throw new LeadershipError('invalid_query');
  const values = input.query ?? {};
  if (values === null || typeof values !== 'object' || Array.isArray(values)) throw new LeadershipError('invalid_query');
  if (input.path.endsWith('/options')) { if (Object.keys(values).length) throw new LeadershipError('invalid_query'); }
  else {
    if (Object.keys(values).some(k => !['month', 'period', 'date', 'company_id'].includes(k))) throw new LeadershipError('invalid_query');
    query({ month: values.month as string, period: values.period as any, ...(values.date !== undefined ? { date: values.date as string } : {}), ...(values.company_id !== undefined ? { companyId: id(values.company_id) } : {}) });
  }
  const encoded = Object.entries(values).map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`).join('&');
  return { method: 'GET', path: `${input.path}${encoded ? `?${encoded}` : ''}`, signal: input.signal };
}
