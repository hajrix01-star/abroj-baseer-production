/** @odoo-module **/

import { expect, globals, test, withFetch } from "@odoo/hoot";
import { waitUntil } from "@odoo/hoot-dom";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { download } from "@web/core/network/download";
import { user } from "@web/core/user";
import { mockService, mountWithCleanup, patchWithCleanup } from "@web/../tests/web_test_helpers";
import { ReportExportButtons } from "@baseer_reports_menu/report_export";

defineMailModels();

function appliedFilters(companyId = 7) {
    return {
        company_id: companyId,
        period: { kind: "custom", date_from: "2026-01-01", date_to: "2026-01-31" },
        comparison: { kind: "none", order: "descending" },
        journal_ids: [12],
    };
}

function deferred() {
    let resolve, reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    return { promise, resolve, reject };
}

function context(props = {}) {
    const component = Object.create(ReportExportButtons.prototype);
    const notifications = [];
    Object.assign(component, {
        props: { reportKey: "owner", filters: appliedFilters(), lang: "ar", ...props },
        state: { busy: false },
        notification: { add: (...args) => notifications.push(args) },
    });
    return { component, notifications };
}

async function mountButtons(props = {}) {
    patchWithCleanup(user, { activeCompany: { id: 7 } });
    const notifications = [];
    mockService("notification", { add: (...args) => notifications.push(args) });
    const response = await withFetch(globals.fetch, () => fetch("/baseer_reports_menu/static/src/report_export.xml"));
    expect(response.ok).toBe(true);
    const component = await mountWithCleanup(ReportExportButtons, {
        templates: await response.text(),
        props: { reportKey: "owner", filters: appliedFilters(), lang: "ar", ...props },
    });
    return { component, notifications };
}

test("shared export sends only report identity, format and captured applied filters", async () => {
    patchWithCleanup(user, { activeCompany: { id: 7 } });
    const requests = [];
    const pending = deferred();
    patchWithCleanup(download, { _download: (options) => { requests.push(options); return pending.promise; } });
    const { component } = context();
    const originalFilters = JSON.parse(JSON.stringify(component.props.filters));
    // Neither a draft period nor a displayed financial value belongs in the request.
    component.draftFilters = appliedFilters();
    component.draftFilters.period.date_to = "2026-02-28";
    component.snapshot = { amount: "999.99", rows: [{ amount: "999.99" }] };
    const exporting = component.exportFile("xlsx");
    expect(component.state.busy).toBe(true);
    // A later filter mutation cannot change a download already started.
    component.props.filters.period.date_to = "2026-03-31";
    await waitUntil(() => requests.length === 1);
    expect(requests[0].url).toBe("/baseer/reports/export");
    expect(Object.keys(requests[0].data).sort()).toEqual(["file_format", "filters", "report_key"]);
    expect(requests[0].data.report_key).toBe("owner");
    expect(requests[0].data.file_format).toBe("xlsx");
    expect(JSON.parse(requests[0].data.filters)).toEqual(originalFilters);
    expect(requests[0].data.filters.includes("999.99")).toBe(false);
    pending.resolve();
    await exporting;
    expect(component.state.busy).toBe(false);
});

test("shared export rejects disabled, absent, invalid-format and stale-company requests", async () => {
    patchWithCleanup(user, { activeCompany: { id: 7 } });
    const requests = [];
    patchWithCleanup(download, { _download: async (options) => { requests.push(options); } });
    for (const props of [{ disabled: true }, { filters: undefined }, { filters: appliedFilters(8) }]) {
        const { component } = context(props);
        await component.exportFile("pdf");
        expect(component.state.busy).toBe(false);
    }
    const { component } = context();
    await component.exportFile("html");
    expect(requests).toEqual([]);
    patchWithCleanup(user, { activeCompany: { id: 8 } });
    await component.exportFile("xlsx");
    expect(requests).toEqual([]);
});

test("shared export suppresses duplicate downloads while pending and permits a later download", async () => {
    patchWithCleanup(user, { activeCompany: { id: 7 } });
    const pending = deferred();
    const requests = [];
    patchWithCleanup(download, { _download: (options) => { requests.push(options); return pending.promise; } });
    const { component, notifications } = context();
    const first = component.exportFile("pdf");
    await component.exportFile("xlsx");
    await component.exportFile("pdf");
    await waitUntil(() => requests.length === 1);
    expect(requests[0].data.file_format).toBe("pdf");
    expect(component.disabled).toBe(true);
    pending.resolve();
    await first;
    expect(component.disabled).toBe(false);
    await component.exportFile("xlsx");
    expect(requests.length).toBe(2);
    expect(requests[1].data.file_format).toBe("xlsx");
    expect(notifications).toEqual([]);
});

test("shared export reports a localized safe failure and always clears busy for retry", async () => {
    patchWithCleanup(user, { activeCompany: { id: 7 } });
    let count = 0;
    patchWithCleanup(download, { _download: async () => { count++; throw new Error("private server detail"); } });
    for (const lang of ["ar", "en"]) {
        const { component, notifications } = context({ lang });
        await component.exportFile("pdf");
        expect(component.state.busy).toBe(false);
        expect(notifications).toEqual([[component.labels.error, { type: "danger" }]]);
        expect(notifications[0][0].includes("private server detail")).toBe(false);
        await component.exportFile("xlsx");
        expect(component.state.busy).toBe(false);
        expect(notifications.length).toBe(2);
    }
    expect(count).toBe(4);
});

test("shared export mounts labeled native buttons and disables both without an applied report", async () => {
    await mountButtons({ filters: undefined });
    const group = document.querySelector(".o_baseer_report_exports");
    expect(group.getAttribute("role")).toBe("group");
    expect(group.getAttribute("aria-label")).toBe("تصدير التقرير");
    const buttons = [...group.querySelectorAll("button")];
    expect(buttons.length).toBe(2);
    expect(buttons.map((button) => button.textContent.trim())).toEqual(["Excel", "PDF"]);
    for (const button of buttons) {
        expect(button.type).toBe("button");
        expect(button.disabled).toBe(true);
        expect(button.querySelector("i").getAttribute("aria-hidden")).toBe("true");
    }
    expect(group.querySelector("[role='status']")).toBe(null);
});

test("shared export honors the parent disabled state even with complete filters", async () => {
    await mountButtons({ disabled: true, lang: "en" });
    expect(document.querySelector(".o_baseer_report_exports").getAttribute("aria-label")).toBe("Export report");
    expect([...document.querySelectorAll(".o_baseer_report_exports button")].every((button) => button.disabled)).toBe(true);
});

test("shared export mounted click exposes loading status, blocks duplicate clicks and recovers", async () => {
    const pending = deferred();
    const requests = [];
    patchWithCleanup(download, { _download: (options) => { requests.push(options); return pending.promise; } });
    const { notifications } = await mountButtons();
    const group = document.querySelector(".o_baseer_report_exports");
    const excel = group.querySelector(".o_baseer_report_xlsx");
    const pdf = group.querySelector(".o_baseer_pl_pdf");
    excel.click();
    // This second event may precede Owl's render: the method guard still blocks it.
    pdf.click();
    await waitUntil(() => group.querySelector("[role='status']"));
    expect(requests.length).toBe(1);
    expect(group.getAttribute("aria-busy")).toBe("true");
    expect(group.querySelector("[role='status']").getAttribute("aria-live")).toBe("polite");
    expect(group.querySelector("[role='status']").textContent).toBe("جارٍ التصدير…");
    expect(excel.disabled).toBe(true);
    expect(pdf.disabled).toBe(true);
    pending.resolve();
    await waitUntil(() => !excel.disabled);
    expect(pdf.disabled).toBe(false);
    expect(group.querySelector("[role='status']")).toBe(null);
    expect(notifications).toEqual([]);
});
