/** @odoo-module **/

import { onWillUnmount, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { FloorScreen } from "@pos_restaurant/app/screens/floor_screen/floor_screen";
import { baseerTableHasContent } from "./table_availability";


function asMilliseconds(value) {
    if (!value) {
        return null;
    }
    if (typeof value.toMillis === "function") {
        return value.toMillis();
    }
    if (value instanceof Date) {
        return value.getTime();
    }
    const parsed = Date.parse(value);
    return Number.isFinite(parsed) ? parsed : null;
}


patch(FloorScreen.prototype, {
    setup() {
        super.setup(...arguments);
        this.baseerTableClock = useState({ now: Date.now() });
        this.baseerTableClockTimer = setInterval(() => {
            this.baseerTableClock.now = Date.now();
        }, 1000);
        onWillUnmount(() => clearInterval(this.baseerTableClockTimer));
    },

    _baseerTablesInGroup(table) {
        const result = [];
        const visit = (candidate) => {
            result.push(candidate);
            for (const child of candidate.children || []) {
                visit(child);
            }
        };
        visit(table.rootTable || table);
        return result;
    },

    baseerTableUsage(table) {
        if (!table || table.parent_id || this.pos.isEditMode) {
            return null;
        }
        const startedAt = this._baseerTablesInGroup(table)
            .flatMap((candidate) => candidate.getOrders().filter((order) => !order.finalized && baseerTableHasContent(order)))
            .map((order) => asMilliseconds(order.date_order))
            .filter(Number.isFinite)
            .reduce((oldest, value) => Math.min(oldest, value), Number.POSITIVE_INFINITY);
        if (!Number.isFinite(startedAt)) {
            return null;
        }
        const elapsedSeconds = Math.max(0, Math.floor((this.baseerTableClock.now - startedAt) / 1000));
        const hours = Math.floor(elapsedSeconds / 3600);
        const minutes = Math.floor((elapsedSeconds % 3600) / 60);
        const seconds = elapsedSeconds % 60;
        const duration = `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
        return {
            duration,
            label: _t("Table use duration %s", duration),
        };
    },
});
