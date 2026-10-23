/** @odoo-module **/

import { destroy, expect, globals, test, withFetch } from "@odoo/hoot";
import { waitUntil } from "@odoo/hoot-dom";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { registry } from "@web/core/registry";
import { ConnectionLostError } from "@web/core/network/rpc";
import { user } from "@web/core/user";
import { clearRegistry, mountWithCleanup, patchWithCleanup } from "@web/../tests/web_test_helpers";
import { BaseerOperationsPreview, buildOwnerTable, prepareOperationsSnapshot } from "@baseer_operations_report/operations";

defineMailModels();

function ownerSnapshot(companyId = 1, sales = "115.00") {
    return {
        company_id: companyId, complete: true, currency_code: "SAR",
        title: "ملخص المبيعات والمدفوعات", basis: "Recorded sales include uncollected sales.",
        period_controls: { anchor_date: "2026-10-22", options: [{ kind: "month", display_label: "Month" }] }, comparison_controls: {}, periods: [{
            key: "current", label: "October", display_label: "October 2026",
            date_from: "2026-10-01", date_to: "2026-10-31", has_unclassified_outflows: true,
            totals: [
                { key: "incoming_total", label: "Sales", amount: sales, negative: false },
                { key: "cash_total", label: "Actual payments", amount: "20.00", negative: false },
                { key: "difference", label: "Sales less payments", amount: "95.00", negative: false },
            ],
            channels: [{ key: "cash", label: "Cash", amount: "57.50", negative: false, percentage: "50.00%" }],
            outflows: [{ key: "purchase:1/2", label: "Purchases", amount: "20.00", negative: false,
                rows: [{ key: "purchase:1/2", label: "Food / Vegetables", amount: "20.00", negative: false }] }],
        }],
    };
}

function ownerSnapshotWithComparison() {
    const snapshot = ownerSnapshot();
    snapshot.periods.push({
        key: "previous", label: "September", display_label: "September 2026",
        date_from: "2026-09-01", date_to: "2026-09-30", has_unclassified_outflows: false,
        totals: [
            { key: "incoming_total", label: "Sales", amount: "90.00", negative: false },
            { key: "cash_total", label: "Actual payments", amount: "10.00", negative: false },
            { key: "difference", label: "Sales less payments", amount: "80.00", negative: false },
        ],
        channels: [{ key: "card", label: "Card", amount: "90.00", negative: false, percentage: "100.00%" }],
        outflows: [{ key: "operating:9", label: "Operating", amount: "10.00", negative: false,
            rows: [{ key: "electricity:9", label: "Electricity", amount: "10.00", negative: false }] }],
    });
    return snapshot;
}

test("owner summary preserves server amounts and percentage strings", () => {
    const output = prepareOperationsSnapshot(ownerSnapshot(), "Baseer", false);
    const period = output.periods[0];
    const table = buildOwnerTable(output.periods);
    expect(output.complete).toBe(true);
    expect(table.sections[0].amounts.current.amount).toBe("115.00");
    expect(period.channels[0].percentage).toBe("50.00%");
    expect(period.outflows[0].rows[0].amount).toBe("20.00");
    expect(table.difference.amounts.current.amount).toBe("95.00");
    expect(period.has_unclassified_outflows).toBe(true);
});

test("owner table unions stable rows in first-seen server order without values for absent periods", () => {
    const table = buildOwnerTable(prepareOperationsSnapshot(ownerSnapshotWithComparison(), "Baseer", false).periods);
    expect(table.sections.map((row) => row.key)).toEqual(["total:incoming_total", "total:cash_total"]);
    expect(table.sections[0].children.map((row) => row.key)).toEqual(["channel:cash", "channel:card"]);
    expect(table.sections[1].children.map((row) => row.key)).toEqual(["outflow:purchase:1/2", "outflow:operating:9"]);
    expect(table.sections[0].children[0].amounts.current.amount).toBe("57.50");
    expect(table.sections[0].children[0].amounts.previous).toBe(undefined);
    expect(table.sections[1].children[1].children[0].key).toBe("outflow:operating:9:electricity:9");
    expect(table.difference.amounts.previous.amount).toBe("80.00");
});

test("owner summary rejects missing values and incomplete leaked amounts", () => {
    const missingTotal = ownerSnapshot();
    missingTotal.periods[0].totals.pop();
    expect(() => prepareOperationsSnapshot(missingTotal, "Baseer", false)).toThrow();
    const incomplete = { ...ownerSnapshot(), complete: false,
        periods: [{ key: "current", label: "October", display_label: "October",
            date_from: "2026-10-01", date_to: "2026-10-31", totals: [] }] };
    expect(() => prepareOperationsSnapshot(incomplete, "Baseer", false)).toThrow();
});

function deferred() {
    let resolve, reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    return { promise, resolve, reject };
}

function loadingContext(companyId = 1) {
    return { default_company_id: companyId, companies: [{ id: companyId, name: "Synthetic company" }],
        journals: [], default_filters: { company_id: companyId,
            period: { kind: "month", anchor_date: "2026-10-22", direction: 0 },
            comparison: { kind: "none", order: "descending" }, journal_ids: [] } };
}

async function loadingTemplates() {
    const paths = ["/baseer_operations_report/static/src/operations.xml",
        "/baseer_reports_menu/static/src/report_selector.xml"];
    const templates = await Promise.all(paths.map(async (path) => {
        const response = await withFetch(globals.fetch, () => fetch(path));
        expect(response.ok).toBe(true);
        return (await response.text()).replace(/<\?xml[^>]*>/, "")
            .replace(/<templates[^>]*>/, "").replace("</templates>", "");
    }));
    return "<templates>" + templates.join("") + "</templates>";
}

async function mountLoadingReport(call) {
    patchWithCleanup(user, { lang: "ar_001", activeCompany: { id: 1 }, hasGroup: async () => true });
    const services = registry.category("services");
    const required = new Map();
    const keep = (name) => {
        if (required.has(name)) { return; }
        const service = services.get(name);
        required.set(name, service);
        for (const dependency of service.dependencies || []) { keep(dependency); }
    };
    for (const name of ["localization", "ui", "hotkey", "popover", "bottom_sheet"]) { keep(name); }
    clearRegistry(services);
    clearRegistry(registry.category("main_components"));
    for (const [name, service] of required) { services.add(name, service); }
    services.add("orm", { start: () => ({ call: (model, method, ...args) => {
        if (!((model === "baseer.profit.loss.report" && method === "get_context") ||
            (model === "baseer.operations.report" && method === "get_owner_snapshot") ||
            (model === "baseer.operations.report" && method === "action_print_owner"))) {
            throw new Error(`Unexpected report RPC: ${model}.${method}`);
        }
        return call(model, method, ...args);
    } }) });
    services.add("action", { start: () => ({ doAction: async () => {} }) });
    const component = await mountWithCleanup(BaseerOperationsPreview, { templates: await loadingTemplates(), props: {} });
    return { component, destroy: () => destroy(component.__owl__.app) };
}

test("owner summary mounts loading then renders server strings without detail RPCs", async () => {
    const context = deferred(), snapshot = deferred();
    const calls = [];
    const { component } = await mountLoadingReport((_model, method) => {
        calls.push(method);
        if (method === "get_context") { return context.promise; }
        if (method === "get_owner_snapshot") { return snapshot.promise; }
        throw new Error("Unexpected RPC");
    });
    expect(document.querySelector(".o_baseer_go_report").getAttribute("dir")).toBe("rtl");
    expect(document.querySelector(".o_baseer_go_report [role='status']").textContent).toBe(component.labels.loading);
    context.resolve(loadingContext());
    await waitUntil(() => calls.includes("get_owner_snapshot"));
    component.apply();
    expect(calls).toEqual(["get_context", "get_owner_snapshot"]);
    snapshot.resolve(ownerSnapshotWithComparison());
    await waitUntil(() => document.querySelector(".o_baseer_owner_difference strong"));
    expect(document.querySelectorAll(".o_baseer_owner_table thead .is-number").length).toBe(4);
    expect(document.querySelector(".o_baseer_owner_section strong").textContent).toBe("115.00");
    expect(document.querySelector(".o_baseer_owner_percentage").textContent).toBe("50.00%");
    expect(document.querySelector(".o_baseer_owner_unclassified").textContent).toBe(component.labels.unclassified);
    expect(document.querySelector(".o_baseer_owner_difference strong").textContent).toBe("95.00");
    expect(document.querySelectorAll(".o_baseer_owner_absent").length).toBeGreaterThan(0);
    const groupToggle = document.querySelector('.o_baseer_owner_group button[aria-label="Purchases"]');
    expect(groupToggle.getAttribute("aria-expanded")).toBe("false");
    groupToggle.click();
    await waitUntil(() => groupToggle.getAttribute("aria-expanded") === "true");
    expect([...document.querySelectorAll(".o_baseer_owner_detail")].some((node) =>
        node.textContent.includes("Food / Vegetables"))).toBe(true);
    groupToggle.click();
    await waitUntil(() => groupToggle.getAttribute("aria-expanded") === "false");
    expect([...document.querySelectorAll(".o_baseer_owner_detail")].some((node) =>
        node.textContent.includes("Food / Vegetables"))).toBe(false);
    const salesToggle = document.querySelector('.o_baseer_owner_section button[aria-label="Sales"]');
    expect(salesToggle.getAttribute("aria-expanded")).toBe("true");
    salesToggle.click();
    await waitUntil(() => salesToggle.getAttribute("aria-expanded") === "false");
    expect(document.querySelector(".o_baseer_owner_percentage")).toBe(null);
    expect(calls).toEqual(["get_context", "get_owner_snapshot"]);
});

test("Arabic owner totals preserve a negative server string and accessible period navigation", async () => {
    const negative = ownerSnapshot();
    negative.periods[0].totals[2] = {
        key: "difference", label: "الفرق بين المبيعات والمدفوعات", amount: "-40.00", negative: true,
    };
    const { component } = await mountLoadingReport((_model, method) => {
        if (method === "get_context") { return Promise.resolve(loadingContext()); }
        if (method === "get_owner_snapshot") { return Promise.resolve(negative); }
        throw new Error("Unexpected RPC");
    });
    await waitUntil(() => document.querySelector(".o_baseer_owner_difference strong"));
    const difference = document.querySelector(".o_baseer_owner_difference strong");
    expect(difference.textContent).toBe("-40.00");
    expect(difference.classList.contains("o_baseer_report_amount")).toBe(true);
    expect(difference.classList.contains("is-negative")).toBe(true);
    expect(document.querySelector(".o_baseer_owner_percentage").classList.contains("o_baseer_report_amount")).toBe(true);
    const periodButton = document.querySelector('button[aria-label="الفترة"]');
    expect(periodButton).not.toBe(null);
    periodButton.click();
    await waitUntil(() => document.querySelector('button[aria-label="السابق شهر"]'));
    expect(document.querySelector('button[aria-label="التالي شهر"]')).not.toBe(null);
    expect(component.labels.previous).toBe("السابق");
});

test("owner summary retries one transport failure without duplicate request", async () => {
    const retry = deferred();
    let calls = 0;
    const { component } = await mountLoadingReport((_model, method) => {
        if (method === "get_context") { return Promise.resolve(loadingContext()); }
        if (method === "get_owner_snapshot") {
            calls++;
            return calls === 1 ? Promise.reject(new ConnectionLostError("/summary")) : retry.promise;
        }
        throw new Error("Unexpected RPC");
    });
    await waitUntil(() => document.querySelector(".o_baseer_go_report [role='alert'] button"));
    document.querySelector(".o_baseer_go_report [role='alert'] button").click();
    expect(calls).toBe(2);
    component.apply();
    expect(calls).toBe(2);
    retry.resolve(ownerSnapshot());
    await waitUntil(() => document.querySelector(".o_baseer_owner_difference strong"));
});

test("company changes fence late owner snapshots", async () => {
    const pending = new Map();
    const { component } = await mountLoadingReport((_model, method, args) => {
        if (method === "get_context") { return Promise.resolve(loadingContext(args[0])); }
        if (method === "get_owner_snapshot") {
            const request = deferred();
            pending.set(args[0].company_id, request);
            return request.promise;
        }
        throw new Error("Unexpected RPC");
    });
    await waitUntil(() => pending.has(1));
    patchWithCleanup(user, { activeCompany: { id: 2 } });
    component.refreshActiveCompany();
    await waitUntil(() => pending.has(2));
    pending.get(2).resolve(ownerSnapshot(2, "222.00"));
    await waitUntil(() => component.state.report !== null);
    pending.get(1).resolve(ownerSnapshot(1, "111.00"));
    await Promise.resolve(); await Promise.resolve();
    expect(component.ownerTable.sections[0].amounts.current.amount).toBe("222.00");
    expect(component.appliedFilters.company_id).toBe(2);
});

test("owner PDF request sends only active server filters to its new action", async () => {
    let printArgs;
    const { component } = await mountLoadingReport((_model, method, args) => {
        if (method === "get_context") { return Promise.resolve(loadingContext()); }
        if (method === "get_owner_snapshot") { return Promise.resolve(ownerSnapshot()); }
        if (method === "action_print_owner") { printArgs = args[0]; return Promise.resolve({ type: "ir.actions.report" }); }
        throw new Error("Unexpected RPC");
    });
    await waitUntil(() => component.state.report !== null);
    await component.printReport();
    expect(printArgs.company_id).toBe(1);
    expect("totals" in printArgs).toBe(false);
    expect("periods" in printArgs).toBe(false);
});

test("incomplete owner source never leaves an old financial display", async () => {
    const { component } = await mountLoadingReport((_model, method) => {
        if (method === "get_context") { return Promise.resolve(loadingContext()); }
        if (method === "get_owner_snapshot") {
            return Promise.resolve({ ...ownerSnapshot(), complete: false, periods: [{ key: "current", label: "October",
                display_label: "October", date_from: "2026-10-01", date_to: "2026-10-31" }] });
        }
        throw new Error("Unexpected RPC");
    });
    await waitUntil(() => component.state.incomplete);
    expect(component.state.report).toBe(null);
    expect(document.querySelector(".o_baseer_owner_summary")).toBe(null);
    expect(document.querySelector(".o_baseer_go_incomplete").textContent).toBe(component.labels.incomplete);
});

test("leaving owner summary fences a late response", async () => {
    const snapshot = deferred();
    const { component, destroy } = await mountLoadingReport((_model, method) => {
        if (method === "get_context") { return Promise.resolve(loadingContext()); }
        if (method === "get_owner_snapshot") { return snapshot.promise; }
        throw new Error("Unexpected RPC");
    });
    await waitUntil(() => component.state.loading);
    destroy();
    snapshot.resolve(ownerSnapshot());
    await Promise.resolve(); await Promise.resolve();
    expect(component.disposed).toBe(true);
    expect(component.state.report).toBe(null);
});
