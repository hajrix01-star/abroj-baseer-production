import { OrdersError } from './types.ts';
import type {
  CatalogQuery, ConfirmInput, ConfirmResult, CreateInput, CreateResult, OrdersEngineDependencies,
  OrdersIdentity, OrdersRequest, PendingAttempt, QuoteInput, RoomsQuery, WriteResult,
} from './types.ts';
import { OrdersJournal, accountKey } from './journal.ts';
import type { Attempt } from './journal.ts';
import { OrdersRoomPreferences } from './roomPreferences.ts';
import {
  bytes, catalogResponse, confirmResponse, createResponse, detailResponse, id, optionsResponse,
  ordersResponse, quoteResponse, receiptDetailResponse, receiptsResponse, roomsResponse, shareResponse, uuid,
  validateConfirmInput, validateCreateInput, validateQuoteInput,
} from './validators.ts';

type Right = 'order_view' | 'order_create' | 'order_receive';
const ROOT = '/bchat/api/v2/orders';
function scopeStamp(identity: OrdersIdentity): string {
  return JSON.stringify([accountKey(identity), identity.epoch, [...identity.companyIds].sort((a, b) => a - b), identity.permissions]);
}
function copy<T>(value: T): T { return JSON.parse(JSON.stringify(value)); }
/** No polling, offline order cache, network retries, or automatic POST replay. */
export class OrdersEngine {
  private deps: OrdersEngineDependencies;
  private journal: OrdersJournal;
  private roomPreferences: OrdersRoomPreferences;
  private quoteEpoch = 0;
  private requests = new Map<string, number>();
  private controllers = new Map<string, AbortController>();
  private inflightWrites = new Set<string>();
  private revoked = new Set<string>();
  private verifiedOptions = new Map<string, { companies: number[]; order_view: boolean; order_create: boolean; order_receive: boolean; workflowVersion: number; receiptListVersion: number }>();

  constructor(dependencies: OrdersEngineDependencies) {
    this.deps = dependencies; this.journal = new OrdersJournal(dependencies.storage);
    this.roomPreferences = new OrdersRoomPreferences(dependencies.storage);
  }
  invalidateQuote(): void { this.quoteEpoch += 1; this.controllers.get('quote')?.abort(); }
  /** Session/screen teardown cancels reads; durable attempts remain untouched. */
  cancelReads(): void {
    for (const controller of this.controllers.values()) controller.abort();
    this.controllers.clear(); this.invalidateQuote();
    for (const [key, sequence] of this.requests) this.requests.set(key, sequence + 1);
  }

  private identity(right: Right, companyId?: number, allowRevoked = false): OrdersIdentity {
    const current = this.deps.identityScope();
    if (!current || !current.verified) throw new OrdersError('unauthorized');
    if (!current.origin || !current.db) throw new OrdersError('unauthorized');
    id(current.uid);
    if (!current.permissions.order_view || !current.permissions[right]) throw new OrdersError('forbidden');
    if (!allowRevoked && this.revoked.has(scopeStamp(current))) throw new OrdersError('forbidden');
    if (companyId !== undefined && !current.companyIds.includes(id(companyId))) throw new OrdersError('forbidden');
    const verified = this.verifiedOptions.get(scopeStamp(current));
    if (!allowRevoked && verified && (!verified.order_view || !verified[right] || (companyId !== undefined && !verified.companies.includes(companyId)))) throw new OrdersError('forbidden');
    return copy(current);
  }
  private guard(start: OrdersIdentity, right: Right, companyId?: number, allowRevoked = false): void {
    const current = this.deps.identityScope();
    if (!current || !current.verified || scopeStamp(current) !== scopeStamp(start)) throw new OrdersError('stale', 'Session or company permissions changed.');
    this.identity(right, companyId, allowRevoked);
  }
  private workflow(start: OrdersIdentity, right: Right, companyId?: number): void {
    this.guard(start, right, companyId);
    if (this.verifiedOptions.get(scopeStamp(start))?.workflowVersion !== 1) throw new OrdersError('server_update_required');
  }
  private globalReceipts(start: OrdersIdentity): void {
    this.guard(start, 'order_receive');
    if (this.verifiedOptions.get(scopeStamp(start))?.receiptListVersion !== 1) throw new OrdersError('server_update_required');
  }
  private conversationScope(companyId: number): OrdersIdentity {
    const start = this.identity('order_create', companyId);
    if (!start.permissions.chat_send) throw new OrdersError('forbidden');
    this.workflow(start, 'order_create', companyId); return start;
  }
  private async request(start: OrdersIdentity, right: Right, companyId: number | undefined, request: OrdersRequest, allowRevoked = false): Promise<unknown> {
    this.guard(start, right, companyId, allowRevoked);
    try {
      const result = await this.deps.transport.request(request);
      this.guard(start, right, companyId, allowRevoked);
      if (result && typeof result === 'object' && 'error' in result) {
        const error = (result as any).error;
        throw new OrdersError(typeof error?.code === 'string' ? error.code : 'server_error', typeof error?.message === 'string' ? error.message : 'Request failed.');
      }
      return result;
    } catch (error) {
      const current = this.deps.identityScope();
      if (!current || !current.verified || scopeStamp(current) !== scopeStamp(start)) throw new OrdersError('stale');
      const status = (error as any)?.status;
      if (status === 401) this.deps.onUnauthorized?.();
      if (status === 403 || (error as any)?.code === 'forbidden') {
        this.revoked.add(scopeStamp(start)); this.deps.onForbidden?.(companyId);
      }
      throw error;
    }
  }
  private async read<T>(key: string, right: Right, companyId: number | undefined, request: OrdersRequest, validate: (value: unknown) => T, allowRevoked = false): Promise<T> {
    const start = this.identity(right, companyId, allowRevoked);
    const sequence = (this.requests.get(key) ?? 0) + 1; this.requests.set(key, sequence);
    this.controllers.get(key)?.abort();
    const controller = new AbortController(); this.controllers.set(key, controller);
    try {
      const result = validate(await this.request(start, right, companyId, { ...request, signal: controller.signal }, allowRevoked));
      if (this.requests.get(key) !== sequence || controller.signal.aborted) throw new OrdersError('stale');
      return result;
    } catch (error) {
      if (controller.signal.aborted || this.requests.get(key) !== sequence) throw new OrdersError('stale');
      throw error;
    } finally { if (this.controllers.get(key) === controller) this.controllers.delete(key); }
  }

  async options(companyId?: number) {
    const right = companyId === undefined ? 'order_view' : 'order_create';
    const start = this.identity(right, companyId, true);
    const result = await this.read('options', right, companyId, { method: 'GET', path: `${ROOT}/options`, ...(companyId === undefined ? {} : { query: { company_id: id(companyId) } }) }, optionsResponse, true);
    this.guard(start, right, companyId, true);
    // Fresh server verification can unlock a previous 403, never elevate local rights.
    if (!result.can_view || (right === 'order_create' && !result.can_create) || result.companies.some(company => !start.companyIds.includes(company.id))) throw new OrdersError('forbidden');
    if (companyId !== undefined && !result.companies.some(company => company.id === companyId)) throw new OrdersError('forbidden');
    this.verifiedOptions.clear();
    this.verifiedOptions.set(scopeStamp(start), { companies: result.companies.map(company => company.id), order_view: result.can_view, order_create: result.can_create, order_receive: result.can_receive, workflowVersion: result.workflow_version ?? 0, receiptListVersion: result.receipt_list_version ?? 0 });
    this.revoked.delete(scopeStamp(start)); return result;
  }
  async catalog(companyId: number, query: CatalogQuery = {}) {
    if (query.q !== undefined && (typeof query.q !== 'string' || bytes(query.q) > 256)) throw new OrdersError('invalid_payload');
    const args: Record<string, string | number> = { company_id: id(companyId) };
    if (query.q !== undefined) args.q = query.q;
    if (query.categoryId !== undefined) args.category_id = id(query.categoryId);
    if (query.afterId !== undefined) args.after_id = id(query.afterId);
    const start = this.identity('order_create', companyId);
    const result = await this.read('catalog', 'order_create', companyId, { method: 'POST', path: `${ROOT}/catalog`, query: args, payload: { api_version: 2 } }, catalogResponse);
    this.guard(start, 'order_create', companyId);
    if (result.next_after_id !== null && (result.next_after_id <= (query.afterId ?? 0) || !result.items.some(item => item.product_id === result.next_after_id))) throw new OrdersError('invalid_response');
    if (query.afterId !== undefined && result.items.some(item => item.product_id <= query.afterId!)) throw new OrdersError('invalid_response');
    if (result.items.some(item => item.image_url && !item.image_url.endsWith(`?company_id=${companyId}`))) throw new OrdersError('invalid_response');
    return result;
  }
  async quote(input: QuoteInput) {
    const payload = copy(input); validateQuoteInput(payload);
    const start = this.identity('order_create', payload.company_id);
    const epoch = ++this.quoteEpoch;
    const result = await this.read('quote', 'order_create', payload.company_id, { method: 'POST', path: `${ROOT}/quote`, payload: { api_version: 2, ...payload } }, quoteResponse);
    this.guard(start, 'order_create', payload.company_id);
    if (epoch !== this.quoteEpoch) throw new OrdersError('stale');
    if (result.company_id !== payload.company_id || result.cart_revision !== payload.cart_revision || result.lines.length !== payload.lines.length || result.lines.some(line => !payload.lines.some(sent => sent.option_id === line.option_id && decimalEquivalent(sent.quantity, line.quantity)))) throw new OrdersError('invalid_response');
    return result;
  }
  async list(beforeId?: number, companyId?: number) {
    const query: Record<string, string | number> = { scope: 'all' };
    if (beforeId !== undefined) query.before_id = id(beforeId);
    const scope = this.identity('order_view', companyId);
    if (companyId !== undefined) { this.workflow(scope, 'order_view', companyId); query.company_id = id(companyId); }
    const result = await this.read('orders', 'order_view', companyId, { method: 'GET', path: ROOT, query }, ordersResponse);
    this.guard(scope, 'order_view', companyId);
    if (companyId !== undefined) this.workflow(scope, 'order_view', companyId);
    const companies = this.verifiedOptions.get(scopeStamp(scope))?.companies ?? scope.companyIds;
    if (result.orders.some(order => !companies.includes(order.company_id))) throw new OrdersError('invalid_response');
    if (companyId !== undefined && result.orders.some(order => order.company_id !== companyId)) throw new OrdersError('invalid_response');
    validateBeforePage(result.orders, result.next_before_id, beforeId); return result;
  }
  async rooms(companyId: number, query: RoomsQuery = {}) {
    const start = this.conversationScope(companyId);
    const args: Record<string, string | number> = { company_id: id(companyId) };
    if (query.q !== undefined) {
      if (typeof query.q !== 'string' || bytes(query.q) > 256) throw new OrdersError('invalid_payload');
      args.q = query.q;
    }
    if (query.afterId !== undefined) args.after_id = id(query.afterId);
    if (query.preferredRoomId !== undefined) args.preferred_room_id = id(query.preferredRoomId);
    const result = await this.read('orderRooms', 'order_create', companyId, { method: 'GET', path: `${ROOT}/rooms`, query: args }, roomsResponse);
    this.workflow(start, 'order_create', companyId);
    if (result.company_id !== companyId || (result.preferred_room !== null && result.preferred_room.id !== query.preferredRoomId)) throw new OrdersError('invalid_response');
    if (result.rooms.some((room, index, all) => room.id <= (query.afterId ?? 0) || (index > 0 && room.id <= all[index - 1].id))) throw new OrdersError('invalid_response');
    if (result.next_after_id !== null && (result.next_after_id <= (query.afterId ?? 0) || result.next_after_id !== result.rooms.at(-1)?.id)) throw new OrdersError('invalid_response');
    return result;
  }
  async savedRoom(companyId: number): Promise<number | null> {
    const start = this.conversationScope(companyId);
    const result = await this.roomPreferences.get(accountKey(start), companyId);
    this.workflow(start, 'order_create', companyId); return result;
  }
  async saveRoom(companyId: number, roomId: number | null): Promise<void> {
    const start = this.conversationScope(companyId);
    if (roomId !== null) {
      id(roomId);
      const current = await this.rooms(companyId, { preferredRoomId: roomId });
      this.workflow(start, 'order_create', companyId);
      if (current.preferred_room?.id !== roomId) throw new OrdersError('room_unavailable');
    }
    await this.roomPreferences.set(accountKey(start), companyId, roomId, () => this.workflow(start, 'order_create', companyId));
    this.workflow(start, 'order_create', companyId);
  }
  async shareOrder(companyId: number, orderId: number, roomId: number) {
    const start = this.conversationScope(companyId); id(orderId); id(roomId);
    const key = `${accountKey(start)}:shareOrder:${companyId}:${orderId}`;
    if (this.inflightWrites.has(key)) throw new OrdersError('busy');
    this.inflightWrites.add(key);
    try {
      const result = shareResponse(await this.request(start, 'order_create', companyId, { method: 'POST', path: `${ROOT}/${orderId}/share`, payload: { api_version: 2, company_id: companyId, room_id: roomId } }));
      this.workflow(start, 'order_create', companyId);
      if (result.order_id !== orderId || result.room_id !== roomId) throw new OrdersError('invalid_response');
      return result;
    } finally { this.inflightWrites.delete(key); }
  }
  async detail(companyId: number, orderId: number) {
    const start = this.identity('order_view', companyId);
    const result = await this.read('detail', 'order_view', companyId, { method: 'GET', path: `${ROOT}/${id(orderId)}`, query: { company_id: id(companyId), scope: 'all' } }, detailResponse);
    this.guard(start, 'order_view', companyId);
    if (result.order.id !== orderId || result.order.company_id !== companyId) throw new OrdersError('invalid_response'); return result;
  }
  async receipts(companyId?: number, beforeId?: number) {
    const query: Record<string, string | number> = companyId === undefined ? { scope: 'all' } : { company_id: id(companyId) };
    if (beforeId !== undefined) query.before_id = id(beforeId);
    const start = this.identity('order_receive', companyId);
    if (companyId === undefined) this.globalReceipts(start);
    const result = await this.read('receipts', 'order_receive', companyId, { method: 'GET', path: `${ROOT}/receipts`, query }, receiptsResponse);
    this.guard(start, 'order_receive', companyId);
    if (companyId === undefined) this.globalReceipts(start);
    const companies = this.verifiedOptions.get(scopeStamp(start))?.companies ?? start.companyIds;
    if (result.orders.some(order => !companies.includes(order.company_id) || (companyId !== undefined && order.company_id !== companyId))) throw new OrdersError('invalid_response');
    validateBeforePage(result.orders, result.next_before_id, beforeId); return result;
  }
  async receiptDetail(companyId: number, orderId: number) {
    const start = this.identity('order_receive', companyId);
    const result = await this.read('receiptDetail', 'order_receive', companyId, { method: 'GET', path: `${ROOT}/receipts/${id(orderId)}`, query: { company_id: id(companyId) } }, receiptDetailResponse);
    this.guard(start, 'order_receive', companyId);
    if (result.order.id !== orderId || result.order.company_id !== companyId) throw new OrdersError('invalid_response'); return result;
  }
  async share(companyId: number, orderId: number) {
    const start = this.identity('order_receive', companyId);
    if (!start.permissions.chat_send) throw new OrdersError('forbidden');
    const result = shareResponse(await this.request(start, 'order_receive', companyId, { method: 'POST', path: `${ROOT}/receipts/${id(orderId)}/share`, payload: { api_version: 2, company_id: id(companyId) } }));
    this.guard(start, 'order_receive', companyId);
    if (result.order_id !== orderId) throw new OrdersError('invalid_response'); return result;
  }
  async create(input: CreateInput): Promise<CreateResult> {
    const value = copy(input); validateCreateInput(value);
    const start = this.identity('order_create', value.company_id);
    this.workflow(start, 'order_create', value.company_id);
    if (value.room_id != null && !start.permissions.chat_send) throw new OrdersError('forbidden');
    const token = uuid(this.deps.uuid());
    const attempt: Attempt = { uuid: token, kind: 'create', companyId: value.company_id, createdAt: this.deps.now(), status: 'unknown', payload: { api_version: 2, ...value, client_uuid: token } };
    await this.journal.add(accountKey(start), attempt);
    const result = await this.submit(start, attempt) as CreateResult;
    this.guard(start, 'order_create', value.company_id); return result;
  }
  async confirm(orderId: number, input: ConfirmInput, expectedLineIds: readonly number[]): Promise<ConfirmResult> {
    id(orderId); const value = copy(input); validateConfirmInput(value, expectedLineIds);
    const start = this.identity('order_receive', value.company_id); const token = uuid(this.deps.uuid());
    const attempt: Attempt = { uuid: token, kind: 'confirm', companyId: value.company_id, orderId, createdAt: this.deps.now(), status: 'unknown', payload: { api_version: 2, ...value, client_uuid: token } };
    await this.journal.add(accountKey(start), attempt);
    const result = await this.submit(start, attempt) as ConfirmResult;
    this.guard(start, 'order_receive', value.company_id); return result;
  }
  async pending(): Promise<PendingAttempt[]> {
    const start = this.identity('order_view'); const attempts = await this.journal.list(accountKey(start));
    this.guard(start, 'order_view');
    const verified = this.verifiedOptions.get(scopeStamp(start));
    return attempts.filter(attempt => attempt.status === 'unknown' && start.companyIds.includes(attempt.companyId) && (!verified || verified.companies.includes(attempt.companyId)) && start.permissions[attempt.kind === 'create' ? 'order_create' : 'order_receive'] && (!verified || verified[attempt.kind === 'create' ? 'order_create' : 'order_receive']))
      .map(({ uuid: token, kind, companyId, orderId, createdAt }) => ({ uuid: token, kind, companyId, ...(orderId === undefined ? {} : { orderId }), createdAt }));
  }
  async retry(token: string): Promise<WriteResult> {
    uuid(token); const start = this.identity('order_view'); const attempts = await this.journal.list(accountKey(start));
    this.guard(start, 'order_view'); const attempt = attempts.find(item => item.uuid === token);
    if (!attempt) throw new OrdersError('not_found');
    this.guard(start, attempt.kind === 'create' ? 'order_create' : 'order_receive', attempt.companyId);
    if (attempt.kind === 'create' && attempt.payload.room_id != null && !start.permissions.chat_send) throw new OrdersError('forbidden');
    if (attempt.status === 'ack') return copy(attempt.result!);
    const result = await this.submit(start, attempt);
    this.guard(start, attempt.kind === 'create' ? 'order_create' : 'order_receive', attempt.companyId); return result;
  }
  private async submit(start: OrdersIdentity, attempt: Attempt): Promise<WriteResult> {
    const right = attempt.kind === 'create' ? 'order_create' : 'order_receive';
    const key = `${accountKey(start)}:${attempt.uuid}`;
    if (this.inflightWrites.has(key)) throw new OrdersError('unknown', 'This attempt is already being sent.', attempt.uuid);
    this.inflightWrites.add(key);
    try {
      this.guard(start, right, attempt.companyId);
      const raw = await this.request(start, right, attempt.companyId, { method: 'POST', path: attempt.kind === 'create' ? ROOT : `${ROOT}/receipts/${attempt.orderId}/confirm`, payload: copy(attempt.payload) });
      const result = attempt.kind === 'create' ? createResponse(raw) : confirmResponse(raw);
      const company = 'order' in result ? result.order.company_id : result.receipt.company_id;
      if (result.client_uuid !== attempt.uuid || company !== attempt.companyId || ('receipt' in result && result.receipt.order_id !== attempt.orderId)) throw new OrdersError('invalid_response');
      if ('order' in result && result.order.requester_id !== start.uid) throw new OrdersError('invalid_response');
      await this.journal.acknowledge(accountKey(start), attempt.uuid, result);
      this.guard(start, right, attempt.companyId);
      return result;
    } catch (error) {
      // Stale UI, lost responses and even failed ACK persistence retain the exact original intent.
      throw new OrdersError('unknown', 'The outcome is unresolved. Retry this attempt with its original UUID.', attempt.uuid, (error as any)?.status);
    } finally { this.inflightWrites.delete(key); }
  }
}
function validateBeforePage(rows: { id: number }[], cursor: number | null, before?: number): void {
  if (rows.some((row, index) => (before !== undefined && row.id >= before) || (index > 0 && row.id >= rows[index - 1].id)) || (cursor !== null && (rows.length === 0 || cursor !== rows[rows.length - 1].id))) throw new OrdersError('invalid_response');
}
function decimalEquivalent(a: string, b: string): boolean {
  // Text normalization for matching a server echo, never amount arithmetic.
  const normalized = (value: string) => { const [whole, fractional = ''] = value.split('.'); return `${whole}.${fractional.padEnd(2, '0')}`; };
  return normalized(a) === normalized(b);
}
