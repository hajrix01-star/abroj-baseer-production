/**
 * BWORK_ORDERS_NATIVE_FIXTURE
 * Isolated Android entry. NEVER imported by App.tsx or the normal entry point.
 * Actual OrdersScreen/OrdersEngine/central UI; in-memory synthetic transport and journal.
 * No runtime/auth/native session, HTTP, credentials, real storage, ERP or stock writes.
 * Fixed response amounts test value transport/display, not a pricing calculation.
 */
import React, { useEffect, useRef, useState } from 'react';
import { BackHandler, ScrollView, Text, View } from 'react-native';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
import { registerRootComponent } from 'expo';
import { OrdersEngine } from '../src/bwork/orders/core/OrdersEngine';
import { OrdersError } from '../src/bwork/orders/core/types';
import type {
  CatalogItem, ConfirmResult, CreateResult, OrderDetail, OrdersIdentity, OrdersOptions,
  OrdersRequest, OrdersStorage, OrderSummary, ReceiptDetail, WriteResult,
} from '../src/bwork/orders/core/types';
import { OrdersScreen } from '../src/bwork/orders/ui/OrdersScreen';
import type { Bootstrap, Room } from '../src/bwork/core/ChatEngine';
import { Brand } from '../src/bwork/ui/Brand';
import { NavigationDrawer, type DrawerAction } from '../src/bwork/ui/NavigationDrawer';
import { Button, colors, IconButton, Label, styles } from '../src/bwork/ui/components';
import { translator, type Language } from '../src/bwork/ui/dictionary';

export const FIXTURE_MARKER = 'BWORK_ORDERS_NATIVE_FIXTURE';
const ORIGIN = 'https://orders-native.invalid';
const STAMP = '2026-10-19T10:42:00Z';
const FIXED_QUOTE = '991.73';
const FIXED_ACTUAL = '831.49';
type Role = 'full' | 'view' | 'create' | 'receive' | 'none';
type LostAck = 'none' | 'create' | 'confirm';
export interface FixtureConfig {
  language: Language; role: Role; chatView: boolean; chatSend: boolean; online: boolean;
  lostAck: LostAck; share403: boolean;
}
const DEFAULT_CONFIG: FixtureConfig = {
  language: 'ar', role: 'full', chatView: false, chatSend: true, online: true, lostAck: 'none', share403: false,
};

function clone<T>(value: T): T { return JSON.parse(JSON.stringify(value)); }
function serverDecimal(value: string): string { const [whole, fraction = ''] = value.split('.'); return `${whole}.${fraction.padEnd(2, '0')}`; }

/** All side effects are Maps in this isolated fixture instance, including the real engine journal. */
export class SyntheticOrdersFixture {
  config: FixtureConfig;
  epoch = 1;
  logs: string[] = [];
  commits = { create: 0, confirm: 0, share: 0 };
  readonly storageValues = new Map<string, string>();
  readonly engine: OrdersEngine;
  private listeners = new Set<() => void>();
  private summaries = new Map<number, OrderSummary>();
  private orderLines = new Map<number, OrderDetail['lines']>();
  private receipts = new Map<number, ConfirmResult>();
  private memo = new Map<string, { payload: string; result: WriteResult }>();
  private lost = new Set<string>();
  private uuidCounter = 0;
  private nextOrder = 4000;

  constructor(config: FixtureConfig = DEFAULT_CONFIG) {
    this.config = { ...config };
    for (let index = 0; index < 61; index++) {
      const order = this.summary(3000 - index, index % 2 === 0 ? 41 : 42);
      order.state = index % 5 === 4 ? 'purchased' : index % 4 === 3 ? 'received' : 'sent';
      if (index === 2) order.room_id = null;
      this.summaries.set(order.id, order);
      this.orderLines.set(order.id, this.seedLines(order.id));
    }
    const storage: OrdersStorage = {
      getItem: async key => this.storageValues.get(key) ?? null,
      setItem: async (key, value) => { this.storageValues.set(key, value); },
    };
    this.engine = new OrdersEngine({
      transport: { request: request => this.request(request) }, storage,
      identityScope: () => this.identityScope(), now: () => Date.now(),
      uuid: () => `10000000-0000-4000-8000-${String(++this.uuidCounter).padStart(12, '0')}`,
      onUnauthorized: () => this.log('DENIED synthetic unauthorized'),
      onForbidden: company => this.log(`DENIED synthetic forbidden company=${company ?? 'all'}`),
    });
  }

  private label(ar: string, en: string) { return this.config.language === 'ar' ? ar : en; }
  private rights() {
    const role = this.config.role;
    return { order_view: role !== 'none', order_create: role === 'full' || role === 'create',
      order_receive: role === 'full' || role === 'receive', chat_send: this.config.chatSend };
  }
  identityScope(): OrdersIdentity {
    return { origin: ORIGIN, db: 'SYNTHETIC_ORDERS_NATIVE', uid: 990001, epoch: this.epoch,
      verified: this.config.online, companyIds: [41, 42], permissions: this.rights() };
  }
  bootstrap(): Bootstrap {
    return { api_version: 2, database: 'SYNTHETIC_ORDERS_NATIVE', user_id: 990001,
      company_ids: [41, 42], current_company_id: 41,
      permissions: { ...this.rights(), chat_view: this.config.chatView, revision: this.epoch },
      profile: { name: 'SYNTHETIC Android fixture', companies: [
        { id: 41, name: 'Fixture Company A', name_ar: 'شركة الاختبار ألف', name_en: 'Fixture Company A' },
        { id: 42, name: 'Fixture Company B', name_ar: 'شركة الاختبار باء', name_en: 'Fixture Company B' },
      ] } };
  }
  rooms(): Room[] {
    if (!this.config.chatView || !this.config.chatSend) return [];
    return [41, 42].map(company => ({ id: company === 41 ? 501 : 502, company_id: company,
      membership_id: company + 900, is_group: true, name: this.label(`غرفة اختبار ${company}`, `Fixture room ${company}`) }));
  }
  subscribe(callback: () => void): () => void { this.listeners.add(callback); return () => { this.listeners.delete(callback); }; }
  log(message: string) {
    this.logs.push(`${String(this.logs.length + 1).padStart(3, '0')} ${message}`);
    if (this.logs.length > 120) this.logs.splice(0, this.logs.length - 120);
    for (const listener of this.listeners) listener();
  }
  configure(update: Partial<FixtureConfig>) {
    this.engine.cancelReads(); this.config = { ...this.config, ...update }; this.epoch++;
    this.log(`CONFIG epoch=${this.epoch} role=${this.config.role} chat_view=${this.config.chatView} chat_send=${this.config.chatSend} online=${this.config.online} lost=${this.config.lostAck} share403=${this.config.share403}`);
  }
  private summary(id: number, company: number): OrderSummary {
    return { id, name: `SYN-${id}`, company_id: company,
      company_name: company === 41 ? this.label('شركة الاختبار ألف', 'Fixture Company A') : this.label('شركة الاختبار باء', 'Fixture Company B'),
      requester_id: 990001, requester_name: this.label('مستخدم صناعي', 'Synthetic requester'), state: 'sent',
      purchase_route: 'representative', purchase_route_name: this.label('مندوب', 'Representative'),
      representative_id: 91, representative_name: this.label('مندوب اختبار', 'Fixture representative'),
      requested_total: FIXED_QUOTE, currency_symbol: 'SAR', submitted_at: STAMP, room_id: company === 41 ? 501 : 502 };
  }
  catalogItems(): CatalogItem[] {
    return Array.from({ length: 30 }, (_, index) => ({ id: 2001 + index, product_id: 1001 + index,
      product_name: this.label(`صنف اختبار ${index + 1}`, `Fixture product ${index + 1}`),
      option_name: this.label(index % 2 ? 'عبوة شراء' : 'كرتون شراء', index % 2 ? 'Purchase pack' : 'Purchase case'),
      uom_name: this.label('وحدة', 'Unit'), packaging_note: this.label('بيانات صناعية فقط', 'Synthetic data only'),
      category_id: index % 2 ? 62 : 61, category_name: this.label(index % 2 ? 'فئة باء' : 'فئة ألف', index % 2 ? 'Category B' : 'Category A'),
      last_price: '17.30', currency_symbol: 'SAR', image_url: '' }));
  }
  private seedLines(orderId: number): OrderDetail['lines'] {
    return this.catalogItems().slice(0, 2).map((item, index) => ({ line_id: orderId * 10 + index + 1,
      option_id: item.id, product_name: item.product_name, option_name: item.option_name,
      requested_qty: index ? '1.00' : '2.00', available: true, current_option: item }));
  }
  private options(): OrdersOptions {
    return { api_version: 2, workflow_version: 1, access: this.rights().order_create || this.rights().order_receive ? 'operator' : 'viewer',
      can_view: this.rights().order_view, can_create: this.rights().order_create, can_receive: this.rights().order_receive,
      companies: this.bootstrap().profile!.companies.map(company => ({ id: company.id, name: this.label(company.name_ar!, company.name_en!) })),
      warehouses: [{ id: 71, name: this.label('مستودع اختبار رئيسي', 'Fixture main warehouse') }, { id: 72, name: this.label('مستودع اختبار ثانٍ', 'Fixture second warehouse') }],
      default_warehouse_id: 71, representatives: [{ id: 91, name: this.label('مندوب اختبار', 'Fixture representative') }],
      categories: [{ id: 61, name: this.label('فئة ألف', 'Category A') }, { id: 62, name: this.label('فئة باء', 'Category B') }],
      purchase_routes: [{ code: 'representative', name: 'Representative' }, { code: 'cash', name: 'Cash' }, { code: 'bank_transfer', name: 'Transfer' }] };
  }
  private detail(company: number, id: number): OrderDetail {
    const order = this.summaries.get(id);
    if (!order || order.company_id !== company) throw new OrdersError('forbidden', 'Synthetic company mismatch', undefined, 403);
    return { api_version: 2, order: { ...order, warehouse_id: 71 }, lines: clone(this.orderLines.get(id)!) };
  }
  private receiptDetail(company: number, id: number): ReceiptDetail {
    const detail = this.detail(company, id);
    return { api_version: 2, order: { ...detail.order, warehouse_name: this.label('مستودع اختبار رئيسي', 'Fixture main warehouse') },
      lines: detail.lines.map(line => ({ line_id: line.line_id, product_name: line.product_name, option_name: line.option_name,
        uom_name: this.label('وحدة', 'Unit'), requested_qty: line.requested_qty, manager_received_qty: line.requested_qty })) };
  }
  private replay(payload: Record<string, unknown>): WriteResult | null {
    const uuid = String(payload.client_uuid), prior = this.memo.get(uuid);
    if (!prior) return null;
    if (prior.payload !== JSON.stringify(payload)) throw new OrdersError('uuid_conflict', 'Synthetic payload changed');
    this.log(`REPLAY sameUUID=${uuid} samePayload=true`);
    return { ...clone(prior.result), replayed: true };
  }
  private maybeLose(kind: 'create' | 'confirm', uuid: string) {
    if (this.config.lostAck === kind && !this.lost.has(`${kind}/${uuid}`)) {
      this.lost.add(`${kind}/${uuid}`); this.log(`LOST_ACK ${kind} uuid=${uuid} syntheticCommitAlreadySaved=true`);
      throw new Error('Synthetic response lost after in-memory commit');
    }
  }

  async request(request: OrdersRequest): Promise<unknown> {
    if (!this.config.online) throw new Error('Synthetic offline');
    if (request.signal?.aborted) throw new OrdersError('stale');
    const query = request.query ?? {}, payload = request.payload ?? {};
    const company = Number(query.company_id ?? payload.company_id ?? 41);
    if (!request.path.startsWith('/bwork/api/v2/orders') || ![41, 42].includes(company)) throw new OrdersError('forbidden', 'Synthetic allowlist', undefined, 403);
    this.log(`${request.method} ${request.path} company=${company}${payload.client_uuid ? ` uuid=${String(payload.client_uuid)}` : ''}`);
    // No fetch/HTTP call exists here. Responses are deterministic fixture objects.
    if (request.path.endsWith('/options')) return clone(this.options());
    if (request.path.endsWith('/rooms')) {
      if (!this.config.chatView || !this.config.chatSend) throw new OrdersError('forbidden');
      const eligible = [{ id: company === 41 ? 501 : 502, name: 'Synthetic purchase room' }];
      const preferred = eligible.find(room => room.id === Number(query.preferred_room_id)) ?? null;
      return { api_version: 2, company_id: company, rooms: eligible.filter(room => room.id > Number(query.after_id ?? 0) && room.name.toLowerCase().includes(String(query.q ?? '').toLowerCase())), next_after_id: null, preferred_room: preferred };
    }
    if (request.path.endsWith('/catalog')) {
      const search = String(query.q ?? '').toLowerCase(), category = Number(query.category_id ?? 0), after = Number(query.after_id ?? 0);
      const matching = this.catalogItems().filter(item => item.product_id > after && (!category || category === item.category_id) && (!search || item.product_name.toLowerCase().includes(search)));
      const items = matching.slice(0, 24); this.log(`CATALOG items=${items.length} option_ids=${items.map(item => item.id).join(',')}`);
      return { api_version: 2, items, next_after_id: matching.length > 24 ? items.at(-1)!.product_id : null };
    }
    if (request.path.endsWith('/quote')) {
      const lines = payload.lines as { option_id: number; quantity: string }[];
      return { api_version: 2, company_id: company, cart_revision: payload.cart_revision,
        lines: lines.map(line => ({ ...line, quantity: serverDecimal(line.quantity), unit_price: '17.30', line_total: '17.30' })),
        estimated_total: FIXED_QUOTE, currency_code: 'SAR', currency_symbol: 'SAR', quoted_at: STAMP };
    }
    const confirm = /^\/bwork\/api\/v2\/orders\/receipts\/(\d+)\/confirm$/.exec(request.path);
    if (confirm) {
      const replay = this.replay(payload); if (replay) return replay;
      const id = Number(confirm[1]), original = this.detail(company, id);
      if (original.order.state === 'purchased') throw new OrdersError('receipt_closed');
      const result: ConfirmResult = { api_version: 2, client_uuid: String(payload.client_uuid), replayed: false,
        receipt: { order_id: id, name: original.order.name, state: 'purchased', company_id: company,
          actual_total: FIXED_ACTUAL, currency_symbol: 'SAR', picking_id: null, confirmed_at: STAMP, confirmed_by_id: 990001 } };
      this.summaries.set(id, { ...original.order, state: 'purchased' }); this.receipts.set(id, result);
      this.memo.set(result.client_uuid, { payload: JSON.stringify(payload), result }); this.commits.confirm++;
      this.log(`COMMIT confirm=${this.commits.confirm} uuid=${result.client_uuid} actual_total=${FIXED_ACTUAL} NO_REAL_STOCK`);
      this.maybeLose('confirm', result.client_uuid); return clone(result);
    }
    const orderShare = /^\/bwork\/api\/v2\/orders\/(\d+)\/share$/.exec(request.path);
    if (orderShare) {
      if (!this.config.chatView || !this.config.chatSend || this.config.share403) throw new OrdersError('forbidden');
      const original = this.detail(company, Number(orderShare[1]));
      const roomId = Number(payload.room_id);
      if (roomId !== (company === 41 ? 501 : 502)) throw new OrdersError('room_unavailable');
      if (original.order.room_id && original.order.room_id !== roomId) throw new OrdersError('order_share_conflict');
      const replayed = original.order.room_id === roomId;
      if (!replayed) { this.summaries.set(original.order.id, { ...original.order, room_id: roomId }); this.commits.share++; }
      return { api_version: 2, order_id: original.order.id, room_id: roomId, message_id: original.order.id + 7000, shared: true, replayed };
    }
    const share = /^\/bwork\/api\/v2\/orders\/receipts\/(\d+)\/share$/.exec(request.path);
    if (share) {
      const id = Number(share[1]), original = this.detail(company, id);
      if (this.config.share403 || !this.config.chatSend) { this.log(`SHARE_403 order=${id} confirmCommits=${this.commits.confirm}`); throw new OrdersError('forbidden', 'Synthetic membership denied', undefined, 403); }
      if (!original.order.room_id) throw new OrdersError('room_unavailable');
      if (!this.receipts.has(id)) throw new OrdersError('receipt_not_confirmed');
      this.commits.share++; this.log(`COMMIT share=${this.commits.share} original_room=${original.order.room_id} confirmCommits=${this.commits.confirm} NO_REAL_MESSAGE`);
      return { api_version: 2, order_id: id, room_id: original.order.room_id, message_id: id + 8000, shared: true, replayed: false };
    }
    const receipt = /^\/bwork\/api\/v2\/orders\/receipts\/(\d+)$/.exec(request.path);
    if (receipt) return this.receiptDetail(company, Number(receipt[1]));
    if (request.path.endsWith('/receipts')) {
      const before = Number(query.before_id ?? Infinity);
      const matching = [...this.summaries.values()].filter(order => order.company_id === company && order.id < before && ['sent', 'received'].includes(order.state)).sort((a, b) => b.id - a.id);
      const orders = matching.slice(0, 30).map(order => ({ ...order, warehouse_name: this.label('مستودع اختبار رئيسي', 'Fixture main warehouse') }));
      return { api_version: 2, orders, next_before_id: matching.length > 30 ? orders.at(-1)!.id : null };
    }
    const detail = /^\/bwork\/api\/v2\/orders\/(\d+)$/.exec(request.path);
    if (detail) return this.detail(company, Number(detail[1]));
    if (request.path === '/bwork/api/v2/orders' && request.method === 'GET') {
      const before = Number(query.before_id ?? Infinity);
      const matching = [...this.summaries.values()].filter(order => order.id < before && (!query.company_id || order.company_id === company)).sort((a, b) => b.id - a.id), orders = matching.slice(0, 30);
      return { api_version: 2, orders: clone(orders), next_before_id: matching.length > 30 ? orders.at(-1)!.id : null };
    }
    if (request.path === '/bwork/api/v2/orders' && request.method === 'POST') {
      const replay = this.replay(payload); if (replay) return replay;
      const order = this.summary(++this.nextOrder, company);
      order.purchase_route = payload.purchase_route as OrderSummary['purchase_route'];
      order.room_id = typeof payload.room_id === 'number' ? payload.room_id : null;
      order.representative_id = typeof payload.representative_partner_id === 'number' ? payload.representative_partner_id : null;
      this.summaries.set(order.id, order);
      const catalog = this.catalogItems(), lines = payload.lines as { option_id: number; quantity: string }[];
      this.orderLines.set(order.id, lines.map((line, index) => { const item = catalog.find(item => item.id === line.option_id)!;
        return { line_id: order.id * 10 + index + 1, option_id: item.id, product_name: item.product_name, option_name: item.option_name,
          requested_qty: serverDecimal(line.quantity), available: true, current_option: item }; }));
      const result: CreateResult = { api_version: 2, order, client_uuid: String(payload.client_uuid), replayed: false };
      this.memo.set(result.client_uuid, { payload: JSON.stringify(payload), result }); this.commits.create++;
      this.log(`COMMIT create=${this.commits.create} uuid=${result.client_uuid} fixed_requested_total=${FIXED_QUOTE} NO_REAL_ORDER`);
      this.maybeLose('create', result.client_uuid); return clone(result);
    }
    throw new OrdersError('invalid_payload', `Unknown synthetic route ${request.path}`);
  }
}

/** Direct engine probe runs in the native JS runtime, separately from manual UI/IME checks. */
export async function runFixtureProbe(): Promise<string> {
  const fixture = new SyntheticOrdersFixture({ ...DEFAULT_CONFIG, language: 'en', lostAck: 'create' });
  const engine = fixture.engine;
  const assert = (condition: unknown, message: string) => { if (!condition) throw new Error(message); };
  await engine.options(); await engine.options(41);
  const catalog = await engine.catalog(41); assert(catalog.items.length === 24, 'catalog24');
  const quote = await engine.quote({ company_id: 41, warehouse_id: 71, cart_revision: 1, lines: [{ option_id: 2001, quantity: '1' }] });
  assert(quote.estimated_total === FIXED_QUOTE, 'fixed server quote');
  let createUuid = '';
  try { await engine.create({ company_id: 41, warehouse_id: 71, representative_partner_id: 91, purchase_route: 'representative', lines: [{ option_id: 2001, quantity: '1' }] }); }
  catch (error) { assert(error instanceof OrdersError && error.code === 'unknown', 'lost create ACK becomes unknown'); createUuid = (error as OrdersError).attemptId!; }
  assert(createUuid && (await engine.pending()).some(attempt => attempt.uuid === createUuid), 'durable pre-POST UUID');
  const created = await engine.retry(createUuid);
  assert('order' in created && created.client_uuid === createUuid && created.replayed && fixture.commits.create === 1, 'same create UUID/payload once');
  fixture.configure({ lostAck: 'confirm', share403: true }); await engine.options();
  const receipt = await engine.receiptDetail(41, 3000); let receiptUuid = '';
  try { await engine.confirm(3000, { company_id: 41, lines: receipt.lines.map(line => ({ line_id: line.line_id, actual_qty: '1', actual_price: '1' })) }, receipt.lines.map(line => line.line_id)); }
  catch (error) { assert(error instanceof OrdersError && error.code === 'unknown', 'lost confirm ACK becomes unknown'); receiptUuid = (error as OrdersError).attemptId!; }
  const confirmed = await engine.retry(receiptUuid);
  assert('receipt' in confirmed && confirmed.client_uuid === receiptUuid && confirmed.replayed && fixture.commits.confirm === 1, 'same confirm UUID once');
  const original = await engine.detail(41, 3000); assert(original.order.room_id === 501 && fixture.rooms().length === 0, 'orders-only original room from detail');
  try { await engine.share(41, 3000); throw new Error('Expected share403'); }
  catch (error) { assert(error instanceof OrdersError && error.status === 403, 'explicit share403'); }
  assert(fixture.commits.confirm === 1 && fixture.commits.share === 0, 'share failure never repeats confirm');
  const workflow = new SyntheticOrdersFixture({ ...DEFAULT_CONFIG, chatView: true });
  await workflow.engine.options();
  const next = await workflow.engine.create({ company_id: 41, warehouse_id: 71, purchase_route: 'cash', representative_partner_id: null, lines: [{ option_id: 2001, quantity: '1' }] });
  await workflow.engine.saveRoom(41, 501);
  assert(await workflow.engine.savedRoom(41) === 501 && await workflow.engine.savedRoom(42) === null, 'scoped conversation default');
  const firstShare = await workflow.engine.shareOrder(41, next.order.id, 501);
  const secondShare = await workflow.engine.shareOrder(41, next.order.id, 501);
  assert(!firstShare.replayed && secondShare.replayed && workflow.commits.create === 1 && workflow.commits.share === 1, 'post-create share replay never duplicates order/message');
  const scopedPage = await workflow.engine.list(undefined, 42);
  assert(scopedPage.orders.every(order => order.company_id === 42), 'company page is filtered server-side');
  return `${FIXTURE_MARKER} PROBE PASS\ncatalog24 / quote=${FIXED_QUOTE}\ncreateUUID=${createUuid} commits=1 replayed=true\nconfirmUUID=${receiptUuid} commits=1 replayed=true\norders-only rooms=0 / originalRoom=501 / share403 / confirmStill=1\nMEMORY ONLY / NO HTTP / NO ERP\n${fixture.logs.join('\n')}`;
}

function PreviewApp() {
  const fixtureRef = useRef<SyntheticOrdersFixture | null>(null);
  if (!fixtureRef.current) fixtureRef.current = new SyntheticOrdersFixture();
  const fixture = fixtureRef.current;
  const [revision, setRevision] = useState(0), [surface, setSurface] = useState<'controls' | 'orders' | 'logs'>('controls');
  const [menu, setMenu] = useState(false), [probe, setProbe] = useState('Not run'), [probeBusy, setProbeBusy] = useState(false);
  const [selectedCompanyId, setSelectedCompanyId] = useState(0);
  const language = fixture.config.language, t = translator(language);
  const configure = (update: Partial<FixtureConfig>) => { fixture.configure(update); setRevision(value => value + 1); };
  useEffect(() => fixture.subscribe(() => setRevision(value => value + 1)), [fixture]);
  useEffect(() => {
    const listener = BackHandler.addEventListener('hardwareBackPress', () => { if (menu) { setMenu(false); return true; } if (surface !== 'controls') { setSurface('controls'); return true; } return false; });
    return () => listener.remove();
  }, [surface, menu]);
  const action = (value: DrawerAction) => {
    if (value === 'ar' || value === 'en') configure({ language: value });
    else if (value === 'logout') { fixture.log('FIXTURE logout: hide surface; no real auth session'); setSurface('controls'); }
    else if (value === 'refresh') configure({});
    setMenu(false);
  };
  return <SafeAreaProvider><SafeAreaView style={styles.page}>
    <View style={{ paddingHorizontal: 8, paddingVertical: 4, backgroundColor: colors.warning }}><Text accessibilityLabel={FIXTURE_MARKER} style={{ fontSize: 10, color: colors.ink }}>{FIXTURE_MARKER} · NO HTTP · MEMORY ONLY</Text></View>
    {surface === 'orders' ? <>
      <View style={[styles.row, { backgroundColor: colors.white, paddingHorizontal: 8 }]}>
        <IconButton icon="menu" label={t('menu')} onPress={() => setMenu(true)} /><View style={{ flex: 1 }}><Brand /></View>
        <Button quiet title="Fixture" onPress={() => setSurface('controls')} />
      </View>
      <OrdersScreen key={fixture.epoch} scopeKey={`${FIXTURE_MARKER}/${fixture.epoch}`} engine={fixture.engine} identity={fixture.bootstrap()}
        language={language} online={fixture.config.online} selectedCompanyId={selectedCompanyId} onCompanyChange={setSelectedCompanyId} rooms={fixture.rooms()} />
      <NavigationDrawer visible={menu} identity={fixture.bootstrap()} language={language} t={t} offline={!fixture.config.online}
        pendingCount={0} busy={false} canManage={false} close={() => setMenu(false)} onAction={action} />
    </> : <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ padding: 16, gap: 12 }}>
      <Label language={language}>{surface === 'logs' ? 'Synthetic request evidence' : 'معاينة Android صناعية معزولة / Isolated native orders fixture'}</Label>
      <Label language={language} muted>Actual OrdersScreen + OrdersEngine + central components. No HTTP, credentials, operational data or persistent storage. Fixed response amounts verify display only, not pricing.</Label>
      {surface === 'logs' ? <>
        <Button title="Back to fixture controls" onPress={() => setSurface('controls')} />
        <Text selectable accessibilityLabel="Native fixture request log" style={{ color: colors.ink, fontSize: 11 }}>{fixture.logs.join('\n') || 'No synthetic requests yet'}</Text>
      </> : <>
        <View style={styles.row}><Button title="AR" quiet={language !== 'ar'} onPress={() => configure({ language: 'ar' })} /><Button title="EN" quiet={language !== 'en'} onPress={() => configure({ language: 'en' })} /></View>
        <Label language={language}>Role / حقوق صناعية: {fixture.config.role}</Label>
        <View style={styles.row}>{(['full', 'view', 'create', 'receive', 'none'] as const).map(role => <Button key={role} title={`Role ${role}`} quiet={role !== fixture.config.role} onPress={() => configure({ role })} />)}</View>
        <Button quiet title={`chat_view ${fixture.config.chatView ? 'ON' : 'OFF (orders-only; rooms=[])'}`} onPress={() => configure({ chatView: !fixture.config.chatView })} />
        <Button quiet title={`chat_send ${fixture.config.chatSend ? 'ON' : 'OFF'}`} onPress={() => configure({ chatSend: !fixture.config.chatSend })} />
        <Button quiet title={`Network ${fixture.config.online ? 'ONLINE synthetic' : 'OFFLINE'}`} onPress={() => configure({ online: !fixture.config.online })} />
        <Label language={language}>Lose one response after synthetic commit: {fixture.config.lostAck}</Label>
        <View style={styles.row}>{(['none', 'create', 'confirm'] as const).map(lostAck => <Button key={lostAck} title={`Lost ACK ${lostAck}`} quiet={lostAck !== fixture.config.lostAck} onPress={() => configure({ lostAck })} />)}</View>
        <Button quiet title={`Share 403 ${fixture.config.share403 ? 'ON' : 'OFF'}`} onPress={() => configure({ share403: !fixture.config.share403 })} />
        <Button title="Open actual OrdersScreen" onPress={() => setSurface('orders')} />
        <Button quiet title="Show synthetic request log" onPress={() => setSurface('logs')} />
        <Button title="Run native engine probe" busy={probeBusy} onPress={() => { if (probeBusy) return; setProbeBusy(true); void runFixtureProbe().then(setProbe).catch(error => setProbe(`PROBE FAIL ${String(error)}`)).finally(() => setProbeBusy(false)); }} />
        <Text selectable accessibilityLabel="Native fixture probe result" style={{ color: colors.ink, fontSize: 11 }}>{probe}</Text>
        <Text accessibilityLabel="Native fixture commits" style={{ color: colors.muted }}>epoch={fixture.epoch} renders={revision} create={fixture.commits.create} confirm={fixture.commits.confirm} share={fixture.commits.share}</Text>
      </>}
    </ScrollView>}
  </SafeAreaView></SafeAreaProvider>;
}

registerRootComponent(PreviewApp);
