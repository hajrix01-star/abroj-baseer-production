# POS cache resilience and official receipt fixes

Version 19.0.1.0.2 ports Odoo 19.0 fd7af53e (2026-10-02) and 1fe5b09b
(2026-11-17) to the pinned 19.0-20260817 runtime. Existing numbering format,
UUID identity, payments and the Docker image remain unchanged. Retained/synced
receipt numbers are removed from the device reuse stack before allocation and
after sync. Genuine released numbers remain reusable, matching upstream.

The native critical-error recovery asset is replaced, retaining its original
named-module alias and cleanup flow. Only localStorage cleanup changes: preserve
device_uuid and every *-unique_device_identifier key without snapshot/restore.
Normal reloadData in the pinned image does not clear localStorage and is untouched.
Native critical recovery STILL deletes IndexedDB/session/cache state; do not use
it to recover unsynchronized sales. Existing duplicates are not renumbered.

Focused tests:

```
node --test custom_addons/baseer_pos_cache_resilience/static/tests/*.test.mjs
```

## Existing service-worker scope

Replaces only the body of Odoo's authenticated `/pos/service-worker.js` endpoint.
Keeps its `/pos` scope, existing `odoo-pos-cache`, and normal service-worker
activation. The service-worker component does not change orders, IndexedDB, local/session storage, cookies,
print agents, other caches, or the installed worker registration.

New writes are limited to same-origin POS boot documents and static assets.
Budget: 128 MiB measured response payloads, 1024 stored request variants,
32 MiB per response. These are conservative application limits, **not browser
disk/quota measurements**. Browser quota failure is separately caught and retried
once; online responses always remain usable. Current core assets are never
evicted to accommodate a new file. A warning says to remain online if required
files cannot be saved.

Legacy migration inventories cache bodies sequentially with bounded read memory.
After the first successful core network fetch it removes only positively
identified product/product-template thumbnails and **opaque** responses from
`https://fonts.odoocdn.com/fonts/noto/` or the Inter stylesheet at
`https://fonts.googleapis.com/css2`. These foreign fonts are not reachable through
the new worker's same-origin offline fallback. Other foreign responses (including
nonopaque fonts and unknown opaque resources) remain untouched. Company logos, receipt images,
boot documents and old asset generations are retained. It does not newly cache
product thumbnails; offline products can therefore lack pictures. Financial
offline data is unaffected. Unknown oversized legacy entries are preserved;
when they exhaust the budget new caching stops and the warning appears. The
first slice deliberately does not retire old core generations automatically.

The POS warning service sends the current native manifest **to the active
controller only**. The worker additionally verifies that the sending client is
controlled by that worker, using `clients.matchAll` without uncontrolled clients.
Native messages and forged new-format messages to installing/waiting workers do
not initiate cleanup or writes.
There is no forced update, refresh, `skipWaiting` or `clients.claim`. Existing
tabs keep their current worker until normal lifecycle handover (close old POS
tabs normally once, after synchronization, at rollout). The new behavior then
applies automatically; do not clear business storage to activate it.

Tests:

```
node --test custom_addons/baseer_pos_cache_resilience/static/tests/cache_resilience.test.mjs
odoo ... -i baseer_pos_cache_resilience --test-enable --test-tags=/baseer_pos_cache_resilience --stop-after-init
```

The original screenshot's 377 MiB cannot be assigned to individual URLs after
that cache was removed. Subsequent QA inspection found 121 opaque external font
entries in `odoo-pos-cache`, with Chrome showing about 941 MiB cache usage despite
only about 55 MiB of readable response sizes. Chrome documents approximately
7 MiB minimum quota padding for each opaque cached response:
https://developer.chrome.com/docs/workbox/caching-resources-during-runtime/
The native worker's broad GET caching created these entries; the new worker does
not cache them and its focused migration removes only the evidenced font paths.
This is not a claim that the original Doha error stack was recovered. Browser QA must still validate
normal worker handover, offline boot and printing; Node mocks do not replace it.
