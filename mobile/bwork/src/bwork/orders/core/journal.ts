import { OrdersError } from './types.ts';
import type { OrdersIdentity, OrdersStorage, PendingAttempt, WriteResult } from './types.ts';
import { bytes, createResponse, confirmResponse, exact, id, uuid, validateCreateInput, validateConfirmInput } from './validators.ts';

export interface Attempt extends PendingAttempt {
  status: 'unknown' | 'ack'; payload: Record<string, unknown>; result?: WriteResult;
}
interface JournalData { version: 1; account: string; attempts: Attempt[] }
const locks = new WeakMap<OrdersStorage, Map<string, Promise<unknown>>>();
export function accountKey(identity: OrdersIdentity): string {
  return JSON.stringify([identity.origin, identity.db, identity.uid]);
}
function storageKey(account: string): string { return `bwork.orders.journal.v1:${encodeURIComponent(account)}`; }
function normalizedDecimal(value: string): string {
  const [whole, fraction = ''] = value.split('.'); return `${whole}.${fraction.padEnd(2, '0')}`;
}
function intent(attempt: Attempt): string {
  const payload = attempt.payload;
  // Match the server's intent normalization without changing the replay bytes.
  const normalized = attempt.kind === 'create' ? {
    company_id: payload.company_id, warehouse_id: payload.warehouse_id,
    representative_partner_id: payload.representative_partner_id,
    purchase_route: payload.purchase_route ?? 'representative',
    ...('room_id' in payload ? { room_id: payload.room_id } : {}),
    lines: (payload.lines as any[]).map(line => ({ option_id: line.option_id, quantity: normalizedDecimal(line.quantity) })).sort((a, b) => a.option_id - b.option_id),
  } : {
    company_id: payload.company_id,
    lines: (payload.lines as any[]).map(line => ({ line_id: line.line_id, actual_qty: normalizedDecimal(line.actual_qty), actual_price: normalizedDecimal(line.actual_price) })).sort((a, b) => a.line_id - b.line_id),
  };
  return JSON.stringify([attempt.kind, attempt.orderId ?? null, normalized]);
}
/** Contains write intents and durable acknowledgements only. Never wiped on logout. */
export class OrdersJournal {
  private storage: OrdersStorage;
  constructor(storage: OrdersStorage) { this.storage = storage; }

  private async locked<T>(account: string, action: () => Promise<T>): Promise<T> {
    let map = locks.get(this.storage);
    if (!map) { map = new Map(); locks.set(this.storage, map); }
    const before = map.get(account) ?? Promise.resolve();
    const running = before.catch(() => undefined).then(action);
    map.set(account, running);
    try { return await running; } finally { if (map.get(account) === running) map.delete(account); }
  }

  private async read(account: string): Promise<JournalData> {
    let raw: string | null;
    try { raw = await this.storage.getItem(storageKey(account)); }
    catch { throw new OrdersError('storage', 'Cannot read the write journal.'); }
    if (raw === null) return { version: 1, account, attempts: [] };
    try {
      if (bytes(raw) > 1048576) throw new Error();
      const data = JSON.parse(raw) as JournalData;
      exact(data, ['version', 'account', 'attempts']);
      if (data.version !== 1 || data.account !== account || !Array.isArray(data.attempts) || data.attempts.length > 21) throw new Error();
      const seen = new Set<string>();
      for (const attempt of data.attempts) {
        exact(attempt, ['uuid', 'kind', 'companyId', 'createdAt', 'status', 'payload'], ['orderId', 'result']);
        uuid(attempt.uuid); id(attempt.companyId);
        if (seen.has(attempt.uuid) || !Number.isFinite(attempt.createdAt) || !['unknown', 'ack'].includes(attempt.status)) throw new Error();
        seen.add(attempt.uuid);
        const payload = attempt.payload;
        if (payload.api_version !== 2 || payload.company_id !== attempt.companyId || payload.client_uuid !== attempt.uuid || bytes(JSON.stringify(payload)) > 65536) throw new Error();
        const { api_version: _version, client_uuid: _token, ...input } = payload;
        if (attempt.kind === 'create') {
          if (attempt.orderId !== undefined) throw new Error();
          validateCreateInput(input as any);
        } else if (attempt.kind === 'confirm') {
          id(attempt.orderId); validateConfirmInput(input as any, (input.lines as any[]).map(row => row.line_id));
        } else throw new Error();
        if (attempt.status === 'ack') {
          const result = attempt.kind === 'create' ? createResponse(attempt.result) : confirmResponse(attempt.result);
          const company = 'order' in result ? result.order.company_id : result.receipt.company_id;
          if (result.client_uuid !== attempt.uuid || company !== attempt.companyId || (attempt.kind === 'confirm' && 'receipt' in result && result.receipt.order_id !== attempt.orderId)) throw new Error();
        } else if (attempt.result !== undefined) throw new Error();
      }
      if (data.attempts.filter(attempt => attempt.status === 'unknown').length > 20) throw new Error();
      return data;
    } catch { throw new OrdersError('storage_corrupt', 'The write journal needs recovery; existing attempts were retained.'); }
  }

  private async write(data: JournalData): Promise<void> {
    const encoded = JSON.stringify(data);
    if (bytes(encoded) > 1048576) throw new OrdersError('storage_full', 'The write journal is full.');
    try {
      await this.storage.setItem(storageKey(data.account), encoded);
      if (await this.storage.getItem(storageKey(data.account)) !== encoded) throw new Error();
    } catch { throw new OrdersError('storage', 'The write journal was not durably acknowledged.'); }
  }

  async list(account: string): Promise<Attempt[]> { return this.locked(account, async () => (await this.read(account)).attempts); }

  async add(account: string, attempt: Attempt): Promise<void> {
    return this.locked(account, async () => {
      const data = await this.read(account);
      const pending = data.attempts.filter(item => item.status === 'unknown');
      const existing = pending.find(item => intent(item) === intent(attempt));
      if (existing) throw new OrdersError('unknown', 'Retry the existing attempt with its original UUID.', existing.uuid);
      if (data.attempts.some(item => item.uuid === attempt.uuid)) throw new OrdersError('invalid_uuid', 'UUID has already been used.');
      if (pending.length >= 20) throw new OrdersError('storage_full', 'Resolve existing attempts before creating another.');
      if (bytes(JSON.stringify(attempt.payload)) > 65536) throw new OrdersError('payload_too_large');
      // Acknowledged entries may be reclaimed; unknown entries never expire or evict.
      await this.write({ ...data, attempts: [...pending, attempt] });
    });
  }

  async acknowledge(account: string, token: string, result: WriteResult): Promise<void> {
    return this.locked(account, async () => {
      const data = await this.read(account);
      const index = data.attempts.findIndex(item => item.uuid === token);
      if (index < 0) throw new OrdersError('storage_corrupt');
      data.attempts[index] = { ...data.attempts[index], status: 'ack', result };
      await this.write(data);
    });
  }
}
