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
    }

    reset() {
        if (this.disposed) return null;
        this.sequence++;
        this.controller?.abort();
        this.controller = new AbortController();
        this.clearPreview();
        this.state.message = null;
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
            const bootstrap = await this.get("/bchat/api/v2/bootstrap", sequence);
            if (!bootstrap || !this.current(sequence)) return;
            if (!bootstrap.permissions?.chat_view || !bootstrap.permissions?.media) throw new Error("denied");
            if (bootstrap.capabilities?.media_gallery_version !== 1) throw new Error("unavailable");
            const page = await this.get("/bchat/api/v2/rooms", sequence);
            if (!page || !this.current(sequence)) return;
            if (page.api_version !== 2 || !Array.isArray(page.rooms) || page.rooms.length > 100 ||
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
            if (cursor) query.set("cursor", cursor);
            const page = await this.get(`/bchat/api/v2/rooms/${room.id}/media?${query}`, sequence);
            if (!page || !this.current(sequence)) return;
            if (page.api_version !== 2 || page.gallery_version !== 1 || page.room_id !== room.id ||
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
            const blob = await this.get(`/bchat/api/v2/media/${row.media.id}/content`, sequence, true);
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
            const value = await this.get(`/bchat/api/v2/rooms/${room.id}/messages/${row.id}`, sequence);
            if (!value || !this.current(sequence)) return;
            if (value.api_version !== 2 || value.message?.id !== row.id) throw new Error("unavailable");
            this.state.message = value.message;
        } catch (error) { this.fail(error, sequence); }
    }

    dispose() {
        if (this.disposed) return;
        this.reset();
        this.disposed = true;
        Object.assign(this.state, { items: [], rooms: [], roomId: "", cursor: null, loading: false, error: "" });
    }
}
