/** @odoo-module **/
// Registered by the optional BWork administration integration.
import { Component, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { GalleryClient } from "./gallery_client";

export class BWorkMediaGallery extends Component {
    static template = "baseer_bwork_admin.MediaGallery";
    static props = ["*"];

    setup() {
        this.state = useState({ rooms: [], roomId: "", kind: "all", order: "newest", items: [],
            cursor: null, loading: false, opening: false, error: "", preview: null, message: null });
        this.client = new GalleryClient(this.state);
        onWillStart(() => this.client.loadRooms());
        onWillUnmount(() => this.client.dispose());
    }
    get errorText() {
        return this.state.error === "denied" ? _t("Media access is unavailable. Refresh your authorized rooms.")
            : _t("Could not load media. Try again when connected.");
    }
    changeRoom(event) { this.state.roomId = event.target.value; return this.client.loadPage(); }
    changeKind(event) { this.state.kind = event.target.value; return this.client.loadPage(); }
    changeOrder(event) { this.state.order = event.target.value; return this.client.loadPage(); }
    refresh() { return this.client.loadRooms(); }
    next() { return this.client.loadPage(true); }
    first() { return this.client.loadPage(); }
    closePreview() { this.client.reset(); }
}
registry.category("actions").add("baseer_bwork_admin.media_gallery", BWorkMediaGallery);
