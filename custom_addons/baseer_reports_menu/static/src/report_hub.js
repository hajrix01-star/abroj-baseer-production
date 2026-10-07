/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";

const copy = {
    ar: {
        title: "تقارير بصير",
        choose: "اختر تقريرًا",
        loading: "جارٍ تحميل التقارير…",
        empty: "لا توجد تقارير بصير متاحة لصلاحياتك.",
        error: "تعذر فتح التقرير. تحقق من صلاحياتك ثم أعد المحاولة.",
    },
    en: {
        title: "Baseer Reports",
        choose: "Choose a report",
        loading: "Loading reports…",
        empty: "No Baseer reports are available for your access rights.",
        error: "Could not open the report. Check your access rights and try again.",
    },
};

export async function allowedReports(definitions, hasGroup) {
    const allowed = await Promise.all(definitions.map(async (definition) => {
        if (!definition.groups?.length || definition.kind !== "component" || !definition.component) {
            return null;
        }
        const matches = await Promise.all(definition.groups.map((group) => hasGroup(group)));
        if (!matches.some(Boolean)) { return null; }
        if (definition.requiredGroups?.length) {
            const required = await Promise.all(definition.requiredGroups.map((group) => hasGroup(group)));
            if (!required.some(Boolean)) { return null; }
        }
        return definition;
    }));
    return allowed.filter(Boolean).sort((left, right) => left.sequence - right.sequence);
}

export class BaseerReportsHub extends Component {
    static template = "baseer_reports_menu.Hub";
    static components = { Dropdown, DropdownItem };
    static props = ["*"];

    setup() {
        this.lang = user.lang?.startsWith("ar") ? "ar" : "en";
        this.options = [];
        this.state = useState({ ready: false, selectedKey: "", error: "" });
        onWillStart(async () => {
            try {
                const definitions = registry.category("baseer_reports").getAll();
                this.options = await allowedReports(definitions, (group) => user.hasGroup(group));
                if (this.options.length) { this.selectReport(this.options[0].key); }
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

    selectReport(key) {
        const option = this.options.find((item) => item.key === key);
        if (!option) { return; }
        this.state.selectedKey = key;
        this.state.error = "";
    }
}

registry.category("actions").add("baseer_reports_hub", BaseerReportsHub);
