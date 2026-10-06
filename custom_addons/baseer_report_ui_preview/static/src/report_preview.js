/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";

const name = (ar, en) => ({ ar, en });
const value = (text, tone = "normal") => ({ text, tone });
const row = (id, kind, title, amounts, children = []) => ({ id, kind, title, amounts, children });

// All figures and references are synthetic presentation fixtures, never report results.
export const SAMPLE_REPORTS = {
    profit: {
        title: name("الربح والخسارة", "Profit and Loss"),
        columns: [name("البند", "Description"), name("الرصيد", "Balance")],
        rows: [
            row("income", "section", name("الإيرادات", "Revenue"), [value("84,500.00")], [
                row("sales", "line", name("مبيعات نموذجية", "Sample sales"), [value("84,500.00")]),
            ]),
            row("income-total", "total", name("إجمالي الإيرادات", "Total revenue"), [value("84,500.00")]),
            row("expenses", "section", name("المصروفات", "Expenses"), [value("−24,300.00", "negative")], [
                row("operations", "line", name("مصروفات تشغيلية نموذجية", "Sample operating expenses"), [value("−18,600.00", "negative")]),
                row("rent", "line", name("إيجار نموذجي", "Sample rent"), [value("−5,700.00", "negative")]),
            ]),
            row("net", "total", name("صافي الربح", "Net profit"), [value("60,200.00")]),
        ],
    },
    tax: {
        title: name("ضريبة القيمة المضافة", "VAT Report"),
        columns: [name("البند", "Item"), name("الأساس", "Base"), name("الضريبة", "Tax")],
        rows: [
            row("sales", "section", name("ضريبة المبيعات", "Sales VAT"), [value("80,000.00"), value("12,000.00")], [
                row("standard", "line", name("مبيعات بالنسبة الأساسية", "Standard-rate sales"), [value("80,000.00"), value("12,000.00")]),
            ]),
            row("purchases", "section", name("ضريبة المشتريات", "Purchase VAT"), [value("25,000.00"), value("3,750.00")], [
                row("domestic", "line", name("مشتريات محلية نموذجية", "Sample domestic purchases"), [value("25,000.00"), value("3,750.00")]),
            ]),
            row("net", "total", name("صافي الضريبة", "Net VAT"), [value("—", "zero"), value("8,250.00")]),
        ],
    },
    tobacco: {
        title: name("رسوم التبغ", "Tobacco Fees"),
        columns: [name("البند", "Item"), name("مدين", "Debit"), name("دائن", "Credit"), name("التراكمي", "Running total")],
        rows: [
            row("day", "section", name("مبيعات اليوم النموذجية", "Sample daily sales"), [value("0.00", "zero"), value("150.00"), value("150.00")], [
                row("receipt", "line", name("عملية بيع نموذجية", "Sample sale"), [value("0.00", "zero"), value("150.00"), value("150.00")]),
            ]),
            row("total", "total", name("إجمالي رسوم الفترة", "Total period fees"), [value("0.00", "zero"), value("150.00"), value("150.00")]),
        ],
    },
    ledger: {
        title: name("دفتر الأستاذ العام", "General Ledger"),
        columns: [name("الحساب", "Account"), name("مدين", "Debit"), name("دائن", "Credit"), name("الرصيد", "Balance")],
        rows: [
            row("cash", "section", name("الصندوق", "Cash"), [value("8,400.00"), value("1,200.00"), value("7,200.00")], [
                row("cash-in", "line", name("تحصيل نموذجي", "Sample receipt"), [value("8,400.00"), value("0.00", "zero"), value("8,400.00")]),
                row("cash-out", "line", name("صرف نموذجي", "Sample payment"), [value("0.00", "zero"), value("1,200.00"), value("−1,200.00", "negative")]),
            ]),
            row("bank", "section", name("البنك", "Bank"), [value("5,100.00"), value("600.00"), value("4,500.00")], [
                row("bank-in", "line", name("إيداع نموذجي", "Sample deposit"), [value("5,100.00"), value("0.00", "zero"), value("5,100.00")]),
            ]),
            row("total", "total", name("إجمالي الحركة النموذجية", "Sample movement total"), [value("13,500.00"), value("1,800.00"), value("11,700.00")]),
        ],
    },
};

export const SAMPLE_ITEMS = [
    { id: 1, date: "2026-10-01", ref: "DEMO/001", account: name("الصندوق", "Cash"), label: name("تحصيل نموذجي", "Sample receipt"), debit: value("2,100.00"), credit: value("0.00", "zero") },
    { id: 2, date: "2026-10-02", ref: "DEMO/002", account: name("مبيعات", "Sales"), label: name("بيع نموذجي", "Sample sale"), debit: value("0.00", "zero"), credit: value("2,100.00") },
    { id: 3, date: "2026-10-03", ref: "DEMO/003", account: name("مصروفات", "Expenses"), label: name("صرف نموذجي", "Sample payment"), debit: value("1,200.00"), credit: value("0.00", "zero") },
    { id: 4, date: "2026-10-04", ref: "DEMO/004", account: name("البنك", "Bank"), label: name("إيداع نموذجي", "Sample deposit"), debit: value("5,100.00"), credit: value("0.00", "zero") },
    { id: 5, date: "2026-10-05", ref: "DEMO/005", account: name("الضريبة", "VAT"), label: name("ضريبة نموذجية", "Sample VAT"), debit: value("0.00", "zero"), credit: value("750.00") },
    { id: 6, date: "2026-10-06", ref: "DEMO/006", account: name("الصندوق", "Cash"), label: name("صرف نقدي نموذجي", "Sample cash outflow"), debit: value("0.00", "zero"), credit: value("600.00", "outflow") },
];

const copy = {
    ar: {
        preview: "معاينة تصميم — بيانات تجريبية", sampleNote: "الأرقام لا تتغير بتغيير خيارات المعاينة، وليست نتائج مالية.",
        pdf: "PDF", xlsx: "XLSX", exportLater: "يتوفر عند ربط البيانات", period: "الفترة", month: "شهر", quarter: "ربع سنة", year: "سنة مالية", custom: "فترة مخصصة",
        comparison: "مقارنة", journals: "الدفاتر", analytic: "التحليلي", posted: "قيود مرحلة", currency: "بالر.س", demo: "تجريبي",
        monthValue: "أكتوبر 2026", quarterValue: "الربع الثالث 2026", yearValue: "2026", customValue: "فترة مخصصة", search: "بحث في العمليات التجريبية…",
        entries: "بنود اليومية", details: "عرض العمليات", back: "العودة إلى التقرير", noRows: "لا توجد عمليات تجريبية مطابقة.",
        date: "التاريخ", reference: "المرجع", account: "الحساب", description: "البيان", debit: "مدين", credit: "دائن", attachments: "معاينة المرفقات", attachmentsEmpty: "لا توجد مرفقات في هذه المعاينة.",
        previous: "السابق", next: "التالي", of: "من", expand: "فتح تفاصيل البند", collapse: "طي تفاصيل البند", chooseReport: "اختر التقرير التجريبي", simulated: "الخيار تجريبي، لا يغيّر الأرقام",
    },
    en: {
        preview: "Design preview — sample data", sampleNote: "Figures do not change with preview options and are not financial results.",
        pdf: "PDF", xlsx: "XLSX", exportLater: "Available after data connection", period: "Period", month: "Month", quarter: "Quarter", year: "Fiscal year", custom: "Custom dates",
        comparison: "Comparison", journals: "Journals", analytic: "Analytic", posted: "Posted entries", currency: "In SAR", demo: "Sample",
        monthValue: "Oct 2026", quarterValue: "Q3 2026", yearValue: "2026", customValue: "Custom dates", search: "Search sample journal items…",
        entries: "Journal Items", details: "View journal items", back: "Back to report", noRows: "No matching sample journal items.",
        date: "Date", reference: "Reference", account: "Account", description: "Label", debit: "Debit", credit: "Credit", attachments: "Attachment preview", attachmentsEmpty: "No attachments in this preview.",
        previous: "Previous", next: "Next", of: "of", expand: "Expand item", collapse: "Collapse item", chooseReport: "Choose sample report", simulated: "Sample option; figures do not change",
    },
};

export function flattenRows(rows, expanded, depth = 0) {
    return rows.flatMap((item) => [
        { ...item, depth },
        ...(expanded[item.id] ? flattenRows(item.children, expanded, depth + 1) : []),
    ]);
}

export function filterItems(items, query, lang) {
    const needle = query.trim().toLocaleLowerCase();
    if (!needle) { return items; }
    return items.filter((item) => [item.date, item.ref, item.account[lang], item.label[lang]]
        .some((field) => field.toLocaleLowerCase().includes(needle)));
}

export class ReportDesignPreview extends Component {
    static template = "baseer_report_ui_preview.Report";
    static components = { Dropdown, DropdownItem };
    static props = ["*"];

    setup() {
        this.lang = user.lang?.startsWith("ar") ? "ar" : "en";
        this.state = useState({ report: "profit", period: "month", expanded: {}, screen: "report", query: "", page: 0, comparison: false, journals: false, analytic: false, posted: true, selected: 0 });
    }

    get labels() { return copy[this.lang]; }
    get reportOptions() { return Object.entries(SAMPLE_REPORTS).map(([key, report]) => ({ key, label: report.title[this.lang] })); }
    get report() { return SAMPLE_REPORTS[this.state.report]; }
    get visibleRows() { return flattenRows(this.report.rows, this.state.expanded); }
    get periodLabel() { return this.labels[`${this.state.period}Value`]; }
    get matchingItems() { return filterItems(SAMPLE_ITEMS, this.state.query, this.lang); }
    get pageItems() { return this.matchingItems.slice(this.state.page * 5, (this.state.page + 1) * 5); }
    get pageEnd() { return Math.min((this.state.page + 1) * 5, this.matchingItems.length); }

    selectReport(key) { this.state.report = key; this.state.expanded = {}; this.state.screen = "report"; }
    selectPeriod(key) { this.state.period = key; }
    toggleRow(id) { this.state.expanded[id] = !this.state.expanded[id]; }
    openItems() { this.state.screen = "items"; this.state.query = ""; this.state.page = 0; }
    back() { this.state.screen = "report"; }
    search(event) { this.state.query = event.target.value; this.state.page = 0; }
    nextPage() { if (this.pageEnd < this.matchingItems.length) { this.state.page++; } }
    previousPage() { if (this.state.page > 0) { this.state.page--; } }
}

registry.category("actions").add("baseer_report_ui_preview", ReportDesignPreview);
