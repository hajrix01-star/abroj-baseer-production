import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";
import { useEffect, useState } from "@odoo/owl";
import { formatFloat } from "@web/views/fields/formatters";

class VoucherListController extends ListController {
    static template = "abroj_contracting.VoucherList";
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.summary = useState({ received: 0, paid: 0, balance: 0 });
        this.summaryRequest = 0;
        useEffect(() => {
            const request = ++this.summaryRequest;
            const domain = this.model.root.domain || [];
            this.orm.call("abroj.contracting.voucher", "abroj_voucher_summary", [domain]).then(result => {
                if (request === this.summaryRequest) Object.assign(this.summary, result);
            });
        }, () => [JSON.stringify(this.model.root.domain)]);
    }
    formatSummary(value) { return formatFloat(value, { digits: [16, 2] }); }
}
registry.category("views").add("abroj_voucher_list", { ...listView, Controller: VoucherListController });
