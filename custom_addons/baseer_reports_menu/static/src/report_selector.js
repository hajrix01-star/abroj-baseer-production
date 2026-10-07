/** @odoo-module **/

import { Component } from "@odoo/owl";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";

export class ReportSelector extends Component {
    static template = "baseer_reports_menu.ReportSelector";
    static components = { Dropdown, DropdownItem };
    static props = ["options", "selectedKey", "label", "lang", "onSelect"];

    get selectedName() {
        const selected = this.props.options.find((option) => option.key === this.props.selectedKey);
        return selected ? this.reportName(selected) : this.props.label;
    }

    reportName(option) { return option.label[this.props.lang] || option.label.en; }
    selectReport(key) { this.props.onSelect(key); }
}
