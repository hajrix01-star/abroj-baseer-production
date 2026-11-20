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
export const formatTablePct = (n) => {
  if (n == null || n === false || !Number.isFinite(Number(n))) return "—";
  const magnitude = Math.abs(Number(n)).toFixed(1);
  return magnitude === "0.0" ? "—" : `${Number(n) < 0 ? "-" : ""}${magnitude}%`;
};
export const chartX = (i, n, width = 700) =>
  width - 48 - (width - 70) * (n <= 1 ? 0.5 : i / (n - 1));
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
  utilities: "الكهرباء والخدمات",
  marketing: "التسويق",
  commissions: "العمولات",
  other_opex: "مصاريف تشغيلية أخرى",
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

class Sparkline extends Component {
  static template = "baseer_dashboard2.Sparkline";
  static props = { values: { optional: true }, gold: { optional: true } };
  get path() {
    const a = this.props.values || [];
    const present = a.filter((v) => v != null).map(Number);
    const min = Math.min(...present, 0);
    const max = Math.max(...present, 1);
    return a
      .map((v, i) =>
        v == null
          ? ""
          : `${i && a[i - 1] != null ? "L" : "M"}${95 - (a.length <= 1 ? 45 : (90 * i) / (a.length - 1))},${28 - ((Number(v) - min) / (max - min)) * 24}`,
      )
      .join(" ");
  }
}
class LineChart extends Component {
  static template = "baseer_dashboard2.LineChart";
  static props = { series: Array, labels: { optional: true } };
  chartX = chartX;
  get max() {
    return Math.max(
      1,
      ...this.props.series.flatMap((s) =>
        s.values.filter((v) => v !== null && v !== undefined).map(Number),
      ),
    );
  }
  y(v) {
    return 205 - ((Number(v) || 0) / this.max) * 165;
  }
  area(values) {
    let segments = [];
    let points = [];
    const flush = () => {
      if (points.length) segments.push(`M${points[0][0]},205 ` + points.map(([x, y]) => `L${x},${y}`).join(" ") + ` L${points.at(-1)[0]},205 Z`);
      points = [];
    };
    values.forEach((value, i) => value == null ? flush() : points.push([chartX(i, values.length), this.y(value)]));
    flush();
    return segments.join(" ");
  }
  compact(value) {
    return Math.abs(value) >= 1000
      ? `${Math.round(value / 1000)}K`
      : formatNumber(value);
  }
  partialPath(values, partial) {
    const i = partial?.findIndex(Boolean) ?? -1;
    return i > 0 && values[i] != null && values[i - 1] != null
      ? `M${chartX(i - 1, values.length)},${this.y(values[i - 1])} L${chartX(i, values.length)},${this.y(values[i])}`
      : "";
  }
  path(values) {
    return values
      .map((v, i) =>
        v === null || v === undefined
          ? ""
          : `${i && values[i - 1] != null ? "L" : "M"}${chartX(i, values.length)},${this.y(v)}`,
      )
      .join(" ");
  }
}
class Money extends Component {
  static template = "baseer_dashboard2.Money";
  static props = { value: { optional: true } };
  format = formatNumber;
}
class Badge extends Component {
  static template = "baseer_dashboard2.Badge";
  static props = { value: { optional: true }, goodWhen: { optional: true } };
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
class Gauge extends Component {
  static template = "baseer_dashboard2.Gauge";
  static props = {
    value: { optional: true },
    target: { optional: true },
    previous: { optional: true },
    max: { optional: true },
  };
  // The gauge uses a fixed 0–100% scale, shared by value and target.
  pos(v) {
    return Math.max(
      0,
      Math.min(100, (100 * (v || 0)) / (this.props.max || 100)),
    );
  }
}
class KpiCard extends Component {
  static template = "baseer_dashboard2.KpiCard";
  static components = { Money, Badge, Sparkline };
  static props = {
    title: String,
    value: { optional: true },
    change: { optional: true },
    trend: { optional: true },
    hero: { optional: true },
    goodWhen: { optional: true },
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
    this.Number = Number;
    this.String = String;
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
  fmt = formatNumber;
  tableFmt = formatTable;
  dateName(d) {
    if (!d) return "—";
    const [, month, day] = d.split("-");
    return `${Number(day)} ${months[Number(month) - 1]}`;
  }
  name(key) {
    return this.state.data?.channel_names?.[key] || labels[key] || key;
  }
  tablePct = formatTablePct;
  pct(v) {
    return v === null || v === undefined ? "—" : `${Number(v).toFixed(1)}%`;
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
    return this.trend.map((x) => this.monthName(x.month).split(" ")[0]);
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
    return t.mode === "yearly" ? t.years : t.months;
  }
  get timelineLabels() {
    return this.timeline.map((x) => x.year || months[x.month - 1]);
  }
  get timelineSeries() {
    return [
      {
        values: this.timeline.map((x) => x.value),
        partial: this.timeline.map((x) => x.partial),
        gold: true,
        area: true,
      },
      { values: this.timeline.map((x) => x.previous), dashed: true },
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
