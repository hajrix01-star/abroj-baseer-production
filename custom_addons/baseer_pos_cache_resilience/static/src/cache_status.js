/** @odoo-module */

import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";

registry.category("services").add("baseer_pos_cache_status", {
    dependencies: ["notification"],
    start(env, { notification }) {
        const workers = navigator.serviceWorker;
        if (!workers) {
            return;
        }
        let warnedAt = 0;
        let sentController = null;
        let sentManifest = null;
        const sendManifest = () => {
            // Native registration sends to an installing worker. Use only the
            // active controller; never take over a cashier's running checkout.
            if (!workers.controller) {
                return;
            }
            try {
                const urls = JSON.parse(globalThis.odoo.urls_to_cache);
                urls.push("/web/static/lib/zxing-library/zxing-library.js");
                const signature = JSON.stringify(urls);
                if (sentController === workers.controller && sentManifest === signature) {
                    return;
                }
                workers.controller.postMessage({ type: "baseer-pos-cache-manifest", urls });
                sentController = workers.controller;
                sentManifest = signature;
            } catch {
                // Missing manifest must not prevent checkout or synchronization.
            }
        };
        workers.addEventListener("message", (event) => {
            if (event.source !== workers.controller || event.data?.type !== "baseer-pos-cache-incomplete") {
                return;
            }
            if (Date.now() - warnedAt < 5 * 60 * 1000) {
                return;
            }
            warnedAt = Date.now();
            notification.add(_t(
                "Some offline files could not be saved. Keep this register connected to the internet. Do not clear site data; contact your administrator if this warning returns."
            ), { type: "warning", sticky: true });
        });
        workers.addEventListener("controllerchange", sendManifest);
        workers.ready.then(sendManifest).catch(() => {});
        sendManifest();
    },
});
