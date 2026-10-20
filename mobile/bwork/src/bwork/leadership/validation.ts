import { LeadershipError } from './types.ts';
import type { Amount, Company, LeadershipCalendar, LeadershipDay, LeadershipIdentity, LeadershipOptions, LeadershipQuery, LeadershipReport } from './types.ts';

export const ROOT = '/bwork/api/v2/leadership';
const invalid = (): never => { throw new LeadershipError('invalid_response'); };
const object = (value: unknown): Record<string, any> => value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, any> : invalid();
const bool = (value: unknown): boolean => typeof value === 'boolean' ? value : invalid();
const integer = (value: unknown, min: number, max: number): number => typeof value === 'number' && Number.isInteger(value) && value >= min && value <= max ? value : invalid();
export const id = (value: unknown): number => integer(value, 1, 2147483647);
const text = (value: unknown, max = 512): string => typeof value === 'string' && value.length <= max && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u202a-\u202e\u2066-\u2069]/.test(value) ? value : invalid();
export const month = (value: unknown): string => typeof value === 'string' && /^(?:18|19|[2-9]\d)\d{2}-(?:0[1-9]|1[0-2])$/.test(value) ? value : invalid();
export function date(value: unknown): string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return invalid();
  month(value.slice(0, 7)); const parsed = new Date(`${value}T12:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value ? value : invalid();
}
export function query(input: LeadershipQuery): LeadershipQuery {
  if (!input || Object.keys(input).some(key => !['month', 'period', 'date', 'companyId'].includes(key))) throw new LeadershipError('invalid_query');
  try { month(input.month); if (Number(input.month.slice(0, 4)) < 1900 || Number(input.month.slice(0, 4)) > 9998 || !['yesterday', 'today', 'month', 'date'].includes(input.period)) return invalid();
    if (input.period === 'date') { if (date(input.date).slice(0, 7) !== input.month) return invalid(); } else if (input.date !== undefined) return invalid();
    if (input.companyId !== undefined) id(input.companyId);
    return { month: input.month, period: input.period, ...(input.date ? { date: input.date } : {}), ...(input.companyId ? { companyId: input.companyId } : {}) };
  } catch { throw new LeadershipError('invalid_query'); }
}
export function bounded(value: unknown): unknown {
  let encoded: string | undefined; try { encoded = JSON.stringify(value); } catch { return invalid(); }
  // Count UTF-8 without a platform-specific TextEncoder dependency.
  if (encoded === undefined || encoded.length > 1048576 || unescape(encodeURIComponent(encoded)).length > 1048576) throw new LeadershipError('response_too_large');
  return value;
}
export function amount(value: unknown): Amount {
  const v = object(value), available = bool(v.available), display = text(v.display, 128);
  if (/[٠-٩۰-۹]/.test(display)) return invalid();
  if (available) {
    if (typeof v.value !== 'string' || !/^-?(?:0|[1-9]\d{0,29})(?:\.\d{1,16})?$/.test(v.value)) return invalid();
  } else if (v.value !== null) return invalid();
  return { value: v.value, display, available };
}
function companies(value: unknown, allowed: number[], maximum = 10): Company[] {
  if (!Array.isArray(value) || value.length > maximum) return invalid();
  const result = value.map(entry => { const v = object(entry), company = { id: id(v.id), name: text(v.name, 256) }; if (!allowed.includes(company.id)) return invalid(); return company; });
  if (new Set(result.map(c => c.id)).size !== result.length) return invalid(); return result;
}
// A version-1 value means supplier bills only, not purchases plus operating costs.
// Both online payloads and persisted snapshots pass this same strict boundary.
function version(v: Record<string, any>): void { if (v.api_version !== 2 || v.leadership_version !== 2) throw new LeadershipError('server_update_required'); }
export function optionsResponse(value: unknown, identity: LeadershipIdentity): LeadershipOptions {
  const v = object(bounded(value)); version(v); const can_view = bool(v.can_view), scope = companies(v.companies, identity.companyIds, 1000);
  if (v.max_companies !== 10 || can_view && (!scope.length || scope.length !== identity.companyIds.length
      || identity.companyIds.some(company => !scope.some(row => row.id === company))) || !can_view && scope.length) return invalid();
  return { api_version: 2, leadership_version: 2, can_view, companies: scope, max_companies: 10 };
}
function day(value: unknown, expected: string): LeadershipDay {
  const v = object(value), dayDate = date(v.date), d = new Date(`${dayDate}T12:00:00Z`), weekday = (d.getUTCDay() + 6) % 7;
  if (dayDate !== expected || v.day !== Number(dayDate.slice(8)) || v.weekday !== weekday || !['target', 'baseline', 'none'].includes(v.basis_kind)) return invalid();
  const result = { date: dayDate, day: integer(v.day, 1, 31), weekday, sales: amount(v.sales), status: text(v.status, 64), status_label: text(v.status_label), has_sales: bool(v.has_sales),
    target: amount(v.target), basis: amount(v.basis), basis_kind: v.basis_kind, ratio: amount(v.ratio), heat_level: text(v.heat_level, 64), coverage_label: text(v.coverage_label) };
  if (result.basis_kind === 'none' && (result.basis.available || result.ratio.available)) return invalid();
  return result;
}
function calendar(value: unknown, expected: string): LeadershipCalendar {
  const v = object(value); if (month(v.month) !== expected || v.week_start !== 5 || !Array.isArray(v.days)) return invalid();
  const count = new Date(`${expected}-01T12:00:00Z`); count.setUTCMonth(count.getUTCMonth() + 1, 0);
  if (v.days.length !== count.getUTCDate()) return invalid();
  return { month: expected, label: text(v.label), week_start: 5, days: v.days.map((entry: unknown, index: number) => day(entry, `${expected}-${String(index + 1).padStart(2, '0')}`)) };
}
export function reportResponse(value: unknown, input: LeadershipQuery, options: LeadershipOptions): LeadershipReport {
  const v = object(bounded(value)); version(v);
  if (v.source !== 'sales_summary' || v.currency !== 'SAR' || v.company_id !== (input.companyId ?? null)) return invalid();
  const expected = input.companyId ? [input.companyId] : options.companies.map(c => c.id), scope = companies(v.companies, expected);
  if (scope.length !== expected.length || expected.some(id => !scope.some(c => c.id === id))) return invalid();
  const filters = object(v.filters), from = date(filters.from), to = date(filters.to);
  const as_of = text(v.as_of, 64); if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(as_of) || !Number.isFinite(Date.parse(as_of))) return invalid();
  // Presentation validation uses the server snapshot, never the device clock.
  const snapshot = new Date(as_of), parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Riyadh', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(snapshot);
  const part = (type: string) => parts.find(p => p.type === type)?.value;
  const serverDay = date(`${part('year')}-${part('month')}-${part('day')}`), previousDay = new Date(`${serverDay}T12:00:00Z`); previousDay.setUTCDate(previousDay.getUTCDate() - 1);
  const yesterday = previousDay.toISOString().slice(0, 10);
  if (filters.month !== input.month || filters.period !== input.period || from > to) return invalid();
  if (input.period === 'today' && (from !== serverDay || to !== serverDay) || input.period === 'yesterday' && (from !== yesterday || to !== yesterday)) return invalid();
  if (input.period === 'date' && (from !== input.date || to !== input.date)) return invalid();
  if (input.period !== 'month' && from !== to) return invalid();
  const currentCalendar = calendar(v.calendar, input.month), prev = new Date(`${input.month}-01T12:00:00Z`); prev.setUTCMonth(prev.getUTCMonth() - 1);
  const previous_calendar = calendar(v.previous_calendar, prev.toISOString().slice(0, 7));
  if (input.period === 'month' && (from !== currentCalendar.days[0].date || to !== currentCalendar.days.at(-1)?.date)) return invalid();
  const overview = object(v.overview), spending = object(overview.spending_breakdown), c = object(overview.current_month), currentMonth = month(c.month), currentFrom = date(c.from), currentTo = date(c.to);
  if (currentMonth !== serverDay.slice(0, 7) || currentFrom !== `${currentMonth}-01` || currentTo !== (serverDay.slice(8) === '01' ? currentFrom : yesterday)) return invalid();
  const weekdaysRaw = object(v.calendar).weekdays;
  if (!Array.isArray(weekdaysRaw) || weekdaysRaw.length !== 7) return invalid();
  const weekdays = weekdaysRaw.map(entry => { const w = object(entry); return { weekday: integer(w.weekday, 0, 6), name: text(w.name, 128), average: amount(w.average), sample_count: integer(w.sample_count, 0, 31) }; });
  if (new Set(weekdays.map(w => w.weekday)).size !== 7) return invalid();
  return { api_version: 2, leadership_version: 2, source: 'sales_summary', companies: scope, company_id: v.company_id, currency: 'SAR', as_of,
    filters: { month: input.month, period: input.period, from, to }, overview: {
      sales: amount(overview.sales), spending: amount(overview.spending), difference: amount(overview.difference), spending_ratio: amount(overview.spending_ratio), difference_ratio: amount(overview.difference_ratio), spending_scope: text(overview.spending_scope),
      spending_breakdown: { purchases: amount(spending.purchases), operating: amount(spending.operating) },
      current_month: { month: currentMonth, from: currentFrom, to: currentTo, sales: amount(c.sales), daily_average: amount(c.daily_average), forecast: amount(c.forecast), sales_change: amount(c.sales_change), spending_change: amount(c.spending_change), difference_change: amount(c.difference_change), completed_days: integer(c.completed_days, 0, 31), previous_sales: amount(c.previous_sales), previous_daily_average: amount(c.previous_daily_average), comparison_label: text(c.comparison_label) } }, calendar: { ...currentCalendar, weekdays }, previous_calendar };
}
