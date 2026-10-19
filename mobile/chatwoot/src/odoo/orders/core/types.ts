/** Wire DTOs for baseer_bchat_procurement, API v2. Amounts stay server strings. */
export type PurchaseRoute = 'representative' | 'cash' | 'bank_transfer';
export type OrderState = 'draft' | 'sent' | 'received' | 'purchased' | 'cancel';
export interface Selection { id: number; name: string }
export interface OrdersIdentity {
  origin: string; db: string; uid: number; epoch: string | number; verified: boolean;
  companyIds: readonly number[];
  permissions: { order_view: boolean; order_create: boolean; order_receive: boolean; chat_send: boolean };
}
export interface OrdersRequest {
  method: 'GET' | 'POST'; path: string;
  query?: Record<string, string | number>; payload?: Record<string, unknown>; signal?: AbortSignal;
}
export interface OrdersTransport { request(request: OrdersRequest): Promise<unknown> }
export interface OrdersStorage { getItem(key: string): Promise<string | null>; setItem(key: string, value: string): Promise<void> }
export interface OrdersOptions {
  api_version: 2; access: 'viewer' | 'operator'; can_view: boolean; can_create: boolean; can_receive: boolean;
  /** Absent on legacy servers; only version 1 enables the post-create workflow. */
  workflow_version?: number;
  /** Version 1 adds one globally paginated, authorized receipt queue. */
  receipt_list_version?: number;
  companies: Selection[]; purchase_routes?: { code: PurchaseRoute; name: string }[];
  warehouses?: Selection[]; representatives?: Selection[]; categories?: Selection[]; default_warehouse_id?: number | null;
}
export interface RoomsQuery { q?: string; afterId?: number; preferredRoomId?: number }
export interface OrderRoomsPage {
  api_version: 2; company_id: number; rooms: Selection[]; next_after_id: number | null;
  preferred_room: Selection | null;
}
export interface CatalogItem {
  id: number; product_id: number; product_name: string; option_name: string; uom_name: string;
  packaging_note: string; category_id: number; category_name: string; last_price: string;
  currency_symbol: string; image_url: string;
}
export interface CatalogPage { api_version: 2; items: CatalogItem[]; next_after_id: number | null }
export interface CatalogQuery { q?: string; categoryId?: number; afterId?: number }
export interface CartLine { option_id: number; quantity: string }
export interface QuoteInput { company_id: number; warehouse_id: number; cart_revision: number; lines: CartLine[] }
export interface QuoteResult {
  api_version: 2; company_id: number; cart_revision: number;
  lines: { option_id: number; quantity: string; unit_price: string; line_total: string }[];
  estimated_total: string; currency_code: string; currency_symbol: string; quoted_at: string;
}
export interface OrderSummary {
  id: number; name: string; company_id: number; company_name: string; requester_id: number; requester_name: string;
  state: OrderState; purchase_route: PurchaseRoute; purchase_route_name: string;
  representative_id: number | null; representative_name: string; requested_total: string;
  currency_symbol: string; submitted_at: string | null; room_id: number | null;
}
export interface OrdersPage { api_version: 2; orders: OrderSummary[]; next_before_id: number | null }
export interface OrderDetail {
  api_version: 2; order: OrderSummary & { warehouse_id: number };
  lines: { line_id: number; option_id: number | false; product_name: string; option_name: string; requested_qty: string;
    available: boolean; current_option: CatalogItem | null }[];
}
export interface CreateInput {
  company_id: number; warehouse_id: number; representative_partner_id: number | null;
  purchase_route?: PurchaseRoute; room_id?: number | null; lines: CartLine[];
}
export interface CreateResult { api_version: 2; order: OrderSummary; client_uuid: string; replayed: boolean }
export interface ReceiptSummary {
  id: number; name: string; state: OrderState; company_id: number; warehouse_name: string;
  submitted_at: string | null; requester_name: string; requested_total: string; currency_symbol: string;
}
export interface ReceiptsPage { api_version: 2; orders: ReceiptSummary[]; next_before_id: number | null }
export interface ReceiptDetail {
  api_version: 2; order: ReceiptSummary;
  lines: { line_id: number; product_name: string; option_name: string; uom_name: string;
    requested_qty: string; manager_received_qty: string }[];
}
export interface ReceiptLineInput { line_id: number; actual_qty: string; actual_price: string }
export interface ConfirmInput { company_id: number; lines: ReceiptLineInput[] }
export interface ConfirmResult {
  api_version: 2; client_uuid: string; replayed: boolean;
  receipt: { order_id: number; name: string; state: 'purchased'; company_id: number; actual_total: string;
    currency_symbol: string; picking_id: number | null; confirmed_at: string | null; confirmed_by_id: number };
}
export interface ShareResult {
  api_version: 2; order_id: number; room_id: number; message_id: number; shared: true; replayed: boolean;
}
export type WriteResult = CreateResult | ConfirmResult;
export interface PendingAttempt {
  uuid: string; kind: 'create' | 'confirm'; companyId: number; orderId?: number; createdAt: number;
}
export interface OrdersEngineDependencies {
  transport: OrdersTransport; storage: OrdersStorage; identityScope: () => OrdersIdentity | null;
  now: () => number; uuid: () => string;
  onUnauthorized?: () => void; onForbidden?: (companyId?: number) => void;
}
export class OrdersError extends Error {
  code: string; attemptId?: string; status?: number;
  constructor(code: string, message = code, attemptId?: string, status?: number) {
    super(message); this.name = 'OrdersError'; this.code = code; this.attemptId = attemptId; this.status = status;
  }
}
