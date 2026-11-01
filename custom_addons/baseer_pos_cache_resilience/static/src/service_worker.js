// @odoo-module ignore
/* global self, caches, fetch, Request, Response, URL */
/* eslint-disable no-restricted-globals */

// Payload bytes are an engineering budget, not the browser's actual disk usage.
// Native POS IndexedDB, local/session storage and other applications are untouched.
const CACHE_NAME = "odoo-pos-cache";
const META_NAME = "baseer-pos-cache-metadata-v1";
const META_URL = new URL("/pos/baseer-cache-state-v1", self.location.origin).href;
const MAX_BYTES = 128 * 1024 * 1024;
const MAX_ENTRY_BYTES = 32 * 1024 * 1024;
const MAX_ENTRIES = 1024;
const MAX_MANIFEST_URLS = 128;
let serialized = Promise.resolve();
let inventory = null;
let manifests = {};
let lastWarning = 0;
let legacyCleaned = false;

function enqueue(operation) {
    const result = serialized.then(operation);
    serialized = result.catch(() => {});
    return result;
}

function entryKey(request) {
    // Vary can retain several responses for one URL. Count each stored request,
    // not just URL strings, and ask Cache API which variants a put replaces.
    return JSON.stringify([request.url, request.method, [...request.headers.entries()]]);
}

function parsedUrl(value) {
    try {
        if (typeof value !== "string" || value.length > 2048) {
            return null;
        }
        const url = new URL(value, self.location.origin);
        return url.origin === self.location.origin && !url.username && !url.password ? url : null;
    } catch {
        return null;
    }
}

function isBootUrl(url) {
    return /^\/pos\/ui\/\d+$/.test(url.pathname) &&
        [...url.searchParams.keys()].every((key) => key === "from_backend" || key === "debug");
}

function isCoreUrl(url) {
    if (!url) {
        return false;
    }
    return isBootUrl(url) || url.pathname.startsWith("/web/assets/") ||
        /^\/[a-zA-Z0-9_]+\/static\//.test(url.pathname);
}

function isProductThumbnail(url) {
    if (!url) {
        return false;
    }
    // Never delete company logos, customer images, receipt rasters or documents.
    if (/^\/web\/image\/(product\.product|product\.template)\/\d+\/image_(128|256|512|1024|1920)(\/[^/]*)?$/.test(url.pathname)) {
        return true;
    }
    return url.pathname === "/web/image" &&
        ["product.product", "product.template"].includes(url.searchParams.get("model")) &&
        /^\d+$/.test(url.searchParams.get("id") || "") &&
        /^image_(128|256|512|1024|1920)$/.test(url.searchParams.get("field") || "");
}

function isLegacyForeignFont(value) {
    try {
        const url = new URL(value);
        if (url.protocol !== "https:" || url.origin === self.location.origin || url.username || url.password) {
            return false;
        }
        if (url.hostname === "fonts.odoocdn.com") {
            return url.port === "" && url.pathname.startsWith("/fonts/noto/");
        }
        if (url.hostname === "fonts.googleapis.com" && url.port === "" && url.pathname === "/css2") {
            const families = url.searchParams.getAll("family");
            return families.length > 0 && families.every((family) => /^Inter(?::|$)/.test(family));
        }
    } catch {
        // Unknown legacy URLs are preserved rather than guessed safe to remove.
    }
    return false;
}

async function measure(response, limit) {
    if (!response?.body) {
        return 0;
    }
    const reader = response.body.getReader();
    let size = 0;
    try {
        while (true) {
            const chunk = await reader.read();
            if (chunk.done) {
                return size;
            }
            size += chunk.value.byteLength;
            if (size > limit) {
                // Do not await cancellation of one branch of a tee'd response.
                reader.cancel().catch(() => {});
                return limit + 1;
            }
        }
    } finally {
        reader.releaseLock();
    }
}

async function warnIncomplete() {
    if (Date.now() - lastWarning < 5 * 60 * 1000) {
        return;
    }
    lastWarning = Date.now();
    try {
        const clients = await self.clients.matchAll({ type: "window" });
        for (const client of clients) {
            client.postMessage({ type: "baseer-pos-cache-incomplete" });
        }
    } catch {
        // Storage diagnostics are never a checkout failure.
    }
    console.info("Baseer POS offline resource cache is incomplete; network access is required.");
}

async function persistManifests() {
    const metadata = await caches.open(META_NAME);
    await metadata.put(META_URL, new Response(JSON.stringify({ version: 1, manifests }), {
        headers: { "Content-Type": "application/json" },
    }));
}

async function initialize(cache) {
    if (inventory) {
        return;
    }
    inventory = new Map();
    try {
        const metadata = await caches.open(META_NAME);
        const stored = await metadata.match(META_URL);
        const state = stored ? await stored.json() : null;
        if (state?.version === 1 && state.manifests && typeof state.manifests === "object") {
            // Metadata carries only bounded core URLs; no order/customer payloads.
            for (const [key, urls] of Object.entries(state.manifests).slice(0, 32)) {
                if (/^\d+$/.test(key) && Array.isArray(urls)) {
                    manifests[key] = urls.slice(0, MAX_MANIFEST_URLS).filter((url) => isCoreUrl(parsedUrl(url)));
                }
            }
        }
    } catch {
        // Inventory always comes from the actual cache, not stale metadata.
    }
    try {
        for (const request of await cache.keys()) {
            const response = await cache.match(request);
            if (response) {
                inventory.set(entryKey(request), await measure(response, MAX_BYTES));
            }
        }
    } catch (error) {
        inventory = null;
        throw error;
    }
}

async function removeLegacyResources(cache) {
    for (const request of await cache.keys()) {
        let removable = isProductThumbnail(parsedUrl(request.url));
        if (!removable && isLegacyForeignFont(request.url)) {
            const response = await cache.match(request);
            // Native POS cached no-cors fonts with browser quota padding. These
            // foreign URLs cannot be read by this worker's same-origin fallback.
            removable = response?.type === "opaque";
        }
        if (removable) {
            await cache.delete(request);
            inventory?.delete(entryKey(request));
        }
    }
}

async function saveResource(request, response) {
    const url = parsedUrl(request.url);
    if (!isCoreUrl(url) || !response.ok || response.redirected || response.type === "opaque") {
        return false;
    }
    // Keep the native POS boot offline contract; never cache no-store elsewhere.
    if (!isBootUrl(url) && /no-store/i.test(response.headers.get("Cache-Control") || "")) {
        return false;
    }
    return enqueue(async () => {
        try {
            const cache = await caches.open(CACHE_NAME);
            await initialize(cache);
            if (!legacyCleaned) {
                // Only after a successful network fetch; never clean during an
                // offline bootstrap where old thumbnails can still be useful.
                await removeLegacyResources(cache);
                legacyCleaned = true;
            }
            const size = await measure(response.clone(), MAX_ENTRY_BYTES);
            const replacedKeys = (await cache.keys(request)).map(entryKey);
            const previous = replacedKeys.reduce((sum, key) => sum + (inventory.get(key) || 0), 0);
            const total = [...inventory.values()].reduce((sum, value) => sum + value, 0);
            if (size > MAX_ENTRY_BYTES || total - previous + size > MAX_BYTES ||
                inventory.size - replacedKeys.length + 1 > MAX_ENTRIES) {
                await warnIncomplete();
                return false;
            }
            try {
                await cache.put(request, response.clone());
            } catch (error) {
                if (error?.name !== "QuotaExceededError") {
                    throw error;
                }
                await removeLegacyResources(cache);
                await cache.put(request, response.clone());
            }
            for (const key of replacedKeys) {
                inventory.delete(key);
            }
            inventory.set(entryKey(request), size);
            return true;
        } catch {
            await warnIncomplete();
            return false;
        }
    });
}

async function networkOrCache(event) {
    const request = event.request;
    const url = parsedUrl(request.url);
    try {
        const response = await fetch(request);
        // Keep the lifetime open for the serialized write, not the network response.
        if (isCoreUrl(url)) {
            event.waitUntil(saveResource(request, response.clone()));
        }
        return response;
    } catch (error) {
        try {
            const cache = await caches.open(CACHE_NAME);
            const response = await cache.match(request);
            if (response) {
                return response;
            }
        } catch {
            // Preserve a real network error if no usable offline copy exists.
        }
        throw error;
    }
}

async function cacheManifest(event) {
    // A page can explicitly post to an installing/waiting worker. Only a client
    // actually controlled by THIS worker may initiate cache writes or migration.
    // Default includeUncontrolled=false is essential to the handover boundary.
    const controlledClients = await self.clients.matchAll({ type: "window" });
    if (!event.source?.id || !controlledClients.some((client) => client.id === event.source.id)) {
        return;
    }
    const client = event.source?.id ? await self.clients.get(event.source.id) : null;
    const sourceUrl = client && parsedUrl(client.url);
    const config = sourceUrl?.pathname.match(/^\/pos\/ui\/(\d+)(?:\/|$)/)?.[1];
    const supplied = event.data.urls;
    if (!config || !Array.isArray(supplied) || supplied.length > MAX_MANIFEST_URLS) {
        return;
    }
    const urls = [...new Set(supplied.map((value) => typeof value === "string" ? parsedUrl(value) : null)
        .filter((url) => isCoreUrl(url) && (!isBootUrl(url) || url.pathname === `/pos/ui/${config}`))
        .map((url) => url.href))];
    if (!urls.length) {
        return;
    }
    await enqueue(async () => {
        const cache = await caches.open(CACHE_NAME);
        await initialize(cache);
        if (Object.hasOwn(manifests, config) || Object.keys(manifests).length < 32) {
            manifests[config] = urls;
            await persistManifests();
        }
    }).catch(warnIncomplete);
    // Sequential precache avoids a burst of large bundle downloads/response clones.
    for (const url of urls) {
        try {
            const request = new Request(url, { credentials: "same-origin" });
            if (!isBootUrl(parsedUrl(url))) {
                const existing = await caches.open(CACHE_NAME).then((cache) => cache.match(request));
                if (existing) {
                    continue;
                }
            }
            const response = await fetch(request);
            if (!await saveResource(request, response)) {
                await warnIncomplete();
            }
        } catch {
            const cached = await caches.open(CACHE_NAME).then((cache) => cache.match(url)).catch(() => null);
            if (!cached) {
                await warnIncomplete();
            }
        }
    }
}

self.addEventListener("fetch", (event) => {
    if (event.request.method !== "GET") {
        return;
    }
    const url = parsedUrl(event.request.url);
    if (isCoreUrl(url) || isProductThumbnail(url)) {
        event.respondWith(networkOrCache(event));
    }
});

self.addEventListener("message", (event) => {
    // Odoo's original message can target a WAITING worker: do not act on it.
    if (event.data?.type === "baseer-pos-cache-manifest") {
        event.waitUntil(cacheManifest(event).catch(warnIncomplete));
    }
});

// Deliberately no skipWaiting(), clients.claim(), forced refresh or blanket delete.
// Old boot documents and asset generations remain until safely retired separately.
