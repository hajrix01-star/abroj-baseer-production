/** @odoo-module **/

import { BaseerProfitLossReport } from "@baseer_profit_loss_report/profit_loss";
import { onWillDestroy, useEffect, useRef } from "@odoo/owl";
import { ConnectionLostError } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { ReportExportButtons } from "@baseer_reports_menu/report_export";

const MODEL = "baseer.operations.report";
const CONTEXT_MODEL = "baseer.profit.loss.report";
const TOTAL_KEYS = ["incoming_total", "cash_total", "difference"];
const labels = {
    ar: {
        title: "ملخص المبيعات والمدفوعات", company: "الشركة", journals: "الدفاتر",
        allJournals: "جميع الدفاتر", selectedJournals: "الدفاتر المختارة",
        incomplete: "لا يمكن عرض أي أرقام قبل التحقق من جميع مصادر الحركة.",
        unclassified: "توجد مدفوعات مثبتة غير مصنفة ضمن المجموع.",
        loading: "جارٍ تحميل الملخص…",
        error: "تعذر عرض الملخص. تحقق من الفترة والصلاحيات ثم أعد المحاولة.",
        connectionError: "تعذر إكمال الاتصال بالخادم. أعد المحاولة.", retry: "إعادة المحاولة",
        channels: "طرق دفع المبيعات", outflows: "المدفوعات حسب الفئة",
        noChannels: "لا توجد طرق دفع مثبتة لهذه الفترة.", noOutflows: "لا توجد مدفوعات مثبتة لهذه الفترة.",
        period: "الفترة", comparison: "المقارنة", month: "شهر", quarter: "ربع سنة",
        fiscalYear: "سنة مالية", customDates: "تواريخ مخصصة", noComparison: "دون مقارنة",
        previousPeriods: "الفترات السابقة", samePeriodLastYear: "الفترة نفسها العام الماضي",
        periods: "فترات", periodOrder: "ترتيب الفترات", descending: "تنازلي", ascending: "تصاعدي",
        previous: "السابق", next: "التالي", from: "من", to: "إلى", current: "الحالية",
        details: "التفاصيل", amount: "المبلغ",
        back: "العودة إلى الملخص", source: "عرض المستند", date: "التاريخ", total: "الإجمالي",
        detailLoading: "جارٍ تحميل العمليات…", noEvents: "لا توجد عمليات لهذا البند في الفترة المحددة.",
        detailError: "تعذر تحميل التفاصيل. تحقق من الاتصال والصلاحيات ثم أعد المحاولة.",
        changed: "تغيرت العمليات منذ عرض الملخص. حدّث الملخص لعرض الأرقام والتفاصيل المتطابقة.",
        refresh: "تحديث الملخص", page: "صفحة", count: "عدد المساهمات",
        allocated: "المبالغ أدناه هي مساهمة كل عملية في البند المختار، وقد تختلف عن إجمالي المستند. في بند الفرق تُعرض المدفوعات بالسالب.",
    },
    en: {
        title: "Sales and Payments Summary", company: "Company", journals: "Journals",
        allJournals: "All journals", selectedJournals: "Selected journals only",
        incomplete: "No amounts can be shown until every movement source is verified.",
        unclassified: "Proven payments are included but remain unclassified.",
        loading: "Loading summary…",
        error: "Could not load the summary. Check the period and access rights, then retry.",
        connectionError: "Could not complete the connection to the server. Retry.", retry: "Retry",
        channels: "Sales payment channels", outflows: "Payments by category",
        noChannels: "No proven payment channels for this period.", noOutflows: "No proven payments for this period.",
        period: "Period", comparison: "Comparison", month: "Month", quarter: "Quarter",
        fiscalYear: "Fiscal year", customDates: "Custom dates", noComparison: "No comparison",
        previousPeriods: "Previous periods", samePeriodLastYear: "Same period last year",
        periods: "Periods", periodOrder: "Period order", descending: "Descending", ascending: "Ascending",
        previous: "Previous", next: "Next", from: "From", to: "To", current: "Current",
        details: "Details", amount: "Amount",
        back: "Back to summary", source: "View document", date: "Date", total: "Total",
        detailLoading: "Loading operations…", noEvents: "No operations for this item in the selected period.",
        detailError: "Could not load details. Check the connection and access rights, then retry.",
        changed: "Operations have changed since the summary was shown. Refresh the summary to see matching amounts and details.",
        refresh: "Refresh summary", page: "Page", count: "Contributions",
        allocated: "Amounts below are each operation’s contribution to the selected item and may differ from the document total. Payments are negative in the difference item.",
    },
};

function text(value) {
    return typeof value === "string" && value.trim() ? value : null;
}

function serverMoney(row) {
    return row && text(row.amount) && typeof row.negative === "boolean";
}

function rows(items, requirePercentage = false) {
    return Array.isArray(items) && items.every((row) => text(row?.key) && text(row?.label) &&
        serverMoney(row) && (!requirePercentage || row.percentage === null || text(row.percentage)));
}

function uniqueKeys(items) {
    return new Set(items.map((item) => item.key)).size === items.length;
}

// This adapter validates shape only. Amounts and percentages remain the exact
// server-formatted strings; the browser never parses or calculates them.
export function prepareOperationsSnapshot(snapshot, companyName, selectedJournals) {
    if (!snapshot || typeof snapshot.complete !== "boolean" || !Array.isArray(snapshot.periods) ||
        !snapshot.periods.length || snapshot.periods.length > 4 || !text(snapshot.currency_code)) {
        throw new Error("Missing owner-summary contract");
    }
    const periodKeys = new Set();
    const periods = snapshot.periods.map((period) => {
        if (!text(period?.key) || periodKeys.has(period.key) || !text(period.label) ||
            !text(period.display_label || period.label) || !text(period.date_from) || !text(period.date_to)) {
            throw new Error("Incomplete owner-summary period");
        }
        periodKeys.add(period.key);
        if (!snapshot.complete) {
            if ("totals" in period || "channels" in period || "outflows" in period) {
                throw new Error("Incomplete owner-summary leaked amounts");
            }
            return { ...period, role: period.key === "current" ? "primary" : "comparison",
                display_label: period.display_label || period.label };
        }
        const totals = period.totals;
        if (!/^[a-f0-9]{64}$/.test(period.revision || "") ||
            !Array.isArray(totals) || totals.length !== TOTAL_KEYS.length ||
            new Set(totals.map((row) => row?.key)).size !== TOTAL_KEYS.length ||
            TOTAL_KEYS.some((key) => !totals.some((row) => row?.key === key && text(row.label) && serverMoney(row))) ||
            !rows(period.channels, true) || !uniqueKeys(period.channels) || !Array.isArray(period.outflows) ||
            !uniqueKeys(period.outflows) ||
            typeof period.has_unclassified_outflows !== "boolean") {
            throw new Error("Incomplete owner-summary values");
        }
        for (const group of period.outflows) {
            if (!text(group?.key) || !text(group?.label) || !serverMoney(group) || !rows(group.rows || []) ||
                !uniqueKeys(group.rows || [])) {
                throw new Error("Incomplete owner-summary outflows");
            }
        }
        return {
            ...period,
            role: period.key === "current" ? "primary" : "comparison",
            display_label: period.display_label || period.label,
        };
    });
    return {
        complete: snapshot.complete,
        title: text(snapshot.title) || "",
        basis: text(snapshot.basis) || "",
        company: { name: companyName, currency_code: snapshot.currency_code },
        period_controls: snapshot.period_controls,
        comparison_controls: snapshot.comparison_controls,
        periods,
        is_partial_journals: selectedJournals,
    };
}

// Presentation-only union. Values are the original server rows: this never
// parses, totals, formats, or substitutes financial values in the browser.
export function buildOwnerTable(periods) {
    const sales = {
        key: "total:incoming_total", kind: "section", label: "", amounts: Object.create(null), children: [],
        emptyLabel: "channels", expandable: true,
    };
    const cash = {
        key: "total:cash_total", kind: "section", label: "", amounts: Object.create(null), children: [],
        emptyLabel: "outflows", expandable: true,
    };
    const difference = { key: "total:difference", kind: "result", label: "", amounts: Object.create(null) };
    const channels = new Map();
    const groups = new Map();

    for (const period of periods) {
        for (const total of period.totals) {
            const target = total.key === "incoming_total" ? sales : total.key === "cash_total" ? cash : difference;
            if (!target.label) { target.label = total.label; }
            target.amounts[period.key] = total;
        }
        for (const channel of period.channels) {
            const key = `channel:${channel.key}`;
            let row = channels.get(key);
            if (!row) {
                row = { key, kind: "channel", label: channel.label, amounts: Object.create(null) };
                channels.set(key, row);
                sales.children.push(row);
            }
            row.amounts[period.key] = channel;
        }
        for (const group of period.outflows) {
            const key = `outflow:${group.key}`;
            let groupRow = groups.get(key);
            if (!groupRow) {
                groupRow = {
                    key, kind: "group", label: group.label, amounts: Object.create(null), children: [], expandable: false,
                };
                groups.set(key, groupRow);
                cash.children.push(groupRow);
            }
            groupRow.amounts[period.key] = group;
            for (const detail of group.rows) {
                const detailKey = `outflow:${group.key}:${detail.key}`;
                let detailRow = groupRow.children.find((row) => row.key === detailKey);
                if (!detailRow) {
                    detailRow = { key: detailKey, kind: "detail", label: detail.label, amounts: Object.create(null) };
                    groupRow.children.push(detailRow);
                }
                groupRow.expandable = true;
                detailRow.amounts[period.key] = detail;
            }
        }
    }
    return { sections: [sales, cash], difference };
}

export class BaseerOperationsPreview extends BaseerProfitLossReport {
    static template = "baseer_operations_report.Preview";
    static components = { ...BaseerProfitLossReport.components, ReportExportButtons };

    setup() {
        super.setup();
        this.state.incomplete = false;
        this.state.incompletePeriod = null;
        this.state.incompleteControls = null;
        this.state.contextReady = false;
        this.resetOwnerExpansion();
        this.contextLoading = false;
        this.snapshotRequest = null;
        this.disposed = false;
        this.state.ownerDetail = null;
        this.detailRequestToken = 0;
        this.reportRoot = useRef("reportRoot");
        this.detailFocusPending = false;
        useEffect(() => {
            if (!this.detailFocusPending) { return; }
            this.detailFocusPending = false;
            const root = this.reportRoot.el;
            if (this.state.ownerDetail) {
                root?.querySelector(".o_baseer_owner_detail_title")?.focus();
            } else if (this.detailReturnTarget) {
                const target = this.detailReturnTarget;
                [...(root?.querySelectorAll("[data-owner-row]") || [])].find((button) =>
                    button.dataset.ownerRow === target.row && button.dataset.ownerPeriod === target.period)?.focus();
            }
        }, () => [this.state.ownerDetail, this.state.ownerDetail?.loading]);
        onWillDestroy(() => {
            this.disposed = true;
            this.requestToken += 1;
            this.companyGeneration += 1;
        });
    }

    // Reuse P&L's setup/bus hooks, but never make its onWillStart await RPC.
    refreshActiveCompany() {
        const companyId = this.activeCompanyId;
        if (this.disposed || (this.contextLoading && this.contextCompanyId === companyId)) { return; }
        this.invalidate();
        this.snapshotRequest = null;
        const generation = ++this.companyGeneration;
        this.state.contextReady = false;
        this.state.filters.company_id = 0;
        this.state.journals = [];
        this.contextLoading = false;
        this.contextCompanyId = companyId;
        if (!companyId) { this.state.error = this.labels.error; return; }
        this.state.loading = true;
        this.contextLoading = true;
        void this.loadCompanyContext(companyId, generation);
    }

    async loadCompanyContext(companyId, generation) {
        try {
            const context = await this.orm.call(CONTEXT_MODEL, "get_context", [companyId]);
            if (this.disposed || generation !== this.companyGeneration || companyId !== this.activeCompanyId) { return; }
            if ((context.default_company_id || context.default_filters?.company_id) !== companyId) {
                throw new Error("Active company mismatch");
            }
            this.installContext(context);
            this.state.contextReady = true;
            await this.apply();
        } catch (error) {
            if (!this.disposed && generation === this.companyGeneration && companyId === this.activeCompanyId) {
                this.state.error = this.reportError(error);
            }
        } finally {
            if (!this.disposed && generation === this.companyGeneration) {
                this.contextLoading = false;
                if (!this.snapshotRequest) { this.state.loading = false; }
            }
        }
    }

    reportError(error) {
        if (typeof error?.data?.message === "string" && error.data.message) { return error.data.message; }
        return error instanceof ConnectionLostError ? this.labels.connectionError : this.labels.error;
    }

    retryLoad() {
        if (this.disposed || this.state.loading) { return; }
        if (!this.state.contextReady) { this.refreshActiveCompany(); return; }
        return this.apply();
    }

    get labels() { return labels[this.lang]; }
    get periodSummary() { return this.state.incompletePeriod?.display_label || super.periodSummary; }
    get periodOptions() { return this.state.incompleteControls?.options || super.periodOptions; }
    get ownerTable() { return buildOwnerTable(this.state.report?.periods || []); }
    get hasUnclassifiedOutflows() {
        return this.state.report?.periods.some((period) => period.has_unclassified_outflows) || false;
    }

    resetOwnerExpansion() {
        this.state.ownerExpanded = { "total:incoming_total": true, "total:cash_total": true };
    }

    isOwnerExpanded(row) { return !!this.state.ownerExpanded[row.key]; }

    toggleOwnerRow(row) {
        if (this.state.loading || !row.expandable) { return; }
        this.state.ownerExpanded[row.key] = !this.state.ownerExpanded[row.key];
    }

    ownerValue(row, periodKey) { return row.amounts[periodKey] || null; }

    ownerAmountClass(value, percentage = false) {
        return `${percentage ? "o_baseer_owner_percentage " : ""}o_baseer_report_amount${value?.negative ? " is-negative" : ""}`;
    }

    ownerRowClass(row) {
        if (row.kind === "section") { return "o_baseer_pl_section o_baseer_owner_section"; }
        if (row.kind === "group") { return "o_baseer_pl_account o_baseer_pl_subtotal o_baseer_owner_group"; }
        return "o_baseer_pl_channel o_baseer_owner_detail";
    }

    installContext(context) {
        super.installContext(context);
        this.companyName = (context.companies || []).find(
            (company) => company.id === this.activeCompanyId)?.name || "";
    }

    invalidate() {
        super.invalidate();
        this.detailRequestToken = (this.detailRequestToken || 0) + 1;
        this.state.ownerDetail = null;
        this.state.incomplete = false;
        this.state.incompletePeriod = null;
        this.state.incompleteControls = null;
    }

    openOwnerDetails(row, periodKey = null) {
        if (!this.appliedFilters || this.state.loading || !this.state.report?.complete) { return; }
        // Labels prefer the current period, then the first column containing
        // this row. Each amount always selects its own column, never a guess.
        const period = periodKey ? this.reportPeriods.find((item) => item.key === periodKey) :
            this.reportPeriods.find((item) => item.key === "current" && row.amounts[item.key]) ||
            this.reportPeriods.find((item) => row.amounts[item.key]);
        if (!period || !row.amounts[period.key]) { return; }
        if (this.state.ownerDetail?.rowKey === row.key &&
            this.state.ownerDetail?.periodKey === period.key && this.state.ownerDetail.loading) { return; }
        this.detailReturnTarget = { row: row.key, period: periodKey || "" };
        this.detailFocusPending = true;
        this.state.ownerDetail = { rowKey: row.key, periodKey: period.key, revision: period.revision,
            label: row.label, periodLabel: period.display_label || period.label,
            expectedAmount: row.amounts[period.key].amount, expectedNegative: row.amounts[period.key].negative,
            page: 1, loading: false, changed: false, error: "", data: null, opening: false };
        return this.loadOwnerDetails(1);
    }

    closeOwnerDetails() {
        this.detailRequestToken += 1;
        this.detailFocusPending = true;
        this.state.ownerDetail = null;
    }

    async loadOwnerDetails(page) {
        const detail = this.state.ownerDetail;
        if (!detail || detail.loading || detail.changed || !this.appliedFilters) { return; }
        const token = ++this.detailRequestToken;
        const reportToken = this.requestToken;
        const companyId = this.activeCompanyId;
        const current = () => !this.disposed && token === this.detailRequestToken &&
            reportToken === this.requestToken && companyId === this.activeCompanyId;
        this.detailFocusPending = true;
        detail.loading = true;
        detail.error = "";
        detail.data = null;
        detail.page = page;
        try {
            const result = await this.orm.call(MODEL, "get_owner_details", [this.appliedFilters,
                detail.rowKey, detail.periodKey, detail.revision, page]);
            if (!current()) { return; }
            if (result?.changed === true) { detail.changed = true; return; }
            if (!result || result.changed !== false || result.company_id !== companyId ||
                result.row_key !== detail.rowKey || result.period_key !== detail.periodKey ||
                result.revision !== detail.revision || result.page !== page || result.page_size !== 50 ||
                !Number.isSafeInteger(result.total_count) || result.total_count < 0 ||
                !serverMoney(result) || !text(result.label) || !text(result.period_label) ||
                !Array.isArray(result.events) || result.events.length > 50 ||
                !uniqueKeys(result.events.map((event) => ({ key: event.event_key }))) ||
                !result.events.every((event) => /^[a-f0-9]{64}$/.test(event.event_key || "") &&
                    text(event.label) && /^\d{4}-\d{2}-\d{2}$/.test(event.date || "") && serverMoney(event))) {
                throw new Error("Unexpected owner-detail contract");
            }
            // String equality is a consistency guard, never browser arithmetic.
            if (result.amount !== detail.expectedAmount || result.negative !== detail.expectedNegative) {
                detail.changed = true;
                return;
            }
            detail.data = result;
        } catch (_error) {
            if (current()) { detail.error = this.labels.detailError; }
        } finally {
            if (current()) { detail.loading = false; }
        }
    }

    async openOwnerSource(event) {
        const detail = this.state.ownerDetail;
        if (!detail?.data || detail.loading || detail.opening || detail.changed || !this.appliedFilters) { return; }
        const token = this.detailRequestToken;
        const reportToken = this.requestToken;
        const companyId = this.activeCompanyId;
        const current = () => !this.disposed && token === this.detailRequestToken &&
            reportToken === this.requestToken && companyId === this.activeCompanyId;
        detail.opening = true;
        detail.error = "";
        try {
            const action = await this.orm.call(MODEL, "action_owner_source", [this.appliedFilters,
                detail.rowKey, detail.periodKey, detail.revision, event.event_key]);
            if (!current()) { return; }
            if (action?.changed === true) {
                detail.changed = true;
                detail.data = null;
                return;
            }
            await this.env.services.action.doAction(action);
        } catch (_error) {
            if (current()) { detail.error = this.labels.detailError; detail.data = null; }
        } finally {
            if (current()) { detail.opening = false; }
        }
    }

    apply(direction = 0) {
        if (this.disposed || !this.state.contextReady) { return; }
        const filters = this.cloneFilters(direction);
        const key = JSON.stringify([this.companyGeneration, filters]);
        if (this.snapshotRequest?.key === key) { return this.snapshotRequest.promise; }
        const request = { key };
        this.snapshotRequest = request;
        request.promise = this.loadSnapshot(filters, request);
        return request.promise;
    }

    async loadSnapshot(filters, request) {
        this.invalidate();
        const token = this.requestToken;
        const generation = this.companyGeneration;
        const companyId = this.activeCompanyId;
        this.state.loading = true;
        try {
            const snapshot = await this.orm.call(MODEL, "get_owner_snapshot", [filters]);
            if (token !== this.requestToken || generation !== this.companyGeneration || companyId !== this.activeCompanyId) { return; }
            if (snapshot.company_id !== companyId || typeof snapshot.complete !== "boolean") {
                throw new Error("Unexpected owner-summary contract");
            }
            if (snapshot.period_controls?.anchor_date) {
                this.state.filters.period.anchor_date = snapshot.period_controls.anchor_date;
            }
            this.state.filters.period.direction = 0;
            const prepared = prepareOperationsSnapshot(snapshot, this.companyName || "", !!filters.journal_ids.length);
            if (!prepared.complete) {
                this.state.incomplete = true;
                this.state.incompleteControls = prepared.period_controls || null;
                this.state.incompletePeriod = prepared.periods.find((period) => period.role === "primary") || prepared.periods[0] || null;
                if (this.state.incompletePeriod) {
                    this.state.filters.period.date_from = this.state.incompletePeriod.date_from;
                    this.state.filters.period.date_to = this.state.incompletePeriod.date_to;
                }
                this.state.report = null;
                this.appliedFilters = null;
                return;
            }
            this.state.report = prepared;
            this.resetOwnerExpansion();
            this.appliedFilters = this.cloneFilters();
        } catch (error) {
            if (token === this.requestToken && generation === this.companyGeneration) {
                this.state.error = this.reportError(error);
            }
        } finally {
            if (token === this.requestToken && generation === this.companyGeneration) { this.state.loading = false; }
            if (this.snapshotRequest === request) { this.snapshotRequest = null; }
        }
    }

    async printReport() {
        if (!this.appliedFilters || !this.state.report?.complete || this.state.loading || this.state.printing) { return; }
        const token = this.requestToken;
        const generation = this.companyGeneration;
        const companyId = this.activeCompanyId;
        this.state.printing = true;
        try {
            const action = await this.orm.call(MODEL, "action_print_owner", [{ ...this.appliedFilters, company_id: companyId }]);
            if (token === this.requestToken && generation === this.companyGeneration && companyId === this.activeCompanyId) {
                await this.env.services.action.doAction(action);
            }
        } catch (error) {
            if (token === this.requestToken && generation === this.companyGeneration) {
                this.state.error = this.reportError(error);
            }
        } finally {
            if (token === this.requestToken && generation === this.companyGeneration) { this.state.printing = false; }
        }
    }
}

registry.category("baseer_reports").add("operations_gross", {
    key: "operations_gross", label: { ar: "ملخص المبيعات والمدفوعات", en: "Sales and Payments Summary" },
    sequence: 45, kind: "component", component: BaseerOperationsPreview,
    groups: ["account.group_account_readonly", "account.group_account_user", "account.group_account_manager"],
});
