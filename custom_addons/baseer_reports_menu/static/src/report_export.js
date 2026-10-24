/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { download } from "@web/core/network/download";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";

const COPY = {
    ar: { title: "تصدير التقرير", busy: "جارٍ التصدير…", excel: "Excel", pdf: "PDF",
        error: "تعذر تصدير التقرير. حدّثه، وجرّب فترة أقصر أو مقارنات أقل، وتحقق من الصلاحيات ثم أعد المحاولة." },
    en: { title: "Export report", busy: "Exporting…", excel: "Excel", pdf: "PDF",
        error: "Could not export the report. Refresh it, try a shorter period or fewer comparisons, and check your access before retrying." },
};

export class ReportExportButtons extends Component {
    static template = "baseer_reports_menu.ExportButtons";
    static props = {
        reportKey: String, filters: { type: Object, optional: true },
        disabled: { type: Boolean, optional: true }, lang: { type: String, optional: true },
    };

    setup() {
        this.state = useState({ busy: false });
        this.notification = useService("notification");
    }

    get labels() { return COPY[this.props.lang === "ar" ? "ar" : "en"]; }
    get disabled() { return this.state.busy || this.props.disabled || !this.props.filters; }

    async exportFile(format) {
        if (this.disabled || !["xlsx", "pdf"].includes(format)) { return; }
        const companyId = Number(user.activeCompany?.id) || 0;
        if (this.props.filters.company_id !== companyId) { return; }
        const filters = JSON.stringify(this.props.filters);
        this.state.busy = true;
        try {
            await download({ url: "/baseer/reports/export", data: {
                report_key: this.props.reportKey, file_format: format, filters,
            } });
        } catch {
            this.notification.add(this.labels.error, { type: "danger" });
        } finally {
            this.state.busy = false;
        }
    }
}
