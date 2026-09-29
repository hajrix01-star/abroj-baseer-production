import fs from 'node:fs';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';

const base = 'custom_addons/baseer_browser_print/static/src/';
const transportSource = fs.readFileSync(base + 'report_transport.js', 'utf8');
const dialogSource = fs.readFileSync(base + 'print_dialog.js', 'utf8');
const xml = fs.readFileSync(base + 'print_dialog.xml', 'utf8');
const strip = source => source.replace(/^import .*;\r?\n/gm, '').replace(/export (class|function|async function) /g, '$1 ');
const R = { status: 'running', checks: [], source_sha256: Object.fromEntries([
    ['report_transport.js', transportSource], ['print_dialog.js', dialogSource], ['print_dialog.xml', xml],
].map(([path, content]) => [path, crypto.createHash('sha256').update(content).digest('hex')])),
    scope: 'Actual production source imported into Node with stubbed Odoo services, timers, DOMParser and iframe. Native getReportUrl is stubbed: verifies exact action delegation, not native URL implementation. No real browser, printing, HTTP, Odoo or database mutation.' };
let requests, timers, cleared, timerSequence, fetchImpl, urlCalls, urlImpl, parseImpl, rpcCalls, rpcStatus;
let destroyed, mounted, hiddenButtons, createdURLs, revokedURLs, downloads, frame, preparedCalls;
const navigatorStub = { pdfViewerEnabled: true };
const user = { context: { lang: 'ar_001', allowed_company_ids: [1, 2], tz: 'Asia/Riyadh' } };
const odoo = { csrf_token: 'fixture-csrf-token' };
const downloadReport = {};
class ConnectionLostError extends Error {}
const browser = {
    setTimeout(fn, delay) { const id = ++timerSequence; timers.set(id, { fn, delay }); return id; },
    clearTimeout(id) { cleared.push(id); timers.delete(id); },
    fetch(...args) { requests.push(args); return fetchImpl(...args); },
};
class DOMParserStub {
    parseFromString(text) {
        const tags = [...text.matchAll(/<(?:textarea|div|pre)[^>]*>([\s\S]*?)<\/(?:textarea|div|pre)>/g)];
        return { body: { children: tags.map(match => ({ textContent: match[1] })), textContent: text } };
    }
}
function getReportUrl(action, type) { urlCalls.push({ action, type }); return urlImpl(action, type); }
function makeErrorFromResponse(data) { const error = new Error(data.message || 'RPC failure'); error.name = 'RPCError'; error.data = data; return error; }
const prepareReport = new Function('browser', '_t', 'parse', 'makeErrorFromResponse', 'getReportUrl',
    'AbortController', 'FormData', 'DOMParser', 'odoo', 'ConnectionLostError',
    strip(transportSource) + '\nreturn prepareReport;')(
    browser, value => value, value => parseImpl(value), makeErrorFromResponse, getReportUrl,
    AbortController, FormData, DOMParserStub, odoo, ConnectionLostError);
const registrations = [];
const URLStub = {
    createObjectURL(blob) { createdURLs.push(blob); return 'blob:fixture-pdf'; },
    revokeObjectURL(url) { revokedURLs.push(url); },
};
const { BrowserPrintDialog, browserPrintHandler } = new Function('Component', 'onMounted', 'onWillDestroy', 'useRef', 'useState', 'browser', 'navigator', 'hidePDFJSButtons',
    'Dialog', '_t', 'downloadFile', 'rpc', 'registry', 'user', 'downloadReport', 'prepareReport', 'URL',
    strip(dialogSource) + '\nreturn { BrowserPrintDialog, browserPrintHandler };')(
    class {}, callback => mounted.push(callback), callback => destroyed.push(callback), () => ({ el: frame }), value => value, browser, navigatorStub, (...args) => hiddenButtons.push(args),
    class {}, value => value, (...args) => downloads.push(args), async (...args) => { rpcCalls.push(args); return rpcStatus; },
    { category(name) { return { add(key, handler) { registrations.push({ name, key, handler }); } }; } },
    user, downloadReport, (...args) => { preparedCalls++; return prepareReport(...args); }, URLStub);

function reset() {
    requests = []; timers = new Map(); cleared = []; timerSequence = 0; urlCalls = []; rpcCalls = [];
    destroyed = []; mounted = []; hiddenButtons = []; navigatorStub.pdfViewerEnabled = true; createdURLs = []; revokedURLs = []; downloads = []; preparedCalls = 0;
    delete downloadReport.wkhtmltopdfStatusProm;
    rpcStatus = 'ok'; odoo.csrf_token = 'fixture-csrf-token';
    urlImpl = () => '/report/pdf/fixture.report/40,41?context=fixture';
    parseImpl = header => { if (!header) { throw new Error('missing header'); }
        return { parameters: { filename: header.match(/filename="([^"]*)"/)?.[1] } }; };
    fetchImpl = async () => response();
    frame = { focusCalls: 0, printCalls: 0, removed: [], removeAttribute(key) { this.removed.push(key); },
        contentWindow: { focus() { frame.focusCalls++; }, print() { frame.printCalls++; } } };
}
function action() { return { type: 'ir.actions.report', report_type: 'qweb-pdf', report_name: 'fixture.report', name: 'Fixture report',
    context: { active_model: 'fixture.wizard', active_id: 40, active_ids: [40, 41], lang: 'en_US', allowed_company_ids: [2] },
    data: { options: { date_from: '2026-09-01', include_details: true } } }; }
function response({ ok = true, type = 'application/pdf', text = '%PDF-1.7\nfixture', disposition = 'attachment; filename="server.pdf"' } = {}) {
    const blob = new Blob([text], { type });
    return { ok, status: ok ? 200 : 500, blob: async () => blob, headers: { get: () => disposition } };
}
function envFixture() {
    const calls = [], dialogs = [];
    return { calls, dialogs, env: { services: {
        ui: { block() { calls.push('block'); }, unblock() { calls.push('unblock'); } },
        dialog: { add(component, props, options) { dialogs.push({ component, props, options }); calls.push('dialog'); } },
    } } };
}
const flush = async () => { for (let i = 0; i < 16; i++) { await Promise.resolve(); } };
async function check(name, fn) {
    reset();
    try { await fn(); R.checks.push({ name, passed: true }); }
    catch (error) { R.checks.push({ name, passed: false, error: error.stack }); }
}

await check('handler is registered in native report handler registry', () => {
    assert.deepEqual(registrations, [{ name: 'ir.actions.report handlers', key: 'baseer_browser_print', handler: browserPrintHandler }]);
});
await check('POST delegates intact wizard action and merges user/action context preserving active ids', async () => {
    const reportAction = action(); const result = await prepareReport(reportAction, user.context);
    const [url, request] = requests[0];
    assert.equal(requests.length, 1); assert.equal(url, '/report/download'); assert.equal(request.method, 'POST');
    assert.equal(urlCalls[0].action, reportAction); assert.equal(urlCalls[0].type, 'pdf');
    assert.deepEqual(JSON.parse(request.body.get('data')), ['/report/pdf/fixture.report/40,41?context=fixture', 'qweb-pdf']);
    assert.deepEqual(JSON.parse(request.body.get('context')), { ...user.context, ...reportAction.context });
    assert.deepEqual(reportAction.data.options, { date_from: '2026-09-01', include_details: true });
    assert.equal(result.filename, 'server.pdf'); assert.equal(await result.blob.slice(0, 5).text(), '%PDF-');
});
await check('authenticated transport supplies CSRF token same-origin no-store and bounded abort signal', async () => {
    let scheduled;
    fetchImpl = async () => { scheduled = [...timers.values()][0]; return response(); };
    await prepareReport(action(), user.context); const request = requests[0][1];
    assert.equal(request.body.get('csrf_token'), 'fixture-csrf-token'); assert.equal(request.credentials, 'same-origin');
    assert.equal(request.cache, 'no-store'); assert.equal(request.body.get('token'), 'baseer-browser-print');
    assert.ok(request.signal instanceof AbortSignal); assert.equal(scheduled.delay, 120000);
    assert.equal(timers.size, 0); assert.equal(cleared.length, 1);
});
await check('missing optional action context or CSRF does not drop user context', async () => {
    odoo.csrf_token = false; const reportAction = action(); delete reportAction.context;
    await prepareReport(reportAction, user.context); assert.deepEqual(JSON.parse(requests[0][1].body.get('context')), user.context);
    assert.equal(requests[0][1].body.has('csrf_token'), false);
});
await check('valid PDF with absent or malformed disposition uses action filename', async () => {
    fetchImpl = async () => response({ disposition: null });
    assert.equal((await prepareReport(action(), user.context)).filename, 'Fixture report.pdf');
    const reportAction = action(); delete reportAction.name;
    assert.equal((await prepareReport(reportAction, user.context)).filename, 'Report.pdf');
});
await check('PDF MIME alone cannot authorize a non-PDF signature', async () => {
    fetchImpl = async () => response({ text: '<html>not PDF</html>' });
    await assert.rejects(prepareReport(action(), user.context), /valid PDF/); assert.equal(timers.size, 0);
});
await check('PDF signature with wrong MIME is rejected without a preview blob', async () => {
    fetchImpl = async () => response({ type: 'text/html' });
    await assert.rejects(prepareReport(action(), user.context), /could not be prepared/); assert.equal(timers.size, 0);
});
await check('HTTP errors preserve parsed native report exception', async () => {
    const data = { message: 'Fixture access denied', data: { name: 'odoo.exceptions.AccessError' } };
    fetchImpl = async () => response({ ok: false, type: 'text/html', text: '<div>ignored</div><textarea>' + JSON.stringify(data) + '</textarea>' });
    await assert.rejects(prepareReport(action(), user.context), error => error.name === 'RPCError' && error.data.data.name === data.data.name);
    assert.equal(timers.size, 0);
});
await check('unstructured server/login failure becomes a preparation error and clears timeout', async () => {
    fetchImpl = async () => response({ ok: false, type: 'text/html', text: '<div>Sign in</div>' });
    await assert.rejects(prepareReport(action(), user.context), /could not be prepared/); assert.equal(cleared.length, 1);
});
await check('network rejection propagates an error and always clears timeout', async () => {
    fetchImpl = async () => { throw new TypeError('fixture network failure'); };
    await assert.rejects(prepareReport(action(), user.context), error => error instanceof ConnectionLostError); assert.equal(timers.size, 0); assert.equal(cleared.length, 1);
});
await check('response body failure also clears timeout', async () => {
    fetchImpl = async () => ({ ok: true, blob: async () => { throw new Error('fixture body failure'); } });
    await assert.rejects(prepareReport(action(), user.context), /body failure/); assert.equal(timers.size, 0);
});
await check('timeout abort yields actionable error and removes its timer', async () => {
    fetchImpl = (_, options) => new Promise((resolve, reject) => options.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError'))));
    const pending = prepareReport(action(), user.context);
    [...timers.values()][0].fn();
    await assert.rejects(pending, /took too long/); assert.equal(timers.size, 0); assert.equal(requests[0][1].signal.aborted, true);
});
await check('synchronous URL preparation failure cannot leak timeout before fetch', async () => {
    urlImpl = () => { throw new Error('fixture URL preparation failure'); };
    await assert.rejects(prepareReport(action(), user.context), /URL preparation failure/);
    assert.equal(requests.length, 0); assert.equal(timers.size, 0);
});
await check('non-PDF and explicit bypass use native fallback without status check or fetch', async () => {
    for (const reportAction of [{ ...action(), report_type: 'qweb-html' }, { ...action(), context: { baseer_download_pdf: true } }]) {
        const f = envFixture(); assert.equal(await browserPrintHandler(reportAction, {}, f.env), false);
        assert.deepEqual(f.calls, []);
    }
    assert.equal(requests.length, 0); assert.equal(rpcCalls.length, 0);
});
await check('wkhtmltopdf missing/broken/upgrade status returns native fallback before fetch', async () => {
    for (const status of ['install', 'broken', 'upgrade', 'workers']) {
        downloadReport.wkhtmltopdfStatusProm = Promise.resolve(status); const f = envFixture();
        assert.equal(await browserPrintHandler(action(), {}, f.env), false); assert.deepEqual(f.calls, []);
    }
    assert.equal(requests.length, 0);
});
await check('wkhtmltopdf probe rejection cannot produce false native fallback or report fetch', async () => {
    downloadReport.wkhtmltopdfStatusProm = Promise.reject(new Error('fixture probe failure'));
    const f = envFixture(); await assert.rejects(browserPrintHandler(action(), {}, f.env), /probe failure/);
    assert.equal(requests.length, 0); assert.deepEqual(f.calls, []);
});
await check('preparation failure unblocks UI and rejects without dialog or duplicate fallback', async () => {
    fetchImpl = async () => response({ text: 'invalid' }); const f = envFixture(); let onClose = 0;
    await assert.rejects(browserPrintHandler(action(), { onClose() { onClose++; } }, f.env), /valid PDF/);
    assert.deepEqual(f.calls, ['block', 'unblock']); assert.equal(f.dialogs.length, 0);
    assert.equal(requests.length, 1); assert.equal(onClose, 0);
});
await check('handler fetches once unblocks before dialog and remains pending until dialog closes', async () => {
    const f = envFixture(); let completed = false, onClose = 0;
    const pending = browserPrintHandler(action(), { onClose() { onClose++; } }, f.env).then(result => { completed = true; return result; });
    await flush();
    assert.deepEqual(f.calls, ['block', 'unblock', 'dialog']); assert.equal(completed, false);
    assert.equal(requests.length, 1); assert.equal(preparedCalls, 1); assert.equal(rpcCalls.length, 1);
    assert.equal(f.dialogs[0].component, BrowserPrintDialog);
    f.dialogs[0].options.onClose(); assert.equal(await pending, true); assert.equal(onClose, 0);
});
await check('dialog add failure rejects after UI is unblocked', async () => {
    const f = envFixture(); f.env.services.dialog.add = () => { throw new Error('fixture dialog failure'); };
    await assert.rejects(browserPrintHandler(action(), {}, f.env), /dialog failure/); assert.deepEqual(f.calls, ['block', 'unblock']);
});
await check('Print readiness is gated in template and load auto-prints only once', () => {
    const dialog = new BrowserPrintDialog(); dialog.props = { blob: new Blob(['%PDF-fixture']), filename: 'fixture.pdf', close() {} }; dialog.setup();
    assert.equal(dialog.state.ready, false); assert.equal(frame.printCalls, 0);
    assert.match(xml, /t-on-click="print" t-att-disabled="!state.ready"/);
    dialog.onLoad(); dialog.onLoad(); assert.equal(dialog.state.ready, true); assert.equal(frame.printCalls, 1);
    dialog.print(); assert.equal(frame.printCalls, 2); assert.equal(frame.focusCalls, 2);
});
await check('Print exceptions show browser-help fallback without fetching another report', () => {
    const dialog = new BrowserPrintDialog(); dialog.props = { blob: new Blob(['%PDF-fixture']), filename: 'fixture.pdf', close() {} }; dialog.setup();
    frame.contentWindow.print = () => { throw new Error('fixture blocked print'); }; dialog.onLoad();
    assert.equal(dialog.state.warning, dialog.labels.help); assert.equal(requests.length, 0);
});
await check('Download is available before readiness and reuses exact prepared Blob/filename', () => {
    const blob = new Blob(['%PDF-fixture']); const dialog = new BrowserPrintDialog();
    dialog.props = { blob, filename: 'fixture.pdf', close() {} }; dialog.setup(); dialog.download(); dialog.onLoad(); dialog.download();
    assert.deepEqual(downloads, [[blob, 'fixture.pdf', 'application/pdf'], [blob, 'fixture.pdf', 'application/pdf']]);
    assert.deepEqual(createdURLs, [blob]); assert.equal(requests.length, 0);
});
await check('dialog destroy clears frame source and revokes only its owned Blob URL', () => {
    const dialog = new BrowserPrintDialog(); dialog.props = { blob: new Blob(['%PDF-fixture']), filename: 'fixture.pdf', close() {} }; dialog.setup();
    destroyed.forEach(callback => callback()); assert.deepEqual(frame.removed, ['src']); assert.deepEqual(revokedURLs, ['blob:fixture-pdf']);
});

await check('HTTP 502 maps to native ConnectionLostError without decoding response body', async () => {
    let bodyReads = 0;
    fetchImpl = async () => ({ status: 502, ok: false, blob: async () => { bodyReads++; return new Blob(['gateway failure']); } });
    await assert.rejects(prepareReport(action(), user.context), error => error instanceof ConnectionLostError);
    assert.equal(bodyReads, 0); assert.equal(timers.size, 0);
});
await check('trailing disposition separator is removed before native filename parser', async () => {
    let parsed;
    parseImpl = header => { parsed = header; assert.ok(!header.endsWith(';')); return { parameters: { filename: 'native-parsed.pdf' } }; };
    fetchImpl = async () => response({ disposition: 'attachment; filename="native-parsed.pdf";' });
    assert.equal((await prepareReport(action(), user.context)).filename, 'native-parsed.pdf');
    assert.equal(parsed, 'attachment; filename="native-parsed.pdf"');
});
await check('PDF MIME parameters do not reject a valid signature', async () => {
    fetchImpl = async () => response({ type: 'application/pdf; charset=binary' });
    assert.equal(await (await prepareReport(action(), user.context)).blob.slice(0, 5).text(), '%PDF-');
});
await check('context serialization error before fetch still clears its timeout', async () => {
    const reportAction = action(); reportAction.context.cycle = reportAction.context;
    await assert.rejects(prepareReport(reportAction, user.context), TypeError);
    assert.equal(requests.length, 0); assert.equal(timers.size, 0);
});
await check('handler timeout rejects and unblocks with no preview dialog', async () => {
    fetchImpl = (_, options) => new Promise((resolve, reject) => options.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError'))));
    const f = envFixture(); const pending = browserPrintHandler(action(), {}, f.env);
    await flush(); assert.deepEqual(f.calls, ['block']); [...timers.values()][0].fn();
    await assert.rejects(pending, /took too long/); assert.deepEqual(f.calls, ['block', 'unblock']);
    assert.equal(f.dialogs.length, 0); assert.equal(timers.size, 0);
});
await check('complete dialog lifecycle reuses one fetched blob for Print and Download until close', async () => {
    const f = envFixture(); let finished = false;
    const pending = browserPrintHandler(action(), {}, f.env).then(value => { finished = true; return value; });
    await flush(); const definition = f.dialogs[0];
    const dialog = new definition.component(); dialog.props = { ...definition.props, close: definition.options.onClose }; dialog.setup();
    dialog.onLoad(); dialog.print(); dialog.download(); dialog.download();
    assert.equal(finished, false); assert.equal(requests.length, 1); assert.equal(preparedCalls, 1);
    assert.equal(frame.printCalls, 2);
    assert.ok(downloads.every(args => args[0] === definition.props.blob && args[1] === definition.props.filename));
    assert.deepEqual(createdURLs, [definition.props.blob]);
    destroyed.forEach(callback => callback()); dialog.props.close(); assert.equal(await pending, true);
    assert.deepEqual(revokedURLs, ['blob:fixture-pdf']); assert.equal(requests.length, 1);
});


function makeDialog() {
    const d = new BrowserPrintDialog(); d.props = { blob: new Blob(['%PDF-fixture']), filename: 'fixture.pdf', close() {} };
    d.setup(); mounted.forEach(fn => fn()); return d;
}
function deferred() { let resolve, reject; const promise = new Promise((r, j) => { resolve = r; reject = j; }); return { promise, resolve, reject }; }
async function fireTimer(delay) {
    const [id, timer] = [...timers.entries()].find(([, item]) => item.delay === delay);
    timers.delete(id); timer.fn(); await flush();
}
function appFixture() {
    return { initializedPromise: Promise.resolve(), pdfDocument: {}, sidebarCalls: 0,
        pdfViewer: { pageViewsReady: true, pagesPromise: Promise.resolve() }, pdfSidebar: { close() {} } };
}
function attachApp(app) { frame.contentWindow.PDFViewerApplication = app; }
await check('native no-load switches after five seconds to bundled viewer with exact same encoded blob', async () => {
    const d = makeDialog(); assert.equal(d.state.src, 'blob:fixture-pdf'); assert.equal(d.state.compatible, false);
    await fireTimer(5000); assert.equal(d.state.compatible, true); assert.equal(d.state.ready, false);
    assert.equal(d.state.src, '/web/static/lib/pdfjs/web/viewer.html?file=blob%3Afixture-pdf#zoom=page-fit');
    assert.equal(createdURLs.length, 1); assert.equal(requests.length, 0);
    assert.deepEqual(hiddenButtons, [[frame, { hideDownload: true }]]);
    assert.equal([...timers.values()][0].delay, 30000);
});
await check('known unsupported native PDF viewer switches immediately without five-second timer', () => {
    navigatorStub.pdfViewerEnabled = false; const d = makeDialog(); assert.equal(d.state.compatible, true);
    assert.ok([...timers.values()].every(timer => timer.delay === 30000)); assert.equal(requests.length, 0);
});
await check('native readiness cancels automatic fallback and explicit alternative remains available', async () => {
    const d = makeDialog(); await d.onLoad(); assert.equal(d.state.ready, true); assert.equal(timers.size, 0);
    assert.equal(frame.printCalls, 1); d.useCompatible(); const src = d.state.src; d.useCompatible();
    assert.equal(d.state.src, src); assert.equal(d.state.ready, false); assert.equal(timers.size, 1);
    assert.match(xml, /t-on-click="useCompatible"/);
});
await check('alternative frame no-load timeout shows help and destroy clears both timers', async () => {
    const d = makeDialog(); d.useCompatible(); await fireTimer(30000);
    assert.equal(d.state.warning, d.labels.help); assert.equal(d.state.ready, false);
    destroyed.forEach(fn => fn()); assert.equal(timers.size, 0); assert.deepEqual(revokedURLs, ['blob:fixture-pdf']);
});
await check('compatible readiness awaits initializedPromise before pages and Print', async () => {
    const d = makeDialog(); d.useCompatible(); const initialized = deferred(); const app = appFixture(); app.initializedPromise = initialized.promise; attachApp(app);
    const loading = d.onLoad(); await flush(); assert.equal(d.state.ready, false); assert.equal(frame.printCalls, 0);
    initialized.resolve(); await loading; await flush(); assert.equal(d.state.ready, true); assert.equal(frame.printCalls, 1);
});
await check('documentloaded alone stays unready until pageViewsReady and pagesPromise complete', async () => {
    const d = makeDialog(); d.useCompatible(); const pages = deferred(); const app = appFixture();
    app.pdfViewer.pageViewsReady = false; app.pdfViewer.pagesPromise = pages.promise; attachApp(app); await d.onLoad();
    assert.equal(d.state.ready, false); assert.equal(frame.printCalls, 0); assert.equal(timers.size, 1);
    app.pdfViewer.pageViewsReady = true; await fireTimer(250); assert.equal(d.state.ready, false);
    pages.resolve(); await flush(); assert.equal(d.state.ready, true); assert.equal(frame.printCalls, 1);
});
await check('missing pdfDocument cannot authorize compatible Print', async () => {
    const d = makeDialog(); d.useCompatible(); const app = appFixture(); app.pdfDocument = null; attachApp(app); await d.onLoad();
    assert.equal(d.state.ready, false); assert.equal(frame.printCalls, 0); destroyed.forEach(fn => fn()); assert.equal(timers.size, 0);
});
await check('page readiness polling is bounded to 120 attempts at 250ms with help afterwards', async () => {
    const d = makeDialog(); d.useCompatible(); const app = appFixture(); app.pdfViewer.pageViewsReady = false; attachApp(app); await d.onLoad();
    let count = 0; while (timers.size && count < 125) { await fireTimer(250); count++; }
    assert.equal(count, 120); assert.equal(timers.size, 0); assert.equal(d.state.warning, d.labels.help); assert.equal(frame.printCalls, 0);
});
await check('destroy while awaiting initialization prevents delayed readiness or timers', async () => {
    const d = makeDialog(); d.useCompatible(); const initialized = deferred(); const app = appFixture(); app.initializedPromise = initialized.promise; attachApp(app);
    const pending = d.onLoad(); destroyed.forEach(fn => fn()); initialized.resolve(); await pending; await flush();
    assert.equal(d.state.ready, false); assert.equal(frame.printCalls, 0); assert.equal(timers.size, 0);
});
await check('destroy while awaiting pages makes continuation inert and clears frame source', async () => {
    const d = makeDialog(); d.useCompatible(); const pages = deferred(); const app = appFixture(); app.pdfViewer.pagesPromise = pages.promise; attachApp(app);
    await d.onLoad(); destroyed.forEach(fn => fn()); pages.resolve(); await flush();
    assert.equal(d.state.ready, false); assert.equal(frame.printCalls, 0); assert.equal(timers.size, 0); assert.deepEqual(frame.removed, ['src']);
});
await check('late scheduled poll after destruction cannot reschedule or print', async () => {
    const d = makeDialog(); d.useCompatible(); const app = appFixture(); app.pdfViewer.pageViewsReady = false; attachApp(app); await d.onLoad();
    const late = [...timers.values()][0].fn; destroyed.forEach(fn => fn()); late(); await flush();
    assert.equal(timers.size, 0); assert.equal(frame.printCalls, 0); d.print(); d.useCompatible(); assert.equal(frame.printCalls, 0);
});
await check('missing or rejected viewer initialization remains unready with download available', async () => {
    const d = makeDialog(); d.useCompatible(); await d.onLoad(); assert.equal(d.state.warning, d.labels.help);
    attachApp({ initializedPromise: Promise.reject(new Error('fixture init failure')) }); await d.onLoad();
    d.download(); assert.equal(downloads[0][0], d.props.blob); assert.equal(d.state.ready, false); assert.equal(requests.length, 0);
});
await check('rejected pages promise shows help without automatic printing', async () => {
    const d = makeDialog(); d.useCompatible(); const app = appFixture(); app.pdfViewer.pagesPromise = Promise.reject(new Error('fixture pages failure')); attachApp(app);
    await d.onLoad(); await flush(); assert.equal(d.state.warning, d.labels.help); assert.equal(d.state.ready, false); assert.equal(frame.printCalls, 0);
});
await check('Print guard enforces readiness and rechecks compatible page views at click time', async () => {
    const d = makeDialog(); d.print(); assert.equal(frame.printCalls, 0); d.useCompatible(); const app = appFixture(); let sidebar = 0; app.pdfSidebar.close = () => sidebar++; attachApp(app);
    await d.onLoad(); await flush(); assert.equal(sidebar, 1); const printed = frame.printCalls;
    app.pdfViewer.pageViewsReady = false; d.print(); assert.equal(frame.printCalls, printed); assert.equal(d.state.warning, d.labels.help);
});
await check('repeated compatible load events cannot auto-print twice after shared page promise', async () => {
    const d = makeDialog(); d.useCompatible(); const pages = deferred(); const app = appFixture(); app.pdfViewer.pagesPromise = pages.promise; attachApp(app);
    await d.onLoad(); await d.onLoad(); pages.resolve(); await flush(); assert.equal(frame.printCalls, 1);
});
await check('repeated compatible load events cannot orphan polling timer after destroy', async () => {
    const d = makeDialog(); d.useCompatible(); const app = appFixture(); app.pdfViewer.pageViewsReady = false; attachApp(app);
    await d.onLoad(); await d.onLoad(); destroyed.forEach(fn => fn()); assert.equal(timers.size, 0);
});

R.status = R.checks.every(check => check.passed) ? 'passed' : 'failed';
fs.writeFileSync('docs/build-governance/bp1-ui-checks.json', JSON.stringify(R, null, 2) + '\n');
console.log(`${R.checks.filter(check => check.passed).length}/${R.checks.length} BP1 checks ${R.status}`);
for (const check of R.checks.filter(check => !check.passed)) { console.error(check.name + '\n' + check.error); }
if (R.status !== 'passed') { process.exitCode = 1; }
