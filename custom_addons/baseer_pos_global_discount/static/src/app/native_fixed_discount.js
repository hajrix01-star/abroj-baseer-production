import { patch } from "@web/core/utils/patch";
import { debounce } from "@web/core/utils/timing";
import { _t } from "@web/core/l10n/translation";
import { user } from "@web/core/user";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { accountTaxHelpers } from "@account/helpers/account_tax";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { PosOrderAccounting } from "@point_of_sale/app/models/accounting/pos_order_accounting";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { NumberPopup } from "@point_of_sale/app/components/popups/number_popup/number_popup";
import { SelectionPopup } from "@point_of_sale/app/components/popups/selection_popup/selection_popup";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";

const taxKey = (taxes) => taxes.map((tax) => tax.id).sort((a, b) => a - b).join("_");
const fixedLine = (order) => (order?.discountLines || []).find((line) => line.baseer_discount_kind === "fixed");

patch(ControlButtons.prototype, {
    async clickDiscount() {
        const order = this.pos.getOrder();
        const cashier = this.pos.getCashier();
        const config = this.pos.config;
        const manager = cashier?._role === "manager" ||
            await user.hasGroup("point_of_sale.group_pos_manager");
        if (config.baseer_global_discount_enabled || this.pos.baseerIsDiscountFrozen(order) || !config.baseer_fixed_discount_enabled ||
            (config.baseer_fixed_discount_allowed !== "all" && !manager)) {
            return super.clickDiscount(...arguments);
        }
        const choice = await makeAwaitable(this.dialog, SelectionPopup, {
            title: _t("نوع الخصم"),
            list: [
                { id: 1, label: _t("نسبة %"), item: "percent" },
                { id: 2, label: _t("مبلغ ثابت"), item: "fixed" },
            ],
        });
        if (choice === "percent") return super.clickDiscount(...arguments);
        if (choice === "fixed") {
            this.dialog.add(NumberPopup, {
                title: _t("مبلغ الخصم"),
                startingValue: fixedLine(order)?.baseer_discount_input || 0,
                getPayload: (value) => this.pos.baseerApplyFixedDiscount(
                    Math.max(0, this.env.utils.parseValidFloat(value.toString()) || 0), order
                ),
            });
        }
    },
});

patch(PosStore.prototype, {
    async setup() {
        await super.setup(...arguments);
        const reapply = debounce((order) => {
            const line = fixedLine(order);
            if (order?.state === "draft" && line) this.baseerApplyFixedDiscount(line.baseer_discount_input, order);
        });
        this.models["pos.order.line"].addEventListener("update", ({ id }) => {
            const line = this.models["pos.order.line"].get(id);
            if (line && !line.isDiscountLine) reapply(line.order_id);
        });
        this.models["pos.order"].addEventListener("update", ({ id, fields }) => {
            if (fields?.some((field) => PosOrderAccounting.accountingFields.has(field))) {
                reapply(this.models["pos.order"].get(id));
            }
        });
    },
    async applyDiscount(percent, order = this.getOrder()) {
        // Native queued reapplication includes the order; ignore stale percent work
        // after the cashier has switched this order to a fixed amount.
        if (arguments.length > 1 && fixedLine(order)) return;
        await super.applyDiscount(...arguments);
        for (const line of order.discountLines || []) {
            line.update({ baseer_discount_kind: "percent", baseer_discount_input: percent,
                baseer_discount_approved_by_user_id: false, baseer_discount_approved_by_employee: 0,
                baseer_discount_approved_by_employee_name: false });
        }
    },
    async baseerApplyFixedDiscount(amount, order = this.getOrder()) {
        const product = this.config.discount_product_id;
        if (!product) {
            this.dialog.add(AlertDialog, { title: _t("No discount product found"), body: _t("The discount product seems misconfigured. Make sure it is flagged as 'Can be Sold' and 'Available in Point of Sale'.") });
            return;
        }
        const existing = Object.fromEntries((order.discountLines || []).map((line) => [taxKey(line.tax_ids), line]));
        const baseLines = order.getOrderlines().filter((line) => line.isGlobalDiscountApplicable()).map((line) =>
            accountTaxHelpers.prepare_base_line_for_taxes_computation(line, line.prepareBaseLineForTaxesComputationExtraValues()));
        accountTaxHelpers.add_tax_details_in_base_lines(baseLines, order.company_id);
        accountTaxHelpers.round_base_lines_tax_details(baseLines, order.company_id);
        const eligible = accountTaxHelpers.prepare_discountable_base_lines(baseLines, order.company_id);
        const aggregated = accountTaxHelpers.aggregate_base_lines_aggregated_values(
            accountTaxHelpers.aggregate_base_lines_tax_details(eligible, () => true));
        const total = Object.values(aggregated).reduce((sum, item) => sum + item.total_excluded_currency + item.tax_amount_currency, 0);
        const cap = this.config.baseer_fixed_discount_max_amount;
        const capped = Math.max(0, Math.min(Number(amount) || 0, cap > 0 ? cap : Infinity, total));
        const result = capped ? accountTaxHelpers.prepare_global_discount_lines(baseLines, order.company_id, "fixed", capped, {
            computation_key: "global_discount",
            grouping_function: () => ({ grouping_key: { product_id: product }, raw_grouping_key: { product_id: product.id } }),
        }) : [];
        const cashier = this.getCashier();
        const old = fixedLine(order);
        const approver = old ? {
            baseer_discount_approved_by_user_id: old.baseer_discount_approved_by_user_id,
            baseer_discount_approved_by_employee: old.baseer_discount_approved_by_employee,
            baseer_discount_approved_by_employee_name: old.baseer_discount_approved_by_employee_name,
        } : {
            baseer_discount_approved_by_user_id: this.user,
            baseer_discount_approved_by_employee: cashier !== this.user ? cashier?.id || 0 : 0,
            baseer_discount_approved_by_employee_name: cashier !== this.user ? cashier?.name || false : false,
        };
        for (const baseLine of result) {
            const values = { extra_tax_data: accountTaxHelpers.export_base_line_extra_tax_data(baseLine),
                price_unit: baseLine.price_unit, baseer_discount_kind: "fixed", baseer_discount_input: amount, ...approver };
            const key = taxKey(baseLine.tax_ids);
            if (existing[key]) {
                existing[key].update(values);
                delete existing[key];
            } else {
                await this.addLineToOrder({ ...values, product_id: baseLine.product_id, qty: baseLine.quantity,
                    tax_ids: [["link", ...baseLine.tax_ids]], product_tmpl_id: baseLine.product_id.product_tmpl_id }, order, { force: true }, false);
            }
        }
        Object.values(existing).forEach((line) => line.delete());
    },
});

patch(PaymentScreen.prototype, {
    async validateOrder() {
        if (this.pos.data.network.offline && fixedLine(this.currentOrder)) {
            this.dialog.add(AlertDialog, { title: _t("مبلغ الخصم"), body: _t("لا يمكن إتمام دفع طلب عليه خصم ثابت بدون اتصال. أعد الاتصال ثم حاول مرة أخرى.") });
            return;
        }
        return super.validateOrder(...arguments);
    },
});
