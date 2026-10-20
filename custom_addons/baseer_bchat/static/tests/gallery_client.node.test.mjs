import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(new URL("../src/bwork_gallery/gallery_client.js", import.meta.url), "utf8");
const { GalleryClient } = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
const room = { id: 5, company_id: 2, membership_id: 11, name: "Own room" };
const row = { id: 8, author_user_id: 7, author_name: "Reader", text: "caption", created_at: "2026-10-20 10:00:00",
    media: { id: 12, kind: "file", size: 3, name: "x.txt", size_label: "3 B" } };
const page = { api_version: 2, gallery_version: 1, room_id: 5, company_id: 2, membership_id: 11,
    kind: "all", order: "newest", items: [row], next_cursor: null };
function harness(fetcher) {
    const state = { rooms: [room], roomId: "5", kind: "all", order: "newest", items: [row],
        cursor: null, loading: false, opening: false, error: "", preview: null, message: null };
    const revoked = [], created = [];
    const urls = { createObjectURL: () => { created.push("blob:test"); return "blob:test"; },
        revokeObjectURL: value => revoked.push(value) };
    return { state, revoked, created, client: new GalleryClient(state, { fetcher, urls }) };
}
const json = value => ({ ok: true, text: async () => JSON.stringify(value) });
function deferred() { let resolve; const promise = new Promise(value => { resolve = value; }); return { resolve, promise }; }

test("native gallery uses same-session GET and only own-member room route", async () => {
    const calls = [];
    const h = harness(async (path, options) => {
        calls.push({ path, options });
        return json(path.endsWith("bootstrap") ? { permissions: { chat_view: true, media: true },
            capabilities: { media_gallery_version: 1 }, company_ids: [2] } : { api_version: 2, rooms: [room] });
    });
    await h.client.loadRooms();
    assert.deepEqual(h.state.rooms, [room]);
    assert.deepEqual(calls.map(item => item.path), ["/bchat/api/v2/bootstrap", "/bchat/api/v2/rooms"]);
    assert.ok(calls.every(({ options }) => options.method === "GET" && options.credentials === "same-origin" && options.cache === "no-store"));
    assert.ok(!calls.some(({ path }) => path.includes("admin")));
});

test("page scope mismatch and denial clear content without raw error text", async () => {
    for (const response of [json({ ...page, membership_id: 99 }), { ok: false, status: 403 }]) {
        const h = harness(async () => response);
        h.state.preview = { url: "blob:old" };
        await h.client.loadPage();
        assert.deepEqual(h.state.items, []);
        assert.equal(h.state.preview, null);
        assert.deepEqual(h.revoked, ["blob:old"]);
        assert.ok(["unavailable", "denied"].includes(h.state.error));
        if (h.state.error === "denied") assert.deepEqual(h.state.rooms, []);
    }
});

test("late old-room page cannot revive after newer filter response", async () => {
    const hold = deferred();
    let calls = 0;
    const h = harness(async () => ++calls === 1 ? hold.promise : json({ ...page, kind: "image", items: [] }));
    const first = h.client.loadPage();
    h.state.kind = "image";
    await h.client.loadPage();
    hold.resolve(json(page));
    await first;
    assert.deepEqual(h.state.items, []);
    assert.equal(h.state.kind, "image");
    assert.equal(h.state.loading, false);
});

test("content blob is released on scope reset or unmount; stale download never creates one", async () => {
    const h = harness(async () => ({ ok: true, blob: async () => new Blob(["abc"]) }));
    await h.client.open(row);
    assert.equal(h.state.preview.url, "blob:test");
    h.client.dispose();
    assert.deepEqual(h.revoked, ["blob:test"]);
    const hold = deferred();
    const late = harness(async () => hold.promise);
    const opening = late.client.open(row);
    late.client.dispose();
    hold.resolve({ ok: true, blob: async () => new Blob(["abc"]) });
    await opening;
    assert.deepEqual(late.created, []);
    assert.equal(late.state.opening, false);
});

test("gallery next page and exact message read never post receipt or history", async () => {
    const calls = [];
    const h = harness(async path => { calls.push(path); return json(path.includes("/messages/") ? { api_version: 2, message: row } : page); });
    h.state.cursor = "scopeCursor";
    await h.client.loadPage(true);
    assert.match(calls[0], /cursor=scopeCursor/);
    await h.client.message(h.state.items[0]);
    assert.equal(calls[1], "/bchat/api/v2/rooms/5/messages/8");
    assert.equal(h.state.message.id, 8);
    assert.ok(!calls.some(path => /receipt|history|read_ack/.test(path)));
});

test("unknown capability, network failure and no-member rooms are honest empty/error states", async () => {
    for (const capability of [undefined, 1]) {
        const h = harness(async path => json(path.endsWith("bootstrap") ? { permissions: { chat_view: true, media: true },
            capabilities: { media_gallery_version: capability }, company_ids: [2] } : { api_version: 2, rooms: [] }));
        await h.client.loadRooms();
        assert.deepEqual(h.state.rooms, []);
        assert.equal(h.state.error, capability ? "" : "unavailable");
    }
    const h = harness(async () => { throw new Error("private server/network details"); });
    await h.client.loadPage();
    assert.equal(h.state.error, "unavailable");
    assert.deepEqual(h.state.items, []);
});

test("retained callbacks after unmount cannot start HTTP or revive any preview", async () => {
    let requests = 0;
    const h = harness(async () => { requests++; return json(page); });
    h.client.dispose();
    assert.deepEqual(h.state.items, []);
    assert.deepEqual(h.state.rooms, []);
    const before = structuredClone(h.state);
    await h.client.loadRooms();
    await h.client.loadPage();
    await h.client.open(row);
    await h.client.message(row);
    await h.client.get('/bchat/api/v2/media/12/content', h.client.sequence, true);
    assert.equal(requests, 0);
    assert.deepEqual(h.created, []);
    assert.deepEqual(h.state, before);
});
