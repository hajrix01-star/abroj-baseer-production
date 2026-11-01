/** @odoo-module */

import { Component, useState } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { Navbar } from "@point_of_sale/app/components/navbar/navbar";
import { ensureSessionReportSynced, reportJpeg } from "./session_report_flow";

export class BaseerCurrentSessionReport extends Component {
    static template = "baseer_pos_print_bridge.CurrentSessionReport";
    static props = { report: Object };
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
                const canvas = await this.pos.printer.renderer.toCanvas(
                    BaseerCurrentSessionReport, { report: attempt.report },
                    { addClass: "pos-receipt-print", pixelRatio: 2.2 }
                );
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
