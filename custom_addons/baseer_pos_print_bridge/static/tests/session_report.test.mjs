import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/app/session_report_flow.js", import.meta.url), "utf8")
    .replace('import { _t } from "@web/core/l10n/translation";', 'const _t = (value) => value;');
const { ensureSessionReportSynced } = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
function fixture() {
    const pending = { orderToCreate: [], orderToUpdate: [], orderToDelete: [] };
    const pos = {
        data: { network: { offline: false, unsyncData: [] } },
        syncingOrders: new Set(),
        getPendingOrder: () => pending,
        getOrderIdsToDelete: () => pending.orderToDelete,
        syncCalls: [],
        async syncAllOrders(options) {
            this.syncCalls.push(options);
            pending.orderToCreate = pending.orderToCreate.filter((order) => !options.orders.includes(order));
            pending.orderToUpdate = pending.orderToUpdate.filter((order) => !options.orders.includes(order));
        },
    };
    return { pos, pending };
}
{
    const { pos, pending } = fixture();
    const draft = { state: "draft", finalized: false };
    const paid = { state: "paid", finalized: true };
    pending.orderToCreate = [draft, paid];
    pending.orderToUpdate = [paid];
    await ensureSessionReportSynced(pos);
    assert.equal(pos.syncCalls.length, 1);
    assert.deepEqual(pos.syncCalls[0], { orders: [paid], throw: true });
    assert.deepEqual(pending.orderToCreate, [draft], "unfinished basket must remain untouched");
}
{
    const { pos } = fixture();
    await ensureSessionReportSynced(pos);
    assert.equal(pos.syncCalls.length, 0);
    pos.data.network.offline = true;
    await assert.rejects(() => ensureSessionReportSynced(pos), /Reconnect/);
}
for (const kind of ["delete", "inflight", "unsync"]) {
    const { pos, pending } = fixture();
    if (kind === "delete") pending.orderToDelete.push(10);
    if (kind === "inflight") pos.syncingOrders.add("paid-uuid");
    if (kind === "unsync") pos.data.network.unsyncData.push({});
    await assert.rejects(() => ensureSessionReportSynced(pos), /Wait/);
    assert.equal(pos.syncCalls.length, 0);
}
{
    const { pos, pending } = fixture();
    pending.orderToCreate.push({ state: "paid" });
    pos.syncAllOrders = async () => {};
    await assert.rejects(() => ensureSessionReportSynced(pos), /not synchronized/);
    pos.syncAllOrders = async () => { throw new Error("network lost"); };
    await assert.rejects(() => ensureSessionReportSynced(pos), /network lost/);
}
// Exercise the actual Navbar handler with mocked Odoo boundary services.
const handlerSource = readFileSync(new URL("../src/app/session_report.js", import.meta.url), "utf8")
    .replace(/^import .*;\r?\n/gm, "")
    .replace("export class", "class");
const setup = `
const _t = (v) => v; class Component {}; class Navbar {}; const useState = (v) => v;
const ensureSessionReportSynced = async () => {}; const reportJpeg = () => 'jpeg';
const Node = { TEXT_NODE: 3 };
const rasterCalls = [];
const toCanvas = async (node, options) => { rasterCalls.push({ node, options }); return { width: options.width * options.pixelRatio }; };
let extension; const patch = (_target, value) => { extension = value; };
`;
const { extension, rasterCalls, renderCurrentSessionReport } = await import(`data:text/javascript;base64,${Buffer.from(setup + handlerSource + '\nexport { extension, rasterCalls };').toString("base64")}`);
const classes = new Set();
const reportText = { nodeType: 3, textContent: 'Cash\u0000 / نقدي\n40.00\u000b' };
const nestedText = { nodeType: 3, textContent: 'Bank\u001f / بنك\t20.00' };
const reportElement = {
    nodeType: 1, childNodes: [reportText, { nodeType: 1, childNodes: [nestedText] }],
    classList: { add: (value) => classes.add(value) }, clientWidth: 270, clientHeight: 801.2,
};
let mounted = 0;
const renderer = {
    async toHtml(component, props) {
        assert.equal(component.template, "baseer_pos_print_bridge.CurrentSessionReport");
        assert.ok(props.report);
        return reportElement;
    },
    async whenMounted({ el, callback }) {
        assert.equal(el, reportElement);
        assert.ok(classes.has("pos-receipt-print"));
        mounted++;
        return callback(el);
    },
    async toCanvas() { throw new Error("Do not use the wrapper that drops font options"); },
};
await renderCurrentSessionReport(renderer, { summary: { total_amount: "40.00" } });
assert.equal(reportText.textContent, "Cash / نقدي\n40.00", "strip XML-invalid controls but preserve Arabic and newline");
assert.equal(nestedText.textContent, "Bank / بنك\t20.00", "sanitize nested text and preserve tab");
assert.deepEqual(rasterCalls[0].options, {
    backgroundColor: "#ffffff", width: 270, height: 802,
    pixelRatio: 2.2, includeQueryParams: true, skipFonts: true,
});
assert.equal(mounted, 1);
const notices = [];
const host = {
    baseerSessionReport: { busy: false }, baseerReportAttempt: null,
    pos: {
        session: { id: 7 }, notification: { add: (...args) => notices.push(args) },
        printer: { renderer },
        data: { async call(_model, method) {
            if (method === "baseer_prepare_current_report") return { token: "original", report: {}, expires_at: Date.now() / 1000 + 300 };
            throw new Error("Lost enqueue response");
        } },
    },
};
await extension.baseerPrintCurrentSession.call(host);
assert.equal(host.baseerSessionReport.busy, false);
assert.equal(host.baseerReportAttempt.token, "original");
const rendersBeforeRetry = rasterCalls.length;
host.pos.data.call = async (_model, method, args) => {
    assert.equal(method, "baseer_enqueue_current_report", "retry must not create a second snapshot");
    assert.equal(args[1], "original");
    return { state: "pending" };
};
await extension.baseerPrintCurrentSession.call(host);
assert.equal(host.baseerReportAttempt, null);
assert.equal(rasterCalls.length, rendersBeforeRetry, "network retry must reuse the first rendered raster");
host.baseerSessionReport.busy = true;
host.pos.data.call = async () => { throw new Error("must not execute"); };
await extension.baseerPrintCurrentSession.call(host);
assert.equal(notices.length, 2);
console.log("Session report sync, draft preservation, local-font native rendering, sanitation, retry and busy tests passed.");
