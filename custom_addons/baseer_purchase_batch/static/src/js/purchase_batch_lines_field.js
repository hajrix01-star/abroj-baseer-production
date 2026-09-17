/** @odoo-module **/

import { registry } from "@web/core/registry";
import { X2ManyField, x2ManyField } from "@web/views/fields/x2many/x2many_field";

/**
 * The core one2many widget creates an inline row immediately.  That works for
 * an existing batch, but a brand-new batch has no database id for the row to
 * reference yet.  Persist the harmless draft first, then hand the interaction
 * straight back to the native Odoo inline-row flow.
 *
 * An empty draft is never financially effective: approval still requires at
 * least one valid invoice row server-side.
 */
export class PurchaseBatchLinesField extends X2ManyField {
    async onAdd(params = {}) {
        if (!this.props.record.resId) {
            const saved = await this.props.record.save({ reload: false });
            if (!saved) {
                return;
            }
        }
        return super.onAdd(params);
    }
}

registry.category("fields").add("baseer_purchase_batch_lines", {
    ...x2ManyField,
    component: PurchaseBatchLinesField,
});
