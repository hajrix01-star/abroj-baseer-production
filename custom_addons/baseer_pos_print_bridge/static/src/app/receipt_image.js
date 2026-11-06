/** @odoo-module */

import { _t } from "@web/core/l10n/translation";

// Match the server's bounded JPEG contract. Preserve the print-head width;
// compress bytes, never crop the receipt or silently remove fiscal content.
export function encodeReceiptJpeg(renderedCanvas, createCanvas = () => document.createElement("canvas")) {
    const width = 576;
    if (!(renderedCanvas.width > 0 && renderedCanvas.height > 0)) {
        throw new Error(_t("The receipt could not be rendered. Reload the receipt and retry."));
    }
    const height = Math.max(1, Math.round(renderedCanvas.height * width / renderedCanvas.width));
    if (height > 12000 || width * height > 5000000) {
        throw new Error(_t("The receipt exceeds the supported print length. Ask a manager to inspect it."));
    }
    const canvas = createCanvas();
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d", { alpha: false });
    if (!context) throw new Error(_t("The receipt image could not be created. Reload and retry."));
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, width, height);
    context.imageSmoothingEnabled = true;
    context.imageSmoothingQuality = "high";
    context.drawImage(renderedCanvas, 0, 0, width, height);
    for (const quality of [0.95, 0.9, 0.85, 0.8]) {
        const url = canvas.toDataURL("image/jpeg", quality);
        if (!url.startsWith("data:image/jpeg;base64,")) {
            throw new Error(_t("The browser could not create a JPEG receipt. Reload and retry."));
        }
        const image = url.slice("data:image/jpeg;base64,".length);
        const padding = image.endsWith("==") ? 2 : image.endsWith("=") ? 1 : 0;
        const bytes = image.length * 3 / 4 - padding;
        console.debug("Baseer receipt image sizing", JSON.stringify({width, height, quality, bytes, accepted: bytes > 0 && bytes <= 256 * 1024}));
        if (bytes > 0 && bytes <= 256 * 1024) return image;
    }
    throw new Error(_t("The receipt image exceeds 256 KB. Ask a manager to inspect it."));
}
