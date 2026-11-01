/** @odoo-module */

import { Component, useState } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { Navbar } from "@point_of_sale/app/components/navbar/navbar";
import { toCanvas } from "@point_of_sale/app/utils/html-to-image";
import { ensureSessionReportSynced, reportJpeg } from "./session_report_flow";

export class BaseerCurrentSessionReport extends Component {
    static template = "baseer_pos_print_bridge.CurrentSessionReport";
    static props = { report: Object };
}

function sanitizeReportText(node) {
    // Preserve the native renderer's SVG/XML text sanitation when using its
    // lower-level image utility. This only touches the report's mounted copy.
    if (node.nodeType === Node.TEXT_NODE) {
        node.textContent = node.textContent.replace(/[\x00-\x08\x0B\x0C\x0E-\x1F]/g, ""); // eslint-disable-line no-control-regex
        return;
    }
    for (const child of node.childNodes) sanitizeReportText(child);
}

export async function renderCurrentSessionReport(renderer, report) {
    const el = await renderer.toHtml(BaseerCurrentSessionReport, { report });
    el.classList.add("pos-receipt-print");
    sanitizeReportText(el);
    // Odoo's renderer.toCanvas wrapper does not forward skipFonts and fixes
    // pixelRatio to 1. Use its public mounting API and native image utility
    // for this system-font-only report; other receipts remain unchanged.
    return renderer.whenMounted({
        el,
        callback: (node) => toCanvas(node, {
            backgroundColor: "#ffffff",
            width: Math.ceil(node.clientWidth),
            height: Math.ceil(node.clientHeight),
            pixelRatio: 2.2,
            includeQueryParams: true,
            skipFonts: true,
        }),
    });
}

patch(Navbar.prototype, {
    setup() {
        super.setup(...arguments);
        this.baseerSessionReport = useState({ busy: false });
        this.baseerReportAttempt = null;
    },

    async baseerPrintCurrentSession() {
        if (this.baseerSessionReport.busy) return;
        this.baseerSessionReport.busy = true;
        try {
            await ensureSessionReportSynced(this.pos);
            // Keep the original signed snapshot and raster through a network
            // retry. The server's idempotency key prevents a duplicate print.
            if (!this.baseerReportAttempt || this.baseerReportAttempt.expires_at <= Date.now() / 1000) {
                this.baseerReportAttempt = await this.pos.data.call(
                    "pos.session", "baseer_prepare_current_report", [[this.pos.session.id]]
                );
            }
            const attempt = this.baseerReportAttempt;
            if (!attempt.image) {
                const canvas = await renderCurrentSessionReport(this.pos.printer.renderer, attempt.report);
                attempt.image = reportJpeg(canvas);
            }
            const result = await this.pos.data.call(
                "pos.session", "baseer_enqueue_current_report",
                [[this.pos.session.id], attempt.token, attempt.image]
            );
            this.baseerReportAttempt = null;
            this.pos.notification.add(
                result.state === "done"
                    ? _t("The session report was already accepted by Windows.")
                    : _t("The current session report is queued for printing."),
                { type: "success" }
            );
        } catch (error) {
            this.pos.notification.add(
                error?.data?.message || error.message || _t("The session report could not be printed."),
                { type: "warning" }
            );
        } finally {
            this.baseerSessionReport.busy = false;
        }
    },
});
