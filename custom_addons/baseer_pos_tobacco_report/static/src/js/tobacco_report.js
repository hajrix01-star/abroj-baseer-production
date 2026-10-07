/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { ReportSelector } from "@baseer_reports_menu/report_selector";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";

const MODEL = "baseer.pos.tobacco.report.wizard";
const copy = {
    ar: {
        title: "كشف رسوم التبغ من نقاط البيع", company: "الشركة", period: "الفترة",
        month: "شهر", custom: "فترة مخصصة", monthName: ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"],
        year: "السنة", from: "من", to: "إلى", products: "إظهار المنتجات", apply: "عرض التقرير", pdf: "PDF", xlsx: "XLSX",
        loading: "جارٍ تحميل التقرير…", error: "تعذر عرض التقرير. تحقق من الخيارات أو الصلاحيات ثم أعد المحاولة.",
        exportError: "تعذر تصدير Excel. تحقق من الصلاحيات والفترة، أو أعد المحاولة بعد اكتمال التصدير الجاري.",
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
        year: "Year", from: "From", to: "To", products: "Show products", apply: "Show report", pdf: "PDF", xlsx: "XLSX",
        loading: "Loading report…", error: "Could not load the report. Check the options or your access rights and retry.",
        exportError: "Could not export Excel. Check access and period, or retry after the current export finishes.",
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
        this.state = useState({ loading: true, printing: false, exporting: false, error: "", data: null, companies: [],
            filters: { company_id: 0, period: "month", month: 1, year: 2026,
                date_from: "", date_to: "", show_products: false, page: 1 } });
        this.requestToken = 0;
        onWillStart(async () => {
            try {
                const context = await this.orm.call(MODEL, "get_hub_context", []);
                this.state.companies = context.companies;
                Object.assign(this.state.filters, {
                    company_id: context.company_id, month: context.month, year: context.year,
                    date_from: context.date_from, date_to: context.date_to,
                });
                await this.load();
            } catch (error) {
                this.state.error = error?.data?.message || this.labels.error;
                this.state.loading = false;
            }
        });
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
        this.state.filters[key] = key === "company_id" || key === "month" || key === "year"
            ? Number(event.target.value) : key === "show_products" ? event.target.checked : event.target.value;
        this.requestToken += 1;
        this.state.filters.page = 1;
        this.state.loading = false;
        this.state.error = "";
        this.state.data = null;
    }
    async load(page = 1) {
        this.state.filters.page = page;
        this.state.loading = true;
        this.state.error = "";
        this.state.data = null;
        const token = ++this.requestToken;
        try {
            const data = await this.orm.call(MODEL, "get_hub_report", [{ ...this.state.filters }]);
            if (token === this.requestToken) { this.state.data = data; }
        } catch (error) {
            if (token === this.requestToken) { this.state.error = error?.data?.message || this.labels.error; }
        } finally {
            if (token === this.requestToken) { this.state.loading = false; }
        }
    }
    async printPdf() {
        if (this.state.printing || this.state.loading || !this.state.data || this.state.data.overflow) { return; }
        this.state.printing = true;
        this.state.error = "";
        try {
            const action = await this.orm.call(MODEL, "action_hub_pdf", [{ ...this.state.filters }]);
            await this.action.doAction(action);
        } catch (error) {
            this.state.error = error?.data?.message || this.labels.error;
        } finally {
            this.state.printing = false;
        }
    }
    async exportXlsx() {
        if (this.state.exporting || this.state.loading || !this.state.data || this.state.data.overflow) { return; }
        this.state.exporting = true;
        this.state.error = "";
        try {
            const action = await this.orm.call(MODEL, "export_hub_xlsx", [{ ...this.state.filters }]);
            await this.action.doAction(action);
        } catch (error) {
            this.state.error = error?.data?.message || this.labels.exportError;
        } finally {
            this.state.exporting = false;
        }
    }
}
