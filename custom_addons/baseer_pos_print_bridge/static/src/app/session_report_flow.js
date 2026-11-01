/** @odoo-module */

import { _t } from "@web/core/l10n/translation";

// Sync completed financial operations only. An unfinished basket is not a sale.
function completedPending(pos) {
    const pending = pos.getPendingOrder();
    return [...new Set([...pending.orderToCreate, ...pending.orderToUpdate])].filter(
        (order) => order.finalized || ["paid", "done", "invoiced", "cancel"].includes(order.state)
    );
}

export async function ensureSessionReportSynced(pos) {
    if (pos.data.network.offline) {
        throw new Error(_t("Reconnect before printing the current session report."));
    }
    // Native syncAllOrders also processes deletions, even with an explicit order
    // list. Do not let a reporting action delete or synchronize an active basket.
    if (pos.getOrderIdsToDelete().length || pos.syncingOrders.size || pos.data.network.unsyncData.length) {
        throw new Error(_t("Wait for pending operations to synchronize, then print the session report."));
    }
    const orders = completedPending(pos);
    if (orders.length) {
        await pos.syncAllOrders({ orders, throw: true });
    }
    if (pos.data.network.offline || completedPending(pos).length || pos.syncingOrders.size
            || pos.getOrderIdsToDelete().length || pos.data.network.unsyncData.length) {
        throw new Error(_t("Some operations have not synchronized. The session report was not printed."));
    }
}

export function reportJpeg(renderedCanvas) {
    const canvas = document.createElement("canvas");
    canvas.width = 576;
    canvas.height = Math.max(1, Math.round(renderedCanvas.height * canvas.width / renderedCanvas.width));
    const context = canvas.getContext("2d", { alpha: false });
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.imageSmoothingEnabled = true;
    context.imageSmoothingQuality = "high";
    context.drawImage(renderedCanvas, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/jpeg", 0.95).replace("data:image/jpeg;base64,", "");
}
