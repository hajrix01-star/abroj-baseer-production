import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const ORIGINAL = readFileSync(new URL("../src/service_worker.js", import.meta.url), "utf8");
const ORIGIN = "https://pos.example.test";
const CORE = "odoo-pos-cache";
const ABS = (url) => new URL(url, ORIGIN).href;
const req = (url, options) => new Request(ABS(url), options);

class FakeCache {
    entries = [];
    attempts = 0;
    beforePut = null;
    matches(stored, request) {
        if (stored.request.url !== request.url || stored.request.method !== request.method) {
            return false;
        }
        return (stored.response.headers.get("Vary") || "").split(",").map((field) => field.trim())
            .filter(Boolean).every((field) => stored.request.headers.get(field) === request.headers.get(field));
    }
    request(value) {
        return typeof value === "string" ? new Request(value) : value;
    }
    async keys(value) {
        return this.entries.filter((entry) => !value || this.matches(entry, this.request(value)))
            .map((entry) => entry.request.clone());
    }
    async match(value) {
        const entry = this.entries.find((candidate) => this.matches(candidate, this.request(value)));
        if (!entry) return undefined;
        const result = entry.response.clone();
        for (const flag of ["type", "redirected"]) {
            if (result[flag] !== entry.response[flag]) Object.defineProperty(result, flag, { value: entry.response[flag] });
        }
        return result;
    }
    async put(value, response) {
        const request = this.request(value);
        this.attempts++;
        await this.beforePut?.(request, response, this.attempts);
        const copy = new Response(await response.arrayBuffer(), { status: response.status, headers: response.headers });
        for (const flag of ["type", "redirected"]) {
            if (copy[flag] !== response[flag]) Object.defineProperty(copy, flag, { value: response[flag] });
        }
        this.entries = this.entries.filter((entry) => !this.matches(entry, request));
        this.entries.push({ request: request.clone(), response: copy });
    }
    async delete(value) {
        const previous = this.entries.length;
        this.entries = this.entries.filter((entry) => !this.matches(entry, this.request(value)));
        return previous !== this.entries.length;
    }
}

function environment({ source = ORIGINAL, caches: sharedCaches = new Map(), network, controlledIds = null } = {}) {
    const handlers = {};
    const notices = [];
    const calls = [];
    const sources = new Map([["cashier", { id: "cashier", url: ABS("/pos/ui/7"), postMessage: (data) => notices.push(data) }]]);
    const forbidden = new Proxy({}, { get() { throw new Error("Business storage must never be touched"); } });
    let fetcher = network || (() => new Response("resource"));
    const cacheStorage = {
        async open(name) {
            if (!sharedCaches.has(name)) {
                sharedCaches.set(name, new FakeCache());
            }
            return sharedCaches.get(name);
        },
        delete() { throw new Error("Whole cache deletion forbidden"); },
    };
    const context = {
        self: {
            location: { origin: ORIGIN },
            clients: {
                get: async (id) => sources.get(id),
                matchAll: async (options) => {
                    assert.notEqual(options?.includeUncontrolled, true, "never treat waiting-worker sources as controlled");
                    return [...sources.values()].filter((client) => controlledIds === null || controlledIds.includes(client.id));
                },
                claim() { throw new Error("No takeover"); },
            },
            addEventListener: (name, handler) => { handlers[name] = handler; },
            skipWaiting() { throw new Error("No forced activation"); },
        },
        caches: cacheStorage,
        fetch: async (request) => { calls.push(request.url); return fetcher(request); },
        Request, Response, URL, Map, Set, Date,
        indexedDB: forbidden, localStorage: forbidden, sessionStorage: forbidden,
        console: { info() {} },
    };
    vm.runInNewContext(source, context);
    return {
        handlers, notices, calls, sources, sharedCaches,
        setNetwork: (callback) => { fetcher = callback; },
        cache: (name = CORE) => cacheStorage.open(name),
        async request(url, options) {
            const tasks = [];
            let response;
            handlers.fetch({ request: req(url, options), respondWith: (value) => { response = value; }, waitUntil: (value) => tasks.push(value) });
            if (!response) {
                return { intercepted: false };
            }
            const result = await response;
            await Promise.all(tasks);
            return { intercepted: true, response: result };
        },
        async message(data, sourceId = "cashier") {
            const tasks = [];
            handlers.message({ data, source: { id: sourceId }, waitUntil: (value) => tasks.push(value) });
            await Promise.all(tasks);
        },
    };
}

const manifest = (urls) => ({ type: "baseer-pos-cache-manifest", urls });
const quotaError = () => Object.assign(new Error("quota"), { name: "QuotaExceededError" });
const tinyBudget = (bytes = 20, entries = 3, perEntry = 12) => ORIGINAL
    .replace("const MAX_BYTES = 128 * 1024 * 1024;", `const MAX_BYTES = ${bytes};`)
    .replace("const MAX_ENTRY_BYTES = 32 * 1024 * 1024;", `const MAX_ENTRY_BYTES = ${perEntry};`)
    .replace("const MAX_ENTRIES = 1024;", `const MAX_ENTRIES = ${entries};`);

test("online resources and no-store POS boot retain offline reload capability", async () => {
    const env = environment({ network: () => new Response("boot", { headers: { "Cache-Control": "no-store" } }) });
    const first = await env.request("/pos/ui/7?from_backend=True");
    assert.equal(await first.response.text(), "boot");
    env.setNetwork(() => { throw new TypeError("offline"); });
    assert.equal(await (await env.request("/pos/ui/7?from_backend=True")).response.text(), "boot");
    assert.equal(env.notices.length, 0);
});

test("API, print/download, foreign requests and POSTs are not intercepted", async () => {
    const env = environment();
    for (const url of ["/web/dataset/call_kw", "/report/pdf/account.report_invoice/1", "/pos/sale_details_report", "/web/content/9", "https://foreign.example/web/assets/x.js"]) {
        assert.equal((await env.request(url)).intercepted, false, url);
    }
    assert.equal((await env.request("/web/assets/x.js", { method: "POST", body: "data" })).intercepted, false);
    assert.equal(env.sharedCaches.size, 0);
});

test("runtime product images are not newly stored; legacy image works offline", async () => {
    const env = environment();
    const image = "/web/image/product.product/8/image_128";
    await env.request(image);
    assert.equal(env.sharedCaches.size, 0);
    await (await env.cache()).put(req(image), new Response("legacy-thumbnail"));
    env.setNetwork(() => { throw new Error("offline"); });
    assert.equal(await (await env.request(image)).response.text(), "legacy-thumbnail");
    await env.message(manifest(["/pos/ui/7"]));
    assert.ok(await (await env.cache()).match(req(image)), "offline bootstrap must not remove thumbnail");
});

test("online bootstrap removes only known product thumbnails, preserving other data", async () => {
    const env = environment();
    const cache = await env.cache();
    const preserved = ["/web/image/res.company/1/logo", "/web/image?model=res.partner&id=1&field=image_128", "/web/content/receipt.png", "/web/assets/old/app.js", "/pos/ui/2"];
    for (const url of preserved) {
        await cache.put(req(url), new Response("keep"));
    }
    const images = ["/web/image/product.product/8/image_128", "/web/image?model=product.template&id=2&field=image_512"];
    for (const url of images) {
        await cache.put(req(url), new Response("expendable"));
    }
    const other = await env.cache("unrelated-cache");
    await other.put(req("/private/sentinel"), new Response("untouched"));
    await env.request("/web/assets/new/app.js");
    for (const url of preserved) {
        assert.ok(await cache.match(req(url)), url);
    }
    for (const url of images) {
        assert.equal(await cache.match(req(url)), undefined, url);
    }
    assert.equal(await (await other.match(req("/private/sentinel"))).text(), "untouched");
});

test("quota retry uses fresh body even if first failed put consumed its body", async () => {
    const env = environment();
    const cache = await env.cache();
    cache.beforePut = async (request, response, attempt) => {
        if (attempt === 1) {
            await response.arrayBuffer();
            throw quotaError();
        }
    };
    assert.equal(await (await env.request("/web/assets/app.js")).response.text(), "resource");
    assert.equal(cache.attempts, 2);
    assert.equal(await (await cache.match(req("/web/assets/app.js"))).text(), "resource");
    assert.equal(env.notices.length, 0);
});

test("persistent quota errors never reject successful network responses and warn once", async () => {
    const env = environment();
    const cache = await env.cache();
    cache.beforePut = async (request, response) => { await response.arrayBuffer(); throw quotaError(); };
    for (const file of ["a", "b"]) {
        assert.equal(await (await env.request(`/web/assets/${file}.js`)).response.text(), "resource");
    }
    assert.equal(cache.attempts, 4);
    assert.equal(env.notices.length, 1);
    assert.equal(env.notices[0].type, "baseer-pos-cache-incomplete");
});

test("oversize core files and full legacy core are preserved via network without eviction", async () => {
    const env = environment({ source: tinyBudget(), network: () => new Response("x".repeat(30)) });
    const cache = await env.cache();
    await cache.put(req("/web/assets/legacy.js"), new Response("x".repeat(25)));
    assert.equal((await (await env.request("/web/assets/new.js")).response.text()).length, 30);
    assert.ok(await cache.match(req("/web/assets/legacy.js")));
    assert.equal(await cache.match(req("/web/assets/new.js")), undefined);
    assert.equal(env.notices.length, 1);
});

test("serialized concurrent writes respect byte and entry budgets", async () => {
    const env = environment({ source: tinyBudget(20, 3), network: () => new Response("12345678") });
    await Promise.all(["a", "b", "c", "d"].map((key) => env.request(`/web/assets/${key}.js`)));
    assert.equal((await (await env.cache()).keys()).length, 2);
    assert.equal(env.notices.length, 1);
    const entryBound = environment({ source: tinyBudget(100, 2), network: () => new Response("x") });
    await Promise.all(["a", "b", "c"].map((key) => entryBound.request(`/web/assets/${key}.js`)));
    assert.equal((await (await entryBound.cache()).keys()).length, 2);
});

test("Vary variants at the same URL count individually toward byte and entry budgets", async () => {
    const env = environment({ source: tinyBudget(20, 3), network: () => new Response("12345678", { headers: { Vary: "Accept-Language" } }) });
    await env.request("/web/assets/same.js", { headers: { "Accept-Language": "ar" } });
    await env.request("/web/assets/same.js", { headers: { "Accept-Language": "en" } });
    await env.request("/web/assets/same.js", { headers: { "Accept-Language": "fr" } });
    assert.equal((await (await env.cache()).keys()).length, 2);
    const restart = environment({ source: tinyBudget(20, 3), caches: env.sharedCaches, network: () => new Response("12345678") });
    await restart.request("/web/assets/new.js");
    assert.equal((await (await restart.cache()).keys()).length, 2, "bootstrap must count both same-URL variants");
});

test("manifest validates source, same origin, resource class and POS configuration", async () => {
    const env = environment();
    env.sources.set("backend", { id: "backend", url: ABS("/odoo"), postMessage() {} });
    await env.message(manifest(["/web/assets/invalid.js"]), "backend");
    assert.equal(env.calls.length, 0);
    await env.message(manifest(["/web/assets/valid.js", "/pos/ui/7", "/pos/ui/9", "/web/dataset/a", "/web/assets/huge.js?q=" + "x".repeat(2048), "https://foreign.example/web/assets/evil.js"]));
    assert.deepEqual(env.calls.sort(), [ABS("/pos/ui/7"), ABS("/web/assets/valid.js")].sort());
    const meta = await env.cache("baseer-pos-cache-metadata-v1");
    const stored = await (await meta.match(ABS("/pos/baseer-cache-state-v1"))).json();
    assert.deepEqual(stored.manifests["7"].sort(), env.calls.sort());
});

test("native messages targeting waiting workers do nothing; no forced lifecycle takeover", async () => {
    const env = environment();
    await env.message({ urlsToCache: ["/pos/ui/7", "/web/assets/old.js"] });
    assert.equal(env.calls.length, 0);
    assert.equal(env.sharedCaches.size, 0);
    assert.equal(env.handlers.install, undefined);
    assert.equal(env.handlers.activate, undefined);
});

test("failed, opaque, redirected and no-store nonboot responses never replace offline assets", async () => {
    for (const kind of ["failed", "opaque", "redirected", "no-store"]) {
        const response = new Response("skip", { status: kind === "failed" ? 500 : 200, headers: kind === "no-store" ? { "Cache-Control": "private, no-store" } : {} });
        if (kind === "opaque") Object.defineProperty(response, "type", { value: "opaque" });
        if (kind === "redirected") Object.defineProperty(response, "redirected", { value: true });
        // Node clone does not retain manually overridden flags; this test invokes
        // the same core saving function using the real marked response.
        const env = environment({ network: () => response });
        const cache = await env.cache();
        await cache.put(req("/web/assets/app.js"), new Response("old"));
        if (kind === "opaque" || kind === "redirected") {
            response.clone = () => response;
        }
        await env.request("/web/assets/app.js");
        assert.equal(await (await cache.match(req("/web/assets/app.js"))).text(), "old", kind);
    }
});

test("offline manifest retains already cached essentials and warns for missing boot files", async () => {
    const env = environment({ network: () => { throw new Error("offline"); } });
    const cache = await env.cache();
    await cache.put(req("/web/assets/app.js"), new Response("old-app"));
    await env.message(manifest(["/web/assets/app.js"]));
    assert.equal(env.notices.length, 0);
    await env.message(manifest(["/web/assets/app.js", "/pos/ui/7"]));
    assert.equal(env.notices.length, 1);
    assert.equal(await (await cache.match(req("/web/assets/app.js"))).text(), "old-app");
});

test("cache API failure does not interrupt online operation", async () => {
    const env = environment();
    const cache = await env.cache();
    cache.keys = async () => { throw new Error("storage unavailable"); };
    assert.equal(await (await env.request("/web/assets/app.js")).response.text(), "resource");
    assert.equal(env.notices.length, 1);
});

test("client sends one manifest per controller and throttles only trusted warnings", async () => {
    const clientSource = readFileSync(new URL("../src/cache_status.js", import.meta.url), "utf8")
        .replace(/^import .*;\r?\n/gm, "");
    const posts = [];
    const events = {};
    const notifications = [];
    let service;
    const controller = { postMessage: (data) => posts.push(data) };
    const workers = { controller, ready: Promise.resolve(), addEventListener: (name, callback) => { events[name] = callback; } };
    vm.runInNewContext(clientSource, {
        registry: { category: () => ({ add: (name, definition) => { service = definition; } }) },
        _t: (text) => text,
        navigator: { serviceWorker: workers },
        odoo: { urls_to_cache: JSON.stringify(["/pos/ui/7", "/web/assets/app.js"]) },
        Date,
    });
    service.start({}, { notification: { add: (...args) => notifications.push(args) } });
    await Promise.resolve();
    assert.equal(posts.length, 1, "ready and immediate start must not duplicate precache");
    events.controllerchange();
    assert.equal(posts.length, 1);
    events.message({ source: {}, data: { type: "baseer-pos-cache-incomplete" } });
    assert.equal(notifications.length, 0);
    events.message({ source: controller, data: { type: "baseer-pos-cache-incomplete" } });
    events.message({ source: controller, data: { type: "baseer-pos-cache-incomplete" } });
    assert.equal(notifications.length, 1);
    workers.controller = { postMessage: (data) => posts.push(data) };
    events.controllerchange();
    assert.equal(posts.length, 2, "new controller must receive current manifest");
});

const opaqueFont = () => {
    const response = new Response("font");
    Object.defineProperty(response, "type", { value: "opaque" });
    return response;
};

test("active online migration reclaims only evidenced foreign opaque font paths", async () => {
    const env = environment();
    const cache = await env.cache();
    const removable = [
        "https://fonts.odoocdn.com/fonts/noto/NotoSans-Regular.woff2",
        "https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=swap",
    ];
    const retainedOpaque = [
        "https://fonts.odoocdn.com/unknown/font.woff2",
        "https://fonts.googleapis.com/css2?family=OtherFont",
        "https://fonts.googleapis.com/css2?family=Inter&family=OtherFont",
        "https://unknown.example/fonts/noto/font.woff2",
        "http://fonts.odoocdn.com/fonts/noto/font.woff2",
        "https://fonts.odoocdn.com:8443/fonts/noto/font.woff2",
        "/web/assets/local-font.woff2",
    ];
    for (const url of [...removable, ...retainedOpaque]) {
        await cache.put(req(url), opaqueFont());
    }
    const nonopaque = "https://fonts.odoocdn.com/fonts/noto/Readable-Regular.woff2";
    await cache.put(req(nonopaque), new Response("readable font"));
    const unrelated = await env.cache("odoo-sw-cache");
    await unrelated.put(req(removable[0]), opaqueFont());
    await cache.put(req("/pos/ui/8"), new Response("previous POS boot"));
    await env.request("/web/assets/current.js");
    for (const url of removable) assert.equal(await cache.match(req(url)), undefined, url);
    for (const url of retainedOpaque) assert.ok(await cache.match(req(url)), url);
    assert.ok(await cache.match(req(nonopaque)));
    assert.ok(await unrelated.match(req(removable[0])));
    assert.equal(await (await cache.match(req("/pos/ui/8"))).text(), "previous POS boot");
});

test("offline manifest does not remove foreign opaque fonts", async () => {
    const env = environment({ network: () => { throw new Error("offline"); } });
    const cache = await env.cache();
    const font = "https://fonts.odoocdn.com/fonts/noto/NotoSans-Regular.woff2";
    await cache.put(req(font), opaqueFont());
    await env.message(manifest(["/pos/ui/7"]));
    assert.ok(await cache.match(req(font)));
});

test("waiting worker rejects even a forged new-format manifest before writes or cleanup", async () => {
    const env = environment({ controlledIds: [] });
    const cache = await env.cache();
    const font = "https://fonts.odoocdn.com/fonts/noto/NotoSans-Regular.woff2";
    await cache.put(req(font), opaqueFont());
    const attempts = cache.attempts;
    await env.message(manifest(["/pos/ui/7", "/web/assets/current.js"]));
    assert.ok(await cache.match(req(font)));
    assert.equal(cache.attempts, attempts);
    assert.equal(env.calls.length, 0);
    assert.equal(env.sharedCaches.has("baseer-pos-cache-metadata-v1"), false);
});
