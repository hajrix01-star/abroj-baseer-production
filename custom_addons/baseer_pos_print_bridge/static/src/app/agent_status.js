/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { Navbar } from "@point_of_sale/app/components/navbar/navbar";
import { onWillStart, onWillUnmount, useState } from "@odoo/owl";

const POLL_INTERVAL_MS = 5000;

patch(Navbar.prototype, {
    setup() {
        super.setup(...arguments);
        this.baseerAgentStatus = useState({
            state: "loading",
            configured: false,
            repair_uri_allowed: false,
        });
        // The POS DataService toggles the global network indicator on every
        // call.  This independent heartbeat must not make the POS header flicker.
        this.baseerOrm = useService("orm");
        this.baseerAgentStatusTimer = null;
        onWillStart(() => this._baseerRefreshAgentStatus());
        onWillUnmount(() => clearTimeout(this.baseerAgentStatusTimer));
    },

    async _baseerRefreshAgentStatus() {
        if (!this.pos.config.baseer_direct_print_enabled) {
            Object.assign(this.baseerAgentStatus, {
                state: "disabled",
                configured: false,
                repair_uri_allowed: false,
            });
            return;
        }
        try {
            const status = await this.baseerOrm.call(
                "pos.config",
                "baseer_agent_status",
                [this.pos.config.id],
                {}
            );
            Object.assign(this.baseerAgentStatus, status || { state: "unknown" });
        } catch {
            // A POS network failure must not be presented as a local agent
            // failure.  The native network indicator remains the authority for
            // connectivity; this only says the health query was unavailable.
            Object.assign(this.baseerAgentStatus, {
                state: "unknown",
                configured: true,
                repair_uri_allowed: false,
            });
        } finally {
            clearTimeout(this.baseerAgentStatusTimer);
            this.baseerAgentStatusTimer = setTimeout(
                () => this._baseerRefreshAgentStatus(),
                POLL_INTERVAL_MS
            );
        }
    },

    baseerOpenAgentRepair() {
        if (this.baseerAgentStatus.repair_uri_allowed) {
            // This literal custom URI is registered by the one-time Windows
            // installer.  Do not append a server, path, token or user input.
            window.location.assign("baseer-print://repair");
        }
    },

    get baseerAgentStatusLabel() {
        return {
            online: _t("متصل"),
            stale: _t("جارٍ الاتصال"),
            offline: _t("إصلاح الطباعة"),
            unconfigured: _t("إعداد الطباعة"),
        }[this.baseerAgentStatus.state] || _t("فحص الاتصال");
    },

    get baseerAgentStatusTitle() {
        return {
            online: _t("وكيل الطباعة متصل"),
            stale: _t("جارٍ التحقق من اتصال وكيل الطباعة"),
            offline: _t("وكيل الطباعة غير متصل، اختر إصلاح الطباعة"),
            unconfigured: _t("وكيل الطباعة يحتاج إعدادًا"),
        }[this.baseerAgentStatus.state] || _t("تعذر التحقق من حالة وكيل الطباعة");
    },
});
