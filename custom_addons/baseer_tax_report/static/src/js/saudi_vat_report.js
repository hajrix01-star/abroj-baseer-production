/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { ReportSelector } from "@baseer_reports_menu/report_selector";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";

const copy = {
    ar: {
        title: "تقرير ضريبة القيمة المضافة", company: "الشركة", period: "الفترة",
        quarter: "ربع سنوي", month: "شهري", year: "السنة", monthValue: "الشهر",
        quarterValue: "الربع", display: "العرض", simple: "مبسط", detailed: "مفصل",
        journals: "الدفاتر", allJournals: "جميع الدفاتر", selectedJournals: "دفاتر مختارة",
        apply: "عرض التقرير", pdf: "PDF", xlsx: "XLSX", item: "البند", base: "الأساس", tax: "الضريبة",
        empty: "لا توجد مبالغ في الفترة المحددة.", noCompany: "لا توجد شركة سعودية متاحة لصلاحياتك.",
        loading: "جارٍ تحميل تقرير الضريبة…", error: "تعذر تحميل التقرير. تحقق من الفترة والصلاحيات ثم أعد المحاولة.",
        exportError: "تعذر تصدير Excel. تحقق من الصلاحيات والفترة ودقة العملة؛ قد يكون الملف تجاوز حد الحجم أو الوقت.",
        source: "عرض القيود الداعمة", expand: "عرض البنود المكوّنة", collapse: "إخفاء البنود المكوّنة",
        selectedWarning: "تحليل الدفاتر المختارة، وليس إجمالي الإقرار لجميع الدفاتر.",
        untaggedVat: "قيود ضريبة القيمة المضافة غير المصنفة", untaggedOther: "قيود ضرائب أخرى غير مصنفة",
        entries: "قيد", signedBalance: "الرصيد", review: "هذه القيود خارج خانات التقرير؛ راجع تصنيفها قبل اعتماد التقرير.",
        viewEntries: "عرض القيود", currency: "العملة",
        months: ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"],
    },
    en: {
        title: "Saudi VAT Report", company: "Company", period: "Period",
        quarter: "Quarterly", month: "Monthly", year: "Year", monthValue: "Month",
        quarterValue: "Quarter", display: "Display", simple: "Summary", detailed: "Detailed",
        journals: "Journals", allJournals: "All journals", selectedJournals: "Selected journals",
        apply: "View report", pdf: "PDF", xlsx: "XLSX", item: "VAT return box", base: "Amount", tax: "VAT",
        empty: "No non-zero boxes for this period.", noCompany: "No Saudi company is available to your access rights.",
        loading: "Loading VAT report…", error: "Could not load the report. Check the period and access, then retry.",
        exportError: "Could not export Excel. Check access, period and currency precision; the file may have exceeded its size or time limit.",
        source: "Open supporting entries", expand: "Show component boxes", collapse: "Hide component boxes",
        selectedWarning: "Selected journals are an analytical view, not the full VAT return.",
        untaggedVat: "Unclassified VAT entries", untaggedOther: "Other unclassified tax entries",
        entries: "entries", signedBalance: "Balance", review: "These entries are outside the VAT return boxes; review their classification before approval.",
        viewEntries: "View entries", currency: "Currency",
        months: ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
    },
};

export class SaudiVatReport extends Component {
    static components = { ReportSelector };
    static template = "baseer_tax_report.SaudiVatReport";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.lang = user.lang?.startsWith("ar") ? "ar" : "en";
        this.epoch = 0;
        this.state = useState({
            companies: [], journals: [], companyId: 0, periodType: "quarter", year: 0,
            month: "1", quarter: "1", displayMode: "simple", journalIds: [],
            data: null, expanded: {}, loading: true, printing: false, exporting: false, error: "",
        });
        onWillStart(() => this.loadOptions());
    }

    get labels() { return copy[this.lang]; }
    get months() { return this.labels.months.map((label, index) => ({ value: String(index + 1), label })); }
    get quarterNumbers() { return ["1", "2", "3", "4"]; }
    get companyJournals() { return this.state.journals.filter((journal) => journal.company_id === this.state.companyId); }
    get journalLabel() {
        return this.state.journalIds.length
            ? `${this.labels.selectedJournals} (${this.state.journalIds.length})`
            : this.labels.allJournals;
    }
    payload() {
        return {
            company_id: this.state.companyId, period_type: this.state.periodType,
            year: this.state.year, month: this.state.month, quarter: this.state.quarter,
            display_mode: this.state.displayMode, journal_ids: [...this.state.journalIds],
        };
    }
    invalidate() {
        this.epoch += 1;
        this.state.data = null;
        this.state.expanded = {};
        this.state.error = "";
        this.state.loading = false;
    }
    onCompanyChange(event) {
        this.state.companyId = Number(event.target.value);
        this.state.journalIds = [];
        this.invalidate();
    }
    onPeriodChange(event) { this.state.periodType = event.target.value; this.invalidate(); }
    onYearChange(event) { this.state.year = Number(event.target.value); this.invalidate(); }
    onMonthChange(event) { this.state.month = event.target.value; this.invalidate(); }
    onQuarterChange(event) { this.state.quarter = event.target.value; this.invalidate(); }
    onDisplayChange(event) { this.state.displayMode = event.target.value; this.invalidate(); }
    onJournalChange(event) {
        const id = Number(event.target.value);
        this.state.journalIds = event.target.checked
            ? [...this.state.journalIds, id]
            : this.state.journalIds.filter((journalId) => journalId !== id);
        this.invalidate();
    }

    async loadOptions() {
        try {
            const options = await this.orm.call("baseer.tax.report.wizard", "get_hub_options", []);
            this.state.companies = options.companies;
            this.state.journals = options.journals;
            this.state.companyId = options.default_company_id || 0;
            this.state.year = options.default_year;
            this.state.quarter = options.default_quarter;
            if (this.state.companyId) { await this.apply(); }
        } catch (error) {
            this.state.error = this.labels.error;
        } finally {
            this.state.loading = false;
        }
    }

    async apply() {
        if (!this.state.companyId) { return; }
        const epoch = ++this.epoch;
        this.state.loading = true;
        this.state.error = "";
        this.state.data = null;
        this.state.expanded = {};
        try {
            const data = await this.orm.call("baseer.tax.report.wizard", "get_hub_report", [this.payload()]);
            if (epoch === this.epoch) { this.state.data = data; }
        } catch (error) {
            if (epoch === this.epoch) { this.state.error = this.labels.error; }
        } finally {
            if (epoch === this.epoch) { this.state.loading = false; }
        }
    }

    async printPdf() {
        if (!this.state.data || this.state.printing) { return; }
        this.state.printing = true;
        try {
            const action = await this.orm.call("baseer.tax.report.wizard", "print_hub_report", [this.payload()]);
            await this.action.doAction(action);
        } catch (error) {
            this.state.error = this.labels.error;
        } finally {
            this.state.printing = false;
        }
    }

    async exportXlsx() {
        if (!this.state.data || this.state.exporting) { return; }
        this.state.exporting = true;
        this.state.error = "";
        try {
            const action = await this.orm.call("baseer.tax.report.wizard", "export_hub_xlsx", [this.payload()]);
            await this.action.doAction(action);
        } catch (error) {
            this.state.error = this.labels.exportError;
        } finally {
            this.state.exporting = false;
        }
    }

    async openCell(box, column) {
        try {
            const action = await this.orm.call("baseer.tax.report.wizard", "open_hub_cell", [this.payload(), box, column]);
            await this.action.doAction(action);
        } catch (error) { this.state.error = this.labels.error; }
    }

    async openException(kind) {
        try {
            const action = await this.orm.call("baseer.tax.report.wizard", "open_hub_exception", [this.payload(), kind]);
            await this.action.doAction(action);
        } catch (error) { this.state.error = this.labels.error; }
    }

    toggleComponents(box, column) {
        const key = `${box}:${column}`;
        this.state.expanded = { ...this.state.expanded, [key]: !this.state.expanded[key] };
    }
    isExpanded(box, column) { return Boolean(this.state.expanded[`${box}:${column}`]); }
    amountClass(state) { return state === "zero" ? "is-zero" : state === "negative" ? "is-negative" : ""; }
    isTotal(number) { return ["6", "12", "13", "16"].includes(number); }
}
