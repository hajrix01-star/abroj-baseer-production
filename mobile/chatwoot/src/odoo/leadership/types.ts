export interface Amount { value: string | null; display: string; available: boolean }
export interface Company { id: number; name: string }
export type Period = 'yesterday' | 'today' | 'month' | 'date';
export interface LeadershipQuery { month: string; period: Period; date?: string; companyId?: number }
export interface LeadershipDay {
  date: string; day: number; weekday: number; sales: Amount; status: string; status_label: string; has_sales: boolean;
  target: Amount; basis: Amount; basis_kind: 'target' | 'baseline' | 'none'; ratio: Amount; heat_level: string; coverage_label: string;
}
export interface LeadershipCalendar { month: string; label: string; week_start: 5; days: LeadershipDay[] }
export interface LeadershipOptions { api_version: 2; leadership_version: 1; can_view: boolean; companies: Company[]; max_companies: 10 }
export interface LeadershipReport {
  api_version: 2; leadership_version: 1; source: 'sales_summary'; companies: Company[]; company_id: number | null; currency: string; as_of: string;
  filters: { month: string; period: Period; from: string; to: string };
  overview: {
    sales: Amount; spending: Amount; difference: Amount; spending_ratio: Amount; difference_ratio: Amount; spending_scope: string;
    current_month: { month: string; from: string; to: string; sales: Amount; daily_average: Amount; forecast: Amount; sales_change: Amount;
      spending_change: Amount; difference_change: Amount; completed_days: number; previous_sales: Amount; previous_daily_average: Amount; comparison_label: string };
  };
  calendar: LeadershipCalendar & { weekdays: { weekday: number; name: string; average: Amount; sample_count: number }[] };
  previous_calendar: LeadershipCalendar;
}
export interface LeadershipIdentity { verified: boolean; origin: string; db: string; uid: number; epoch: string | number; companyIds: number[]; canView: boolean }
export interface LeadershipRequest { method: 'GET'; path: string; query?: Record<string, string | number>; signal?: AbortSignal; payload?: never }
export interface LeadershipDependencies { transport: { request: (request: LeadershipRequest) => Promise<unknown> }; identityScope: () => LeadershipIdentity | null; onUnauthorized?: () => void; onForbidden?: () => void }
export class LeadershipError extends Error {
  code: string; status?: number;
  constructor(code: string, status?: number) { super(code); this.name = 'LeadershipError'; this.code = code; this.status = status; }
}
export const accessDenied = (error: unknown): boolean => !!error && typeof error === 'object' && ('status' in error && [401, 403].includes(Number(error.status)) || 'code' in error && ['unauthorized', 'forbidden', 'session'].includes(String(error.code)));
