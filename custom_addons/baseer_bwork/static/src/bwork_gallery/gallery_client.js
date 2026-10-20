/** @odoo-module **/
// Content reader belongs to BWork messaging; native admin metadata stays JS-free.

// One feature-local state owner, shared by the Owl action and focused tests.
// No disk storage, ORM source reads, receipts, or client-owned byte formatting.
export class GalleryClient {
    constructor(state, { fetcher = globalThis.fetch.bind(globalThis), urls = globalThis.URL } = {}) {
        this.state = state;
        this.fetcher = fetcher;
        this.urls = urls;
        this.sequence = 0;
        this.controller = null;
        this.disposed = false;
        this.retentionVersion = 0;
        this.csrfToken = null;
        this.watchTimer = null;
        this.watchController = null;
        this.focusListener = () => { void this.checkCurrentRoom(); };
    }

    reset() {
        if (this.disposed) return null;
        this.sequence++;
        this.controller?.abort();
        this.controller = new AbortController();
        this.clearPreview();
        this.state.message = null;
        this.state.preserveTargetId = null;
        this.state.opening = false;
        return this.sequence;
    }

    clearPreview() {
        if (this.state.preview?.url) this.urls.revokeObjectURL(this.state.preview.url);
        this.state.preview = null;
    }

    current(sequence) { return !this.disposed && sequence === this.sequence; }

    async get(path, sequence, binary = false) {
        if (!this.current(sequence)) return null;
        const response = await this.fetcher(path, {
            method: "GET", credentials: "same-origin", cache: "no-store",
            signal: this.controller.signal, redirect: "error",
        });
        if (!this.current(sequence)) return null;
        if (!response.ok) throw new Error(response.status === 403 || response.status === 401 ? "denied" : "unavailable");
        if (binary) {
            if (this.retentionVersion === 1) {
                const room = this.selectedRoom();
                const revision = response.headers?.get?.("X-BWork-Content-Revision");
                if (!room || revision !== String(room.content_revision)) throw new Error("unavailable");
            }
            const blob = await response.blob();
            if (!this.current(sequence)) return null;
            if (!blob.size || blob.size > 10 * 1024 * 1024) throw new Error("unavailable");
            return blob;
        }
        const raw = await response.text();
        if (!this.current(sequence)) return null;
        if (new TextEncoder().encode(raw).length > 128 * 1024) throw new Error("unavailable");
        return JSON.parse(raw);
    }

    selectedRoom() { return this.state.rooms.find(value => String(value.id) === String(this.state.roomId)); }

    validRooms(rooms) {
        return Array.isArray(rooms) && rooms.length <= 100 && rooms.every(room =>
            Number.isSafeInteger(room.id) && room.id > 0 &&
            Number.isSafeInteger(room.membership_id) && room.membership_id > 0 &&
            Number.isSafeInteger(room.company_id) && room.company_id > 0 &&
            (this.retentionVersion !== 1 || (Number.isSafeInteger(room.content_revision) && room.content_revision >= 0)));
    }

    sameRevision(payload, room) {
        return this.retentionVersion !== 1 || (room && Number.isSafeInteger(payload.content_revision) &&
            payload.content_revision >= 0 && payload.content_revision === room.content_revision);
    }

    startWatching() {
        if (this.disposed || this.watchTimer !== null) return;
        // Read-only metadata polling, not message receipts or a second cache.
        this.watchTimer = globalThis.setInterval(() => { void this.checkCurrentRoom(); }, 15000);
        globalThis.addEventListener?.("focus", this.focusListener);
    }

    async checkCurrentRoom() {
        const room = this.selectedRoom();
        if (this.disposed || !room || this.state.loading || this.state.opening || this.watchController) return;
        const sequence = this.sequence;
        const controller = new AbortController();
        this.watchController = controller;
        try {
            const response = await this.fetcher("/bwork/api/v2/rooms", {
                method: "GET", credentials: "same-origin", cache: "no-store", redirect: "error", signal: controller.signal,
            });
            if (!this.current(sequence)) return;
            if (!response.ok) throw new Error(response.status === 401 || response.status === 403 ? "denied" : "unavailable");
            const raw = await response.text();
            if (!this.current(sequence)) return;
            if (new TextEncoder().encode(raw).length > 128 * 1024) throw new Error("unavailable");
            const page = JSON.parse(raw);
            if (page.api_version !== 2 || !this.validRooms(page.rooms)) throw new Error("unavailable");
            const next = page.rooms.find(value => value.id === room.id);
            if (!next || next.membership_id !== room.membership_id || next.company_id !== room.company_id) {
                this.fail(new Error("denied"), sequence);
                return;
            }
            if (this.retentionVersion === 1 && next.content_revision !== room.content_revision) {
                // Invalidate ObjectURLs, original-message text and page rows
                // before exposing anything from the changed server snapshot.
                this.reset();
                Object.assign(this.state, { rooms: page.rooms, items: [], cursor: null, error: "" });
                await this.loadPage();
            } else if (this.state.error === "unavailable") {
                this.state.rooms = page.rooms;
                await this.loadPage();
            } else {
                this.state.rooms = page.rooms;
            }
        } catch (error) {
            if (this.current(sequence) && error.name !== "AbortError") {
                // Once a revision-aware check fails, do not leave an old
                // binary preview open under uncertain server authorization.
                this.clearPreview();
                this.state.message = null;
                if (error.message === "denied") this.fail(error, sequence);
                else if (this.retentionVersion === 1) this.fail(new Error("unavailable"), sequence);
            }
        } finally { if (this.watchController === controller) this.watchController = null; }
    }

    fail(error, sequence) {
        if (!this.current(sequence) || error.name === "AbortError") return;
        this.clearPreview();
        this.state.message = null;
        this.state.items = [];
        this.state.cursor = null;
        this.state.error = error.message === "denied" ? "denied" : "unavailable";
        if (error.message === "denied") {
            this.state.rooms = [];
            this.state.roomId = "";
        }
    }

    async loadRooms() {
        if (this.disposed) return;
        const sequence = this.reset();
        Object.assign(this.state, { loading: true, error: "", items: [], cursor: null, roomId: "", rooms: [] });
        try {
            const bootstrap = await this.get("/bwork/api/v2/bootstrap", sequence);
            if (!bootstrap || !this.current(sequence)) return;
            if (!bootstrap.permissions?.chat_view || !bootstrap.permissions?.media) throw new Error("denied");
            if (bootstrap.capabilities?.media_gallery_version !== 1) throw new Error("unavailable");
            const retention = bootstrap.capabilities?.retention_version;
            if (retention !== undefined && retention !== 1) throw new Error("unavailable");
            this.retentionVersion = retention === 1 ? 1 : 0;
            this.csrfToken = typeof bootstrap.csrf_token === "string" && bootstrap.csrf_token.length <= 4096 ? bootstrap.csrf_token : null;
            this.state.canManageRetention = bootstrap.capabilities?.can_manage_retention === true;
            const page = await this.get("/bwork/api/v2/rooms", sequence);
            if (!page || !this.current(sequence)) return;
            if (page.api_version !== 2 || !this.validRooms(page.rooms) ||
                page.rooms.some(room => !Number.isSafeInteger(room.id) || room.id <= 0 ||
                    !Number.isSafeInteger(room.membership_id) || room.membership_id <= 0 ||
                    !bootstrap.company_ids.includes(room.company_id))) throw new Error("unavailable");
            this.state.rooms = page.rooms;
        } catch (error) { this.fail(error, sequence); }
        finally { if (this.current(sequence)) this.state.loading = false; }
    }

    async loadPage(next = false) {
        if (this.disposed) return;
        const room = this.state.rooms.find(value => String(value.id) === String(this.state.roomId));
        const cursor = next ? this.state.cursor : null;
        const sequence = this.reset();
        Object.assign(this.state, { loading: !!room, error: "", items: [], cursor: null });
        if (!room || (next && !cursor)) return;
        try {
            const query = new URLSearchParams({ kind: this.state.kind, order: this.state.order, limit: "30" });
            const search = (this.state.search || "").trim();
            if (search.length > 64 || new TextEncoder().encode(search).length > 128) throw new Error("unavailable");
            if (search) query.set("q", search);
            if (cursor) query.set("cursor", cursor);
            const page = await this.get(`/bwork/api/v2/rooms/${room.id}/media?${query}`, sequence);
            if (!page || !this.current(sequence)) return;
            if (page.api_version !== 2 || !this.sameRevision(page, room) || page.gallery_version !== 1 || page.room_id !== room.id ||
                page.company_id !== room.company_id || page.membership_id !== room.membership_id ||
                page.kind !== this.state.kind || page.order !== this.state.order ||
                !Array.isArray(page.items) || page.items.length > 60 ||
                (page.next_cursor !== null && (typeof page.next_cursor !== "string" || !page.next_cursor.length || page.next_cursor.length > 256)) ||
                page.items.some(row => !Number.isSafeInteger(row.id) || row.id <= 0 ||
                    !Number.isSafeInteger(row.author_user_id) || row.author_user_id <= 0 ||
                    !row.media || !Number.isSafeInteger(row.media.id) || row.media.id <= 0 ||
                    !["image", "file", "audio"].includes(row.media.kind) ||
                    !Number.isSafeInteger(row.media.size) || row.media.size <= 0 ||
                    typeof row.media.name !== "string" || typeof row.media.size_label !== "string")) throw new Error("unavailable");
            this.state.items = page.items;
            this.state.cursor = page.next_cursor;
        } catch (error) { this.fail(error, sequence); }
        finally { if (this.current(sequence)) this.state.loading = false; }
    }

    async open(row) {
        if (this.disposed) return;
        const sequence = this.reset();
        this.state.error = "";
        this.state.opening = true;
        try {
            // Rows are never arbitrary paths; existing content route rechecks
            // membership, company, permission, inverse links and visibility.
            if (!this.state.items.includes(row)) throw new Error("unavailable");
            const blob = await this.get(`/bwork/api/v2/media/${row.media.id}/content`, sequence, true);
            if (!blob || !this.current(sequence)) return;
            if (blob.size !== row.media.size) throw new Error("unavailable");
            const url = this.urls.createObjectURL(blob);
            this.state.preview = { url, kind: row.media.kind, name: row.media.name };
        } catch (error) { this.fail(error, sequence); }
        finally { if (this.current(sequence)) this.state.opening = false; }
    }

    async message(row) {
        if (this.disposed) return;
        const sequence = this.reset();
        this.state.error = "";
        try {
            const room = this.state.rooms.find(value => String(value.id) === String(this.state.roomId));
            if (!room || !this.state.items.includes(row)) throw new Error("unavailable");
            const value = await this.get(`/bwork/api/v2/rooms/${room.id}/messages/${row.id}`, sequence);
            if (!value || !this.current(sequence)) return;
            if (value.api_version !== 2 || !this.sameRevision(value, room) || value.message?.id !== row.id) throw new Error("unavailable");
            this.state.message = value.message;
        } catch (error) { this.fail(error, sequence); }
    }

    requestPreserve(row) {
        if (this.disposed || !this.state.canManageRetention || !this.state.items.includes(row)) return;
        if (row.retention_preserved === true) this.state.preserveTargetId = row.id;
        else return this.preserve(row, true);
    }

    cancelPreserve() { this.state.preserveTargetId = null; }

    async preserve(row, preserved) {
        if (this.disposed || !this.state.canManageRetention || !this.csrfToken || !this.state.items.includes(row)) return;
        // Removing a hold needs a second, explicit action. A UI flag never
        // replaces the backend permission/current-membership checks.
        if (!preserved && this.state.preserveTargetId !== row.id) return;
        const room = this.selectedRoom();
        if (!room) return;
        const sequence = this.reset();
        this.state.opening = true;
        this.state.error = "";
        try {
            const body = new URLSearchParams({ csrf_token: this.csrfToken, payload: JSON.stringify({
                api_version: 2, membership_id: room.membership_id, preserved,
            }) });
            const response = await this.fetcher(`/bwork/api/v2/rooms/${room.id}/messages/${row.id}/preserve`, {
                method: "POST", credentials: "same-origin", cache: "no-store", redirect: "error", body, signal: this.controller.signal,
            });
            if (!this.current(sequence)) return;
            if (!response.ok) throw new Error(response.status === 403 || response.status === 401 ? "denied" : "unavailable");
            const raw = await response.text();
            if (!this.current(sequence)) return;
            if (new TextEncoder().encode(raw).length > 128 * 1024) throw new Error("unavailable");
            const result = JSON.parse(raw);
            if (result.api_version !== 2 || result.room_id !== room.id || result.company_id !== room.company_id ||
                result.membership_id !== room.membership_id || !this.sameRevision(result, room) ||
                result.message?.id !== row.id || result.message.retention_preserved !== preserved ||
                result.message.media?.id !== row.media.id) throw new Error("unavailable");
            this.state.items = this.state.items.map(item => item.id === row.id ? result.message : item);
        } catch (error) { this.fail(error, sequence); }
        finally { if (this.current(sequence)) this.state.opening = false; }
    }

    dispose() {
        if (this.disposed) return;
        if (this.watchTimer !== null) globalThis.clearInterval(this.watchTimer);
        this.watchTimer = null;
        this.watchController?.abort();
        this.watchController = null;
        globalThis.removeEventListener?.("focus", this.focusListener);
        this.reset();
        this.disposed = true;
        this.csrfToken = null;
        Object.assign(this.state, { items: [], rooms: [], roomId: "", cursor: null, loading: false, error: "" });
    }
}
