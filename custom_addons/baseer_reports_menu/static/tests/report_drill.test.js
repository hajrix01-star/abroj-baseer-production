/** @odoo-module **/
import { Component, useState, xml } from "@odoo/owl";
import { expect, globals, test, withFetch } from "@odoo/hoot";
import { click, waitUntil } from "@odoo/hoot-dom";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { mockService, mountWithCleanup, patchWithCleanup } from "@web/../tests/web_test_helpers";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { AmountDetailsDialog, ReportDrillDialog, useReportDrill } from "@baseer_reports_menu/report_drill";

defineMailModels();
const selector = { kind: "summary", measure: "closing" };
const result = { title: "الرصيد", value: "125.00", basis: "مجموع المكونات", page: 1, page_size: 50, total_count: 1,
    columns: [{ key: "label", label: "المصدر" }, { key: "amount", label: "المبلغ", numeric: true }],
    rows: [{ key: 1, cells: { label: "قيد", amount: "125.00" }, source: { kind: "source", line_id: 9, parent: selector } }] };
function context(call) {
    const component = Object.create(ReportDrillDialog.prototype);
    const actions = [], closed = [];
    Object.assign(component, { props: { reportKey: "activity", filters: { company_id: 7 }, selector, lang: "ar", close: () => closed.push(true) },
        state: { data: null, busy: false, error: "", history: [], selector, page: 1 }, epoch: 0, alive: true,
        orm: { call }, action: { doAction: async (action) => actions.push(action) } });
    return { component, actions, closed };
}

test("details ignore late responses and use authoritative value, never add displayed cells", async () => {
    patchWithCleanup(user, { activeCompany: { id: 7 } });
    const pending = [];
    const { component } = context(() => new Promise((resolve) => pending.push(resolve)));
    const first = component.load();
    component.state.selector = { kind: "summary", measure: "debit" };
    const second = component.load();
    pending[1]({ ...result, value: "999.99" }); await second;
    pending[0](result); await first;
    expect(component.state.data.value).toBe("999.99");
    expect(component.state.busy).toBe(false);
});

test("details block stale-company source actions and failures allow retry", async () => {
    patchWithCleanup(user, { activeCompany: { id: 7 } });
    let fail = true, calls = 0;
    const { component, actions, closed } = context(async () => { calls++; if (fail) { throw new Error("private details"); } return result; });
    await component.load();
    expect(component.state.error).toBe(component.labels.error);
    expect(component.state.error.includes("private details")).toBe(false);
    fail = false; await component.load();
    expect(component.state.data).toEqual(result);
    patchWithCleanup(user, { activeCompany: { id: 8 } });
    await component.activate(result.rows[0]);
    await component.load();
    expect(actions).toEqual([]);
    expect(calls).toBe(2);
    expect(closed).toEqual([true]);
});

test("component navigation keeps its selector and page and source action rechecks server", async () => {
    patchWithCleanup(user, { activeCompany: { id: 7 } });
    const calls = [];
    const { component, actions } = context(async (...args) => { calls.push(args); return args[1] === "open_source" ? { type: "ir.actions.act_window" } : result; });
    await component.activate({ drill: { kind: "line", line_id: 3, measure: "running" } });
    expect(component.state.history.length).toBe(1);
    await component.back();
    expect(component.state.selector).toEqual(selector);
    await component.activate(result.rows[0]);
    expect(calls.at(-1)[1]).toBe("open_source");
    expect(calls.at(-1)[2][2]).toEqual(result.rows[0].source);
    expect(actions.length).toBe(1);
});

test("shared hook captures applied filters before later edits", async () => {
    patchWithCleanup(user, { activeCompany: { id: 7 } });
    const dialogs = [];
    mockService("dialog", { add: (Class, props) => dialogs.push([Class, props]) });
    class Launcher extends Component {
        static template = xml`<button t-on-click="() => this.drill.open({kind: 'summary', measure: 'closing'})">Open</button>`;
        static props = ["*"];
        setup() { this.filters = { company_id: 7, date_to: "2026-01-31" }; this.drill = useReportDrill("activity", () => this.filters, () => "ar"); }
    }
    const launcher = await mountWithCleanup(Launcher);
    await click("button");
    launcher.filters.date_to = "2026-02-28";
    expect(dialogs[0][0]).toBe(ReportDrillDialog);
    expect(dialogs[0][1].filters.date_to).toBe("2026-01-31");
});

test("shared detail dialog renders Arabic server values, clickable sources and no HTML injection", async () => {
    patchWithCleanup(user, { activeCompany: { id: 7 } });
    mockService("orm", { call: async () => ({ ...result, title: "<img src=x>", rows: result.rows }) });
    const response = await withFetch(globals.fetch, () => fetch("/baseer_reports_menu/static/src/report_drill.xml"));
    expect(response.ok).toBe(true);
    class Launcher extends Component {
        static template = xml`<button id="open-real-detail" t-on-click="() => this.drill.open({kind: 'summary', measure: 'closing'})">Open</button>`;
        static props = ["*"];
        setup() { this.drill = useReportDrill("activity", () => ({ company_id: 7 }), () => "ar"); }
    }
    await mountWithCleanup(Launcher, { templates: await response.text() });
    await click("#open-real-detail");
    await waitUntil(() => document.querySelector(".o_baseer_drill_value"));
    expect(".o_baseer_report_drill").toHaveAttribute("dir", "rtl");
    expect(".o_baseer_drill_value").toHaveText("125.00");
    expect(".o_baseer_drill_table button").toHaveCount(2);
    expect(".o_baseer_report_drill img").toHaveCount(0);
});

test("shared presentation handles loading, retry, changed, empty and paging without altering strings", async () => {
    const response = await withFetch(globals.fetch, () => fetch("/baseer_reports_menu/static/src/report_drill.xml"));
    const calls = [];
    class Launcher extends Component {
        static template = xml`<button id="open-presentation" t-on-click="open">Open</button>`;
        static props = ["*"];
        setup() {
            this.dialog = useService("dialog");
            this.view = useState({ busy: true, error: "", data: null, changedText: "", hasBack: false });
        }
        open() {
            this.dialog.add(AmountDetailsDialog, { view: this.view, lang: "en",
                retry: () => calls.push("retry"), refresh: () => calls.push("refresh"),
                activate: (row) => calls.push(row.source), page: (delta) => calls.push(delta),
                back: () => calls.push("back") });
        }
    }
    const launcher = await mountWithCleanup(Launcher, { templates: await response.text() });
    await click("#open-presentation");
    await waitUntil(() => document.querySelector('.o_baseer_report_drill[aria-busy="true"]'));
    expect(".o_baseer_report_drill").toHaveAttribute("dir", "ltr");
    expect(".o_baseer_report_drill [role='status']").toHaveText("Loading details…");
    Object.assign(launcher.view, { busy: false, error: "Safe error" });
    await waitUntil(() => document.querySelector(".o_baseer_drill_retry"));
    await click(".o_baseer_drill_retry");
    expect(calls).toEqual(["retry"]);
    Object.assign(launcher.view, { error: "", changedText: "Refresh required" });
    await waitUntil(() => document.querySelector(".o_baseer_drill_refresh"));
    await click(".o_baseer_drill_refresh");
    expect(calls).toEqual(["retry", "refresh"]);
    Object.assign(launcher.view, { changedText: "", data: { ...result, value: "−1,234.50", rows: [] } });
    await waitUntil(() => document.querySelector(".o_baseer_drill_empty"));
    expect(".o_baseer_drill_value").toHaveText("−1,234.50");
    expect(".o_baseer_drill_empty").toHaveText("No sources for this value in the selected scope.");
    launcher.view.data = { ...result, total_count: 51 };
    launcher.view.hasBack = true;
    await waitUntil(() => document.querySelector(".o_baseer_drill_next"));
    expect(".o_baseer_drill_count span").toHaveText("51");
    await click(".o_baseer_drill_next");
    await click(".o_baseer_drill_back");
    await click(".o_baseer_drill_table tbody tr:first-child td:first-child button");
    expect(calls).toEqual(["retry", "refresh", 1, "back", result.rows[0].source]);
    await click(".o_baseer_drill_close");
    await waitUntil(() => !document.querySelector(".o_baseer_amount_details_dialog"));
    expect(document.activeElement.id).toBe("open-presentation");
});
