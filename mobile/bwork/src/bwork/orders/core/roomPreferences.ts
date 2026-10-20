import { OrdersError } from './types.ts';
import type { OrdersStorage } from './types.ts';
import { bytes, exact, id } from './validators.ts';

const locks = new WeakMap<OrdersStorage, Map<string, Promise<unknown>>>();

/** Stores IDs only. This preference is not an authorization or a write journal. */
export class OrdersRoomPreferences {
  private storage: OrdersStorage;
  constructor(storage: OrdersStorage) { this.storage = storage; }

  private key(account: string, companyId: number): string {
    return `bwork.orders.room.v1:${encodeURIComponent(account)}:${id(companyId)}`;
  }
  private async serial<T>(key: string, work: () => Promise<T>): Promise<T> {
    let map = locks.get(this.storage);
    if (!map) { map = new Map(); locks.set(this.storage, map); }
    const previous = map.get(key) ?? Promise.resolve();
    const running = previous.catch(() => undefined).then(work);
    map.set(key, running);
    try { return await running; } finally { if (map.get(key) === running) map.delete(key); }
  }
  async get(account: string, companyId: number): Promise<number | null> {
    const key = this.key(account, companyId);
    return this.serial(key, async () => {
      let raw: string | null;
      try { raw = await this.storage.getItem(key); }
      catch { throw new OrdersError('storage', 'Cannot read the conversation preference.'); }
      if (raw === null) return null;
      try {
        if (bytes(raw) > 4096) throw new Error();
        const value = exact(JSON.parse(raw), ['version', 'account', 'company_id', 'room_id']);
        if (value.version !== 1 || value.account !== account || value.company_id !== companyId) throw new Error();
        return value.room_id === null ? null : id(value.room_id);
      } catch { throw new OrdersError('preference_corrupt', 'Choose the default conversation again.'); }
    });
  }
  async set(account: string, companyId: number, roomId: number | null, guard: () => void): Promise<void> {
    const key = this.key(account, companyId);
    if (roomId !== null) id(roomId);
    return this.serial(key, async () => {
      guard();
      const raw = JSON.stringify({ version: 1, account, company_id: companyId, room_id: roomId });
      if (bytes(raw) > 4096) throw new OrdersError('storage_full');
      try { await this.storage.setItem(key, raw); }
      catch { throw new OrdersError('storage', 'Cannot save the conversation preference.'); }
      guard();
    });
  }
}
