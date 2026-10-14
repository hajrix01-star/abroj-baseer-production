/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { ReportSelector } from "@baseer_reports_menu/report_selector";
import { useBus, useService } from "@web/core/utils/hooks";
import { user, userBus } from "@web/core/user";

const MODEL = "baseer.pos.tobacco.report.wizard";
const copy = {
    ar: {
        title: "كشف رسوم التبغ من نقاط البيع", company: "الشركة", period: "الفترة",
        month: "شهر", custom: "فترة مخصصة", monthName: ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"],
        year: "السنة", from: "من", to: "إلى", products: "إظهار المنتجات", apply: "عرض التقرير", pdf: "PDF",
        loading: "جارٍ تحميل التقرير…", error: "تعذر عرض التقرير. تحقق من الخيارات أو الصلاحيات ثم أعد المحاولة.",
        noCompany: "الشركة النشطة غير مؤهلة لتقرير رسوم التبغ.",
        applyHint: "اضغط «عرض التقرير» لتطبيق الخيارات.",
        empty: "لا توجد عمليات رسوم تبغ مكتملة في هذه الفترة.", overflow: "تجاوزت الفترة الحد الآمن البالغ 5,000 سطر من نقاط البيع. قسّمها إلى فترات أقصر.",
        opening: "المجموع في بداية الفترة", debit: "خارج / مردود", credit: "داخل / بيع", closing: "صافي رسوم الفترة",
        date: "التاريخ والوقت", order: "رقم طلب نقطة البيع", product: "المنتج والكمية", type: "النوع", running: "الإجمالي التراكمي",
        rows: "السطور", of: "من", page: "صفحة", previous: "السابق", next: "التالي", currency: "العملة",
        mismatch: "اختلاف إجمالي الطلب المعاد احتسابه عن المحفوظ", computed: "المعاد احتسابه", saved: "المحفوظ",
        moreExceptions: "تظهر بقية الاختلافات في PDF.",
    },
    en: {
        title: "POS Tobacco Fee Register", company: "Company", period: "Period",
        month: "Month", custom: "Custom dates", monthName: ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
        year: "Year", from: "From", to: "To", products: "Show products", apply: "Show report", pdf: "PDF",
        loading: "Loading report…", error: "Could not load the report. Check the options or your access rights and retry.",
        noCompany: "The active company is not eligible for the tobacco-fee report.",
        applyHint: "Select Show report to apply the options.",
        empty: "No completed POS tobacco-fee sales were found in this period.", overflow: "This period exceeds the safe limit of 5,000 POS lines. Split it into shorter periods.",
        opening: "Period cumulative total at start", debit: "Out / refunds", credit: "In / sales", closing: "Net fees for period",
        date: "Date and time", order: "POS order number", product: "Product and quantity", type: "Type", running: "Cumulative total",
        rows: "Rows", of: "of", page: "Page", previous: "Previous", next: "Next", currency: "Currency",
        mismatch: "Recalculated order totals differ from saved totals", computed: "Recalculated", saved: "Saved",
        moreExceptions: "More differences are listed in the PDF.",
    },
};

export class BaseerTobaccoReport extends Component {
    static components = { ReportSelector };
    static template = "baseer_pos_tobacco_report.HubReport";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.lang = user.lang?.startsWith("ar") ? "ar" : "en";
        this.state = useState({ loading: true, printing: false, error: "", data: null,
            filters: { company_id: 0, period: "month", month: 1, year: 2026,
                date_from: "", date_to: "", show_products: false, page: 1 } });
        this.requestToken = 0;
        this.companyGeneration = 0;
        useBus(userBus, "ACTIVE_COMPANIES_CHANGED", () => this.refreshActiveCompany());
        onWillStart(() => this.refreshActiveCompany());
    }

    get activeCompanyId() { return Number(user.activeCompany?.id) || 0; }
    get periodCaption() {
        const data = this.state.data;
        if (!data) { return ""; }
        const match = /^(\d{4})-(\d{2})-01$/.exec(data.date_from || "");
        if (data.period_kind === "month" && match &&
            data.date_to === `${match[1]}-${match[2]}-${String(new Date(Date.UTC(Number(match[1]), Number(match[2]), 0)).getUTCDate()).padStart(2, "0")}`) {
            return `${this.labels.monthName[Number(match[2]) - 1]} ${match[1]}`;
        }
        return `${data.from_text} — ${data.to_text}`;
    }
    async refreshActiveCompany() {
        const generation = ++this.companyGeneration;
        const companyId = this.activeCompanyId;
        this.requestToken += 1;
        this.state.filters.company_id = 0;
        this.state.data = null;
        this.state.error = "";
        if (!companyId) { this.state.error = this.labels.noCompany; this.state.loading = false; return; }
        this.state.loading = true;
        try {
            const context = await this.orm.call(MODEL, "get_hub_context", []);
            if (generation !== this.companyGeneration || companyId !== this.activeCompanyId) { return; }
            if (companyId && context.company_id !== companyId) {
                this.state.error = this.labels.noCompany;
                return;
            }
            Object.assign(this.state.filters, {
                company_id: context.company_id, month: context.month, year: context.year,
                date_from: context.date_from, date_to: context.date_to, page: 1,
            });
            if (this.state.filters.company_id) { await this.load(); }
        } catch (error) {
            if (generation === this.companyGeneration) { this.state.error = error?.data?.message || this.labels.error; }
        } finally {
            if (generation === this.companyGeneration) { this.state.loading = false; }
        }
    }

    get labels() { return copy[this.lang]; }
    get monthOptions() { return this.labels.monthName.map((name, index) => ({ value: index + 1, name })); }
    amountClass(value, outflow = false) {
        if (!value || value === "0.00") { return "o_baseer_report_amount is-zero"; }
        return `o_baseer_report_amount${outflow ? " is-outflow" : value.startsWith("-") ? " is-negative" : ""}`;
    }
    updateFilter(event) {
        const key = event.target.name;
        if (!Object.hasOwn(this.state.filters, key)) { return; }
        this.state.filters[key] = key === "month" || key === "year"
            ? Number(event.target.value) : key === "show_products" ? event.target.checked : event.target.value;
        this.requestToken += 1;
        this.state.filters.page = 1;
        this.state.loading = false;
        this.state.error = "";
        this.state.data = null;
    }
    async load(page = 1) {
        if (!this.state.filters.company_id || this.state.filters.company_id !== this.activeCompanyId) { return; }
        this.state.filters.page = page;
        this.state.loading = true;
        this.state.error = "";
        this.state.data = null;
        const token = ++this.requestToken;
        const generation = this.companyGeneration;
        const companyId = this.activeCompanyId;
        try {
            const data = await this.orm.call(MODEL, "get_hub_report", [{ ...this.state.filters }]);
            if (token === this.requestToken && generation === this.companyGeneration && companyId === this.activeCompanyId) { this.state.data = data; }
        } catch (error) {
            if (token === this.requestToken && generation === this.companyGeneration) { this.state.error = error?.data?.message || this.labels.error; }
        } finally {
            if (token === this.requestToken && generation === this.companyGeneration) { this.state.loading = false; }
        }
    }
    async printPdf() {
        if (this.state.printing || this.state.loading || !this.state.data || this.state.data.overflow) { return; }
        this.state.printing = true;
        this.state.error = "";
        const token = this.requestToken;
        const companyId = this.activeCompanyId;
        try {
            const action = await this.orm.call(MODEL, "action_hub_pdf", [{ ...this.state.filters }]);
            if (token === this.requestToken && companyId === this.activeCompanyId) { await this.action.doAction(action); }
        } catch (error) {
            if (token === this.requestToken && companyId === this.activeCompanyId) {
                this.state.error = error?.data?.message || this.labels.error;
            }
        } finally {
            this.state.printing = false;
        }
    }
}
