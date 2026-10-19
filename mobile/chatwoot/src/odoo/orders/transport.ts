import { OrdersError, type OrdersRequest } from './core/types.ts';
import { bytes } from './core/validators.ts';
import type { Request } from '../core/ChatEngine';

const base = '/bchat/api/v2/orders';
const positive = (value: unknown) => typeof value === 'number'
  ? Number.isSafeInteger(value) && value > 0 && value <= 2147483647
  : typeof value === 'string' && /^[1-9][0-9]*$/.test(value) && Number(value) <= 2147483647;

/** A deliberately narrow facade over the existing authenticated native transport. */
export function ordersNativeRequest(input: OrdersRequest, csrf: string): Request {
  const path = input.path;
  if (typeof path !== 'string' || path.includes('?') || path.includes('#')) throw new OrdersError('invalid_path');
  let allowed: string[] | null = null;
  let required: string[] = [];
  if (input.method === 'GET') {
    if (path === `${base}/options`) allowed = ['company_id'];
    else if (path === base) { allowed = ['scope', 'before_id', 'company_id']; required = ['scope']; }
    else if (path === `${base}/rooms`) { allowed = ['company_id', 'q', 'after_id', 'preferred_room_id']; required = ['company_id']; }
    else if (new RegExp(`^${base}/[1-9][0-9]*$`).test(path)) { allowed = ['company_id', 'scope']; required = ['company_id']; }
    else if (path === `${base}/receipts`) { allowed = ['company_id', 'before_id']; required = ['company_id']; }
    else if (new RegExp(`^${base}/receipts/[1-9][0-9]*$`).test(path)) { allowed = ['company_id']; required = ['company_id']; }
  } else if (input.method === 'POST') {
    if (path === `${base}/catalog`) { allowed = ['company_id', 'q', 'category_id', 'after_id']; required = ['company_id']; }
    else if (path === base || path === `${base}/quote`
      || new RegExp(`^${base}/receipts/[1-9][0-9]*/(?:confirm|share)$`).test(path)
      || new RegExp(`^${base}/[1-9][0-9]*/share$`).test(path)) allowed = [];
  }
  if (!allowed) throw new OrdersError('invalid_path');
  const pathId = path.slice(base.length).match(/^\/(?:receipts\/)?([0-9]+)(?:\/|$)/)?.[1];
  if (pathId !== undefined && !positive(pathId)) throw new OrdersError('invalid_path');
  const query = input.query ?? {};
  if (typeof query !== 'object' || Array.isArray(query) || required.some(key => !(key in query))) throw new OrdersError('invalid_payload');
  for (const [key, value] of Object.entries(query)) {
    if (!allowed.includes(key) || (key === 'scope' ? value !== 'all'
      : key === 'q' ? typeof value !== 'string' || bytes(value) > 256
        : !positive(value))) throw new OrdersError('invalid_payload');
  }
  if (input.method === 'GET' && input.payload !== undefined) throw new OrdersError('invalid_payload');
  const encoded = Object.entries(query).map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`).join('&');
  const output: Request = { method: input.method, path: `${path}${encoded ? `?${encoded}` : ''}`, signal: input.signal };
  if (input.method === 'POST') {
    if (typeof csrf !== 'string' || !csrf.trim() || csrf.length > 1024) throw new OrdersError('unauthorized');
    if (!input.payload || typeof input.payload !== 'object' || Array.isArray(input.payload) || input.payload.api_version !== 2) throw new OrdersError('invalid_payload');
    let payload: string;
    try { payload = JSON.stringify(input.payload); }
    catch { throw new OrdersError('invalid_payload'); }
    if (`csrf_token=${encodeURIComponent(csrf)}&payload=${encodeURIComponent(payload)}`.length > 65536) throw new OrdersError('payload_too_large');
    output.form = { csrf_token: csrf, payload };
  }
  return output;
}
