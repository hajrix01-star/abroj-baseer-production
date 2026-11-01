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
let extension; const patch = (_target, value) => { extension = value; };
`;
const { extension } = await import(`data:text/javascript;base64,${Buffer.from(setup + handlerSource + '\nexport { extension };').toString("base64")}`);
const notices = [];
const host = {
    baseerSessionReport: { busy: false }, baseerReportAttempt: null,
    pos: {
        session: { id: 7 }, notification: { add: (...args) => notices.push(args) },
        printer: { renderer: { toCanvas: async () => ({}) } },
        data: { async call(_model, method) {
            if (method === "baseer_prepare_current_report") return { token: "original", report: {}, expires_at: Date.now() / 1000 + 300 };
            throw new Error("Lost enqueue response");
        } },
    },
};
await extension.baseerPrintCurrentSession.call(host);
assert.equal(host.baseerSessionReport.busy, false);
assert.equal(host.baseerReportAttempt.token, "original");
host.pos.data.call = async (_model, method, args) => {
    assert.equal(method, "baseer_enqueue_current_report", "retry must not create a second snapshot");
    assert.equal(args[1], "original");
    return { state: "pending" };
};
await extension.baseerPrintCurrentSession.call(host);
assert.equal(host.baseerReportAttempt, null);
host.baseerSessionReport.busy = true;
host.pos.data.call = async () => { throw new Error("must not execute"); };
await extension.baseerPrintCurrentSession.call(host);
assert.equal(notices.length, 2);
console.log("Session report sync, draft preservation, retry and busy tests passed.");
