import { OrdersError } from './types.ts';
import type {
  CatalogPage, ConfirmInput, ConfirmResult, CreateInput, CreateResult, OrderDetail,
  OrdersOptions, OrdersPage, QuoteInput, QuoteResult, ReceiptDetail, ReceiptsPage, ShareResult,
} from './types.ts';

type Obj = Record<string, any>;
export function invalid(message: string): never { throw new OrdersError('invalid_payload', message); }
export function object(value: unknown): Obj {
  if (!value || typeof value !== 'object' || Array.isArray(value)) invalid('Expected an object.');
  return value as Obj;
}
export function exact(value: unknown, required: string[], optional: string[] = []): Obj {
  const row = object(value);
  if (required.some(key => !(key in row)) || Object.keys(row).some(key => !required.includes(key) && !optional.includes(key))) invalid('Unexpected fields.');
  return row;
}
export function id(value: unknown): number {
  if (!Number.isInteger(value) || (value as number) < 1 || (value as number) > 2147483647) invalid('Invalid record ID.');
  return value as number;
}
export function uuid(value: unknown): string {
  if (typeof value !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value)) invalid('Expected UUIDv4.');
  return value.toLowerCase();
}
/** UTF-8 byte count without requiring browser/Node globals in React Native. */
export function bytes(value: string): number {
  let count = 0;
  for (const character of value) {
    const point = character.codePointAt(0)!;
    count += point <= 0x7f ? 1 : point <= 0x7ff ? 2 : point <= 0xffff ? 3 : 4;
  }
  return count;
}
function text(value: unknown, max = 512): void {
  if (typeof value !== 'string' || bytes(value) > max) invalid('Invalid server text.');
}
function bool(value: unknown): void { if (typeof value !== 'boolean') invalid('Expected boolean.'); }
function array(value: unknown, maximum: number, minimum = 0): any[] {
  if (!Array.isArray(value) || value.length > maximum || value.length < minimum) invalid('Invalid list size.');
  return value;
}
function unique(values: unknown[]): void { if (new Set(values).size !== values.length) invalid('Duplicate record.'); }
export function decimal(value: unknown, digits: number, positive = false): string {
  if (typeof value !== 'string' || !new RegExp(`^(?:[1-9][0-9]{0,${digits - 1}}|0)(?:\\.[0-9]{1,2})?$`).test(value)) invalid('Use decimal strings with at most two decimal places.');
  if (positive && !/[1-9]/.test(value)) invalid('Quantity must be positive.');
  return value;
}
function money(value: unknown): void {
  if (typeof value !== 'string' || !/^-?(?:0|[1-9][0-9]*)\.[0-9]{2}$/.test(value) || value.length > 40) invalid('Invalid server amount.');
}
function stamp(value: unknown): void {
  if (value !== null && (typeof value !== 'string' || !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/.test(value))) invalid('Invalid server timestamp.');
}
function nullableId(value: unknown): void { if (value !== null) id(value); }
function state(value: unknown): void { if (!['draft', 'sent', 'received', 'purchased', 'cancel'].includes(value as string)) invalid('Invalid order state.'); }
function route(value: unknown): void { if (!['representative', 'cash', 'bank_transfer'].includes(value as string)) invalid('Invalid purchase route.'); }
function base(value: unknown): Obj {
  const row = object(value);
  if (row.api_version !== 2 || bytes(JSON.stringify(row)) > 65536) invalid('Invalid API response.');
  return row;
}
function selections(value: unknown, limit: number): void {
  const rows = array(value, limit); rows.forEach(row => { object(row); id(row.id); text(row.name); }); unique(rows.map(row => row.id));
}
function cartLines(value: unknown): void {
  const rows = array(value, 100, 1);
  rows.forEach(row => { exact(row, ['option_id', 'quantity']); id(row.option_id); decimal(row.quantity, 6, true); });
  unique(rows.map(row => row.option_id));
}
export function validateQuoteInput(value: QuoteInput): void {
  const row = exact(value, ['company_id', 'warehouse_id', 'cart_revision', 'lines']);
  id(row.company_id); id(row.warehouse_id); id(row.cart_revision); cartLines(row.lines);
}
export function validateCreateInput(value: CreateInput): void {
  const row = exact(value, ['company_id', 'warehouse_id', 'representative_partner_id', 'lines'], ['purchase_route', 'room_id']);
  id(row.company_id); id(row.warehouse_id); nullableId(row.representative_partner_id); cartLines(row.lines);
  if ('purchase_route' in row) route(row.purchase_route);
  if (row.purchase_route && row.purchase_route !== 'representative' && row.representative_partner_id !== null) invalid('This route cannot have a representative.');
  if ('room_id' in row) nullableId(row.room_id);
}
export function validateConfirmInput(value: ConfirmInput, expectedLineIds: readonly number[]): void {
  const row = exact(value, ['company_id', 'lines']); id(row.company_id);
  const rows = array(row.lines, 100, 1);
  rows.forEach(line => {
    exact(line, ['line_id', 'actual_qty', 'actual_price']); id(line.line_id);
    decimal(line.actual_qty, 6); decimal(line.actual_price, 9);
    if (/[1-9]/.test(line.actual_qty) !== /[1-9]/.test(line.actual_price)) invalid('Actual quantity and price are inconsistent.');
  });
  unique(rows.map(line => line.line_id));
  const ids = array(expectedLineIds, 100, 1); ids.forEach(id); unique(ids);
  if (ids.length !== rows.length || rows.some(line => !ids.includes(line.line_id))) invalid('All receipt lines are required.');
  if (!rows.some(line => /[1-9]/.test(line.actual_qty))) invalid('At least one item must be received.');
}
function catalogItem(value: unknown): void {
  const row = object(value);
  ['id', 'product_id', 'category_id'].forEach(key => id(row[key]));
  ['product_name', 'option_name', 'uom_name', 'packaging_note', 'category_name', 'currency_symbol'].forEach(key => text(row[key]));
  money(row.last_price); text(row.image_url, 512);
  if (row.image_url !== '' && !/^\/bchat\/api\/v2\/orders\/image\/[1-9][0-9]*\?company_id=[1-9][0-9]*$/.test(row.image_url)) invalid('Invalid catalogue image path.');
}
function orderSummary(value: unknown): void {
  const row = object(value); id(row.id); id(row.company_id); id(row.requester_id);
  ['name', 'company_name', 'requester_name', 'purchase_route_name', 'representative_name', 'currency_symbol'].forEach(key => text(row[key]));
  state(row.state); route(row.purchase_route); nullableId(row.representative_id); nullableId(row.room_id); money(row.requested_total); stamp(row.submitted_at);
}
function receiptSummary(value: unknown): void {
  const row = object(value); id(row.id); id(row.company_id); state(row.state);
  ['name', 'warehouse_name', 'requester_name', 'currency_symbol'].forEach(key => text(row[key]));
  money(row.requested_total); stamp(row.submitted_at);
}
export function optionsResponse(value: unknown): OrdersOptions {
  const row = base(value); selections(row.companies, 20);
  if (!['operator', 'viewer'].includes(row.access)) invalid('Invalid access.');
  ['can_view', 'can_create', 'can_receive'].forEach(key => bool(row[key]));
  if (row.purchase_routes !== undefined) array(row.purchase_routes, 3).forEach(item => { route(item.code); text(item.name); });
  if (row.warehouses !== undefined) selections(row.warehouses, 50);
  if (row.representatives !== undefined) selections(row.representatives, 100);
  if (row.categories !== undefined) selections(row.categories, 100);
  if (row.default_warehouse_id !== undefined) nullableId(row.default_warehouse_id);
  return row as OrdersOptions;
}
export function catalogResponse(value: unknown): CatalogPage {
  const row = base(value); array(row.items, 24).forEach(catalogItem); nullableId(row.next_after_id);
  unique(row.items.map((item: Obj) => item.id)); return row as CatalogPage;
}
export function quoteResponse(value: unknown): QuoteResult {
  const row = base(value); id(row.company_id); id(row.cart_revision);
  array(row.lines, 100, 1).forEach(line => { id(line.option_id); money(line.quantity); money(line.unit_price); money(line.line_total); });
  unique(row.lines.map((line: Obj) => line.option_id)); money(row.estimated_total); text(row.currency_code, 32); text(row.currency_symbol); stamp(row.quoted_at);
  if (row.quoted_at === null) invalid('Missing quote time.'); return row as QuoteResult;
}
export function ordersResponse(value: unknown): OrdersPage {
  const row = base(value); array(row.orders, 30).forEach(orderSummary); nullableId(row.next_before_id);
  unique(row.orders.map((item: Obj) => item.id)); return row as OrdersPage;
}
export function detailResponse(value: unknown): OrderDetail {
  const row = base(value); orderSummary(row.order); id(row.order.warehouse_id);
  array(row.lines, 100).forEach(line => {
    id(line.line_id); if (line.option_id !== false) id(line.option_id); text(line.product_name); text(line.option_name);
    money(line.requested_qty); bool(line.available); if (line.current_option !== null) catalogItem(line.current_option);
    if (line.available !== (line.current_option !== null)) invalid('Inconsistent current option.');
  }); unique(row.lines.map((line: Obj) => line.line_id)); return row as OrderDetail;
}
export function receiptsResponse(value: unknown): ReceiptsPage {
  const row = base(value); array(row.orders, 30).forEach(receiptSummary); nullableId(row.next_before_id);
  if (row.orders.some((order: Obj) => !['sent', 'received'].includes(order.state))) invalid('Invalid receipt queue state.');
  unique(row.orders.map((item: Obj) => item.id)); return row as ReceiptsPage;
}
export function receiptDetailResponse(value: unknown): ReceiptDetail {
  const row = base(value); receiptSummary(row.order);
  array(row.lines, 100, 1).forEach(line => {
    id(line.line_id); ['product_name', 'option_name', 'uom_name'].forEach(key => text(line[key])); money(line.requested_qty); money(line.manager_received_qty);
  }); unique(row.lines.map((line: Obj) => line.line_id)); return row as ReceiptDetail;
}
export function createResponse(value: unknown): CreateResult {
  const row = base(value); orderSummary(row.order); uuid(row.client_uuid); bool(row.replayed); return row as CreateResult;
}
export function confirmResponse(value: unknown): ConfirmResult {
  const row = base(value); uuid(row.client_uuid); bool(row.replayed); const receipt = object(row.receipt);
  id(receipt.order_id); id(receipt.company_id); id(receipt.confirmed_by_id); nullableId(receipt.picking_id);
  text(receipt.name); text(receipt.currency_symbol); money(receipt.actual_total); stamp(receipt.confirmed_at);
  if (receipt.state !== 'purchased') invalid('Receipt is not complete.'); return row as ConfirmResult;
}
export function shareResponse(value: unknown): ShareResult {
  const row = base(value); id(row.order_id); id(row.room_id); id(row.message_id); bool(row.replayed);
  if (row.shared !== true) invalid('Receipt was not shared.'); return row as ShareResult;
}
