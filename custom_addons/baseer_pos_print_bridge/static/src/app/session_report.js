/** @odoo-module */

import { Component, useState } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { Dialog } from "@web/core/dialog/dialog";
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

export class BaseerCurrentSessionReportDialog extends Component {
    static template = "baseer_pos_print_bridge.CurrentSessionReportDialog";
    static components = { Dialog, BaseerCurrentSessionReport };
    static props = { close: Function, pos: Object, snapshot: Object };

    setup() {
        this.state = useState({ snapshot: this.props.snapshot, busy: false, printed: false, error: null });
        this.reportImage = null;
    }

    get title() {
        return _t("Current session report");
    }

    async refreshReport() {
        if (this.state.busy) return;
        this.state.busy = true;
        this.state.error = null;
        try {
            await ensureSessionReportSynced(this.props.pos);
            const snapshot = await this.props.pos.data.call(
                "pos.session", "baseer_prepare_current_report", [[this.props.pos.session.id]]
            );
            this.state.snapshot = snapshot;
            this.reportImage = null;
            this.state.printed = false;
        } catch (error) {
            this.state.error = error?.data?.message || error.message || _t("The session report could not be loaded.");
        } finally {
            this.state.busy = false;
        }
    }

    async printReport() {
        if (this.state.busy || this.state.printed || !this.state.snapshot.print_available) return;
        this.state.busy = true;
        this.state.error = null;
        try {
            const snapshot = this.state.snapshot;
            if (snapshot.expires_at <= Date.now() / 1000) {
                throw new Error(_t("This preview has expired. Refresh the report before printing."));
            }
            await ensureSessionReportSynced(this.props.pos);
            // Print only the figures currently visible. Never refresh amounts
            // silently on Print, and keep this raster/token on a network retry.
            if (!this.reportImage) {
                const canvas = await renderCurrentSessionReport(this.props.pos.printer.renderer, snapshot.report);
                this.reportImage = reportJpeg(canvas);
            }
            await this.props.pos.data.call(
                "pos.session", "baseer_enqueue_current_report",
                [[this.props.pos.session.id], snapshot.token, this.reportImage]
            );
            this.state.printed = true;
        } catch (error) {
            this.state.error = error?.data?.message || error.message || _t("The session report could not be printed.");
        } finally {
            this.state.busy = false;
        }
    }
}

patch(Navbar.prototype, {
    setup() {
        super.setup(...arguments);
        this.baseerSessionReport = useState({ busy: false });
    },

    async baseerViewCurrentSession() {
        if (this.baseerSessionReport.busy) return;
        this.baseerSessionReport.busy = true;
        try {
            await ensureSessionReportSynced(this.pos);
            const snapshot = await this.pos.data.call(
                "pos.session", "baseer_prepare_current_report", [[this.pos.session.id]]
            );
            this.dialog.add(BaseerCurrentSessionReportDialog, { pos: this.pos, snapshot });
        } catch (error) {
            this.pos.notification.add(
                error?.data?.message || error.message || _t("The session report could not be loaded."),
                { type: "warning" }
            );
        } finally {
            this.baseerSessionReport.busy = false;
        }
    },
});
