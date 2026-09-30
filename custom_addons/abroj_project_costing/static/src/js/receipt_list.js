/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { X2ManyField, x2ManyField } from "@web/views/fields/x2many/x2many_field";


export class AbrojReceiptListField extends X2ManyField {
    setup() {
        super.setup();
        this.orm = useService("orm");
    }

    async openRecord(record) {
        if (!record.resId) {
            return super.openRecord(record);
        }
        // The native x2many row dialog does not mount the receipt's custom form
        // controller. Use the same action as the eye button for saved receipts.
        const action = await this.orm.call(
            "abroj.cost.receipt", "action_open_receipt_view", [[record.resId]]
        );
        return this.action.doAction(action);
    }
}

registry.category("fields").add("abroj_receipt_list", {
    ...x2ManyField,
    component: AbrojReceiptListField,
});
