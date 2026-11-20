/** @odoo-module **/
import { Component, onWillStart, useState, useExternalListener } from "@odoo/owl";
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
const months = [
  "يناير",
  "فبراير",
  "مارس",
  "أبريل",
  "مايو",
  "يونيو",
  "يوليو",
  "أغسطس",
  "سبتمبر",
  "أكتوبر",
  "نوفمبر",
  "ديسمبر",
];
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
  expenses: "المصاريف", profit: "الأرباح", ratios: "النسب", breakeven: "نقطة التعادل", gross_sales_by_channel: "المبيعات حسب القناة", apps: "التطبيقات", apps_unreceived: "التطبيقات غير المستلمة", customers: "العملاء", hours: "أوقات الذروة", inout: "الداخل والخارج", unpaid_bills: "الفواتير غير المسددة", timeline: "المسار الزمني", heatmap: "التقويم الحراري", sales_vat: "ضريبة المبيعات",
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
  static template = "baseer_dashboard2.Sparkline";
  static props = { values: { optional: true }, previous: { optional: true }, gold: { optional: true }, secondaryGold: { optional: true }, navy: { optional: true }, mini: { optional: true }, stretch: { optional: true }, ratioPercent: { optional: true }, amountDecimal: { optional: true }, partial: { optional: true } };
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
  static props = { series: Array, labels: { optional: true }, percent: { optional: true }, compactTop: { optional: true }, fiveTicks: { optional: true } };
  chartX = chartX;
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
    const entries = this.renderedSeries.filter(s => s.firstLabel || s.endpoint)
      .map(s => ({ series: s, value: s.values.findLast(v => v != null) }))
      .filter(entry => entry.value != null)
      .map(entry => ({ ...entry, y: Math.max(12, Math.min(200, this.y(entry.value) - 8)) }))
      .sort((a, b) => a.y - b.y);
    for (let i = 1; i < entries.length; i++) entries[i].y = Math.max(entries[i].y, entries[i - 1].y + 12);
    if (entries.length && entries.at(-1).y > 200) {
      entries.at(-1).y = 200;
      for (let i = entries.length - 2; i >= 0; i--) entries[i].y = Math.min(entries[i].y, entries[i + 1].y - 12);
    }
    return entries.find(entry => entry.series === series)?.y ?? this.y(value) - 8;
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
class Track extends Component {
  static template = "baseer_dashboard2.Track";
  static props = {
    value: { optional: true },
    max: { optional: true },
    gold: { optional: true },
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
  static template = "baseer_dashboard2.Ring";
  static props = { value: { optional: true } };
  get offset() {
    return 264 * (1 - Math.max(0, Math.min(100, this.props.value || 0)) / 100);
  }
}
export class Gauge extends Component {
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
    previousTrend: { optional: true },
    partial: { optional: true },
    hero: { optional: true },
    goodWhen: { optional: true },
    foodProgress: { optional: true },
    warning: { optional: true },
    partialMonth: { optional: true },
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

class Dashboard2 extends Component {
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
      metric: "gross",
      closed: {},
    });
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
  async load() {
    this.state.loading = true;
    this.state.error = "";
    try {
      if (!this.state.company && this.state.page !== "glossary") {
        this.state.data = { available: false, reason: "لا توجد شركات متاحة" };
      } else {
        this.state.data = await this.orm.call(
          "baseer.dashboard2.service",
          "get_section",
          [
            this.state.page === "pnl" ? this.state.view : this.state.page,
            {
              company_key: this.state.company,
              period: this.state.period,
              timeline_mode: this.state.timeline,
              heatmap_month: this.state.period.mode === "month" ? this.state.period.month : this.state.period.date_to.slice(0, 7),
            },
          ],
        );
      }
    } catch (e) {
      this.state.error = e.message || String(e);
    } finally {
      this.state.loading = false;
    }
  }
  async choose(key, value) {
    this.state[key] = value;
    if (["page", "company", "mode", "timeline", "period"].includes(key))
      this.persist(key);
    if (key !== "mode") await this.load();
  }
  async periodChange(key, value) {
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
    const [, month, day] = d.split("-");
    return `${Number(day)} ${months[Number(month) - 1]}`;
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
  monthName(m) {
    if (!m) return "—";
    const [y, n] = m.split("-");
    return `${months[Number(n) - 1]} ${y}`;
  }
  get current() {
    return this.state.data?.current || {};
  }
  get trend() {
    return this.state.data?.trend || [];
  }
  get trendLabels() {
    return this.trend.map((x) => this.monthName(x.month).split(" ")[0] + (x.partial ? " (جزئي)" : ""));
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
    return this.timeline.map((x) => (x.year || months[x.month - 1]) + (x.partial ? " (جزئي)" : ""));
  }
  get timelineSeries() {
    return [
      {
        values: this.timeline.map((x) => x.value),
        partial: this.timeline.map((x) => x.partial),
        gold: true,
        area: true,
        name: timelineYear(this.state.period),
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
        .map((c) => '"' + c.innerText.replaceAll('"', '""') + '"')
        .join(","),
    );
    const a = document.createElement("a");
    a.href = URL.createObjectURL(
      new Blob(["\ufeff" + rows.join("\n")], {
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
