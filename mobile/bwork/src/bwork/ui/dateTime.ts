/** Presentation-only Gregorian/date conversion. Odoo remains the time authority. */
export interface DateTimeParts { year: string; month: string; day: string; hour: string; minute: string }
export const westernDigits = (value: string): string => value.replace(/[٠-٩]/g, d => String('٠١٢٣٤٥٦٧٨٩'.indexOf(d)))
  .replace(/[۰-۹]/g, d => String('۰۱۲۳۴۵۶۷۸۹'.indexOf(d)));
const pad = (value: number) => String(value).padStart(2, '0');
export function localParts(iso: string | null, fallback = new Date()): DateTimeParts {
  const parsed = iso ? new Date(iso) : fallback;
  const date = Number.isFinite(parsed.getTime()) ? parsed : fallback;
  return { year: String(date.getFullYear()), month: pad(date.getMonth() + 1), day: pad(date.getDate()), hour: pad(date.getHours()), minute: pad(date.getMinutes()) };
}
export function partsToUTC(parts: DateTimeParts): string | null {
  const values = [parts.year, parts.month, parts.day, parts.hour, parts.minute].map(westernDigits);
  if (values.some(value => !/^\d+$/.test(value))) return null;
  const [year, month, day, hour, minute] = values.map(Number);
  if (year < 1900 || year > 9999 || month < 1 || month > 12 || day < 1 || day > 31 || hour < 0 || hour > 23 || minute < 0 || minute > 59) return null;
  const date = new Date(year, month - 1, day, hour, minute, 0, 0);
  // Reject invalid days and local times skipped by daylight-saving changes.
  if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day || date.getHours() !== hour || date.getMinutes() !== minute) return null;
  const iso = date.toISOString().replace('.000Z', 'Z');
  return /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(iso) ? iso : null;
}
export function dateTimeLabel(iso: string, language: 'ar' | 'en'): string {
  const date = new Date(iso);
  if (!Number.isFinite(date.getTime())) return '';
  return new Intl.DateTimeFormat(language === 'ar' ? 'ar-SA' : 'en-GB', {
    calendar: 'gregory', numberingSystem: 'latn', year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).format(date);
}
export function calendarDays(year: number, month: number): (number | null)[] {
  const first = new Date(year, month - 1, 1).getDay(), count = new Date(year, month, 0).getDate();
  return Array.from({ length: Math.ceil((first + count) / 7) * 7 }, (_, index) => index >= first && index < first + count ? index - first + 1 : null);
}
