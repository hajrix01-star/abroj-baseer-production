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
            key: "current", revision: "a".repeat(64), label: "October", display_label: "October 2026",
            date_from: "2026-10-01", date_to: "2026-10-31", has_unclassified_outflows: true,
            totals: [
                { key: "incoming_total", label: "Sales", amount: sales, negative: false },
                { key: "cash_total", label: "Actual payments", amount: "20.00", negative: false },
                { key: "difference", label: "Sales less payments", amount: "95.00", negative: false },
            ],
            channels: [{ key: "cccccccccccccccccccc", label: "Cash", amount: "57.50", negative: false, percentage: "50.00%" }],
            outflows: [{ key: "purchase", label: "Purchases", amount: "20.00", negative: false,
                rows: [{ key: "dddddddddddddddddddd", label: "Food / Vegetables", amount: "20.00", negative: false }] }],
        }],
    };
}

function ownerSnapshotWithComparison() {
    const snapshot = ownerSnapshot();
    snapshot.periods.push({
        key: "previous", revision: "b".repeat(64), label: "September", display_label: "September 2026",
        date_from: "2026-09-01", date_to: "2026-09-30", has_unclassified_outflows: false,
        totals: [
            { key: "incoming_total", label: "Sales", amount: "90.00", negative: false },
            { key: "cash_total", label: "Actual payments", amount: "10.00", negative: false },
            { key: "difference", label: "Sales less payments", amount: "80.00", negative: false },
        ],
        channels: [{ key: "aaaaaaaaaaaaaaaaaaaa", label: "Card", amount: "90.00", negative: false, percentage: "100.00%" }],
        outflows: [{ key: "operating_account", label: "Operating", amount: "10.00", negative: false,
            rows: [{ key: "eeeeeeeeeeeeeeeeeeee", label: "Electricity", amount: "10.00", negative: false }] }],
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
    expect(table.sections[0].children.map((row) => row.key)).toEqual(["channel:cccccccccccccccccccc", "channel:aaaaaaaaaaaaaaaaaaaa"]);
    expect(table.sections[1].children.map((row) => row.key)).toEqual(["outflow:purchase", "outflow:operating_account"]);
    expect(table.sections[0].children[0].amounts.current.amount).toBe("57.50");
    expect(table.sections[0].children[0].amounts.previous).toBe(undefined);
    expect(table.sections[1].children[1].children[0].key).toBe("outflow:operating_account:eeeeeeeeeeeeeeeeeeee");
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

async function mountLoadingReport(call, doAction = async () => {}) {
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
            (model === "baseer.operations.report" && method === "get_owner_details") ||
            (model === "baseer.operations.report" && method === "action_owner_source") ||
            (model === "baseer.operations.report" && method === "action_print_owner"))) {
            throw new Error(`Unexpected report RPC: ${model}.${method}`);
        }
        return call(model, method, ...args);
    } }) });
    services.add("action", { start: () => ({ doAction }) });
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

function detailResult(args, amount = "115.00", extra = {}) {
    return { changed: false, company_id: args[0].company_id, row_key: args[1], period_key: args[2],
        revision: args[3], page: args[4], page_size: 50, total_count: 1, amount, negative: false,
        label: "Sales", period_label: "October 2026", events: [{ event_key: "c".repeat(64),
            date: "2026-10-12", label: "INV/001", amount, negative: false }], ...extra };
}

test("every owner row and present amount is a drilldown separate from folding", async () => {
    const requests = [];
    const snapshot = ownerSnapshotWithComparison();
    const expected = new Map();
    const table = buildOwnerTable(snapshot.periods);
    for (const row of [...table.sections, ...table.sections.flatMap((section) => section.children),
        ...table.sections.flatMap((section) => section.children.flatMap((row) => row.children || [])), table.difference]) {
        for (const [period, value] of Object.entries(row.amounts)) { expected.set(`${row.key}|${period}`, value); }
    }
    const { component } = await mountLoadingReport((_model, method, args) => {
        if (method === "get_context") { return Promise.resolve(loadingContext()); }
        if (method === "get_owner_snapshot") { return Promise.resolve(snapshot); }
        if (method === "get_owner_details") {
            requests.push(args);
            const value = expected.get(`${args[1]}|${args[2]}`);
            return Promise.resolve(detailResult(args, value.amount));
        }
        throw new Error("Unexpected RPC");
    });
    await waitUntil(() => component.state.report !== null);
    for (const group of component.ownerTable.sections[1].children) { component.toggleOwnerRow(group); }
    await waitUntil(() => document.querySelector('[data-owner-row="outflow:operating_account:eeeeeeeeeeeeeeeeeeee"]'));
    const buttons = [...document.querySelectorAll("[data-owner-row]")].map((button) => ({
        row: button.dataset.ownerRow, period: button.dataset.ownerPeriod,
    }));
    expect(buttons.length).toBe(expected.size + new Set([...expected.keys()].map((key) => key.split("|")[0])).size);
    for (const target of buttons) {
        const button = [...document.querySelectorAll("[data-owner-row]")].find((node) =>
            node.dataset.ownerRow === target.row && node.dataset.ownerPeriod === target.period);
        button.click();
        await waitUntil(() => component.state.ownerDetail?.data);
        const call = requests[requests.length - 1];
        expect(call[1]).toBe(target.row);
        const period = target.period || (expected.has(`${target.row}|current`) ? "current" : "previous");
        expect(call[2]).toBe(period);
        expect(call[3]).toBe((period === "current" ? "a" : "b").repeat(64));
        expect(document.querySelector(".o_baseer_owner_detail_total strong").textContent)
            .toBe(expected.get(`${target.row}|${period}`).amount);
        document.querySelector(".o_baseer_owner_back").click();
        await waitUntil(() => document.querySelector(".o_baseer_owner_summary"));
        expect(document.activeElement.dataset.ownerRow).toBe(target.row);
        expect(document.activeElement.dataset.ownerPeriod).toBe(target.period);
    }
    expect(requests.length).toBe(buttons.length);
    expect(component.isOwnerExpanded(component.ownerTable.sections[1].children[0])).toBe(true);
});

test("details page through exact server contributions and open a revalidated source", async () => {
    const requests = [], actions = [];
    const { component } = await mountLoadingReport((_model, method, args) => {
        if (method === "get_context") { return Promise.resolve(loadingContext()); }
        if (method === "get_owner_snapshot") { return Promise.resolve(ownerSnapshot()); }
        requests.push({ method, args });
        if (method === "get_owner_details") { return Promise.resolve(detailResult(args, "115.00", { total_count: 51 })); }
        if (method === "action_owner_source") { return Promise.resolve({ type: "ir.actions.act_window", res_model: "account.move", res_id: 7 }); }
        throw new Error("Unexpected RPC");
    }, async (action) => actions.push(action));
    await waitUntil(() => component.state.report !== null);
    await component.openOwnerDetails(component.ownerTable.sections[0], "current");
    await waitUntil(() => document.querySelector(".o_baseer_owner_next"));
    document.querySelector(".o_baseer_owner_next").click();
    await waitUntil(() => component.state.ownerDetail?.data?.page === 2);
    expect(requests[1].args[4]).toBe(2);
    await waitUntil(() => document.querySelector(".o_baseer_owner_source"));
    document.querySelector(".o_baseer_owner_source").click();
    await waitUntil(() => actions.length === 1);
    expect(requests[2].args).toEqual([component.appliedFilters, "total:incoming_total", "current", "a".repeat(64), "c".repeat(64)]);
    expect(actions[0].res_id).toBe(7);
});

test("changed detail or source revision hides events and requests a new summary", async () => {
    let changed = false, source = false;
    const { component } = await mountLoadingReport((_model, method, args) => {
        if (method === "get_context") { return Promise.resolve(loadingContext()); }
        if (method === "get_owner_snapshot") { return Promise.resolve(ownerSnapshot()); }
        if (method === "get_owner_details") { return Promise.resolve(changed ? { changed: true } : detailResult(args)); }
        if (method === "action_owner_source") { source = true; return Promise.resolve({ changed: true }); }
        throw new Error("Unexpected RPC");
    }, async () => { throw new Error("Stale source action must not run"); });
    await waitUntil(() => component.state.report !== null);
    await component.openOwnerDetails(component.ownerTable.sections[0]);
    await component.openOwnerSource(component.state.ownerDetail.data.events[0]);
    expect(source).toBe(true);
    expect(component.state.ownerDetail.data).toBe(null);
    expect(component.state.ownerDetail.changed).toBe(true);
    component.closeOwnerDetails();
    changed = true;
    await component.openOwnerDetails(component.ownerTable.sections[0]);
    await waitUntil(() => document.querySelector(".o_baseer_owner_refresh"));
    expect(document.querySelector(".o_baseer_owner_events")).toBe(null);
    document.querySelector(".o_baseer_owner_refresh").click();
    await waitUntil(() => document.querySelector(".o_baseer_owner_summary"));
    expect(component.state.ownerDetail).toBe(null);
});

test("details retry safely and fence late responses after back, company change and destroy", async () => {
    let calls = 0;
    let pending;
    const { component, destroy } = await mountLoadingReport((_model, method, args) => {
        if (method === "get_context") { return Promise.resolve(loadingContext(args[0])); }
        if (method === "get_owner_snapshot") { return Promise.resolve(ownerSnapshot(args[0].company_id)); }
        if (method === "get_owner_details") {
            calls++;
            if (calls === 1) { return Promise.reject(new ConnectionLostError("/details")); }
            pending = { ...deferred(), args };
            return pending.promise;
        }
        throw new Error("Unexpected RPC");
    });
    await waitUntil(() => component.state.report !== null);
    await component.openOwnerDetails(component.ownerTable.sections[0]);
    expect(component.state.ownerDetail.error).toBe(component.labels.detailError);
    const request = component.loadOwnerDetails(1);
    component.loadOwnerDetails(1);
    expect(calls).toBe(2);
    component.closeOwnerDetails();
    pending.resolve(detailResult(pending.args)); await request;
    expect(component.state.ownerDetail).toBe(null);
    const second = component.openOwnerDetails(component.ownerTable.sections[0]);
    patchWithCleanup(user, { activeCompany: { id: 2 } });
    component.refreshActiveCompany();
    pending.resolve(detailResult(pending.args)); await second;
    await waitUntil(() => component.appliedFilters?.company_id === 2);
    expect(component.state.ownerDetail).toBe(null);
    const third = component.openOwnerDetails(component.ownerTable.sections[0]);
    destroy(); pending.resolve(detailResult(pending.args)); await third;
    expect(component.state.ownerDetail.data).toBe(null);
});

test("detail payload mismatches and source errors never display unverified operations", async () => {
    let mode = "wrongAmount";
    const { component } = await mountLoadingReport((_model, method, args) => {
        if (method === "get_context") { return Promise.resolve(loadingContext()); }
        if (method === "get_owner_snapshot") { return Promise.resolve(ownerSnapshot()); }
        if (method === "get_owner_details") {
            return Promise.resolve(detailResult(args, mode === "wrongAmount" ? "999.00" : "115.00",
                mode === "wrongCompany" ? { company_id: 9 } : {}));
        }
        if (method === "action_owner_source") { return Promise.reject(new Error("Denied source")); }
        throw new Error("Unexpected RPC");
    }, async () => { throw new Error("Rejected source must not open"); });
    await waitUntil(() => component.state.report !== null);
    await component.openOwnerDetails(component.ownerTable.sections[0]);
    expect(component.state.ownerDetail.changed).toBe(true);
    expect(component.state.ownerDetail.data).toBe(null);
    component.closeOwnerDetails(); mode = "wrongCompany";
    await component.openOwnerDetails(component.ownerTable.sections[0]);
    expect(component.state.ownerDetail.error).toBe(component.labels.detailError);
    expect(component.state.ownerDetail.data).toBe(null);
    component.closeOwnerDetails(); mode = "valid";
    await component.openOwnerDetails(component.ownerTable.sections[0]);
    await component.openOwnerSource(component.state.ownerDetail.data.events[0]);
    expect(component.state.ownerDetail.error).toBe(component.labels.detailError);
    expect(component.state.ownerDetail.opening).toBe(false);
});
