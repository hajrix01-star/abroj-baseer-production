/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";
import { View } from "@web/views/view";

const copy = {
    ar: {
        title: "تقارير بصير",
        choose: "اختر تقريرًا",
        loading: "جارٍ فتح التقرير…",
        empty: "لا توجد تقارير بصير متاحة لصلاحياتك.",
        error: "تعذر فتح التقرير. تحقق من صلاحياتك ثم أعد المحاولة.",
    },
    en: {
        title: "Baseer Reports",
        choose: "Choose a report",
        loading: "Opening report…",
        empty: "No Baseer reports are available for your access rights.",
        error: "Could not open the report. Check your access rights and try again.",
    },
};

export async function allowedReports(definitions, hasGroup) {
    const allowed = await Promise.all(definitions.map(async (definition) => {
        if (!definition.groups?.length) { return null; }
        const matches = await Promise.all(definition.groups.map((group) => hasGroup(group)));
        return matches.some(Boolean) ? definition : null;
    }));
    return allowed.filter(Boolean).sort((left, right) => left.sequence - right.sequence);
}

export function formViewProps(action) {
    const formView = action.views?.find(([, type]) => type === "form");
    if (action.type !== "ir.actions.act_window" || !action.res_model || !formView) {
        throw new Error("Expected a form window action for a Baseer report");
    }
    return {
        resModel: action.res_model,
        type: "form",
        viewId: formView[0] || false,
        views: action.views,
        resId: action.res_id || false,
        context: action.context || {},
        display: { controlPanel: false },
    };
}

export class BaseerReportsHub extends Component {
    static template = "baseer_reports_menu.Hub";
    static components = { Dropdown, DropdownItem, View };
    static props = ["*"];

    setup() {
        this.action = useService("action");
        this.lang = user.lang?.startsWith("ar") ? "ar" : "en";
        this.options = [];
        this.viewProps = null;
        this.requestEpoch = 0;
        this.state = useState({ ready: false, loading: false, selectedKey: "", error: "" });
        onWillStart(async () => {
            try {
                const definitions = registry.category("baseer_reports").getAll();
                this.options = await allowedReports(definitions, (group) => user.hasGroup(group));
                if (this.options.length) { await this.selectReport(this.options[0].key); }
            } catch (error) {
                this.state.error = this.labels.error;
            } finally {
                this.state.ready = true;
            }
        });
    }

    get labels() { return copy[this.lang]; }
    get selectedReport() { return this.options.find((option) => option.key === this.state.selectedKey); }
    get selectedComponent() { return this.selectedReport?.component; }
    reportName(option) { return option.label[this.lang] || option.label.en; }

    async selectReport(key) {
        const option = this.options.find((item) => item.key === key);
        if (!option) { return; }
        const epoch = ++this.requestEpoch;
        this.state.selectedKey = key;
        this.state.loading = true;
        this.state.error = "";
        this.viewProps = null;
        try {
            if (option.kind === "form") {
                const action = await this.action.loadAction(option.actionXmlId);
                if (epoch !== this.requestEpoch) { return; }
                this.viewProps = formViewProps(action);
            } else if (option.kind !== "component" || !option.component) {
                throw new Error("Unknown Baseer report type");
            }
        } catch (error) {
            if (epoch === this.requestEpoch) { this.state.error = this.labels.error; }
        } finally {
            if (epoch === this.requestEpoch) { this.state.loading = false; }
        }
    }
}

registry.category("actions").add("baseer_reports_hub", BaseerReportsHub);
