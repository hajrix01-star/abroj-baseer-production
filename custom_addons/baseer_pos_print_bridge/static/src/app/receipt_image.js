/** @odoo-module */

import { _t } from "@web/core/l10n/translation";

// Safari's JPEG encoder may add EXIF to a canvas image. The server rejects
// EXIF metadata; remove only those APP1 segments without touching image data.
function stripReceiptExif(image) {
    const binary = atob(image);
    const invalid = () => new Error(_t("The browser could not create a JPEG receipt. Reload and retry."));
    if (binary.charCodeAt(0) !== 0xff || binary.charCodeAt(1) !== 0xd8) throw invalid();
    const parts = [binary.slice(0, 2)];
    let offset = 2;
    let removed = false;
    while (offset < binary.length) {
        const start = offset;
        if (binary.charCodeAt(offset++) !== 0xff) throw invalid();
        while (binary.charCodeAt(offset) === 0xff) offset++;
        const marker = binary.charCodeAt(offset++);
        if (marker === 0xda || marker === 0xd9) {
            parts.push(binary.slice(start));
            return removed ? btoa(parts.join("")) : image;
        }
        if (marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7)) {
            parts.push(binary.slice(start, offset));
            continue;
        }
        if (offset + 2 > binary.length) throw invalid();
        const length = binary.charCodeAt(offset) * 256 + binary.charCodeAt(offset + 1);
        const end = offset + length;
        if (length < 2 || end > binary.length) throw invalid();
        if (marker === 0xe1 && binary.slice(offset + 2, offset + 8) === "Exif\x00\x00") {
            removed = true;
        } else {
            parts.push(binary.slice(start, end));
        }
        offset = end;
    }
    throw invalid();
}

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
        const image = stripReceiptExif(url.slice("data:image/jpeg;base64,".length));
        const padding = image.endsWith("==") ? 2 : image.endsWith("=") ? 1 : 0;
        const bytes = image.length * 3 / 4 - padding;
        console.debug("Baseer receipt image sizing", JSON.stringify({width, height, quality, bytes, accepted: bytes > 0 && bytes <= 256 * 1024}));
        if (bytes > 0 && bytes <= 256 * 1024) return image;
    }
    throw new Error(_t("The receipt image exceeds 256 KB. Ask a manager to inspect it."));
}
