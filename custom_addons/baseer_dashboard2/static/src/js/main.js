/** @odoo-module **/
import { Component, onWillStart, onWillUnmount, useState, useExternalListener } from "@odoo/owl";
import { dashboardTooltip } from "./tooltip";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export const formatNumber = (n) =>
  n === null || n === undefined || n === false || !Number.isFinite(Number(n))
    ? "—"
    : new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(Number(n) === 0 || Math.abs(Number(n)) < 0.5 ? 0 : n);
export const formatTable = (n, minus = false) => {
  if (n == null || n === false || !Number.isFinite(Number(n))) return "—";
  const magnitude = formatNumber(Math.abs(Number(n)));
  if (magnitude === "0") return "—";
  return Number(n) < 0 ? (minus ? `-${magnitude}` : `(${magnitude})`) : magnitude;
};
const roundedPercentMagnitude = (n) => (Math.round((Math.abs(Number(n)) + Number.EPSILON * Math.abs(Number(n))) * 10) / 10).toFixed(1);
export const formatTablePct = (n) => {
  if (n == null || n === false || !Number.isFinite(Number(n))) return "—";
  const magnitude = roundedPercentMagnitude(n);
  return magnitude === "0.0" ? "—" : `${Number(n) < 0 ? "−" : ""}${magnitude}%`;
};
export const formatPercent = (n) => n == null || n === false || !Number.isFinite(Number(n)) ? "—" : `${Number(n) < 0 ? "−" : ""}${roundedPercentMagnitude(n)}%`;
export const formatPoints = (n) => n == null || n === false || !Number.isFinite(Number(n)) ? "—" : `${Number(n) < 0 ? "−" : ""}${roundedPercentMagnitude(n)}`;
export const ratioDifference = (value, previous) => value == null || previous == null ? null : value - previous;
export const formatTargetPercent = (n) => n == null ? "—" : `${Number(n).toLocaleString("en-US", { maximumFractionDigits: 1 })}%`;
export const timelineYear = (period) => (period?.mode === "month" ? period.month : period?.date_to)?.slice(0, 4) || "";
export const chartX = (i, n, width = 700) =>
  width - 48 - (width - 70) * (n <= 1 ? 0.5 : i / (n - 1));
export const miniX = (i, n) => 95 - (n <= 1 ? 45 : 90 * i / (n - 1));
// Full names suit titles and pickers; use short names for dense tables, charts and year tiles.
export const MONTHS_FULL = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
export const MONTHS_SHORT = MONTHS_FULL.map((name) => name.slice(0, 3));
export function monthLabel(ym, { short = false, year = false, partial = false, isolate = false } = {}) {
  if (!ym) return "—";
  const [y, m] = ym.split("-");
  const name = (short ? MONTHS_SHORT : MONTHS_FULL)[Number(m) - 1];
  const label = name + (year ? " " + y : "") + (partial ? " (جزئي)" : "");
  return isolate ? `\u2068${label}\u2069` : label;
}
export const plainCsvText = (value) => value.replace(/[\u2066-\u2069]/g, "");
const months = MONTHS_FULL;
const weekdays = [
  "السبت",
  "الأحد",
  "الإثنين",
  "الثلاثاء",
  "الأربعاء",
  "الخميس",
  "الجمعة",
];
const labels = {
  sales_net: "المبيعات",
  revenue: "الإيرادات",
  food_cost: "تكلفة الأكل",
  salaries: "الرواتب",
  expenses_total: "المصاريف",
  net_profit: "صافي الربح",
  gross_profit: "مجمل الربح",
  operating_profit: "الربح التشغيلي",
  rent: "الإيجار",
  utilities: "الكهرباء والماء",
  marketing: "التسويق",
  commissions: "العمولات",
  other_opex: "مصاريف أخرى",
  other_non_operating: "مصاريف أخرى",
  depreciation: "الإهلاك",
  non_operating: "غير تشغيلي",
  zakat_tax: "الزكاة والضريبة",
  other_income: "الإيرادات الأخرى",
  food_pct: "نسبة تكلفة الأكل",
  salaries_pct: "نسبة الرواتب",
  prime_pct: "التكلفة الأساسية",
  net_margin_pct: "صافي هامش الربح",
  purchases: "المشتريات",
  bank: "بنك",
  cash: "نقد", card: "شبكة", keeta: "كيتا", hunger: "هنقرستيشن", jahez: "جاهز", transfer: "تحويل بنكي", credit: "آجل", other: "أخرى", unclassified: "غير مصنف",
  expenses: "المصاريف", profit: "الأرباح", ratios: "النسب", breakeven: "نقطة التعادل", gross_sales_by_channel: "المبيعات حسب القناة", apps: "التطبيقات", apps_unreceived: "التطبيقات غير المستلمة", customers: "العملاء", hours: "أوقات الذروة", inout: "الداخل والخارج", unpaid_bills: "الفواتير غير المسددة", timeline: "المسار الزمني", heatmap: "التقويم الحراري", sales_vat: "ضريبة المبيعات", tax_basis: "مصدر الضريبة", waterfall: "شلال الربح",
};
const pages = [
  ["overview", "نظرة عامة", "ملخص الأداء المالي للفترة المحددة", "▦"],
  ["revenue", "الإيرادات", "المبيعات حسب طريقة الدفع وعمولات التطبيقات", "⌁"],
  ["expenses", "المصاريف", "توزيع المصاريف وتطورها شهرياً", "▤"],
  ["ratios", "النسب", "مؤشرات الأداء الرئيسية للمطعم ونقطة التعادل", "٪"],
  ["pnl", "الربح والخسارة", "قائمة الدخل بالشكل المحاسبي", "▦"],
  ["heatmap", "التقويم الحراري", "المبيعات والعملاء حسب اليوم", "▣"],
  ["glossary", "المصطلحات", "شرح مختصر لكل رقم ونسبة في التقرير", "▤"],
];
const getStored = (key, fallback) => {
  try {
    return (
      JSON.parse(localStorage.getItem("baseer_dashboard2." + key)) ?? fallback
    );
  } catch {
    return fallback;
  }
};

export const niceStep = (range, count = 4) => {
  const raw = Math.max(range, 1e-12) / count;
  const power = 10 ** Math.floor(Math.log10(raw));
  return ([1, 2, 2.5, 5, 10].find((n) => n * power >= raw) || 10) * power;
};
export const periodRange = (period) => {
  if (!period?.date_from || !period?.date_to) return "—";
  const [fromYear, fromMonth, fromDay] = period.date_from.split("-");
  const [toYear, toMonth, toDay] = period.date_to.split("-");
  return `${Number(fromDay)}/${Number(fromMonth)}${fromYear !== toYear ? `/${fromYear}` : ""} – ${Number(toDay)}/${Number(toMonth)}/${toYear}`;
};
export const hourLabel = hour => `${hour % 12 || 12}${hour >= 12 ? 'م' : 'ص'}`;
export const hasDisplayValues = (values) => (values || []).some(v => v != null && Number.isFinite(Number(v)) && Math.abs(Number(v)) >= 0.5);
export const hasPoints = (values) => (values || []).some((v) => v != null && Number.isFinite(Number(v)));
export const multiplePoints = (values) => (values || []).filter(v => v != null && Number.isFinite(Number(v))).length > 1 ? values : [];
export class Sparkline extends Component {
  miniX = miniX;
  setup() { this.hover = useState({ index: -1 }); }
  static template = "baseer_dashboard2.Sparkline";
  static props = { months: { optional: true }, previousYear: { optional: true }, previousYearSecondary: { optional: true }, unit: { optional: true }, values: { optional: true }, previous: { optional: true }, gold: { optional: true }, secondaryGold: { optional: true }, navy: { optional: true }, mini: { optional: true }, stretch: { optional: true }, ratioPercent: { optional: true }, amountDecimal: { optional: true }, partial: { optional: true }, onDrill: { optional: true }, canDrill: { optional: true } };
  get slots() { return (this.props.values || []).map((_, i) => i); }
  sparkPoint(a, i, secondary = false) {
    if (a?.[i] == null) return null;
    if (this.props.mini) return this.miniPoint(a, i, secondary);
    const values = [...(this.props.values || []), ...(this.props.previous || [])].filter(v => v != null).map(Number);
    const lo = Math.min(...values), hi = Math.max(...values);
    return {x: miniX(i, a.length), y: 28 - (Number(a[i])-lo)/(hi-lo || 1)*24};
  }
  sparkInfo(event, index) {
    const svg = event.currentTarget.ownerSVGElement, rect = svg.getBoundingClientRect();
    const matrix = svg.getScreenCTM(), local = new DOMPoint(event.clientX,event.clientY).matrixTransform(matrix.inverse());
    const y = local.y;
    const candidates = [{values:this.props.values, prior:this.props.previousYear, secondary:false}, {values:this.props.previous, prior:this.props.previousYearSecondary, secondary:true}]
      .map(x => ({...x, point:this.sparkPoint(x.values,index,x.secondary)})).filter(x => x.point);
    if (!candidates.length) return null;
    const c = candidates.reduce((a,b) => Math.abs(a.point.y-y) <= Math.abs(b.point.y-y) ? a : b);
    const screen = new DOMPoint(c.point.x,c.point.y).matrixTransform(matrix), x=screen.x, py=screen.y;
    const prior = c.prior?.[index], value=c.values[index], percent = c.secondary && this.props.ratioPercent || this.props.unit === 'percent';
    const format = percent ? formatPercent : this.props.unit === 'orders' && !c.secondary ? formatNumber : v => v == null ? '—' : `${formatNumber(v)} ر.س`;
    const month=this.props.months?.[index];
    const rows=[['الشهر',month && /^\d{4}-\d{2}$/.test(month) ? monthLabel(month,{year:true}) : (month || '—')],['القيمة',format(value)],['نفس الشهر العام الماضي',format(prior)],['التغير',formatPercent(prior == null || Number(prior) === 0 ? null : (value-prior)/Math.abs(prior)*100)]];
    return {rows, options:{rect:{left:x-4,right:x+4,top:py-4,bottom:py+4,width:8,height:8}, drill:this.props.canDrill?.(index,c.secondary) ? e => this.props.onDrill?.(e,index,c.secondary) : null}};
  }
  sparkEnter(event,index) { if (event.pointerType === 'touch') return; const tip=this.sparkInfo(event,index); if (tip) { this.hover.index=index; dashboardTooltip.show(event.currentTarget,tip.rows,tip.options); } }
  sparkLeave(event) { if (event.pointerType !== 'touch') { this.hover.index=-1; dashboardTooltip.deferClose(); } }
  sparkTap(event,index) { if (event.pointerType !== 'touch') return; const tip=this.sparkInfo(event,index); if (tip) { this.hover.index=index; dashboardTooltip.toggle(event.currentTarget,tip.rows,tip.options); } }
  miniPoint(a, i, ratio = false) {
    const values = (a || []).filter(v => v != null).map(Number);
    if (!values.length || a[i] == null) return null;
    const lo = Math.min(...values), hi = Math.max(...values);
    return { x: miniX(i, a.length), y: (ratio ? 11 : 27) - (Number(a[i]) - lo) / (hi - lo || 1) * 7 };
  }
  miniPath(a, ratio = false, area = false) {
    let segments = [], points = [];
    const flush = () => { if (points.length) { const first = points[0], last = points[points.length - 1]; segments.push((area ? `M${first.x},31 L` : 'M') + points.map(p => `${p.x},${p.y}`).join(' L') + (area ? ` L${last.x},31 Z` : '')); } points = []; };
    (a || []).forEach((v, i) => { const p = this.miniPoint(a, i, ratio); if (p) points.push(p); else flush(); }); flush(); return segments.join(' ');
  }
  endpoints(a) { const indices = (a || []).map((v, i) => v == null ? -1 : i).filter(i => i >= 0); return indices.length > 1 ? [indices[0], indices[indices.length - 1]] : indices; }
  miniDotStyle(a, i, ratio = false) {
    const point = this.miniPoint(a, i, ratio);
    return `left:${point.x}%;top:${point.y / 32 * 100}%`;
  }
  miniLabelStyle(a, i, ratio = false) {
    const point = this.miniPoint(a, i, ratio), right = point.x <= 50;
    return `left:calc(${point.x}% ${right ? '+' : '-'} 10px);top:calc(${point.y / 32 * 100}% - 6px);transform:translate(${right ? '0' : '-100%'}, -100%)`;
  }
  short(v, ratio = false, decimal = false) { return ratio ? formatPercent(v).slice(0, -1) : Math.abs(v) >= 1000 ? `${decimal ? (v / 1000).toFixed(1) : Math.round(v / 1000)}K` : `${Math.round(v)}`; }
  endpoint(a) {
    const i = (a || []).findLastIndex(v => v != null);
    if (i < 0) return null;
    const values = [...(this.props.values || []), ...(this.props.previous || [])].filter(v => v != null).map(Number);
    const min = Math.min(...values), max = Math.max(...values);
    return { x: 95 - (a.length <= 1 ? 45 : 90 * i / (a.length - 1)), y: 28 - (Number(a[i]) - min) / (max - min || 1) * 24 };
  }
  path(a, partialOnly = false) {
    a = a || [];
    const scaleValues = this.props.secondaryGold ? a : [...(this.props.values || []), ...(this.props.previous || [])];
    const present = scaleValues.filter((v) => v != null).map(Number);
    const min = Math.min(...present), max = Math.max(...present);
    return a.map((v, i) => v == null || (partialOnly && !this.props.partial?.[i] && !this.props.partial?.[i + 1]) ? "" : `${i && a[i - 1] != null && (partialOnly ? this.props.partial?.[i] : !this.props.partial?.[i]) ? "L" : "M"}${95 - (a.length <= 1 ? 45 : 90 * i / (a.length - 1))},${28 - (Number(v) - min) / (max - min || 1) * 24}`).join(" ");
  }
}
export class LineChart extends Component {
  static template = "baseer_dashboard2.LineChart";
  static props = { series: Array, labels: { optional: true }, months: { optional: true }, percent: { optional: true }, compactTop: { optional: true }, fiveTicks: { optional: true } };
  chartX = chartX;
  setup() { this.hover = useState({ index: -1, series: -1 }); }
  get slots() { return Array.from({ length: Math.max(0, ...this.renderedSeries.map(s => s.values.length)) }, (_, i) => i); }
  slotWidth() { return this.slots.length > 1 ? 630 / (this.slots.length - 1) : 630; }
  pointInfo(event, index) {
    const svg = event.currentTarget.ownerSVGElement;
    const rect = svg.getBoundingClientRect();
    const box = svg.viewBox.baseVal;
    const matrix=svg.getScreenCTM();
    const y = new DOMPoint(event.clientX,event.clientY).matrixTransform(matrix.inverse()).y;
    const candidates = this.renderedSeries.map((s, n) => ({ s, n })).filter(({s}) => (!s.dashed || s.endpoint) && s.values[index] != null);
    if (!candidates.length) return null;
    const {s, n} = candidates.reduce((a, b) => Math.abs(this.y(a.s.values[index]) - y) <= Math.abs(this.y(b.s.values[index]) - y) ? a : b);
    const screen=new DOMPoint(chartX(index,s.values.length),this.y(s.values[index])).matrixTransform(matrix);
    const xScreen=screen.x, yScreen=screen.y;
    const point = {left:xScreen-4, right:xScreen+4, top:yScreen-4, bottom:yScreen+4, width:8, height:8};
    const fallback = this.props.labels?.[index] || '—';
    const short = String(fallback).replace(/[^A-Za-z]/g, '').slice(0, 3);
    const monthNumber = MONTHS_SHORT.findIndex(m => m.toLowerCase() === short.toLowerCase()) + 1;
    const month = this.props.months?.[index] ? monthLabel(this.props.months[index], {year:true}) : monthNumber ? monthLabel(`2000-${String(monthNumber).padStart(2,'0')}`) : fallback;
    const prior = s.previousYear?.[index] ?? null;
    const val = s.values[index];
    const format = this.props.percent ? formatPercent : v => v == null ? '—' : `${formatNumber(v)} ر.س`;
    const change = prior == null || Number(prior) === 0 ? null : (val-prior)/Math.abs(prior)*100;
    return { n, rows: [['الشهر', month], ...(s.name ? [['المؤشر', s.name]] : []), ['القيمة',format(val)], ['نفس الشهر العام الماضي',format(prior)], ['التغير',formatPercent(change)]], options: {rect:point, bounds:svg, drill:s.drill ? e => s.drill(e,index) : null} };
  }
  pointEnter(event, index) {
    if (event.pointerType === 'touch') return;
    const info = this.pointInfo(event,index); if (!info) return;
    this.hover.index=index; this.hover.series=info.n;
    dashboardTooltip.show(event.currentTarget,info.rows,info.options);
  }
  pointLeave(event) { if (event.pointerType !== 'touch') { this.hover.index=-1; dashboardTooltip.deferClose(); } }
  pointTap(event, index) {
    if (event.pointerType !== 'touch') return;
    const info = this.pointInfo(event,index); if (!info) return;
    this.hover.index=index; this.hover.series=info.n;
    dashboardTooltip.toggle(event.currentTarget,info.rows,info.options);
  }
  get renderedSeries() { return this.props.series.filter((s) => hasPoints(s.values)); }
  get scale() {
    const values = this.renderedSeries.flatMap((s) => s.values.filter((v) => v != null).map(Number));
    const low = Math.min(0, ...values), high = Math.max(0, ...values);
    const step = niceStep(high - low);
    const min = Math.floor(low / step) * step;
    return { min, max: Math.max(this.props.fiveTicks ? min + 4 * step : step, Math.ceil(high / step) * step), step };
  }
  get ticks() {
    const { min, max, step } = this.scale;
    return Array.from({ length: Math.round((max - min) / step) + 1 }, (_, i) => min + i * step);
  }
  y(v) { const {min, max} = this.scale; return 205 - (Number(v) - min) / (max - min) * 165; }
  labelY(series, value) {
    const peers = this.renderedSeries.filter(s => (s.firstLabel || s.endpoint) && !s.dashed)
      .map(s => s.values.findLast(v => v != null)).filter(v => v != null);
    const below = !series.dashed && peers.length > 1 && value < Math.max(...peers);
    return this.y(value) + (below ? 19 : -10);
  }
  area(values) {
    const baseline = this.y(0); let segments = [], points = [];
    const flush = () => { if (points.length) segments.push(`M${points[0][0]},${baseline} ` + points.map(([x,y]) => `L${x},${y}`).join(" ") + ` L${points.at(-1)[0]},${baseline} Z`); points = []; };
    values.forEach((value, i) => value == null ? flush() : points.push([chartX(i, values.length), this.y(value)])); flush(); return segments.join(" ");
  }
  compact(value) { if (this.props.percent) return formatPercent(value); return Math.abs(value) >= 1000000 ? `${+(value / 1000000).toFixed(1)}M` : Math.abs(value) >= 1000 ? `${Math.round(value / 1000)}K` : formatNumber(value); }
  isPeak(value, values) { return value != null && Number(value) === Math.max(...values.filter((v) => v != null).map(Number)); }
  partialPath(values, partial) {
    const i = partial?.findIndex(Boolean) ?? -1;
    return i > 0 && values[i] != null && values[i - 1] != null ? `M${chartX(i - 1, values.length)},${this.y(values[i - 1])} L${chartX(i, values.length)},${this.y(values[i])}` : "";
  }
  path(values, partial) { return values.map((v, i) => v == null ? "" : `${i && values[i - 1] != null && !partial?.[i] ? "L" : "M"}${chartX(i, values.length)},${this.y(v)}`).join(" "); }
}
class Money extends Component {
  static template = "baseer_dashboard2.Money";
  static props = { value: { optional: true } };
  format = formatNumber;
}
export class Badge extends Component {
  formatPercent = formatPercent;
  formatPoints = formatPoints;
  static template = "baseer_dashboard2.Badge";
  static props = { value: { optional: true }, goodWhen: { optional: true }, warning: { optional: true }, partial: { optional: true }, points: { optional: true } };
  get good() {
    return this.props.goodWhen === "down"
      ? this.props.value <= 0
      : this.props.value >= 0;
  }
}
const visualTip = {
  click(event) { if (event.pointerType === 'touch') event.stopPropagation(); },
  enter(event, rows) { if (event.pointerType !== 'touch') dashboardTooltip.show(event.currentTarget, rows); },
  leave(event) { if (event.pointerType !== 'touch') dashboardTooltip.deferClose(); },
  tap(event, rows) {
    const drill = event.target.closest('.bd2-drill');
    if (event.pointerType !== 'touch' || event.target.closest('.bd2-spark') || (drill && event.currentTarget.contains(drill))) return;
    dashboardTooltip.toggle(event.currentTarget, rows);
  },
};

class Track extends Component {
  tip = visualTip;
  get tipRows() { return [['التاريخ', this.props.date], ['المبلغ', this.props.value == null ? '—' : `${formatNumber(this.props.value)} ر.س`], ['العملاء', this.props.customers == null ? null : formatNumber(this.props.customers)], ['المناسبة', this.props.occasion]]; }
  static template = "baseer_dashboard2.Track";
  static props = {
    value: { optional: true },
    max: { optional: true },
    gold: { optional: true },
    date: { optional: true }, customers: { optional: true }, occasion: { optional: true },
  };
  get width() {
    return Math.min(
      100,
      Math.max(
        0,
        (100 * Math.abs(this.props.value || 0)) /
          (Math.abs(this.props.max) || 1),
      ),
    );
  }
}
class Ring extends Component {
  tip = visualTip;
  get tipRows() { return [['التاريخ', this.props.date], ['المبلغ', this.props.amount == null ? null : `${formatNumber(this.props.amount)} ر.س`], ['العملاء', this.props.customers == null ? null : formatNumber(this.props.customers)], ['المناسبة', this.props.occasion], ['النسبة', formatPercent(this.props.value)]]; }
  static template = "baseer_dashboard2.Ring";
  static props = { value: { optional: true }, date: { optional: true }, amount: { optional: true }, customers: { optional: true }, occasion: { optional: true } };
  get offset() {
    return 264 * (1 - Math.max(0, Math.min(100, this.props.value || 0)) / 100);
  }
}
export class Gauge extends Component {
  tip = visualTip;
  get tipRows() { return [['النسبة', formatPercent(this.props.value)], ['المستهدف', formatPercent(this.props.target)], ['السابق', formatPercent(this.props.previous)]]; }
  static template = "baseer_dashboard2.Gauge";
  static props = {
    value: { optional: true },
    target: { optional: true },
    previous: { optional: true },
    max: { optional: true },
    operator: { optional: true },
  };
  targetLabel() {
    return `${this.props.operator === "le" ? "≤" : "≥"}${Number(this.props.target).toLocaleString("en-US", { maximumFractionDigits: 1 })}%`;
  }
  // Value, target, and previous period share the displayed gauge scale.
  pos(v) {
    return Math.max(
      0,
      Math.min(100, (100 * (v || 0)) / (this.props.max || 100)),
    );
  }
}
export const iconPath = (key) => ({
  sales_net: 'M3 4h2l2 11h10l3-8H6 M9 20h.01 M17 20h.01', food_cost: 'M4 3v7a3 3 0 0 0 6 0V3 M7 3v18 M16 3v18 M16 3c3 2 4 6 4 9h-4', salaries: 'M16 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2 M10 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8 M17 11a4 4 0 0 0 0-8 M20 21v-2a4 4 0 0 0-3-4', expenses_total: 'M3 6h18v14H3z M3 10h18 M16 15h2', net_profit: 'M8 3h8v5a4 4 0 0 1-8 0z M8 5H4v2a4 4 0 0 0 4 4 M16 5h4v2a4 4 0 0 1-4 4 M12 12v6 M8 21h8 M9 18h6', apps: 'M4 20 20 4 M10 4h10v10', customers: 'M16 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2 M10 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8', ticket: 'M5 3h14v18l-3-2-4 2-4-2-3 2z M8 8h8 M8 12h8', rent: 'M3 6h18v14H3z M3 10h18 M16 15h2', purchases: 'M3 4h2l2 11h10l3-8H6 M9 20h.01 M17 20h.01'
}[key] || 'M3 6h18v14H3z M3 10h18');
export function customerCutoverLabel(date) {
  if (!date) return null;
  const [, month, day] = date.split('-');
  return `من ${Number(day)}/${Number(month)}`;
}
export class KpiCard extends Component {
  tip = visualTip;
  get tipRows() { return [['المؤشر', this.props.title], ['الشهر', this.props.months?.at(-1) ? monthLabel(this.props.months.at(-1), {year:true}) : null], ['القيمة', this.props.unit === 'orders' ? formatNumber(this.props.value) : this.props.value == null ? '—' : `${formatNumber(this.props.value)} ر.س`], ['التغير', formatPercent(this.props.change)]]; }
  static template = "baseer_dashboard2.KpiCard";
  iconPath = iconPath;
  formatPercent = formatPercent;
  formatNumber = formatNumber;
  static components = { Money, Badge, Sparkline };
  static props = {
    title: String,
    headingSubtitle: { optional: true },
    subtitle: { optional: true },
    subtitlePercent: { optional: true },
    unit: { optional: true },
    icon: { optional: true },
    value: { optional: true },
    change: { optional: true },
    trend: { optional: true },
    months: { optional: true },
    previousYearTrend: { optional: true },
    previousTrend: { optional: true },
    partial: { optional: true },
    hero: { optional: true },
    goodWhen: { optional: true },
    foodProgress: { optional: true },
    warning: { optional: true },
    partialMonth: { optional: true },
    onDrill: { optional: true },
  };
}

export class InfoPopup extends Component {
  static template = "baseer_dashboard2.InfoPopup";
  static props = { title: String, explanation: String };
  setup() {
    this.state = useState({ open: false });
    useExternalListener(document, "click", (event) => {
      if (!event.target.closest(".info-popup") || !this.root?.contains(event.target)) this.state.open = false;
    });
    useExternalListener(document, "keydown", (event) => {
      if (event.key === "Escape") this.state.open = false;
    });
  }
  toggle(event) {
    this.root = event.currentTarget.parentElement;
    this.state.open = !this.state.open;
  }
}

export class Dashboard2 extends Component {
  tip = visualTip;
  dayTip(day) { return [['التاريخ', `${this.dateName(day.date)} ${day.date.slice(0,4)}`], ['المبلغ', day.gross == null ? '—' : `${formatNumber(day.gross)} ر.س`], ['العملاء', formatNumber(day.customers)], ['المناسبة', (day.events || []).map(e => e.name).join('، ')]]; }
  static template = "baseer_dashboard2.Main";
  static components = {
    Sparkline,
    LineChart,
    Money,
    Badge,
    Track,
    Ring,
    Gauge,
    KpiCard,
    InfoPopup,
  };
  setup() {
    this.customerCutoverLabel = customerCutoverLabel;
    this.hasDisplayValues = hasDisplayValues;
    this.miniX = miniX;
    this.hourLabel = hourLabel;
    for (const name of [
      "series",
      "totalExpense",
      "name",
      "pct",
      "monthName",
      "level",
      "dayValue",
      "dayTip",
    ])
      this[name] = this[name].bind(this);
    this.orm = useService("orm");
    this.action = useService("action");
    this.state = useState({
      meta: null,
      data: null,
      loading: true,
      error: "",
      page: getStored("page", "overview"),
      company: getStored("company", null),
      mode: getStored("mode", "light"),
      period: getStored("period", null),
      timeline: getStored("timeline", "monthly"),
      view: "pnl",
      pnl_view: null,
      pnl_range: null,
      metric: "gross",
      closed: {},
      cashDrills: {},
      navOpen: false,
    });
    useExternalListener(window, "keydown", (event) => { if (event.key === "Escape") this.state.navOpen = false; });
    onWillUnmount(() => { this.loadToken++; dashboardTooltip.destroy(); });
    this.loadToken = 0;
    onWillStart(() => this.init());
  }
  async init() {
    try {
      const m = await this.orm.call(
        "baseer.dashboard2.service",
        "get_meta",
        [],
      );
      this.state.meta = m;
      if (!m.companies.some((c) => c.key === this.state.company))
        this.state.company = m.default_company_key;
      this.state.period ||= {
        mode: "month",
        month: m.default_month,
        date_from: m.today,
        date_to: m.today,
      };
      // Only an explicit user selection is stored, so an untouched installation follows the server default.
      this.state.pnl_view = getStored("pnl_view", null) || m.pnl_default_view || "month";
      this.resetPnlRange();
      await this.load();
    } catch (e) {
      this.state.error = e.message;
      this.state.loading = false;
    }
  }
  persist(key) {
    localStorage.setItem(
      "baseer_dashboard2." + key,
      JSON.stringify(this.state[key]),
    );
  }
  pnlDrillable(key, child) {
    return ["revenue", "food_cost", "gross_profit", "salaries", "rent", "utilities", "marketing", "commissions", "other_opex", "depreciation", "operating_profit", "other_income", "zakat_tax", "net_profit"].includes(key) && (!child || !child.startsWith("channel:"));
  }
  bridgeDrillKey(key) {
    if (key === "commissions") return "recorded_commissions";
    return ["sales_net", "food_cost", "gross_profit", "salaries", "rent", "utilities", "marketing", "depreciation", "operating_profit", "other_income", "zakat_tax", "net_profit"].includes(key) ? key : null;
  }
  async drillPnl(event, key, child, column) {
    event.stopPropagation();
    if (event.type === "keydown" && event.key !== "Enter") return;
    const action = await this.orm.call("baseer.dashboard2.service", "get_drilldown", [{
      section: "pnl", key, child, column, company_key: this.state.company,
      period: this.state.period, pnl_view: this.state.pnl_view, pnl_range: this.state.pnl_range,
    }]);
    await this.env.services.action.doAction(action);
  }
  async drill(event, section, key, extra = {}) {
    event.stopPropagation();
    if (event.type === "keydown" && event.key !== "Enter") return;
    const action = await this.orm.call("baseer.dashboard2.service", "get_drilldown", [{
      section, key, company_key: this.state.company, period: this.state.period, ...extra,
    }]);
    await this.env.services.action.doAction(action);
  }
  monthPeriod(month) {
    const [year, number] = month.split('-').map(Number);
    const end = `${month}-${String(new Date(year, number, 0).getDate()).padStart(2, '0')}`;
    const selectedEnd = this.state.period.mode === 'month'
      ? `${this.state.period.month}-${String(new Date(Number(this.state.period.month.slice(0, 4)), Number(this.state.period.month.slice(5, 7)), 0).getDate()).padStart(2, '0')}`
      : this.state.period.date_to;
    return {mode: 'range', date_from: `${month}-01`, date_to: end < selectedEnd ? end : selectedEnd};
  }
  miniDrillable(item, index, previous) {
    if (item === 2 && previous) return false;
    if (item !== 1) return true;
    const counts = this.state.data.sales?.trend?.[index]?.source_counts;
    return !!counts?.summary !== !!counts?.pos;
  }
  miniDrill(event, item, index, previous) {
    if (!this.miniDrillable(item, index, previous)) return;
    const month = this.state.data.purchases.trend[index].month;
    return this.drill(event, 'overview', ['purchases', 'apps', 'customers'][item], {period: this.monthPeriod(month)});
  }
  async load() {
    const token = ++this.loadToken;
    const company = this.state.company;
    const period = { ...this.state.period };
    let loadCashDrills = false;
    this.state.loading = true;
    this.state.error = "";
    this.state.cashDrills = {};
    try {
      if (!this.state.company && this.state.page !== "glossary") {
        this.state.data = { available: false, reason: "لا توجد شركات متاحة" };
      } else {
        const data = await this.orm.call(
          "baseer.dashboard2.service",
          "get_section",
          [
            this.state.page === "pnl" ? this.state.view : this.state.page,
            {
              ...(this.state.page === "pnl" && this.state.view === "pnl" ? {pnl_view: this.state.pnl_view, pnl_range: this.state.pnl_range} : {}),
              company_key: this.state.company,
              period: this.state.period,
              timeline_mode: this.state.timeline,
              heatmap_month: this.state.period.mode === "month" ? this.state.period.month : this.state.period.date_to.slice(0, 7),
            },
          ],
        );
        if (token !== this.loadToken) return;
        this.state.data = data;
        loadCashDrills = this.state.page === "pnl" && this.state.view === "inout";
      }
    } catch (e) {
      if (token === this.loadToken) this.state.error = e.message || String(e);
    } finally {
      if (token === this.loadToken) this.state.loading = false;
    }
    if (loadCashDrills && token === this.loadToken) this.loadCashDrills(token, company, period);
  }
  async loadCashDrills(token, company, period) {
    try {
      const drills = await this.orm.call("baseer.dashboard2.service", "get_cash_drill_availability", [{company_key: company, period}]);
      if (token === this.loadToken && this.state.page === "pnl" && this.state.view === "inout" &&
          company === this.state.company && JSON.stringify(period) === JSON.stringify(this.state.period)) this.state.cashDrills = drills;
    } catch (_) {
      // Availability is optional; cash-out figures remain non-drillable on failure.
    }
  }
  async choose(key, value) {
    this.state[key] = value;
    if (key === "pnl_view") { this.persist(key); if (value === "range") this.resetPnlRange(); }
    if (key === "page") this.state.navOpen = false;
    if (["page", "company", "mode", "timeline", "period"].includes(key))
      this.persist(key);
    if (key !== "mode") await this.load();
  }
  resetPnlRange() {
    const p = this.state.period;
    if (p.mode === "range") this.state.pnl_range = {date_from: p.date_from, date_to: p.date_to};
    else {
      const [y, m] = p.month.split("-").map(Number);
      const last = new Date(Date.UTC(y, m, 0)).getUTCDate();
      this.state.pnl_range = {date_from: p.month + "-01", date_to: p.month + "-" + String(last).padStart(2, "0")};
    }
  }
  async pnlRangeChange(key, value) {
    this.state.pnl_range[key] = value;
    const r = this.state.pnl_range;
    if (r.date_from && r.date_to && r.date_from <= r.date_to) await this.load();
  }
  async periodChange(key, value) {
    this.state.cashDrills = {};
    this.state.period[key] = value;
    this.persist("period");
    if (
      this.state.period.mode === "month" ||
      (this.state.period.date_from &&
        this.state.period.date_to &&
        this.state.period.date_from <= this.state.period.date_to)
    )
      await this.load();
  }
  get icons() {
    return {
      overview: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
      revenue: "M3 17l6-6 4 4 8-9 M15 6h6v6",
      expenses: "M3 5h18v14H3z M3 9h18 M7 15h5",
      ratios: "M5 19L19 5 M7 7h.01 M17 17h.01",
      pnl: "M4 3h16v18H4z M4 9h16 M4 15h16 M12 9v12",
      heatmap: "M3 5h18v16H3z M7 2v6 M17 2v6 M3 10h18 M7 14h3v3H7z",
      glossary: "M4 4h14a2 2 0 012 2v14H6a2 2 0 01-2-2z M7 8h9 M7 12h9 M7 16h6",
    };
  }
  get page() {
    return pages.find((p) => p[0] === this.state.page) || pages[0];
  }
  get pages() {
    return pages;
  }
  get labels() {
    return labels;
  }
  get months() {
    return months;
  }
  get weekdays() {
    return weekdays;
  }
  number(value) { return Number(value); }
  objectEntries(value) { return Object.entries(value); }
  objectKeys(value) { return Object.keys(value); }
  previousYear() { return Number(timelineYear(this.state.period)) - 1; }
  weekdayName(date) { return weekdays[(new Date(date + "T12:00:00").getDay() + 1) % 7]; }
  selectMonth(index) { this.periodChange("month", this.state.period.month.slice(0, 4) + "-" + String(index + 1).padStart(2, "0")); }
  fmt = formatNumber;
  tableFmt = formatTable;
  periodRange = periodRange;
  dateName(d) {
    if (!d) return "—";
    const [, , day] = d.split("-");
    return `${Number(day)} ${monthLabel(d)}`;
  }
  name(key) {
    return this.state.data?.channel_names?.[key] || labels[key] || key;
  }
  tablePct = formatTablePct;
  ratioDifference = ratioDifference;
  targetPercent = formatTargetPercent;
  pct(v) {
    return formatPercent(v);
  }
  monthName(m, short = false, year = true, partial = false) {
    return monthLabel(m, { short, year, partial, isolate: partial });
  }
  get current() {
    return this.state.data?.current || {};
  }
  get trend() {
    return this.state.data?.trend || [];
  }
  get trendLabels() {
    return this.trend.map((x) => this.monthName(x.month, true, false, x.partial));
  }
  series(key, category = false) {
    return this.trend.map((x) =>
      x.has_data === false
        ? null
        : category
          ? x.data.categories?.[key]
          : x.data[key],
    );
  }
  get timeline() {
    const t = this.state.data?.timeline;
    if (!t) return [];
    const rows = t.mode === "yearly" ? t.years : t.months;
    return rows;
  }
  bridgeStyle(row, index) {
    const rows = this.state.data?.bridge || [];
    const total = Math.abs(this.current.sales_net) || 1;
    let running = 0;
    for (let i = 0; i < index; i++) {
      const r = rows[i];
      running = ['sales_net', 'gross_profit', 'operating_profit', 'net_profit'].includes(r.key) ? r.amount : running + r.amount;
    }
    const subtotal = ['sales_net', 'gross_profit', 'operating_profit', 'net_profit'].includes(row.key);
    const start = subtotal ? 0 : Math.min(running, running + row.amount);
    return `right:${Math.max(0, Math.min(100, start / total * 100))}%;width:${Math.max(0, Math.min(100, Math.abs(row.amount) / total * 100))}%`;
  }
  get timelineLabels() {
    return this.timeline.map((x) => x.year ? String(x.year) + (x.partial ? " (جزئي)" : "") : monthLabel(`2000-${String(x.month).padStart(2, "0")}`, { short: true, partial: x.partial, isolate: x.partial }));
  }
  get timelineMonths() { return this.state.timeline === "monthly" ? this.timeline.map(x => `${timelineYear(this.state.period)}-${String(x.month).padStart(2, "0")}`) : []; }
  get timelineSeries() {
    return [
      {
        values: this.timeline.map((x) => x.value),
        previousYear: this.timeline.map((x) => x.previous),
        partial: this.timeline.map((x) => x.partial),
        gold: true,
        area: true,
        name: timelineYear(this.state.period),
        drill: (event, index) => this.drill(event, this.state.page, 'timeline_point', {timeline_mode: this.state.timeline, index}),
      },
      { values: this.timeline.map((x) => x.previous), dashed: true, name: String(Number(timelineYear(this.state.period)) - 1) },
    ];
  }
  get hasCustomers() {
    return (this.state.data?.days || []).some((d) => d.customers !== null);
  }
  dayValue(day) {
    return this.state.metric === "customers"
      ? day.customers
      : this.state.metric === "ticket"
        ? day.customers
          ? day.pos_gross / day.customers
          : null
        : day.gross;
  }
  get calendarCells() {
    const d = this.state.data?.days || [];
    if (!d.length) return [];
    const day = new Date(d[0].date + "T00:00:00Z").getUTCDay();
    return [...Array((day + 1) % 7).fill(null), ...d];
  }
  yearPadding(month) {
    if (!month.days.length) return [];
    const day = new Date(month.days[0].date + "T00:00:00Z").getUTCDay();
    return Array.from({ length: (day + 1) % 7 }, (_, i) => i);
  }
  level(day) {
    if (day.gross == null) return 0;
    const a = (this.state.data?.days || []).map((d) => d.gross ?? 0);
    const max = Math.max(1, ...a);
    return Math.max(1, Math.min(5, Math.ceil((day.gross / max) * 5)));
  }
  get companyName() {
    return (
      this.state.meta?.companies.find((c) => c.key === this.state.company)
        ?.label || "—"
    );
  }
  get expenses() {
    return this.state.data?.ranked || [];
  }
  get peakHours() {
    const active = new Set(Array.from({ length: 16 }, (_, i) => (11 + i) % 24));
    for (const cell of this.state.data.hours.matrix) if (cell.orders) active.add(cell.hour);
    return Array.from({ length: 24 }, (_, i) => (11 + i) % 24).filter((hour) => active.has(hour));
  }
  peakValue(day, hour) {
    return this.state.data.hours.matrix.find((cell) => cell.weekday === day && cell.hour === hour)?.orders || 0;
  }
  peakLevel(value) {
    const max = Math.max(1, ...this.state.data.hours.matrix.map((cell) => cell.orders || 0));
    return value ? Math.max(1, Math.ceil(value / max * 5)) : 0;
  }
  peakAverage(values) { return (values.reduce((sum, value) => sum + value, 0) / values.length).toFixed(1); }
  operatingExpense = (d) => this.totalExpense(d) - (d?.categories?.zakat_tax || 0);
  changeValue(value, previous) { return previous && value != null ? (value - previous) / Math.abs(previous) * 100 : null; }
  multiplePoints = multiplePoints;
  iconPath = iconPath;
  totalExpense(d) {
    return Object.entries(d?.categories || {})
      .filter(([k]) => !["revenue", "other_income"].includes(k))
      .reduce((a, [, v]) => a + v, 0);
  }
  async saveTarget(key, event) {
    const v = event.target.value;
    if (v !== "" && Number(v) >= 0 && Number(v) <= 100) {
      await this.orm.call("baseer.dashboard2.service", "save_target", [
        this.state.company,
        key,
        Number(v),
      ]);
      await this.load();
    }
  }
  toggleRow(key) {
    this.state.closed[key] = !this.state.closed[key];
  }
  exportCsv() {
    const table = document.querySelector(".o_bd2 .export-table");
    if (!table) return;
    const rows = [...table.rows].map((r) =>
      [...r.cells]
        .map((c) => '"' + plainCsvText(c.innerText).replaceAll('"', '""') + '"')
        .join(","),
    );
    const a = document.createElement("a");
    a.href = URL.createObjectURL(
      new Blob(["\ufeff" + (this.state.view === "pnl" ? "قبل الضريبة" : "شامل الضريبة") + "\n" + rows.join("\n")], {
        type: "text/csv;charset=utf-8",
      }),
    );
    a.download = "dashboard.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  }
  async addEvent() {
    await this.action.doAction(
      {
        type: "ir.actions.act_window",
        res_model: "baseer.dashboard2.event",
        views: [[false, "form"]],
        target: "new",
      },
      { onClose: () => this.load() },
    );
  }
}
registry.category("actions").add("baseer_dashboard2.main", Dashboard2);
