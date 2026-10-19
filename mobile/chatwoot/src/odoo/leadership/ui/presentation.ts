import type { Language } from '../../ui/dictionary';
import type { Amount, LeadershipDay } from '../types';
import { leadershipTranslator, type LeadershipWord } from '../dictionary';
export function snapshotDate(asOf: string): string {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Riyadh', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date(asOf));
  return ['year', 'month', 'day'].map(type => parts.find(p => p.type === type)?.value).join('-');
}
export const monthLabel = (month: string, language: Language): string => new Intl.DateTimeFormat(language === 'ar' ? 'ar-SA' : 'en-GB', { calendar: 'gregory', numberingSystem: 'latn', month: 'long', year: 'numeric', timeZone: 'UTC' }).format(new Date(`${month}-01T12:00:00Z`));
export function dayWord(day: LeadershipDay, asOf: string): LeadershipWord {
  const today = snapshotDate(asOf);
  if (day.date > today) return 'future'; if (day.date === today) return 'inProgress';
  if (day.status === 'conflict') return 'conflict'; if (day.status === 'missing') return 'noRecords';
  if (day.status === 'incomplete' || day.status === 'partial') return 'partial';
  if (day.status === 'closed') return 'closed';
  if (day.has_sales && day.sales.available && /^-?0(?:\.0+)?$/.test(day.sales.value ?? '')) return 'recordedZero';
  return day.status === 'complete' ? 'full' : 'unavailable';
}
export const dayLabel = (day: LeadershipDay, asOf: string, language: Language): string => leadershipTranslator(language)(dayWord(day, asOf));
export const coverageLabel = (day: LeadershipDay, companyCount: number, language: Language): string => leadershipTranslator(language)(['complete', 'closed'].includes(day.status) ? companyCount > 1 ? 'allComplete' : 'singleComplete' : 'incompleteCoverage');

/** Calendar labels only: exact decimal ceil toward +infinity, never a business total.
 * Keep the source Amount untouched; detail/overview retain the server display.
 * Decimal strings avoid binary floating-point loss for large amounts/tiny fractions.
 */
export function calendarIntegerDisplay(amount: Amount | undefined): string {
  if (!amount?.available || amount.value === null) return '—';
  const parts = /^(-?)(\d+)(?:\.(\d+))?$/.exec(amount.value);
  if (!parts) return '—';
  const [, sign, whole, fraction = ''] = parts;
  let integer = whole;
  if (!sign && /[1-9]/.test(fraction)) {
    const digits = whole.split('');
    let index = digits.length - 1;
    while (index >= 0 && digits[index] === '9') { digits[index] = '0'; index--; }
    if (index < 0) digits.unshift('1');
    else digits[index] = String.fromCharCode(digits[index].charCodeAt(0) + 1);
    integer = digits.join('');
  }
  const grouped = integer.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return sign && integer !== '0' ? `-${grouped}` : grouped;
}

/** Units/sign/semantic color only: never recompute the server percentage. */
export function percentagePresentation(amount: Amount | undefined, trend?: 'higher' | 'lower') {
  if (!amount?.available || amount.value === null) return { display: amount?.display ?? '—', tone: 'neutral' as const };
  const zero = /^-?0(?:\.0+)?$/.test(amount.value), negative = amount.value.startsWith('-');
  const tone = !trend || zero ? 'neutral' : negative === (trend === 'lower') ? 'favorable' : 'unfavorable';
  return { display: `${trend && !zero && !negative ? '+' : ''}${amount.display}%`, tone };
}
