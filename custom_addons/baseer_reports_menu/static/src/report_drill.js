/** @odoo-module **/
import { Component, onMounted, onWillUnmount, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useBus, useService } from "@web/core/utils/hooks";
import { user, userBus } from "@web/core/user";

const COPY = {
    ar: { title: "تفاصيل المبلغ", loading: "جارٍ تحميل التفاصيل…", error: "تعذر عرض التفاصيل. تحقق من الفترة والصلاحيات، وجرّب فترة أقصر ثم أعد المحاولة.",
        empty: "لا توجد مصادر لهذه القيمة ضمن النطاق المحدد.", retry: "إعادة المحاولة", back: "رجوع", previous: "السابق", next: "التالي", close: "إغلاق", source: "عرض المصدر",
        current: "تفاصيل حالية وفق فلاتر التقرير المختارة؛ قد تتغير بعد التصحيحات أو الترحيل.", page: "صفحة", refresh: "تحديث التقرير", count: "عدد البنود" },
    en: { title: "Amount details", loading: "Loading details…", error: "Could not load details. Check the period and access, try a shorter period, then retry.",
        empty: "No sources for this value in the selected scope.", retry: "Retry", back: "Back", previous: "Previous", next: "Next", close: "Close", source: "View source",
        current: "Current details under the selected report filters; corrections or posting may change them.", page: "Page", refresh: "Refresh report", count: "Items" },
};
const clone = (value) => JSON.parse(JSON.stringify(value));

// Presentation only: controllers retain authorization, revision and request
// guards. Amounts are already formatted by the server, never calculated here.
export class AmountDetailsDialog extends Component {
    static template = "baseer_reports_menu.AmountDetailsDialog";
    static components = { Dialog };
    static props = {
        view: Object, lang: String, close: Function, retry: Function,
        activate: Function, page: Function,
        back: { type: Function, optional: true },
        refresh: { type: Function, optional: true },
    };
    get labels() { return COPY[this.props.lang === "ar" ? "ar" : "en"]; }
}

export class ReportDrillDialog extends Component {
    static template = "baseer_reports_menu.DrillDialog";
    static components = { AmountDetailsDialog };
    static props = { reportKey: String, filters: Object, selector: Object, lang: String, close: Function };
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ data: null, busy: false, error: "", history: [], selector: clone(this.props.selector), page: 1 });
        this.epoch = 0;
        this.alive = true;
        useBus(userBus, "ACTIVE_COMPANIES_CHANGED", () => { this.epoch++; this.props.close(); });
        onWillUnmount(() => { this.alive = false; this.epoch++; });
        onMounted(() => this.load());
    }
    get labels() { return COPY[this.props.lang === "ar" ? "ar" : "en"]; }
    get view() {
        return { data: this.state.data, busy: this.state.busy, error: this.state.error,
            hasBack: this.state.history.length > 0 };
    }
    get sameCompany() { return this.props.filters.company_id === Number(user.activeCompany?.id); }
    async load() {
        if (!this.sameCompany) { this.props.close(); return; }
        const epoch = ++this.epoch;
        this.state.busy = true;
        this.state.error = "";
        this.state.data = null;
        try {
            const data = await this.orm.call("baseer.report.drill", "get_drilldown", [
                this.props.reportKey, this.props.filters, clone(this.state.selector), this.state.page,
            ]);
            if (this.alive && epoch === this.epoch && this.sameCompany) { this.state.data = data; }
        } catch {
            if (this.alive && epoch === this.epoch) { this.state.error = this.labels.error; }
        } finally {
            if (this.alive && epoch === this.epoch) { this.state.busy = false; }
        }
    }
    async activate(row) {
        if (this.state.busy || !this.sameCompany) { return; }
        if (row.drill) {
            this.state.history.push({ selector: clone(this.state.selector), page: this.state.page });
            this.state.selector = clone(row.drill);
            this.state.page = 1;
            return this.load();
        }
        if (!row.source) { return; }
        const epoch = ++this.epoch;
        this.state.busy = true;
        this.state.error = "";
        try {
            const action = await this.orm.call("baseer.report.drill", "open_source", [this.props.reportKey, this.props.filters, clone(row.source)]);
            if (this.alive && epoch === this.epoch && this.sameCompany) {
                await this.action.doAction(action);
                this.props.close();
            }
        } catch {
            if (this.alive && epoch === this.epoch) { this.state.error = this.labels.error; }
        } finally {
            if (this.alive && epoch === this.epoch) { this.state.busy = false; }
        }
    }
    back() {
        if (this.state.busy || !this.state.history.length) { return; }
        const prior = this.state.history.pop();
        this.state.selector = prior.selector;
        this.state.page = prior.page;
        return this.load();
    }
    page(delta) { if (!this.state.busy) { this.state.page += delta; return this.load(); } }
}

export function useReportDrill(reportKey, getFilters, getLang) {
    const dialog = useService("dialog");
    const orm = useService("orm");
    const action = useService("action");
    const notification = useService("notification");
    let busy = false;
    return {
        open(selector) {
            const filters = getFilters();
            if (!filters || filters.company_id !== Number(user.activeCompany?.id)) { return; }
            dialog.add(ReportDrillDialog, { reportKey, filters: clone(filters), selector: clone(selector), lang: getLang() });
        },
        async openSource(selector) {
            const filters = getFilters();
            if (busy || !filters || filters.company_id !== Number(user.activeCompany?.id)) { return; }
            const captured = clone(filters);
            busy = true;
            try {
                const result = await orm.call("baseer.report.drill", "open_source", [reportKey, captured, clone(selector)]);
                if (captured.company_id === Number(user.activeCompany?.id)) { await action.doAction(result); }
            } catch {
                notification.add(COPY[getLang() === "ar" ? "ar" : "en"].error, { type: "danger" });
            } finally { busy = false; }
        },
    };
}
