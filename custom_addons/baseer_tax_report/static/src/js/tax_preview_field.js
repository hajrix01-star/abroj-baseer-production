/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { HtmlField, htmlField } from "@web/views/fields/html/html_field";

export class TaxPreviewField extends HtmlField {
    static template = "baseer_tax_report.TaxPreviewField";

    setup() {
        super.setup();
        this.action = useService("action");
        this.orm = useService("orm");
    }

    async onPreviewClick(event) {
        if (event.target.closest("a.btr-help")) {
            event.preventDefault();
            return;
        }
        const link = event.target.closest("a.btr-open, a.btr-expand, a.btr-row-link");
        const row = event.target.closest("tr.btr-row");
        if ((!link && !row) || !event.currentTarget.contains(link || row)) {
            return;
        }
        const reference = (link || row).dataset.id || "";
        if (/^(?:[1-9]|1[0-6])$/.test(reference)) {
            event.preventDefault();
            const details = event.currentTarget.querySelector(
                `.btr-row-actions[data-id="${reference}"]`
            );
            if (details) {
                details.classList.toggle("d-none");
                const label = row?.querySelector("a.btr-row-link");
                label?.setAttribute("aria-expanded", String(!details.classList.contains("d-none")));
            }
            return;
        }
        if (!/^(?:[1-9]|1[0-6]):(?:base|tax)$/.test(reference)) {
            return;
        }
        event.preventDefault();
        if (link.classList.contains("btr-expand")) {
            const details = event.currentTarget.querySelector(
                `.btr-components[data-id="${reference}"]`
            );
            if (details) {
                details.classList.toggle("d-none");
                link.setAttribute("aria-expanded", String(!details.classList.contains("d-none")));
            }
            return;
        }
        if (this.opening) {
            return;
        }
        this.opening = true;
        try {
            // The selected period and company may be unsaved. Persist only this
            // transient wizard before asking the server for its scoped domain.
            if (!(await this.props.record.save({ reload: false }))) {
                return;
            }
            const [box, component] = reference.split(":");
            const action = await this.orm.call(
                "baseer.tax.report.wizard",
                "action_open_cell",
                [[this.props.record.resId], box, component]
            );
            await this.action.doAction(action);
        } finally {
            this.opening = false;
        }
    }
}

registry.category("fields").add("baseer_tax_preview", {
    ...htmlField,
    component: TaxPreviewField,
});
