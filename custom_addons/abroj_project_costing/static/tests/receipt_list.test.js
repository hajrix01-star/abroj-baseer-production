/** @odoo-module **/

import { expect, test } from "@odoo/hoot";
import { AbrojReceiptListField } from "@abroj_project_costing/js/receipt_list";


test.tags("desktop");
test("clicking a saved receipt row uses the same action as the eye button", async () => {
    const receiptAction = { type: "ir.actions.act_window", res_id: 42 };
    const context = {
        orm: {
            async call(model, method, args) {
                expect(model).toBe("abroj.cost.receipt");
                expect(method).toBe("action_open_receipt_view");
                expect(args).toEqual([[42]]);
                return receiptAction;
            },
        },
        action: {
            async doAction(action) {
                expect(action).toBe(receiptAction);
                expect.step("read-only receipt opened");
            },
        },
    };

    await AbrojReceiptListField.prototype.openRecord.call(context, { resId: 42 });
    expect.verifySteps(["read-only receipt opened"]);
});
