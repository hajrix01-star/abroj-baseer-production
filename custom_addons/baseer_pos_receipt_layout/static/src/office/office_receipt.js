/** @odoo-module **/

import { App, Component, whenReady } from "@odoo/owl";
import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";
import { createRelatedModels } from "@point_of_sale/app/models/related_models";
import { registry } from "@web/core/registry";
import { getTemplate } from "@web/core/templates";
import { rpc } from "@web/core/network/rpc";
import { _t, appTranslateFn } from "@web/core/l10n/translation";
import { localizationService } from "@web/core/l10n/localization_service";
import { user } from "@web/core/user";

export class OfficeReceipt extends Component {
    static template = "baseer_pos_receipt_layout.OfficeReceipt";
    static components = { OrderReceipt };
    static props = { order: { type: Object, optional: true }, image: { type: String, optional: true } };

    async print() {
        await document.fonts.ready;
        await Promise.all([...document.querySelectorAll(".baseer-office-paper img")].map(async (img) => {
            if (img.decode) {
                await img.decode();
            }
        }));
        window.print();
    }
}

async function callOrder(method, values = []) {
    return rpc(`/web/dataset/call_kw/pos.order/${method}`, {
        model: "pos.order", method,
        args: [[odoo.baseer_office_order_id], ...values], kwargs: { context: user.context },
    });
}

async function startOfficeReceipt() {
    await whenReady();
    const root = document.getElementById("baseer-office-receipt-root");
    try {
        // Start only localization. Never start POS, hardware, sync or bus services.
        await localizationService.start();
        luxon.Settings.defaultNumberingSystem = "latn";
        const payload = await callOrder("baseer_office_receipt_data");
        let props;
        if (payload.image) {
            props = { image: `data:image/jpeg;base64,${payload.image}` };
        } else {
            const classes = {};
            const relations = Object.fromEntries(Object.entries(payload.params).map(([name, params]) => [name, params.relations]));
            for (const cls of registry.category("pos_available_models").getAll()) {
                if (!(cls.pythonModel in relations)) {
                    continue;
                }
                classes[cls.pythonModel] = cls;
                relations[cls.pythonModel] = { ...relations[cls.pythonModel], ...(cls.extraFields || {}) };
            }
            const { models } = createRelatedModels(relations, classes);
            models.loadConnectedData(payload.data);
            const order = models["pos.order"].get(odoo.baseer_office_order_id);
            await callOrder("baseer_validate_office_receipt", [{
                total: order.currency.round(order.priceIncl), tax: order.amountTaxes,
                paid: order.amountPaid, change: order.change,
                lines: order.lines.map((line) => ({ id: line.id, excl: line.priceExcl, incl: line.priceIncl })),
            }]);
            await order.config.cacheReceiptLogo();
            props = { order };
        }
        root.replaceChildren();
        // Some installed Orderline display extensions request usePos even in
        // receipt mode. Supply configuration only; there is no running store,
        // sync, hardware service or callable print/kitchen action in this view.
        const env = { services: { pos: Object.freeze({ config: props.order?.config }) } };
        await new App(OfficeReceipt, { getTemplate, translateFn: appTranslateFn, props, env }).mount(root);
    } catch (error) {
        root.replaceChildren();
        const message = document.createElement("p");
        message.className = "alert alert-danger m-3";
        message.setAttribute("role", "alert");
        message.textContent = error.data?.message || _t("The receipt could not be displayed. Please try again.");
        root.append(message);
        console.error("Office receipt could not be displayed", error);
    }
}

startOfficeReceipt();
