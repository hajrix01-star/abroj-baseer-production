/** @odoo-module */

import { PosStore } from "@point_of_sale/app/services/pos_store";
import { ask } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

patch(PosStore.prototype, {
    async closeSession() {
        if (this.config.baseer_zatca_phase2_enabled) {
            const status = await this.data.call("pos.session", "baseer_zatca_phase2_status", [
                this.session.id,
            ]);
            const summary = _t("زاتكا: مُرحّل %s، معلّق %s، أخطاء %s.", status.sent, status.pending, status.error);
            if (status.pending || status.error) {
                const proceed = await ask(this.dialog, {
                    title: _t("زاتكا تحتاج إلى متابعة"),
                    body: summary,
                    confirmLabel: _t("المتابعة لاحقًا والاستمرار"),
                    cancelLabel: _t("البقاء في الكاشير"),
                });
                if (!proceed) {
                    return;
                }
            } else {
                this.notification.add(summary, { type: "success" });
            }
        }
        return super.closeSession(...arguments);
    },
});
