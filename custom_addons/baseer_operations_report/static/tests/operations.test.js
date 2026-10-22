/** @odoo-module **/

import { destroy, expect, globals, test, withFetch } from "@odoo/hoot";
import { click, waitUntil } from "@odoo/hoot-dom";
import { Component, xml } from "@odoo/owl";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { registry } from "@web/core/registry";
import { ConnectionLostError } from "@web/core/network/rpc";
import { user } from "@web/core/user";
import { clearRegistry, mountWithCleanup, patchWithCleanup } from "@web/../tests/web_test_helpers";
import { BaseerReportsHub } from "@baseer_reports_menu/report_hub";
import { ReportSelector } from "@baseer_reports_menu/report_selector";
import { BaseerOperationsPreview, prepareOperationsSnapshot } from "@baseer_operations_report/operations";

defineMailModels();

test("operations preview preserves server amounts, row order, and detail fingerprints", () => {
    const fingerprint = "a".repeat(64);
    const snapshot = {
        complete: false, currency_code: "SAR", periods: [{
            key: "current", label: "2026-10-01 — 2026-10-31",
            rows: ["income", "cost_of_sales", "gross_profit", "expense",
                "net_operating_income", "other_income", "other_expense",
                "net_other_income", "net_income"].map((key) => ({
                    key, amount: key === "income" ? "115.00" : key === "net_income" ? "-7.50" : "0.00",
                    negative: key === "net_income",
                })),
            accounts: { income: [{ account_id: 7, account_code: "400000",
                account_name: "Sales", amount: "115.00", negative: false,
                source_count: 1, fingerprint, channels: [
                    { key: "cash", name: "Cash", amount: "50.00", negative: false },
                    { key: "card", name: "Card", amount: "65.00", negative: false },
                ] }], cost_of_sales: [], expense: [],
                other_income: [], other_expense: [] },
        }],
    };
    const output = prepareOperationsSnapshot(snapshot, "Baseer", false, {
        income: "Income", net_income: "Net operations",
    });
    expect(output.report.complete).toBe(false);
    expect(output.report.rows.map((row) => row.key)).toEqual([
        "income", "cost_of_sales", "gross_profit", "expense",
        "net_operating_income", "other_income", "other_expense",
        "net_other_income", "net_income",
    ]);
    expect(output.report.rows[0].amounts.current.amount).toBe("115.00");
    expect(output.report.rows[8].amounts.current.amount).toBe("-7.50");
    expect(output.accounts.income[0].fingerprints.current).toBe(fingerprint);
    expect(output.accounts.income[0].sourceCounts.current).toBe(1);
    expect(output.accounts.income[0].channels[0].amounts.current.amount).toBe("50.00");
    expect(output.accounts.income[0].channels[1].amounts.current.amount).toBe("65.00");
    const comparison = structuredClone(snapshot.periods[0]);
    comparison.key = "previous";
    comparison.accounts.income[0].channels = [
        { key: "card", name: "Card", amount: "-7.50", negative: true },
    ];
    const compared = prepareOperationsSnapshot({ ...snapshot,
        periods: [snapshot.periods[0], comparison] }, "Baseer", false, {});
    expect(compared.accounts.income[0].channels).toHaveLength(2);
    expect(compared.accounts.income[0].channels[1].amounts.previous).toEqual({ amount: "-7.50", negative: true });
    expect(compared.accounts.income[0].channels[0].amounts.previous).toBe(undefined);
    expect(compared.accounts.income[0].amounts.current.amount).toBe("115.00");
    const completeOutput = prepareOperationsSnapshot({ ...snapshot, complete: true },
        "Baseer", false, { income: "Income", net_income: "Net operations" });
    expect(completeOutput.report.complete).toBe(true);
});

test("operations preview rejects a missing financial row instead of showing zero", () => {
    expect(() => prepareOperationsSnapshot({ complete: false, periods: [{
        key: "current", rows: [{ key: "income", amount: "115.00", negative: false }],
        accounts: { income: [], cost_of_sales: [], expense: [],
            other_income: [], other_expense: [] },
    }] }, "Baseer", false, { income: "Income" })).toThrow();
});

test("operations preview rejects a missing completeness state", () => {
    expect(() => prepareOperationsSnapshot({ periods: [] }, "Baseer", false, {})).toThrow();
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

function loadingSnapshot(companyId = 1, amount = "115.00") {
    return { company_id: companyId, complete: true, currency_code: "SAR",
        period_controls: { anchor_date: "2026-10-22", options: [] }, periods: [{
            key: "current", role: "primary", label: "October", date_from: "2026-10-01", date_to: "2026-10-31",
            rows: ["income", "cost_of_sales", "gross_profit", "expense", "net_operating_income",
                "other_income", "other_expense", "net_other_income", "net_income"].map((key) => ({
                key, amount: key === "income" ? amount : "0.00", negative: false,
            })), accounts: { income: [], cost_of_sales: [], expense: [], other_income: [], other_expense: [] },
        }] };
}

async function loadingTemplates(withHub = false) {
    const paths = ["/baseer_operations_report/static/src/operations.xml",
        "/baseer_reports_menu/static/src/report_selector.xml"];
    if (withHub) { paths.push("/baseer_reports_menu/static/src/report_hub.xml"); }
    const templates = await Promise.all(paths.map(async (path) => {
        const response = await withFetch(globals.fetch, () => fetch(path));
        expect(response.ok).toBe(true);
        return (await response.text()).replace(/<\?xml[^>]*>/, "")
            .replace(/<templates[^>]*>/, "").replace("</templates>", "");
    }));
    return "<templates>" + templates.join("") + "</templates>";
}

async function mountLoadingReport(call, ComponentClass = BaseerOperationsPreview) {
    patchWithCleanup(user, { lang: "ar_001", activeCompany: { id: 1 }, hasGroup: async () => true });
    // Mount native dropdowns/overlays without starting unrelated applications
    // (e.g. POS data initialization) from the combined unit-test asset bundle.
    // The test helpers restore both registries after every test.
    const services = registry.category("services");
    const required = new Map();
    const keep = (name) => {
        if (required.has(name)) { return; }
        const service = services.get(name);
        required.set(name, service);
        for (const dependency of service.dependencies || []) { keep(dependency); }
    };
    for (const name of ["ui", "hotkey", "popover", "bottom_sheet"]) { keep(name); }
    clearRegistry(services);
    clearRegistry(registry.category("main_components"));
    for (const [name, service] of required) { services.add(name, service); }
    services.add("orm", { start: () => ({ call: (model, method, ...args) => {
        if (!((model === "baseer.profit.loss.report" && method === "get_context") ||
            (model === "baseer.operations.report" && method === "get_source_snapshot"))) {
            throw new Error(`Unexpected report RPC: ${model}.${method}`);
        }
        return call(model, method, ...args);
    } }) });
    services.add("action", { start: () => ({ doAction: async () => {} }) });
    const component = await mountWithCleanup(ComponentClass, {
        templates: await loadingTemplates(ComponentClass === BaseerReportsHub), props: {},
    });
    return { component, destroy: () => destroy(component.__owl__.app) };
}

test("Operations mounts its own Arabic loading surface before context and snapshot finish", async () => {
    const context = deferred(), snapshot = deferred();
    const calls = [];
    const { component } = await mountLoadingReport((_model, method) => {
        calls.push(method);
        if (method === "get_context") { return context.promise; }
        if (method === "get_source_snapshot") { return snapshot.promise; }
        throw new Error("Unexpected RPC");
    });
    expect(document.querySelector(".o_baseer_go_report").getAttribute("dir")).toBe("rtl");
    expect(document.querySelector(".o_baseer_go_report [role='status']").textContent).toBe(component.labels.loading);
    expect(document.querySelector(".o_baseer_go_report table")).toBe(null);
    expect(document.querySelector(".o_baseer_report_filters")).toBe(null);
    expect(calls).toEqual(["get_context"]);
    context.resolve(loadingContext());
    await waitUntil(() => calls.includes("get_source_snapshot"));
    component.apply(); // Identical pending request must not start another RPC.
    expect(calls).toEqual(["get_context", "get_source_snapshot"]);
    expect(document.querySelector(".o_baseer_go_report table")).toBe(null);
    snapshot.resolve(loadingSnapshot());
    await waitUntil(() => document.querySelector(".o_baseer_pl_income .is-number"));
    expect(document.querySelector(".o_baseer_pl_income .is-number").textContent).toBe("115.00");
    expect(component.state.loading).toBe(false);
});

test("actual hub and selector replace the previous report while Operations RPC is pending", async () => {
    class PreviousVatFixture extends Component {
        static components = { ReportSelector };
        static props = ["*"];
        static template = xml`<div class="operations-test-old-vat"><ReportSelector
            options="props.reportOptions" selectedKey="props.selectedReportKey"
            label="props.reportSelectorLabel" lang="'ar'" onSelect="props.onReportSelect"/>
            <strong>Previous VAT fixture</strong></div>`;
    }
    const definitions = registry.category("baseer_reports");
    const operations = definitions.get("operations_gross");
    patchWithCleanup(definitions, { getAll: () => [
        { key: "previous_vat_fixture", kind: "component", sequence: 1, groups: ["accounting"],
            label: { ar: "ضريبة القيمة المضافة", en: "VAT" }, component: PreviousVatFixture }, operations,
    ] });
    const snapshot = deferred();
    let snapshotCalls = 0;
    await mountLoadingReport((_model, method) => {
        if (method === "get_context") { return Promise.resolve(loadingContext()); }
        if (method === "get_source_snapshot") { snapshotCalls++; return snapshot.promise; }
        throw new Error("Unexpected RPC");
    }, BaseerReportsHub);
    expect(document.querySelector(".operations-test-old-vat") !== null).toBe(true);
    await click(".o_baseer_report_switcher");
    await waitUntil(() => [...document.querySelectorAll(".dropdown-item")]
        .some((item) => item.textContent.trim() === "العمليات الإجمالية"));
    [...document.querySelectorAll(".dropdown-item")]
        .find((item) => item.textContent.trim() === "العمليات الإجمالية").click();
    await waitUntil(() => snapshotCalls === 1 && document.querySelector(".o_baseer_go_report"));
    expect(document.querySelector(".operations-test-old-vat")).toBe(null);
    expect(document.querySelector(".o_baseer_go_report [role='status']") !== null).toBe(true);
    expect(document.querySelector(".o_baseer_go_report table")).toBe(null);
    snapshot.resolve(loadingSnapshot());
    await waitUntil(() => document.querySelector(".o_baseer_pl_income .is-number"));
});

test("connection failure offers one manual retry without duplicating the pending RPC", async () => {
    const retry = deferred();
    let calls = 0;
    const { component } = await mountLoadingReport((_model, method) => {
        if (method === "get_context") { return Promise.resolve(loadingContext()); }
        if (method === "get_source_snapshot") {
            calls++;
            return calls === 1 ? Promise.reject(new ConnectionLostError("/synthetic-report")) : retry.promise;
        }
        throw new Error("Unexpected RPC");
    });
    await waitUntil(() => document.querySelector(".o_baseer_go_report [role='alert'] button"));
    expect(component.state.error).toBe(component.labels.connectionError);
    const button = document.querySelector(".o_baseer_go_report [role='alert'] button");
    button.click(); button.click();
    expect(calls).toBe(2);
    component.apply();
    expect(calls).toBe(2);
    retry.resolve(loadingSnapshot());
    await waitUntil(() => document.querySelector(".o_baseer_pl_income .is-number"));
    expect(component.state.error).toBe("");
});

test("source AccessError stays distinct and never reveals old or zero financial rows", async () => {
    const message = "Synthetic source evidence was denied";
    let calls = 0;
    const { component } = await mountLoadingReport((_model, method) => {
        if (method === "get_context") { return Promise.resolve(loadingContext()); }
        if (method === "get_source_snapshot") {
            calls++;
            return Promise.reject({ data: { name: "odoo.exceptions.AccessError", message } });
        }
        throw new Error("Unexpected RPC");
    });
    await waitUntil(() => component.state.error === message);
    expect(component.state.error === component.labels.connectionError).toBe(false);
    expect(document.querySelector(".o_baseer_go_report table")).toBe(null);
    expect(calls).toBe(1);
});

test("a failed context retries context before requesting any financial snapshot", async () => {
    const retryContext = deferred();
    const calls = [];
    await mountLoadingReport((_model, method) => {
        calls.push(method);
        if (method === "get_context") {
            return calls.length === 1 ? Promise.reject(new ConnectionLostError("/synthetic-context")) : retryContext.promise;
        }
        if (method === "get_source_snapshot") { return Promise.resolve(loadingSnapshot()); }
        throw new Error("Unexpected RPC");
    });
    await waitUntil(() => document.querySelector(".o_baseer_go_report [role='alert'] button"));
    const button = document.querySelector(".o_baseer_go_report [role='alert'] button");
    button.click(); button.click();
    expect(calls).toEqual(["get_context", "get_context"]);
    retryContext.resolve(loadingContext());
    await waitUntil(() => document.querySelector(".o_baseer_pl_income .is-number"));
    expect(calls).toEqual(["get_context", "get_context", "get_source_snapshot"]);
});

test("company changes fence late snapshots and keep exact current-company server amounts", async () => {
    const pending = new Map();
    const { component } = await mountLoadingReport((_model, method, args) => {
        if (method === "get_context") { return Promise.resolve(loadingContext(args[0])); }
        if (method === "get_source_snapshot") {
            const request = deferred(); pending.set(args[0].company_id, request); return request.promise;
        }
        throw new Error("Unexpected RPC");
    });
    await waitUntil(() => pending.has(1));
    patchWithCleanup(user, { activeCompany: { id: 2 } });
    component.refreshActiveCompany();
    await waitUntil(() => pending.has(2));
    pending.get(2).resolve(loadingSnapshot(2, "222.00"));
    await waitUntil(() => component.state.report !== null);
    pending.get(1).resolve(loadingSnapshot(1, "111.00"));
    await Promise.resolve(); await Promise.resolve();
    expect(component.state.report.rows[0].amounts.current.amount).toBe("222.00");
    expect(component.appliedFilters.company_id).toBe(2);
});

test("leaving Operations fences late success and starts no replacement request", async () => {
    const snapshot = deferred();
    let calls = 0;
    const { component, destroy } = await mountLoadingReport((_model, method) => {
        if (method === "get_context") { return Promise.resolve(loadingContext()); }
        if (method === "get_source_snapshot") { calls++; return snapshot.promise; }
        throw new Error("Unexpected RPC");
    });
    await waitUntil(() => calls === 1);
    destroy();
    snapshot.resolve(loadingSnapshot());
    await Promise.resolve(); await Promise.resolve();
    expect(component.disposed).toBe(true);
    expect(component.state.report).toBe(null);
    expect(calls).toBe(1);
});

test("a new-company context failure can retry while the previous snapshot is still pending", async () => {
    const oldSnapshot = deferred();
    let snapshotCalls = 0;
    const { component } = await mountLoadingReport((_model, method, args) => {
        if (method === "get_context") {
            return args[0] === 1 ? Promise.resolve(loadingContext())
                : Promise.reject(new ConnectionLostError("/synthetic-company-context"));
        }
        if (method === "get_source_snapshot") { snapshotCalls++; return oldSnapshot.promise; }
        throw new Error("Unexpected RPC");
    });
    await waitUntil(() => snapshotCalls === 1);
    patchWithCleanup(user, { activeCompany: { id: 2 } });
    component.refreshActiveCompany();
    await waitUntil(() => component.state.error === component.labels.connectionError);
    expect(component.state.loading).toBe(false);
    expect(component.state.contextReady).toBe(false);
    oldSnapshot.resolve(loadingSnapshot());
    await Promise.resolve(); await Promise.resolve();
    expect(component.state.report).toBe(null);
    expect(component.state.error).toBe(component.labels.connectionError);
});

test("clearing the active company cannot suppress a fresh context when returning to it", async () => {
    const oldContext = deferred(), newContext = deferred();
    let contextCalls = 0, snapshotCalls = 0;
    const { component } = await mountLoadingReport((_model, method) => {
        if (method === "get_context") {
            contextCalls++;
            return contextCalls === 1 ? oldContext.promise : newContext.promise;
        }
        if (method === "get_source_snapshot") {
            snapshotCalls++;
            return Promise.resolve(loadingSnapshot());
        }
        throw new Error("Unexpected RPC");
    });
    expect(contextCalls).toBe(1);
    patchWithCleanup(user, { activeCompany: { id: 0 } });
    component.refreshActiveCompany();
    expect(component.contextLoading).toBe(false);
    expect(component.state.contextReady).toBe(false);
    expect(component.state.loading).toBe(false);
    patchWithCleanup(user, { activeCompany: { id: 1 } });
    component.refreshActiveCompany();
    expect(contextCalls).toBe(2);
    newContext.resolve(loadingContext());
    await waitUntil(() => document.querySelector(".o_baseer_pl_income .is-number"));
    oldContext.resolve(loadingContext());
    await Promise.resolve(); await Promise.resolve();
    expect(contextCalls).toBe(2);
    expect(snapshotCalls).toBe(1);
    expect(component.state.report.rows[0].amounts.current.amount).toBe("115.00");
});
