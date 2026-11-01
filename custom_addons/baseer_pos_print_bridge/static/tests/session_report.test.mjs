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
const _t = (v) => v; class Component {}; class Navbar {}; class Dialog {}; const useState = (v) => v;
const ensureSessionReportSynced = async () => {}; const reportJpeg = () => 'jpeg';
const Node = { TEXT_NODE: 3 };
const rasterCalls = [];
const toCanvas = async (node, options) => { rasterCalls.push({ node, options }); return { width: options.width * options.pixelRatio }; };
let extension; const patch = (_target, value) => { extension = value; };
`;
const { extension, rasterCalls, renderCurrentSessionReport, BaseerCurrentSessionReportDialog } = await import(`data:text/javascript;base64,${Buffer.from(setup + handlerSource + '\nexport { extension, rasterCalls };').toString("base64")}`);
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
const openedDialogs = [];
const calls = [];
const originalSnapshot = { token: "original", report: {}, expires_at: Date.now() / 1000 + 300, print_available: true };
const host = {
    baseerSessionReport: { busy: false },
    dialog: { add: (component, props) => openedDialogs.push({ component, props }) },
    pos: {
        session: { id: 7 }, notification: { add: (...args) => notices.push(args) },
        printer: { renderer },
        data: { async call(_model, method) {
            calls.push(method);
            if (method === "baseer_prepare_current_report") return originalSnapshot;
            throw new Error("Lost enqueue response");
        } },
    },
};
const rendersBeforePreview = rasterCalls.length;
await extension.baseerViewCurrentSession.call(host);
assert.equal(host.baseerSessionReport.busy, false);
assert.deepEqual(calls, ["baseer_prepare_current_report"]);
assert.equal(rasterCalls.length, rendersBeforePreview, "opening preview must never rasterize");
assert.equal(openedDialogs.length, 1);
assert.equal(openedDialogs[0].component, BaseerCurrentSessionReportDialog);
function createDialog(snapshot) {
    const dialog = Object.create(BaseerCurrentSessionReportDialog.prototype);
    dialog.props = { pos: host.pos, snapshot, close: () => {} };
    dialog.setup();
    return dialog;
}
const dialog = createDialog(openedDialogs[0].props.snapshot);
assert.equal(dialog.reportImage, null);
await dialog.printReport();
assert.equal(dialog.state.busy, false);
assert.equal(dialog.state.printed, false);
assert.equal(dialog.state.snapshot.token, "original");
assert.equal(dialog.reportImage, "jpeg");
assert.match(dialog.state.error, /Lost enqueue response/);
const rendersBeforeRetry = rasterCalls.length;
host.pos.data.call = async (_model, method, args) => {
    assert.equal(method, "baseer_enqueue_current_report", "retry must not create a second snapshot");
    assert.equal(args[1], "original");
    calls.push(method);
    return { state: "pending" };
};
await dialog.printReport();
assert.equal(dialog.state.printed, true);
assert.equal(rasterCalls.length, rendersBeforeRetry, "network retry must reuse the first rendered raster");
const callsAfterPrint = calls.length;
await dialog.printReport();
assert.equal(calls.length, callsAfterPrint, "successful preview is not silently printed a second time");

const refreshedSnapshot = { token: "refreshed", report: { summary: { total_amount: "50.00" } }, expires_at: Date.now() / 1000 + 300, print_available: true };
host.pos.data.call = async (_model, method) => {
    assert.equal(method, "baseer_prepare_current_report", "refresh is read-only and must not enqueue");
    return refreshedSnapshot;
};
await dialog.refreshReport();
assert.equal(dialog.state.snapshot, refreshedSnapshot);
assert.equal(dialog.state.printed, false);
assert.equal(dialog.reportImage, null);
assert.equal(rasterCalls.length, rendersBeforeRetry, "refresh must never rasterize");

host.pos.data.call = async () => { throw new Error("must not call server"); };
const expiredDialog = createDialog({ ...originalSnapshot, expires_at: 0 });
await expiredDialog.printReport();
assert.match(expiredDialog.state.error, /expired.*Refresh/);
assert.equal(expiredDialog.state.snapshot.token, "original", "Print must not replace visible figures with an unseen fresh report");
assert.equal(expiredDialog.reportImage, null);
const noPrinterDialog = createDialog({ ...originalSnapshot, print_available: false });
await noPrinterDialog.printReport();
assert.equal(noPrinterDialog.reportImage, null);
assert.equal(noPrinterDialog.state.busy, false);
assert.equal(rasterCalls.length, rendersBeforeRetry);

host.baseerSessionReport.busy = true;
host.pos.data.call = async () => { throw new Error("must not execute"); };
await extension.baseerViewCurrentSession.call(host);
assert.equal(openedDialogs.length, 1);
host.baseerSessionReport.busy = false;
await extension.baseerViewCurrentSession.call(host);
assert.equal(host.baseerSessionReport.busy, false);
assert.equal(notices.length, 1);
const template = readFileSync(new URL("../src/app/session_report.xml", import.meta.url), "utf8");
assert.match(template, /onSelected="\(\) => this\.baseerViewCurrentSession\(\)"/);
assert.match(template, /View session report/);
assert.doesNotMatch(template, /DropdownItem t-if="pos\.config\.baseer_direct_print_enabled"/);
assert.match(template, /t-if="state\.snapshot\.print_available"[\s\S]*t-on-click="printReport"/);
console.log("Session report preview-only opening/refresh, explicit printing, expiry, permissions visibility, rendering and retry tests passed.");
