/** @odoo-module **/

import { BaseerProfitLossReport } from "@baseer_profit_loss_report/profit_loss";
import { onWillDestroy } from "@odoo/owl";
import { ConnectionLostError } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";

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
        if (!Array.isArray(totals) || totals.length !== TOTAL_KEYS.length ||
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
        this.state.incomplete = false;
        this.state.incompletePeriod = null;
        this.state.incompleteControls = null;
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
