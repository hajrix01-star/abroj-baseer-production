import { TasksError } from './core/types.ts';
import type { TasksRequest } from './core/types.ts';
import { bytes, payloadInput } from './core/validators.ts';
import type { Request } from '../core/ChatEngine';

const ROOT = '/bchat/api/v2/work-tasks';
const positive = (value: unknown) => (typeof value === 'number' && Number.isInteger(value) && value > 0 && value <= 2147483647)
  || (typeof value === 'string' && /^[1-9][0-9]*$/.test(value) && Number(value) <= 2147483647);
/** Strict isolated facade: no legacy task endpoint, arbitrary path, payload query or JSON POST. */
export function tasksNativeRequest(input: TasksRequest, csrf: string): Request {
  const path = input.path;
  if (typeof path !== 'string' || path.includes('?') || path.includes('#')) throw new TasksError('invalid_path');
  let allowed: string[] | undefined; let required: string[] = [];
  const match = path.match(new RegExp(`^${ROOT}/([1-9][0-9]*)(/transition)?$`));
  if (match && !positive(match[1])) throw new TasksError('invalid_path');
  if (input.method === 'GET') {
    if (path === `${ROOT}/options`) allowed = [];
    else if (path === `${ROOT}/assignees`) { allowed = ['company_id', 'q', 'after_id']; required = ['company_id']; }
    else if (path === ROOT) allowed = ['view', 'state', 'company_id', 'before_id'];
    else if (match && !match[2]) { allowed = ['company_id']; required = ['company_id']; }
    if (input.payload !== undefined) throw new TasksError('invalid_payload');
  } else if (input.method === 'POST' && (path === ROOT || (match && match[2]))) allowed = [];
  if (!allowed) throw new TasksError('invalid_path');
  const query = input.query ?? {};
  if (!query || typeof query !== 'object' || Array.isArray(query) || required.some(k => !(k in query))) throw new TasksError('invalid_payload');
  for (const [key, value] of Object.entries(query)) {
    if (!allowed.includes(key) || (key === 'q' ? typeof value !== 'string' || bytes(value) > 256
      : key === 'view' ? !['mine', 'created'].includes(String(value))
        : key === 'state' ? !['open', 'done', 'cancelled'].includes(String(value)) : !positive(value))) throw new TasksError('invalid_payload');
  }
  const encoded = Object.entries(query).map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`).join('&');
  const result: Request = { method: input.method, path: `${path}${encoded ? `?${encoded}` : ''}`, signal: input.signal };
  if (input.method === 'POST') {
    if (typeof csrf !== 'string' || !csrf.trim() || csrf.length > 1024) throw new TasksError('unauthorized');
    try { payloadInput(path === ROOT ? 'create' : 'transition', input.payload as Record<string, any>); }
    catch { throw new TasksError('invalid_payload'); }
    let payload: string; try { payload = JSON.stringify(input.payload); } catch { throw new TasksError('invalid_payload'); }
    if (bytes(`csrf_token=${encodeURIComponent(csrf)}&payload=${encodeURIComponent(payload)}`) > 65536) throw new TasksError('payload_too_large');
    result.form = { csrf_token: csrf, payload };
  }
  return result;
}
