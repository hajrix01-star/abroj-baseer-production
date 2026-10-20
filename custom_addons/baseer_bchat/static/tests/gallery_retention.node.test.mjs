import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(new URL("../src/bwork_gallery/gallery_client.js", import.meta.url), "utf8");
const { GalleryClient } = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
const room = { id: 5, company_id: 2, membership_id: 11, name: "Own room", content_revision: 2 };
const row = { id: 8, author_user_id: 7, author_name: "Reader", text: "caption", retention_preserved: false,
    created_at: "2026-10-20 10:00:00", media: { id: 12, kind: "file", size: 3, name: "x.txt", size_label: "3 B" } };
const page = { api_version: 2, gallery_version: 1, room_id: 5, company_id: 2, membership_id: 11,
    content_revision: 2, kind: "all", order: "newest", items: [row], next_cursor: null };
const json = value => ({ ok: true, text: async () => JSON.stringify(value) });
function harness(fetcher) {
    const state = { rooms: [room], roomId: "5", kind: "all", order: "newest", search: "", items: [row],
        cursor: null, loading: false, opening: false, error: "", preview: null, message: null,
        canManageRetention: false, preserveTargetId: null };
    const revoked = [], created = [];
    const client = new GalleryClient(state, { fetcher, urls: {
        createObjectURL: () => { created.push("blob:test"); return "blob:test"; },
        revokeObjectURL: value => revoked.push(value),
    } });
    client.retentionVersion = 1;
    return { state, client, revoked, created };
}
function deferred() { let resolve; const promise = new Promise(value => { resolve = value; }); return { resolve, promise }; }

test("revision-aware bootstrap rejects missing, rollback-shaped and malformed room revisions", async () => {
    for (const revision of [undefined, -1, "2", true, Number.MAX_SAFE_INTEGER + 1]) {
        const h = harness(async path => json(path.endsWith("bootstrap") ? {
            company_ids: [2], csrf_token: "test-csrf", permissions: { chat_view: true, media: true },
            capabilities: { media_gallery_version: 1, retention_version: 1 },
        } : { api_version: 2, rooms: [{ ...room, content_revision: revision }] }));
        await h.client.loadRooms();
        assert.deepEqual(h.state.items, []);
        assert.deepEqual(h.state.rooms, []);
        assert.equal(h.state.error, "unavailable");
    }
});

test("changed or missing history/detail revisions cannot expose stale rows or quoted text", async () => {
    for (const revision of [undefined, 1, 3]) {
        const h = harness(async () => json({ ...page, content_revision: revision, message: row }));
        await h.client.loadPage();
        assert.deepEqual(h.state.items, []);
        h.state.items = [row];
        await h.client.message(row);
        assert.equal(h.state.message, null);
        assert.deepEqual(h.state.items, []);
    }
});

test("protected binary needs the exact content revision before creating a blob URL", async () => {
    for (const revision of [null, "1", "3", "02"]) {
        const h = harness(async () => ({ ok: true, headers: { get: () => revision }, blob: async () => new Blob(["abc"]) }));
        await h.client.open(row);
        assert.deepEqual(h.created, []);
        assert.equal(h.state.preview, null);
    }
    const h = harness(async () => ({ ok: true, headers: { get: () => "2" }, blob: async () => new Blob(["abc"]) }));
    await h.client.open(row);
    assert.deepEqual(h.created, ["blob:test"]);
});

test("metadata poll revokes open ObjectURLs and old quotes before loading the new revision", async () => {
    const seen = [];
    let h;
    h = harness(async path => {
        seen.push(path);
        if (path.endsWith("/rooms")) return json({ api_version: 2, rooms: [{ ...room, content_revision: 3 }] });
        assert.equal(h.state.preview, null);
        assert.equal(h.state.message, null);
        assert.deepEqual(h.state.items, []);
        return json({ ...page, content_revision: 3, items: [] });
    });
    h.state.preview = { url: "blob:old" };
    h.state.message = { ...row, text: "old quote" };
    await h.client.checkCurrentRoom();
    assert.deepEqual(h.revoked, ["blob:old"]);
    assert.deepEqual(h.state.items, []);
    assert.equal(h.state.rooms[0].content_revision, 3);
    assert.equal(seen.length, 2);
});

test("late room-metadata response is fenced by a changed view and disposed watchers cannot fetch", async () => {
    const wait = deferred();
    let calls = 0;
    const h = harness(async () => { calls++; return wait.promise; });
    const polling = h.client.checkCurrentRoom();
    h.client.reset();
    h.state.roomId = "9";
    wait.resolve(json({ api_version: 2, rooms: [{ ...room, content_revision: 3 }] }));
    await polling;
    assert.equal(h.state.roomId, "9");
    assert.equal(h.state.rooms[0].content_revision, 2);
    h.client.dispose();
    await h.client.checkCurrentRoom();
    assert.equal(calls, 1);
});

test("literal filename query is encoded and cannot change filters or cursor", async () => {
    let requested;
    const h = harness(async path => { requested = path; return json(page); });
    h.state.search = "a_%&cursor=private";
    await h.client.loadPage();
    const query = new URL(requested, "https://example.invalid").searchParams;
    assert.equal(query.get("q"), "a_%&cursor=private");
    assert.equal(query.get("cursor"), null);
    assert.equal(query.get("kind"), "all");
});

test("server hold needs capability and CSRF; removing it requires explicit second action", async () => {
    const calls = [];
    const h = harness(async (path, options) => {
        const payload = JSON.parse(options.body.get("payload"));
        calls.push({ path, options, payload });
        assert.equal(options.body.get("csrf_token"), "test-csrf");
        return json({ api_version: 2, room_id: 5, company_id: 2, membership_id: 11, content_revision: 2,
            message: { ...row, retention_preserved: payload.preserved } });
    });
    await h.client.requestPreserve(row);
    assert.equal(calls.length, 0);
    h.state.canManageRetention = true;
    await h.client.requestPreserve(row);
    assert.equal(calls.length, 0);
    h.client.csrfToken = "test-csrf";
    await h.client.requestPreserve(row);
    assert.equal(calls.length, 1);
    assert.equal(h.state.items[0].retention_preserved, true);
    const held = h.state.items[0];
    await h.client.preserve(held, false);
    assert.equal(calls.length, 1);
    await h.client.requestPreserve(held);
    assert.equal(h.state.preserveTargetId, row.id);
    assert.equal(calls.length, 1);
    await h.client.preserve(held, false);
    assert.equal(calls.length, 2);
    assert.equal(h.state.items[0].retention_preserved, false);
    assert.ok(calls.every(call => call.options.method === "POST" && call.options.credentials === "same-origin"));
});

test("scope or revision mismatch on hold response clears untrusted media", async () => {
    const h = harness(async () => json({ api_version: 2, room_id: 5, company_id: 999, membership_id: 11,
        content_revision: 2, message: { ...row, retention_preserved: true } }));
    h.state.canManageRetention = true; h.client.csrfToken = "test-csrf";
    await h.client.preserve(row, true);
    assert.deepEqual(h.state.items, []);
    assert.equal(h.state.error, "unavailable");
});
